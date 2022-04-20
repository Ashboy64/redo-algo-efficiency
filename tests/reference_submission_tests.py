"""Test that each reference submission can run a train and eval step.

This is a brief test that runs the for the workload and reference submission
code for one train and one eval step for all workloads, without the real data
iterator because it is not realistic to have all datasets available at testing
time. For end-to-end tests of submission_runner.py see
submission_runner_test.py.

Assumes that each reference submission is using the external tuning ruleset and
that it is defined in:
"reference_submissions/{workload}/{workload}_{framework}/submission.py"
"reference_submissions/{workload}/tuning_search_space.json".
"""
import copy
import importlib
import json
import os

from absl import flags
from absl import logging
from absl.testing import absltest
import numpy as np
import torch

from algorithmic_efficiency import halton
from algorithmic_efficiency import random_utils as prng
import submission_runner

flags.DEFINE_boolean('use_fake_input_queue', True, 'Use fake data examples.')
FLAGS = flags.FLAGS
PYTORCH_DEVICE = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')

_EXPECTED_METRICS = {
    'mnist': {
        'jax': {'test/accuracy': 0.0947265625},
        'pytorch': {'test/accuracy': 0.109375},
    }
}


def _make_fake_input_queue_fn(workload_name,
                              framework,
                              global_batch_size,
                              num_unique_fake_batches):

  def f(*unused_args, **unused_kwargs):
    del unused_args
    del unused_kwargs
    if workload_name == 'mnist':
      data_shape = (28, 28, 1)
      num_classes = 10
    elif workload_name == 'imagenet':
      data_shape = (224, 224, 3)
      num_classes = 1000
    else:
      raise ValueError(
          f'Workload {workload_name} does not have a fake data shape defined '
          'yet, you can add it or use --use_fake_input_queue=false.')

    if framework == 'jax':
      batch_shape = (1, global_batch_size)
    else:
      batch_shape = (global_batch_size,)

    np.random.seed(42)
    for _ in range(num_unique_fake_batches):
      examples = np.random.normal(size=(*batch_shape,
                                        *data_shape)).astype(np.float32)
      labels = np.random.randint(0, num_classes, size=batch_shape)
      # labels = np.eye(num_classes)[dense_labels]
      masks = np.ones_like((*batch_shape, *data_shape), dtype=np.float32)
      if framework == 'pytorch':
        examples = torch.from_numpy(examples).to(PYTORCH_DEVICE)
        labels = torch.from_numpy(labels).to(PYTORCH_DEVICE)
      yield examples, labels, masks

  return f


def _test_submission(workload_name,
                     framework,
                     submission_path,
                     search_space_path,
                     data_dir,
                     use_fake_input_queue):
  FLAGS.framework = framework
  workload_metadata = copy.deepcopy(submission_runner.WORKLOADS[workload_name])
  workload_metadata['workload_path'] = os.path.join(
      submission_runner.BASE_WORKLOADS_DIR,
      workload_metadata['workload_path'] + '_' + framework,
      'workload.py')
  workload = submission_runner.import_workload(
      workload_path=workload_metadata['workload_path'],
      workload_class_name=workload_metadata['workload_class_name'])

  submission_module_path = submission_runner.convert_filepath_to_module(
      submission_path)
  submission_module = importlib.import_module(submission_module_path)

  init_optimizer_state = submission_module.init_optimizer_state
  update_params = submission_module.update_params
  data_selection = submission_module.data_selection
  get_batch_size = submission_module.get_batch_size
  global_batch_size = get_batch_size(workload_name)

  # Get a sample hyperparameter setting.
  with open(search_space_path, 'r', encoding='UTF-8') as search_space_file:
    hyperparameters = halton.generate_search(
        json.load(search_space_file), num_trials=1)[0]

  rng = prng.PRNGKey(0)
  data_rng, opt_init_rng, model_init_rng, rng = prng.split(rng, 4)
  model_params, model_state = workload.init_model_fn(model_init_rng)
  if use_fake_input_queue:
    workload.build_input_queue = _make_fake_input_queue_fn(
        workload_name, framework, global_batch_size, num_unique_fake_batches=1)
  input_queue = workload.build_input_queue(
      data_rng, 'train', data_dir=data_dir, global_batch_size=global_batch_size)
  optimizer_state = init_optimizer_state(workload,
                                         model_params,
                                         model_state,
                                         hyperparameters,
                                         opt_init_rng)

  global_step = 0
  data_select_rng, update_rng, eval_rng = prng.split(rng, 3)
  (selected_train_input_batch,
   selected_train_label_batch,
   selected_train_mask_batch) = data_selection(workload,
                                               input_queue,
                                               optimizer_state,
                                               model_params,
                                               hyperparameters,
                                               global_step,
                                               data_select_rng)
  _, model_params, model_state = update_params(
      workload=workload,
      current_param_container=model_params,
      current_params_types=workload.model_params_types,
      model_state=model_state,
      hyperparameters=hyperparameters,
      input_batch=selected_train_input_batch,
      label_batch=selected_train_label_batch,
      mask_batch=selected_train_mask_batch,
      loss_type=workload.loss_type,
      optimizer_state=optimizer_state,
      eval_results=[],
      global_step=global_step,
      rng=update_rng)

  eval_result = workload.eval_model(global_batch_size,
                                    model_params,
                                    model_state,
                                    eval_rng,
                                    data_dir)
  return eval_result


class ReferenceSubmissionTest(absltest.TestCase):
  """Tests for reference submissions."""

  def test_submission(self):
    # Example: /home/znado/algorithmic-efficiency/tests
    self_location = os.path.dirname(os.path.realpath(__file__))
    # Example: /home/znado/algorithmic-efficiency
    repo_location = '/'.join(self_location.split('/')[:-1])
    references_dir = f'{repo_location}/reference_submissions'
    for workload_name in os.listdir(references_dir):
      workload_dir = f'{repo_location}/reference_submissions/{workload_name}'
      search_space_path = f'{workload_dir}/tuning_search_space.json'
      for framework in ['jax', 'pytorch']:
        submission_dir = f'{workload_dir}/{workload_name}_{framework}'
        if os.path.exists(submission_dir):
          submission_path = (f'reference_submissions/{workload_name}/'
                             f'{workload_name}_{framework}/submission.py')
          data_dir = None  # DO NOT SUBMIT
          logging.info(f'\n\n========= Testing {workload_name} in {framework}.')
          eval_result = _test_submission(workload_name,
                                         framework,
                                         submission_path,
                                         search_space_path,
                                         data_dir,
                                         FLAGS.use_fake_input_queue)
          expected = _EXPECTED_METRICS[workload_name][framework]
          metric_name = list(expected.keys())[0]
          actual_value = eval_result[metric_name]
          expected_value = expected[metric_name]
          self.assertAlmostEqual(actual_value, expected_value, places=3)


if __name__ == '__main__':
  absltest.main()
