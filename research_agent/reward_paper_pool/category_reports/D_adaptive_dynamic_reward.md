# D_adaptive_dynamic_reward: Adaptive / Dynamic Reward Weighting

## Category Definition
reward weights change over time, adaptive weighting, self-adaptive reward, dynamic multi-objective reward, non-stationary reward schedule

## Typical Reward Formula
`R_t = sum_i w_i(t) * r_i`

## Representative Papers
| Year | Paper | Venue | Score |
| --- | --- | --- | --- |
| 2024 | [Highly Efficient Self-Adaptive Reward Shaping for Reinforcement Learning](http://arxiv.org/abs/2408.03029v4) | arXiv | 0.417 |
| 1724672365008 | [Loss- and Reward-Weighting for Efficient Distributed Reinforcement Learning](https://openreview.net/forum?id=1EGVvwFSDd) | OpenReview | 0.333 |
| 1609459200000 | [Reward prediction for representation learning and reward shaping](https://openreview.net/forum?id=6kLPZCUq2d) | OpenReview | 0.417 |
| 1640995200000 | [Reward Shaping Using Convolutional Neural Network](https://openreview.net/forum?id=6lm1jxxLXb) | OpenReview | 0.75 |
| 1609459200000 | [Temporal-Logic-Based Reward Shaping for Continuing Reinforcement Learning Tasks](https://openreview.net/forum?id=MhrATccbtk) | OpenReview | 0.75 |
| 1695513826906 | [Logic-Based Adaptive Reward Shaping for Reinforcement Learning](https://openreview.net/forum?id=RPWs9kOv0I) | OpenReview | 0.5 |
| 1706793503406 | [Reward Shaping for Reinforcement Learning with An Assistant Reward Agent](https://openreview.net/forum?id=a3XFF0PGLU) | OpenReview | 0.75 |
| 1746057600000 | [Learn to Reason Efficiently with Adaptive Length-based Reward Shaping](https://openreview.net/forum?id=d3Wjfs6Z2k) | OpenReview | 0.417 |
| 1388534400000 | [Multi-objectivization of reinforcement learning problems by reward shaping](https://openreview.net/forum?id=dJu2kVsDTs) | OpenReview | 0.75 |
| 1704067200000 | [Reinforcement Learning with Dynamic Multi-Reward Weighting for Multi-Style Controllable Generation](https://openreview.net/forum?id=ed1vRqpFUa) | OpenReview | 0.333 |
| 1662100671446 | [Developing Clinical Artificial Intelligence for Obstetric Ultrasound to Improve Access in Underserved Regions: Protocol for a Computer-Assisted Low-Cost Point-of-Care UltraSound (CALOPUS) Study](https://openreview.net/forum?id=eeA3cqe2U1) | OpenReview | 0.417 |
| 1770134364903 | [Learning to Optimize Multi-Objective Alignment Through Dynamic Reward Weighting](https://openreview.net/forum?id=fdmS41jXQQ) | OpenReview | 0.333 |
| 1778671900417 | [ARMS: Automatic Reward Shaping for Sparse-Reward Multi-Agent Reinforcement Learning](https://openreview.net/forum?id=hZ9gu1iO12) | OpenReview | 0.75 |
| 1704067200000 | [Dynamic Multi-Reward Weighting for Multi-Style Controllable Generation](https://openreview.net/forum?id=kt5hqJJwGs) | OpenReview | 0.333 |
| 1356998400000 | [Perpetual Assurances for Self-Adaptive Systems](https://openreview.net/forum?id=pT1SSsY1Ta) | OpenReview | 0.417 |

## GitHub Implementations
| Repo | Stars | Reward Files | License |
| --- | --- | --- | --- |
| No linked repository yet |  |  |  |

## HRRL Transfer
Use the method only as a local reward component and keep safety checks outside the learned residual action.

## Control Layer Fit
| Layer | Fit |
| --- | --- |
| lqr_residual | unknown |
| stanley_residual | high |
| balance_control | unknown |
| path_tracking | high |
| safety_gate | high |

## Agent-Executable Modification Templates
| Method | Layers | Template |
| --- | --- | --- |
| Adaptive / Dynamic Reward Weighting | stanley_residual, path_tracking | weights = schedule(step, error_stats); reward = sum(weights[k] * terms[k] for k in terms) |
| Adaptive / Dynamic Reward Weighting | stanley_residual, path_tracking | weights = schedule(step, error_stats); reward = sum(weights[k] * terms[k] for k in terms) |
| Adaptive / Dynamic Reward Weighting | stanley_residual, path_tracking | weights = schedule(step, error_stats); reward = sum(weights[k] * terms[k] for k in terms) |
| Adaptive / Dynamic Reward Weighting | stanley_residual, path_tracking | weights = schedule(step, error_stats); reward = sum(weights[k] * terms[k] for k in terms) |
| Adaptive / Dynamic Reward Weighting | stanley_residual, path_tracking | weights = schedule(step, error_stats); reward = sum(weights[k] * terms[k] for k in terms) |
| Adaptive / Dynamic Reward Weighting | stanley_residual, path_tracking | weights = schedule(step, error_stats); reward = sum(weights[k] * terms[k] for k in terms) |
| Adaptive / Dynamic Reward Weighting | stanley_residual, path_tracking | weights = schedule(step, error_stats); reward = sum(weights[k] * terms[k] for k in terms) |
| Adaptive / Dynamic Reward Weighting | stanley_residual, path_tracking | weights = schedule(step, error_stats); reward = sum(weights[k] * terms[k] for k in terms) |

## Risks And Reward Hacking
- Proxy rewards can dominate true task success.
- Safety penalties should be hard-gated where violations are unacceptable.
- Dynamic or generated rewards require regression checks against baseline controllers.
