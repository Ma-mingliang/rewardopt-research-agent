# E_hierarchical_reward: Hierarchical Reward / HRL Reward Design

## Category Definition
high-level reward, low-level reward, manager worker reward, option-level reward, subtask reward

## Typical Reward Formula
`R = R_manager(g, s) + R_worker(a, g, s)`

## Representative Papers
| Year | Paper | Venue | Score |
| --- | --- | --- | --- |
| 2025 | [Tool-Star: Empowering LLM-Brained Multi-Tool Reasoner via Reinforcement Learning](http://arxiv.org/abs/2505.16410v1) | arXiv | 0.333 |
| 2025 | [TIGeR: Tool-Integrated Geometric Reasoning in Vision-Language Models for Robotics](http://arxiv.org/abs/2510.07181v3) | arXiv | 0.333 |
| 2026 | [Seg-ReSearch: Segmentation with Interleaved Reasoning and External Search](http://arxiv.org/abs/2602.04454v1) | arXiv | 0.333 |
| 2026 | [Hierarchical Reward Design from Language: Enhancing Alignment of Agent Behavior with Human Specifications](http://arxiv.org/abs/2602.18582v1) | arXiv | 0.333 |
| 2026 | [ARISE: Agent Reasoning with Intrinsic Skill Evolution in Hierarchical Reinforcement Learning](http://arxiv.org/abs/2603.16060v2) | arXiv | 0.333 |
| 2026 | [PokeRL: Reinforcement Learning for Pokemon Red](http://arxiv.org/abs/2604.10812v1) | arXiv | 0.333 |
| 1704067200000 | [Enhancing Embedding and Hierarchical Reward Shaping for Multi-Hop Reasoning with Reinforcement Learning](https://openreview.net/forum?id=3NAPbA3fN3) | OpenReview | 0.5 |
| 1704067200000 | [Comprehensive Overview of Reward Engineering and Shaping in Advancing Reinforcement Learning Applications](https://openreview.net/forum?id=A0CEcoE9BP) | OpenReview | 0.333 |
| 1727793680555 | [Improving Generalization in Visual Reinforcement Learning via Conflict-aware Gradient Agreement Augmentation](https://openreview.net/forum?id=DPkAk1oh3X) | OpenReview | 0.75 |
| 1764703641074 | [Guiding Multiagent Multitask Reinforcement Learning by a Hierarchical Framework With Logical Reward Shaping](https://openreview.net/forum?id=LZ6dT5UdzQ) | OpenReview | 0.333 |
| 1672531200000 | [Toward Computationally Efficient Inverse Reinforcement Learning via Reward Shaping](https://openreview.net/forum?id=SnXIEztSfF) | OpenReview | 0.5 |
| 1546300800000 | [Feudal Multi-Agent Hierarchies for Cooperative Reinforcement Learning](https://openreview.net/forum?id=TECQL4FLD0) | OpenReview | 0.417 |
| 1672531200000 | [Learning to Solve Multiple-TSP With Time Window and Rejections via Deep Reinforcement Learning](https://openreview.net/forum?id=VLZ97QbJR2) | OpenReview | 0.417 |
| 1706793503406 | [Reward Shaping for Reinforcement Learning with An Assistant Reward Agent](https://openreview.net/forum?id=a3XFF0PGLU) | OpenReview | 0.75 |
| 1737644878503 | [Deep Reinforcement Learning from Hierarchical Preference Design](https://openreview.net/forum?id=pw5ySjY11s) | OpenReview | 0.417 |

## GitHub Implementations
| Repo | Stars | Reward Files | License |
| --- | --- | --- | --- |
| No linked repository yet |  |  |  |

## HRRL Transfer
Use the method only as a local reward component and keep safety checks outside the learned residual action.

## Control Layer Fit
| Layer | Fit |
| --- | --- |
| lqr_residual | high |
| stanley_residual | high |
| balance_control | high |
| path_tracking | unknown |
| safety_gate | high |

## Agent-Executable Modification Templates
| Method | Layers | Template |
| --- | --- | --- |
| Hierarchical Reward / HRL Reward Design | lqr_residual, stanley_residual, balance_control | reward = goal_progress_reward + low_level_tracking_reward - control_cost |
| Hierarchical Reward / HRL Reward Design | lqr_residual, stanley_residual, balance_control | reward = goal_progress_reward + low_level_tracking_reward - control_cost |
| Hierarchical Reward / HRL Reward Design | lqr_residual, stanley_residual, balance_control, safety_gate | reward = goal_progress_reward + low_level_tracking_reward - control_cost |
| Hierarchical Reward / HRL Reward Design | lqr_residual, stanley_residual, balance_control | reward = goal_progress_reward + low_level_tracking_reward - control_cost |
| Hierarchical Reward / HRL Reward Design | lqr_residual, stanley_residual, balance_control | reward = goal_progress_reward + low_level_tracking_reward - control_cost |
| Hierarchical Reward / HRL Reward Design | lqr_residual, stanley_residual, balance_control | reward = goal_progress_reward + low_level_tracking_reward - control_cost |
| Hierarchical Reward / HRL Reward Design | lqr_residual, stanley_residual, balance_control | reward = goal_progress_reward + low_level_tracking_reward - control_cost |
| Hierarchical Reward / HRL Reward Design | lqr_residual, stanley_residual, balance_control | reward = goal_progress_reward + low_level_tracking_reward - control_cost |

## Risks And Reward Hacking
- Proxy rewards can dominate true task success.
- Safety penalties should be hard-gated where violations are unacceptable.
- Dynamic or generated rewards require regression checks against baseline controllers.
