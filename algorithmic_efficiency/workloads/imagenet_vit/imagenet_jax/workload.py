"""ImageNet workload implemented in Jax."""
import copy
from typing import Dict, Tuple

from flax import jax_utils
import jax
import jax.numpy as jnp

from algorithmic_efficiency import spec
from algorithmic_efficiency.workloads.imagenet_resnet.imagenet_jax.workload import \
    ImagenetResNetWorkload
from algorithmic_efficiency.workloads.imagenet_vit.imagenet_jax import models
from algorithmic_efficiency.workloads.imagenet_vit.workload import \
    BaseImagenetVitWorkload
from algorithmic_efficiency.workloads.imagenet_vit.workload import \
    decode_variant


# Make sure we inherit from the ViT base workload first.
class ImagenetVitWorkload(BaseImagenetVitWorkload, ImagenetResNetWorkload):

  def initialized(self, key, model):
    input_shape = (1, 224, 224, 3)
    variables = jax.jit(model.init)({'params': key}, jnp.ones(input_shape))
    model_state, params = variables.pop('params')
    return params, model_state

  def init_model_fn(self, rng: spec.RandomState) -> spec.ModelInitState:
    self._model_kwargs = {'num_classes': 1000, **decode_variant('B/32')}
    model = models.ViT(**self._model_kwargs)
    params, model_state = self.initialized(rng, model)
    self._param_shapes = jax.tree_map(lambda x: spec.ShapeTuple(x.shape),
                                      params)
    model_state = jax_utils.replicate(model_state)
    params = jax_utils.replicate(params)
    return params, model_state

  def model_fn(
      self,
      params: spec.ParameterContainer,
      augmented_and_preprocessed_input_batch: Dict[str, spec.Tensor],
      model_state: spec.ModelAuxiliaryState,
      mode: spec.ForwardPassMode,
      rng: spec.RandomState,
      dropout_prob: float,
      aux_dropout_prob: float,
      update_batch_norm: bool) -> Tuple[spec.Tensor, spec.ModelAuxiliaryState]:
    del model_state
    del aux_dropout_prob
    del update_batch_norm
    model_kwargs = copy.deepcopy(self._model_kwargs)
    model_kwargs['dropout_prob'] = dropout_prob
    model = models.ViT(**model_kwargs)
    train = mode == spec.ForwardPassMode.TRAIN
    print(rng)
    logits = model.apply(
        {'params': params},
        augmented_and_preprocessed_input_batch['inputs'],
        rngs={'dropout': rng},
        train=train)
    return logits, None

  def _eval_model_on_split(self,
                           split: str,
                           num_examples: int,
                           global_batch_size: int,
                           params: spec.ParameterContainer,
                           model_state: spec.ModelAuxiliaryState,
                           rng: spec.RandomState,
                           data_dir: str,
                           global_step: int = 0):
    model_state = None
    return super()._eval_model_on_split(split,
                                        num_examples,
                                        global_batch_size,
                                        params,
                                        model_state,
                                        rng,
                                        data_dir,
                                        global_step)
