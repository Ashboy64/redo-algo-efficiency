import os

# Disable GPU access for both jax and pytorch.
os.environ['CUDA_VISIBLE_DEVICES'] = ''

import jax
import jraph
import numpy as np
import torch

from algorithmic_efficiency import spec
from algorithmic_efficiency.workloads.ogbg.ogbg_jax.workload import \
    OgbgWorkload as JaxWorkload
from algorithmic_efficiency.workloads.ogbg.ogbg_pytorch.workload import \
    OgbgWorkload as PyTorchWorkload
from tests.modeldiffs.diff import out_diff

MLP_HIDDEN_DIMS = len(PyTorchWorkload.hidden_dims)

def key_transform(k):
  new_key = []
  bn = False
  ln = False
  graph_network = False
  "Sequential_0', 'GraphNetwork_0', 'Sequential_0', 'Linear_0', 'weight'"
  print("Key transform input ", k)
  graph_network_index = 0
  seq_index = 0
  for i in k:
    bn = bn or 'BatchNorm' in i
    ln = ln or 'LayerNorm' in i
    graph_network = graph_network or 'GraphNetwork'  in i
    if 'Sequential' in i:
      seq_index = i.split('_')[1]
      continue
    elif 'GraphNetwork' in i:
      graph_network_index = i.split('_')[1]
      continue
    elif 'Linear' in i:
      layer_index = i.split('_')[1]
      if graph_network:
        count = graph_index * 3 * MLP_HIDDEN_DIMS + seq_index * MLP_HIDDEN_DIMS + layer_index
        i = 'Dense_' + str(count)
      elif layer_index == 0:
        i = 'node_embedding'
      elif layer_index == 1:
        i = 'edge_embedding'
    elif 'LayerNorm' in i:
      layer_index = i.split('_')[1]
      count = graph_index * 3 * MLP_HIDDEN_DIMS + seq_index * MLP_HIDDEN_DIMS + layer_index
      i = 'LayerNorm_' + str(count)
    elif 'weight' in i:
      if bn or ln:
        i = i.replace('weight', 'scale')
      else:
        i = i.replace('weight', 'kernel')
    new_key.append(i)
  print("New key output", new_key)
  return tuple(new_key)


def sd_transform(sd):
  # pylint: disable=locally-disabled, modified-iterating-dict, consider-using-dict-items
  keys = list(sd.keys())
  out = {}
  for k in keys:
    new_key = k
    if len(k) == 5:
      _, gn_id, seq_id = k[:3]
      gn_id = int(gn_id.split('_')[1])
      seq_id = int(seq_id.split('_')[1])
      if 'LayerNorm' in k[3]:
        new_key = (k[3].replace('0', f'{gn_id*3+seq_id}'), k[4])
      else:
        new_key = (k[3].replace('0', f'{gn_id*3+seq_id+2}'), k[4])
    elif len(k) == 2 and k[0] == 'Dense_2':
      new_key = ('Dense_17', k[1])
    out[new_key] = sd[k]

  return out


if __name__ == '__main__':
  # pylint: disable=locally-disabled, not-callable

  jax_workload = JaxWorkload()
  pytorch_workload = PytWorkload()

  pyt_batch = dict(
      n_node=torch.LongTensor([5]),
      n_edge=torch.LongTensor([5]),
      nodes=torch.randn(5, 9),
      edges=torch.randn(5, 3),
      globals=torch.randn(1, 128),
      senders=torch.LongTensor(list(range(5))),
      receivers=torch.LongTensor([(i + 1) % 5 for i in range(5)]))

  jax_batch = {k: np.array(v) for k, v in pyt_batch.items()}

  # Test outputs for identical weights and inputs.
  graph_j = jraph.GraphsTuple(**jax_batch)
  graph_p = jraph.GraphsTuple(**pyt_batch)

  jax_batch = {'inputs': graph_j}
  pyt_batch = {'inputs': graph_p}

  pytorch_model_kwargs = dict(
      augmented_and_preprocessed_input_batch=pyt_batch,
      model_state=None,
      mode=spec.ForwardPassMode.EVAL,
      rng=None,
      update_batch_norm=False)

  jax_model_kwargs = dict(
      augmented_and_preprocessed_input_batch=jax_batch,
      mode=spec.ForwardPassMode.EVAL,
      rng=jax.random.PRNGKey(0),
      update_batch_norm=False)

  out_diff(
      jax_workload=jax_workload,
      pytorch_workload=pytorch_workload,
      jax_model_kwargs=jax_model_kwargs,
      pytorch_model_kwargs=pytorch_model_kwargs,
      key_transform=key_transform,
      sd_transform=sd_transform,
      out_transform=None)
