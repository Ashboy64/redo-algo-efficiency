"""MNIST workload implemented in Jax."""

import contextlib
import struct
import time
import itertools
from typing import Tuple
from collections import OrderedDict

from jax.interpreters.batching import batch
from workloads.mnist.workload import Mnist

import spec
import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import transforms
from torchvision.datasets import MNIST

DATA_DIR = '~/'
DEVICE='cuda'

"""
TODO: match network definition in mnist_jax
"""
class _Model(nn.Module):

    def __init__(self, input_size=28*28, num_hidden=128, num_classes=10):
        super(_Model, self).__init__()

        self.net = nn.Sequential(OrderedDict([
            ('layer1',     torch.nn.Linear(input_size, num_hidden, bias=True)),
            ('layer1_sig', torch.nn.Sigmoid()),
            ('layer2',     torch.nn.Linear(num_hidden, num_classes, bias=True)),
            ('output',     torch.nn.LogSoftmax(dim=1))
        ]))

    def forward(self, x: spec.Tensor):
        output = self.net(x)

        return output


class MnistWorkload(Mnist):

  def __init__(self):
    self._eval_ds = None

  def _build_dataloader(self,
      data_rng: spec.RandomState,
      split: str,
      batch_size: int):

    assert split in ['train', 'test']
    is_train = split == 'train'

    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.1307, ), (0.3081, ))
    ])

    dataset = MNIST(DATA_DIR, train=is_train, download=True, transform=transform)

    # TODO: set seeds properly
    dataloader = torch.utils.data.DataLoader(
      dataset,
      batch_size=batch_size,
      shuffle=is_train,
      pin_memory=True
    )

    if is_train:
      dataloader = itertools.cycle(dataloader)

    return dataloader


  def build_input_queue(
      self,
      data_rng: spec.RandomState,
      split: str,
      batch_size: int):
    return iter(self._build_dataloader(data_rng, split, batch_size))

  @property
  def param_shapes(self):
    """
    TODO: return shape tuples from model as a tree
    """
    raise NotImplementedError

  def model_params_types(self):
    pass

  # Return whether or not a key in spec.ParameterTree is the output layer
  # parameters.
  def is_output_params(self, param_key: spec.ParameterKey) -> bool:
    pass

  def preprocess_for_train(
      self,
      selected_raw_input_batch: spec.Tensor,
      selected_label_batch: spec.Tensor,
      rng: spec.RandomState) -> spec.Tensor:
    del rng
    return self.preprocess_for_eval(
        selected_raw_input_batch, selected_label_batch, None, None)

  def preprocess_for_eval(
      self,
      raw_input_batch: spec.Tensor,
      raw_label_batch: spec.Tensor,
      train_mean: spec.Tensor,
      train_stddev: spec.Tensor) -> spec.Tensor:
    del train_mean
    del train_stddev

    N = raw_input_batch.size()[0]
    raw_input_batch = raw_input_batch.view(N, -1)
    return (raw_input_batch.to(DEVICE), raw_label_batch.to(DEVICE))

  _InitState = Tuple[spec.ParameterTree, spec.ModelAuxillaryState]
  def init_model_fn(self, rng: spec.RandomState) -> _InitState:
    torch.random.manual_seed(rng[0])
    model = _Model(input_size=28*28).to(DEVICE)

    return model, None

  def model_fn(
      self,
      params: spec.ParameterTree,
      augmented_and_preprocessed_input_batch: spec.Tensor,
      model_state: spec.ModelAuxillaryState,
      mode: spec.ForwardPassMode,
      rng: spec.RandomState,
      update_batch_norm: bool) -> Tuple[spec.Tensor, spec.ModelAuxillaryState]:
    del model_state
    del rng
    del update_batch_norm

    model = params

    if mode == spec.ForwardPassMode.EVAL:
        model.eval()

    contexts = {
      spec.ForwardPassMode.EVAL: torch.no_grad,
      spec.ForwardPassMode.TRAIN: contextlib.nullcontext
    }

    with contexts[mode]():
      logits_batch = model(augmented_and_preprocessed_input_batch)


    return logits_batch, None

  # LossFn = Callable[Tuple[spec.Tensor, spec.Tensor], spec.Tensor]
  # Does NOT apply regularization, which is left to the submitter to do in
  # `update_params`.
  def loss_fn(
      self,
      label_batch: spec.Tensor,
      logits_batch: spec.Tensor,
      loss_type: spec.LossType) -> spec.Tensor:  # differentiable

    if loss_type is not spec.LossType.SOFTMAX_CROSS_ENTROPY:
      raise NotImplementedError

    return F.nll_loss(logits_batch, label_batch)

  def _eval_metric(self, logits, labels):
    _, predicted = torch.max(logits.data, 1)
    accuracy = (predicted == labels).cpu().numpy().mean()
    return accuracy

  def eval_model(
      self,
      params: spec.ParameterTree,
      model_state: spec.ModelAuxillaryState,
      rng: spec.RandomState):
    """Run a full evaluation of the model."""
    # TODO: use a split rng
    # data_rng, model_rng = jax.random.split(rng, 2)
    data_rng, model_rng = rng[:2]

    eval_batch_size = 2000
    num_batches = 10000 // eval_batch_size
    if self._eval_ds is None:
      self._eval_ds = self._build_dataloader(
          data_rng, split='test', batch_size=eval_batch_size)
    eval_iter = iter(self._eval_ds)
    total_loss = 0.
    total_accuracy = 0.
    for (images, labels) in eval_iter:
      (images, labels) = self.preprocess_for_eval(images, labels, None, None)
      logits, _ = self.model_fn(
          params,
          images,
          model_state,
          spec.ForwardPassMode.EVAL,
          model_rng,
          update_batch_norm=False)
      # TODO(znado): add additional eval metrics?
      # total_loss += self.loss_fn(labels, logits, self.loss_type)
      total_accuracy += self._eval_metric(logits, labels)
    return float(total_accuracy / num_batches)
