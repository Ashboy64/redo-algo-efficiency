"""Jax submission for the target-setting run on OGBG with AdamW."""

from typing import Dict, List, Tuple

import jax
from jax import lax
import jax.numpy as jnp
import optax

from algorithmic_efficiency import spec
from target_setting_runs.data_selection import \
    data_selection  # pylint: disable=unused-import
from target_setting_runs.jax_nadamw import \
    init_optimizer_state  # pylint: disable=unused-import


def get_batch_size(workload_name):
  # Return the global batch size.
  del workload_name
  return 512


def train_step(workload,
               opt_update_fn,
               model_state,
               optimizer_state,
               current_param_container,
               batch,
               rng,
               label_smoothing):

  def loss_fn(params):
    logits_batch, new_model_state  = workload.model_fn(
        params,
        batch,
        model_state,
        spec.ForwardPassMode.TRAIN,
        rng,
        update_batch_norm=True)
    mask_batch = batch['weights']
    per_example_losses = workload.loss_fn(
        batch['targets'],
        logits_batch,
        mask_batch,
        label_smoothing=label_smoothing)
    mean_loss = (
        jnp.sum(jnp.where(mask_batch, per_example_losses, 0)) /
        jnp.sum(mask_batch))
    return mean_loss, new_model_state

  grad_fn = jax.value_and_grad(loss_fn, has_aux=True)
  (_, new_model_state), grad = grad_fn(current_param_container)
  grad = lax.pmean(grad, axis_name='batch')
  updates, new_optimizer_state = opt_update_fn(
      grad, optimizer_state, current_param_container)
  updated_params = optax.apply_updates(current_param_container, updates)
  return new_model_state, new_optimizer_state, updated_params


def update_params(workload: spec.Workload,
                  current_param_container: spec.ParameterContainer,
                  current_params_types: spec.ParameterTypeTree,
                  model_state: spec.ModelAuxiliaryState,
                  hyperparameters: spec.Hyperparameters,
                  batch: Dict[str, spec.Tensor],
                  loss_type: spec.LossType,
                  optimizer_state: spec.OptimizerState,
                  eval_results: List[Tuple[int, float]],
                  global_step: int,
                  rng: spec.RandomState) -> spec.UpdateReturn:
  """Return (updated_optimizer_state, updated_params, updated_model_state)."""
  del current_params_types
  del loss_type
  del eval_results
  del global_step

  optimizer_state, opt_update_fn = optimizer_state
  pmapped_train_step = jax.pmap(
      train_step,
      axis_name='batch',
      in_axes=(None, None, 0, 0, 0, 0, 0, None),
      static_broadcasted_argnums=(0, 1))
  dropout_rngs = jax.random.split(rng, jax.local_device_count())
  label_smoothing = (
      hyperparameters.label_smoothing if hasattr(hyperparameters,
                                                 'label_smoothing') else 0.0)
  new_model_state, new_optimizer_state, new_params = pmapped_train_step(
      workload, opt_update_fn, model_state, optimizer_state,
      current_param_container, batch, dropout_rngs, label_smoothing)
  return (new_optimizer_state, opt_update_fn), new_params, new_model_state
