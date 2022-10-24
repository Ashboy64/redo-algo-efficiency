"""CIFAR workload parent class."""

from algorithmic_efficiency import spec


class BaseCifarWorkload(spec.Workload):

  def has_reached_goal(self, eval_result: float) -> bool:
    return eval_result['validation/accuracy'] > self.target_value

  @property
  def target_value(self):
    return 0.85

  @property
  def loss_type(self):
    return spec.LossType.SOFTMAX_CROSS_ENTROPY

  @property
  def num_train_examples(self):
    return 45000

  @property
  def num_eval_train_examples(self):
    return 10000

  @property
  def num_validation_examples(self):
    return 5000

  @property
  def num_test_examples(self):
    return 10000

  @property
  def eval_batch_size(self):
    return 1024

  @property
  def train_mean(self):
    return [0.49139968 * 255, 0.48215827 * 255, 0.44653124 * 255]

  @property
  def train_stddev(self):
    return [0.24703233 * 255, 0.24348505 * 255, 0.26158768 * 255]

  # data augmentation settings
  @property
  def scale_ratio_range(self):
    return (0.08, 1.0)

  @property
  def aspect_ratio_range(self):
    return (0.75, 4.0 / 3.0)

  @property
  def center_crop_size(self):
    return 32

  @property
  def max_allowed_runtime_sec(self):
    return 3600  # 1 hours

  @property
  def eval_period_time_sec(self):
    return 600  # 10 mins

  @property
  def step_hint(self) -> int:
    # Note that the target setting algorithms were not actually run on this
    # workload, but for completeness we provide the number of steps for 100
    # epochs at batch size 1024.
    return 4883
