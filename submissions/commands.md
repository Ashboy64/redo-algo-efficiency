# ReDO + NAdamW for MNIST workload

python3 submission_runner.py \
    --framework=pytorch \
    --workload=mnist \
    --experiment_dir=/home/ashishrao/redo_optimizer/experiment-dir \
    --experiment_name=redo_nadamw \
    --submission_path=submissions/redo_nadamw.py \
    --tuning_search_space=submissions/tuning_search_space.json \
    --num_tuning_trials=3 \
    --tuning_ruleset=external \
    --overwrite=True \
    --use_wandb=True

# Test development algo for MNIST workload

python3 submission_runner.py \
    --framework=pytorch \
    --workload=mnist \
    --experiment_dir=/home/ashishrao/redo_optimizer/experiment-dir \
    --experiment_name=test_development \
    --submission_path=reference_algorithms/development_algorithms/mnist/mnist_pytorch/submission.py \
    --tuning_search_space=reference_algorithms/development_algorithms/mnist/tuning_search_space.json \
    --num_tuning_trials=3 \
    --tuning_ruleset=external \
    --overwrite=True \
    --use_wandb=True


# Test Paper Baseline SGD + Momentum for MNIST workload

python3 submission_runner.py \
    --framework=pytorch \
    --workload=mnist \
    --experiment_dir=/home/ashishrao/redo_optimizer/experiment-dir \
    --experiment_name=test_momentum \
    --submission_path=reference_algorithms/paper_baselines/momentum/pytorch/submission.py \
    --tuning_search_space=reference_algorithms/paper_baselines/momentum/tuning_search_space.json \
    --num_tuning_trials=3 \
    --tuning_ruleset=external \
    --overwrite=True \
    --use_wandb=True
