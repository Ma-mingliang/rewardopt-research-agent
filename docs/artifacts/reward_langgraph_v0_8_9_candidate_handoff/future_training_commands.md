# Future Training Commands

**These commands are NOT executed in v0.8.9.**

They are provided as templates for when resource constraints (pagefile, memory) are addressed
or when a CPU/low-resource training mode is selected.

## Prerequisites

Before running any training command:
1. Ensure pagefile is set to at least 32GB (or use CPU-only mode)
2. Ensure env.py hash is `e19703467be71e20`
3. Ensure baseline guard passes
4. Apply the candidate patch to env.py before training

## Train Top 1 Candidate (control_energy)

```bash
# 1. Apply patch
cd D:/research-agent/HRRL2
git apply D:/research-agent/docs/artifacts/reward_langgraph_v0_8_9_candidate_handoff/candidate_patches/test_control_energy_005.diff

# 2. Train
conda run -n langgraph python D:/research-agent/run_optimizer.py ^
  --project D:/research-agent/HRRL2 ^
  --optimizer reward_langgraph ^
  --max-iterations 1 ^
  --batch-size 1 ^
  --execution-python E:/Anaconda/envs/RL2/python.exe ^
  --staged-eval ^
  --baseline-manifest D:/research-agent/docs/baselines/hrrl2_operational_baseline.yaml

# 3. Restore baseline
git checkout -- env.py
```

## Train Top 2 Candidates (control_energy + risk_penalty)

```bash
# Apply and train sequentially
cd D:/research-agent/HRRL2

# Candidate 1: control_energy
git apply D:/research-agent/docs/artifacts/reward_langgraph_v0_8_9_candidate_handoff/candidate_patches/test_control_energy_005.diff
conda run -n langgraph python D:/research-agent/run_optimizer.py --project D:/research-agent/HRRL2 --optimizer reward_langgraph --max-iterations 1 --batch-size 1 --execution-python E:/Anaconda/envs/RL2/python.exe --staged-eval --baseline-manifest D:/research-agent/docs/baselines/hrrl2_operational_baseline.yaml
git checkout -- env.py

# Candidate 2: risk_penalty
git apply D:/research-agent/docs/artifacts/reward_langgraph_v0_8_9_candidate_handoff/candidate_patches/test_pbrs_001.diff
conda run -n langgraph python D:/research-agent/run_optimizer.py --project D:/research-agent/HRRL2 --optimizer reward_langgraph --max-iterations 1 --batch-size 1 --execution-python E:/Anaconda/envs/RL2/python.exe --staged-eval --baseline-manifest D:/research-agent/docs/baselines/hrrl2_operational_baseline.yaml
git checkout -- env.py
```

## Run Full Eval After Training

After a candidate is trained and accepted:

```bash
conda run -n langgraph python D:/research-agent/run_eval.py ^
  --project D:/research-agent/HRRL2 ^
  --seeds 42 43 44 ^
  --episodes 30
```

## Optional Multi-Seed Confirmation

For production confidence, train with 3 different seeds:

```bash
for seed in 42 43 44; do
  conda run -n langgraph python D:/research-agent/run_optimizer.py ^
    --project D:/research-agent/HRRL2 ^
    --optimizer reward_langgraph ^
    --max-iterations 1 ^
    --batch-size 1 ^
    --execution-python E:/Anaconda/envs/RL2/python.exe ^
    --staged-eval ^
    --baseline-manifest D:/research-agent/docs/baselines/hrrl2_operational_baseline.yaml
done
```
