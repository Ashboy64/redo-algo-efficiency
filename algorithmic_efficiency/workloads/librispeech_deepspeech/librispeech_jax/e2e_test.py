from algorithmic_efficiency.workloads.librispeech_deepspeech.librispeech_jax import \
    models
from algorithmic_efficiency.workloads.librispeech_conformer import \
    input_pipeline

import jax 
import jax.numpy as jnp 
import optax
import os
import flax.linen as nn
import flax 
import torch 
import wandb 

wandb.init()

print(torch.cuda.device_count())
print(jax.local_device_count())

a = torch.cuda.device_count()

# os.environ['TF_CPP_MIN_LOG_LEVEL'] = '0'


config = models.DeepspeechConfig()
model = models.Deepspeech(config)

print(model)

inputs = jnp.zeros((2, 320000))
input_paddings = jnp.zeros((2, 320000))

print(a)
rng = jax.random.PRNGKey(0)
params_rng, data_rng, dropout_rng = jax.random.split(rng, 3)

print('initing model .....')                                                
vars = model.init(
    {'params': params_rng, 'dropout': dropout_rng}, 
    inputs, 
    input_paddings, 
    train=True)

print('inited model')

batch_stats = vars['batch_stats']
params = vars['params']
warmup_steps = 2
learning_rate_init=0.002


ds = input_pipeline.get_librispeech_dataset('train-clean-100',
                                            '../../librispeech_conformer/work_dir/data',
                                            data_rng,
                                            False,
                                            8,
                                            1)

def rsqrt_schedule(
    init_value: float,
    shift: int = 0):
  def schedule(count):
    return init_value * (count + shift)**-.5 * shift**.5

  return schedule

def create_learning_rate_schedule(learning_rate: float, warmup_steps: int):
  """Creates a rsqrt schedule with linear warmup."""
  return optax.join_schedules([
      optax.linear_schedule(
          init_value=0, end_value=learning_rate, transition_steps=warmup_steps),
      rsqrt_schedule(init_value=learning_rate, shift=warmup_steps),
  ],
  boundaries=[warmup_steps])

learning_rate_fn = create_learning_rate_schedule(
    learning_rate=learning_rate_init, 
    warmup_steps=warmup_steps
)


optimizer_init_fn, optimizer_update_fn = optax.adamw(
    learning_rate_fn, 
    b1=0.9, 
    b2=0.98, 
    eps=1e-9, 
    weight_decay=0.1
)
optimizer_state = optimizer_init_fn(params)
print('optimizer initialized')

def shard(batch, n_devices=None):
    if n_devices is None:
      n_devices = jax.local_device_count()

    # Otherwise, the entries are arrays, so just reshape them.
    def _shard_array(array):
      return array.reshape((n_devices, -1) + array.shape[1:])

    return jax.tree_map(_shard_array, batch)

replicated_params = flax.jax_utils.replicate(params)
replicated_batch_stats = flax.jax_utils.replicate(batch_stats)
replicated_optimizer_state = flax.jax_utils.replicate(optimizer_state)

num_train_step = 0

print('starting training loop')

for batch in iter(ds):
    batch = jax.tree_map(lambda x: x._numpy(), batch)  # pylint: disable=protected-access
    # batch = self.maybe_pad_batch(batch, batch_size, padding_value=1.0)
    # batch = self.shard(batch)
    def update_step(batch, params, batch_stats, optimizer_state):
        def loss_fn(params, batch_stats):
            inputs, input_paddings = batch['inputs']

            (logits, logit_paddings), new_batch_stats = model.apply({
                'params': params,
                'batch_stats': batch_stats
            }, inputs, input_paddings, train=True, rngs = {'dropout': dropout_rng}, mutable=['batch_stats'])
            targets, target_paddings = batch['targets']
            logprobs = nn.log_softmax(logits)
            per_seq_loss = optax.ctc_loss(logprobs,
                                        logit_paddings,
                                        targets,
                                        target_paddings)
            normalizer = jnp.sum(1 - target_paddings)
            normalized_loss = jnp.sum(per_seq_loss) / jnp.maximum(normalizer, 1)

            return normalized_loss, new_batch_stats

        grad_fn = jax.value_and_grad(loss_fn, has_aux=True)
        (loss_val, new_batch_stats), grads = grad_fn(params, batch_stats)
        updates, new_optimizer_state = optimizer_update_fn(grads, optimizer_state, params)
        new_params = optax.apply_updates(params, updates)
        
        return new_params, new_batch_stats, new_optimizer_state, loss_val

    pmapped_update_step = jax.pmap(update_step, axis_name='batch', in_axes=(0, 0, 0, 0))
    
    batch = shard(batch)
    replicated_params, replicated_batch_stats, replicated_optimizer_state, loss_val = pmapped_update_step(batch, replicated_params, replicated_batch_stats, replicated_optimizer_state)

    #params, batch_stats, optimizer_state, loss_val = update_step(batch, params, batch_stats, optimizer_state)
    print('{}) loss_value = {}'.format(num_train_step, loss_val.mean()))
    num_train_step = num_train_step + 1