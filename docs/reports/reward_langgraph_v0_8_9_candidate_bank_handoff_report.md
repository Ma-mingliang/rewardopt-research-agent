# v0.8.9: Candidate Bank Packaging and Future-Training Handoff

**Date**: 2026-06-17
**Branch**: reward-langgraph-v0.8.9-candidate-bank-handoff
**Tag**: reward-langgraph-v0.8.9

## v0.8.8 Summary

v0.8.8 ran a real proposal-only diversity campaign using the v0.8.7 DiversityScheduler. It produced 3 validation-ready semantic reward candidates from 3 unique templates across 3 categories. Template diversity score: 1.0. All semantic gates passed.

## Why v0.8.9 Does Not Train

Training requires significant memory (Windows pagefile > 32GB). v0.8.9 packages the validation-ready candidates into reusable artifacts so training can be executed when resource constraints are addressed or when a CPU/low-resource training mode is selected.

## Candidate Handoff Artifacts

| File | Purpose |
|------|---------|
| `top_candidates_summary.md` | Ranked candidate table with risk notes |
| `candidate_patches/test_control_energy_005.diff` | Rank 1 patch |
| `candidate_patches/test_pbrs_001.diff` | Rank 2 patch |
| `candidate_patches/test_curriculum_003.diff` | Rank 3 patch |
| `candidate_metadata.json` | Machine-readable metadata |
| `future_training_commands.md` | Training command templates (not executed) |
| `README.md` | Usage instructions |

## Top Candidate Table

| Rank | Template | Category | Reward Terms | Score | Complexity | Risk Note | Action |
|------|----------|----------|-------------|-------|------------|-----------|--------|
| 1 | test_control_energy_005 | D_adaptive_dynamic | control_energy penalty (quadratic) | 0.626 | 0.16 | Possible under-actuation, worse tracking | keep_for_future_training |
| 2 | test_pbrs_001 | A_potential_based | risk_penalty (angular_velocity + error) | 0.605 | 0.30 | Potential function may conflict with objective | keep_for_future_training |
| 3 | test_curriculum_003 | C_curriculum_subgoal | stability_penalty (near-fall conditions) | 0.605 | 0.30 | Shaping mismatch or overfitting to stages | keep_for_future_training |

## Patch Export Paths

- `docs/artifacts/reward_langgraph_v0_8_9_candidate_handoff/candidate_patches/test_control_energy_005.diff`
- `docs/artifacts/reward_langgraph_v0_8_9_candidate_handoff/candidate_patches/test_pbrs_001.diff`
- `docs/artifacts/reward_langgraph_v0_8_9_candidate_handoff/candidate_patches/test_curriculum_003.diff`

## Candidate Risk Notes

### test_control_energy_005 (Rank 1)
- **Possible benefit**: smoother actions, lower control energy
- **Possible risk**: under-actuation, worse tracking, slower correction
- Adds `control_energy = -0.01 * target_handle_angle ** 2`

### test_pbrs_001 (Rank 2)
- **Possible benefit**: dense progress shaping via risk penalty
- **Possible risk**: potential function may conflict with original objective
- Adds `risk_penalty = -3.0` when `angular_velocity > 1.5 or current_error > 0.3`

### test_curriculum_003 (Rank 3)
- **Possible benefit**: staged learning signal via stability penalty
- **Possible risk**: shaping mismatch or overfitting to artificial stages
- Adds `stability_penalty = -5.0` when `angular_velocity > 2.0 or current_error > 0.5`

**No performance improvement is claimed because no training was run.**

## Future Training Commands

Generated in `future_training_commands.md`. Includes:
- Train top 1 candidate (control_energy)
- Train top 2 candidates (control_energy + risk_penalty)
- Run full eval after training
- Optional multi-seed confirmation

**These commands are NOT executed in v0.8.9.**

## Consistency Check

All 3 patches verified against baseline env.py:
- Patch applies to env.py
- Compilation passes
- AST parse passes
- env.py baseline hash unchanged (e19703467be71e20)

| Patch | Applies | Compiles | AST | Status |
|-------|---------|----------|-----|--------|
| test_control_energy_005 | yes | yes | yes | PASS |
| test_pbrs_001 | yes | yes | yes | PASS |
| test_curriculum_003 | yes | yes | yes | PASS |

## Recommendation

- **Keep top control_energy candidate as first future training candidate**
- Keep curriculum and PBRS candidates as alternatives
- Do not train until resource issue is acceptable or CPU/low-resource mode is selected

## Test Results

```
55 key tests: PASSED
```

## Commit and Tag

- **Commit**: `docs: add candidate bank handoff artifacts`
- **Tag**: `reward-langgraph-v0.8.9`
