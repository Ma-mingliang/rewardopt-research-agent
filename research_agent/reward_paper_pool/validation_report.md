# Reward Paper Pool Validation Report

Hard checks passed: YES

## Summary
- total_papers: 118
- total_methods: 142
- total_github_repos: 120
- linked_github_repos: 110
- duplicate_ratio: 0.0424

## Hard Checks
- PASS: each category has >= 10 papers ({})
- PASS: each paper has title abstract url (bad=0)
- PASS: each method has required fields (bad=0)
- PASS: at least 5 github repos linked (linked=110)
- PASS: duplicate papers <= 5% (duplicate_ratio=0.0424)
- PASS: each category has >= 3 method templates ({})
- PASS: 8 categories exist (categories=8)
- PASS: total papers >= 80 (papers=118)
- PASS: github projects >= 10 (repos=120)
- PASS: method_pool >= 30 (methods=142)
- PASS: at least 10 methods apply to HRRL/residual control (methods=90)
- PASS: at least 5 methods apply to lqr_residual (methods=31)
- PASS: at least 5 methods apply to stanley_residual (methods=90)
- PASS: at least 5 methods apply to safety_gate (methods=28)

## Category Counts
- A_potential_based_reward: 27
- B_safety_constraint_reward: 21
- C_curriculum_subgoal_reward: 20
- D_adaptive_dynamic_reward: 19
- E_hierarchical_reward: 16
- F_residual_aware_reward: 14
- G_llm_reward_generation: 13
- H_learned_preference_reward: 29
