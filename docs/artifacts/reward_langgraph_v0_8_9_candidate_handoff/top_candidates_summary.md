# Top Candidates Summary

**Source run_id**: 20260617_123033_reward_langgraph_8bac43
**env_hash**: e19703467be71e20
**Baseline manifest**: docs/baselines/hrrl2_operational_baseline.yaml

## Candidate Ranking Table

| Rank | Candidate | Template | Category | Reward Terms | Score | Complexity | Source Penalty | Syntax | Validation | Risk Note | Recommendation |
|------|-----------|----------|----------|-------------|-------|------------|----------------|--------|------------|-----------|----------------|
| 1 | reward_langgraph_c001 | test_control_energy_005 | D_adaptive_dynamic_reward | control_energy penalty (quadratic cost on action magnitude) | 0.626 | 0.16 | 0.05 | valid | passed | Possible under-actuation, worse tracking, slower correction | keep_for_future_training |
| 2 | reward_langgraph_c001 | test_pbrs_001 | A_potential_based_reward | risk_penalty (angular_velocity > 1.5 or current_error > 0.3) | 0.605 | 0.30 | 0.05 | valid | passed | Potential function may conflict with original objective | keep_for_future_training |
| 3 | reward_langgraph_c001 | test_curriculum_003 | C_curriculum_subgoal_reward | stability_penalty (angular_velocity > 2.0 or current_error > 0.5) | 0.605 | 0.30 | 0.05 | valid | passed | Shaping mismatch or overfitting to artificial stages | keep_for_future_training |

## Variables Used

| Candidate | Variables |
|-----------|-----------|
| test_control_energy_005 | target_handle_angle |
| test_pbrs_001 | angular_velocity, current_error |
| test_curriculum_003 | angular_velocity, current_error |

## Notes

- All candidates passed semantic gate and syntax validation
- All candidates were generated via semantic_regeneration (not primary proposal)
- No training was performed — these are validation-ready patches only
- Performance improvement cannot be claimed without training
