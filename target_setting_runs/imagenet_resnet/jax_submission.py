"""
Jax submission for the target-setting run on ImageNet-ResNet with Nesterov.
"""

import functools
from typing import Dict, List, Tuple

import jax
from jax import lax
import jax.numpy as jnp
import optax

from algorithmic_efficiency import spec
from target_setting_runs.data_selection import \
    data_selection  # pylint: disable=unused-import
from target_setting_runs.jax_nesterov import \
    init_optimizer_state  # pylint: disable=unused-import


def get_batch_size(workload_name):
  # Return the global batch size.
  del workload_name
  return 1024


@functools.partial(
    jax.pmap,
    axis_name='batch',
    in_axes=(None, None, 0, 0, None, 0, 0, 0),
    static_broadcasted_argnums=(0, 1))
def pmapped_train_step(workload,
                       opt_update_fn,
                       model_state,
                       optimizer_state,
                       lr,
                       current_param_container,
                       batch,
                       rng):

  def _loss_fn(params):
    """Loss function used for training."""
    logits, new_model_state = workload.model_fn(
        params,
        batch,
        model_state,
        spec.ForwardPassMode.TRAIN,
        rng,
        update_batch_norm=True)
    loss = jnp.mean(workload.loss_fn(batch['targets'], logits))
    return loss, (new_model_state, logits)

  grad_fn = jax.value_and_grad(_loss_fn, has_aux=True)
  aux, grad = grad_fn(current_param_container)
  grad = lax.pmean(grad, axis_name='batch')
  new_model_state, _ = aux[1]
  # Inject learning rate into optimizer state.
  optimizer_state.hyperparams['learning_rate'] = lr
  updates, new_optimizer_state = opt_update_fn(grad, optimizer_state,
                                               current_param_container)
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
  del hyperparameters
  del loss_type
  del eval_results

  optimizer_state, opt_update_fn = optimizer_state
  lr_schedule_fn = optimizer_state['lr_schedule_fn']
  optimizer_state = optimizer_state['optimizer_state']

  lr = lr_schedule_fn(global_step)
  per_device_rngs = jax.random.split(rng, jax.local_device_count())
  new_model_state, new_optimizer_state, new_params = pmapped_train_step(
      workload, opt_update_fn, model_state, optimizer_state, lr,
      current_param_container, batch, per_device_rngs)

  new_optimizer_state = {
      'optimizer_state': new_optimizer_state, 'lr_schedule_fn': lr_schedule_fn
  }

  return (new_optimizer_state, opt_update_fn), new_params, new_model_state
