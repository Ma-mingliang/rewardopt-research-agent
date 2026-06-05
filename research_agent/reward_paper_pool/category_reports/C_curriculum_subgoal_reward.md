# C_curriculum_subgoal_reward: Curriculum / Subgoal / Progress Reward

## Category Definition
stage-wise reward, subgoal reward, progress reward, automatic curriculum, task decomposition

## Typical Reward Formula
`R = R_task + beta_stage * progress(s, goal_k)`

## Representative Papers
| Year | Paper | Venue | Score |
| --- | --- | --- | --- |
| 2021 | [Reward Shaping with Subgoals for Social Navigation](http://arxiv.org/abs/2104.06410v1) | arXiv | 0.333 |
| 1758259419628 | [Subgoal-Guided Reward Shaping: Improving Preference-Based Offline Reinforcement Learning via Conditional VAEs](https://openreview.net/forum?id=5T1vMQldr8) | OpenReview | 0.583 |
| 1748896331408 | [Curriculum Reinforcement Learning for Complex Reward Functions](https://openreview.net/forum?id=DHOxjoy1sP) | OpenReview | 0.333 |
| 1727793680555 | [Improving Generalization in Visual Reinforcement Learning via Conflict-aware Gradient Agreement Augmentation](https://openreview.net/forum?id=DPkAk1oh3X) | OpenReview | 0.75 |
| 1738368000000 | [Improving the Effectiveness of Potential-Based Reward Shaping in Reinforcement Learning](https://openreview.net/forum?id=HqWHxvZCMJ) | OpenReview | 0.917 |
| 1715724069512 | [Robot Policy Learning with Temporal Optimal Transport Reward](https://openreview.net/forum?id=LEed5Is4oi) | OpenReview | 0.417 |
| 1609459200000 | [Temporal-Logic-Based Reward Shaping for Continuing Reinforcement Learning Tasks](https://openreview.net/forum?id=MhrATccbtk) | OpenReview | 0.75 |
| 1758311563996 | [ARM-FM: Automated Reward Machines via Foundation Models for Compositional Reinforcement Learning](https://openreview.net/forum?id=OBpQdCWLfd) | OpenReview | 0.417 |
| 1745469789760 | [HALO : Human Preference Aligned Offline Reward Learning for Robot Navigation](https://openreview.net/forum?id=PMKwnV6Azi) | OpenReview | 0.417 |
| 1746798833131 | [Progress Reward Model for Reinforcement Learning via Large Language Models](https://openreview.net/forum?id=TJhHb6CscW) | OpenReview | 0.75 |
| 1746057600000 | [Curriculum-RLAIF: Curriculum Alignment with Reinforcement Learning from AI Feedback](https://openreview.net/forum?id=UV9aa45wyM) | OpenReview | 0.417 |
| 1706793503406 | [Reward Shaping for Reinforcement Learning with An Assistant Reward Agent](https://openreview.net/forum?id=a3XFF0PGLU) | OpenReview | 0.75 |
| 1706821470146 | [Probabilistic Subgoal Representations for Hierarchical Reinforcement Learning](https://openreview.net/forum?id=b6AwZauZPV) | OpenReview | 0.417 |
| 1388534400000 | [Multi-objectivization of reinforcement learning problems by reward shaping](https://openreview.net/forum?id=dJu2kVsDTs) | OpenReview | 0.75 |
| 1778671900417 | [ARMS: Automatic Reward Shaping for Sparse-Reward Multi-Agent Reinforcement Learning](https://openreview.net/forum?id=hZ9gu1iO12) | OpenReview | 0.75 |

## GitHub Implementations
| Repo | Stars | Reward Files | License |
| --- | --- | --- | --- |
| [ai-boost/awesome-prompts](https://github.com/ai-boost/awesome-prompts) | 8125 |  | GPL-3.0 |
| [nibzard/awesome-agentic-patterns](https://github.com/nibzard/awesome-agentic-patterns) | 4633 |  | Apache-2.0 |

## HRRL Transfer
Use the method only as a local reward component and keep safety checks outside the learned residual action.

## Control Layer Fit
| Layer | Fit |
| --- | --- |
| lqr_residual | unknown |
| stanley_residual | high |
| balance_control | unknown |
| path_tracking | high |
| safety_gate | unknown |

## Agent-Executable Modification Templates
| Method | Layers | Template |
| --- | --- | --- |
| Curriculum / Subgoal / Progress Reward | stanley_residual, path_tracking | reward += stage_weight[current_stage] * (prev_dist_to_subgoal - dist_to_subgoal) |
| Curriculum / Subgoal / Progress Reward | stanley_residual, path_tracking | reward += stage_weight[current_stage] * (prev_dist_to_subgoal - dist_to_subgoal) |
| Curriculum / Subgoal / Progress Reward | stanley_residual, path_tracking | reward += stage_weight[current_stage] * (prev_dist_to_subgoal - dist_to_subgoal) |
| Curriculum / Subgoal / Progress Reward | stanley_residual, path_tracking | reward += stage_weight[current_stage] * (prev_dist_to_subgoal - dist_to_subgoal) |
| Curriculum / Subgoal / Progress Reward | stanley_residual, path_tracking | reward += stage_weight[current_stage] * (prev_dist_to_subgoal - dist_to_subgoal) |
| Curriculum / Subgoal / Progress Reward | stanley_residual, path_tracking | reward += stage_weight[current_stage] * (prev_dist_to_subgoal - dist_to_subgoal) |
| Curriculum / Subgoal / Progress Reward | stanley_residual, path_tracking | reward += stage_weight[current_stage] * (prev_dist_to_subgoal - dist_to_subgoal) |
| Curriculum / Subgoal / Progress Reward | stanley_residual, path_tracking | reward += stage_weight[current_stage] * (prev_dist_to_subgoal - dist_to_subgoal) |

## Risks And Reward Hacking
- Proxy rewards can dominate true task success.
- Safety penalties should be hard-gated where violations are unacceptable.
- Dynamic or generated rewards require regression checks against baseline controllers.
