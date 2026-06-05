# B_safety_constraint_reward: Safety / Constraint / Risk-Aware Reward

## Category Definition
safety penalty, constraint penalty, barrier function, collision penalty, fall penalty, risk-aware reward

## Typical Reward Formula
`R_safe = R_task - lambda_c * violation_cost - lambda_r * risk`

## Representative Papers
| Year | Paper | Venue | Score |
| --- | --- | --- | --- |
| 2023 | [Risk-Aware Reward Shaping of Reinforcement Learning Agents for Autonomous Driving](http://arxiv.org/abs/2306.03220v2) | arXiv | 0.417 |
| 2026 | [Zero-Shot, Safe and Time-Efficient UAV Navigation via Potential-Based Reward Shaping, Control Lyapunov and Barrier Functions](http://arxiv.org/abs/2605.01787v1) | arXiv | 0.417 |
| 1704067200000 | [Constrained Reinforcement Learning with Smoothed Log Barrier Function](https://openreview.net/forum?id=3zar4HaKPW) | OpenReview | 0.583 |
| 1704067200000 | [OASIS: Conditional Distribution Shaping for Offline Safe Reinforcement Learning](https://openreview.net/forum?id=7lfMNvNMFj) | OpenReview | 0.417 |
| 1758215448348 | [Harmonic Constrained Reinforcement Learning](https://openreview.net/forum?id=CawuNEM1jE) | OpenReview | 0.333 |
| 1704067200000 | [Fear based Intrinsic Reward as a Barrier Function for Continuous Reinforcement Learning](https://openreview.net/forum?id=DHToyEBVMT) | OpenReview | 0.417 |
| 1738368000000 | [Reinforcement Learning based Constrained Optimal Control: an Interpretable Reward Design](https://openreview.net/forum?id=DbUuZrhOqp) | OpenReview | 0.5 |
| 1738368000000 | [Improving the Effectiveness of Potential-Based Reward Shaping in Reinforcement Learning](https://openreview.net/forum?id=HqWHxvZCMJ) | OpenReview | 0.917 |
| 1672531200000 | [Risk-Aware Reward Shaping of Reinforcement Learning Agents for Autonomous Driving](https://openreview.net/forum?id=IMlPdFbVIN) | OpenReview | 0.583 |
| 1609459200000 | [Temporal-Logic-Based Reward Shaping for Continuing Reinforcement Learning Tasks](https://openreview.net/forum?id=MhrATccbtk) | OpenReview | 0.75 |
| 1640995200000 | [A Simple Reward-free Approach to Constrained Reinforcement Learning](https://openreview.net/forum?id=PNhyPbC4z7) | OpenReview | 0.333 |
| 1695513826906 | [Logic-Based Adaptive Reward Shaping for Reinforcement Learning](https://openreview.net/forum?id=RPWs9kOv0I) | OpenReview | 0.5 |
| 1388534400000 | [Multi-objectivization of reinforcement learning problems by reward shaping](https://openreview.net/forum?id=dJu2kVsDTs) | OpenReview | 0.75 |
| 1758361657741 | [ROSARL: Reward-Only Safe Reinforcement Learning](https://openreview.net/forum?id=qcz3g6mH3L) | OpenReview | 0.333 |
| 1704067200000 | [Gradient shaping for multi-constraint safe reinforcement learning](https://openreview.net/forum?id=raOaiciHbs) | OpenReview | 0.333 |

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
| stanley_residual | unknown |
| balance_control | unknown |
| path_tracking | unknown |
| safety_gate | high |

## Agent-Executable Modification Templates
| Method | Layers | Template |
| --- | --- | --- |
| Safety / Constraint / Risk-Aware Reward | safety_gate | reward -= collision_penalty if min_distance < safe_distance else 0.0 |
| Safety / Constraint / Risk-Aware Reward | safety_gate | reward -= collision_penalty if min_distance < safe_distance else 0.0 |
| Safety / Constraint / Risk-Aware Reward | safety_gate | reward -= collision_penalty if min_distance < safe_distance else 0.0 |
| Safety / Constraint / Risk-Aware Reward | safety_gate | reward -= collision_penalty if min_distance < safe_distance else 0.0 |
| Safety / Constraint / Risk-Aware Reward | safety_gate | reward -= collision_penalty if min_distance < safe_distance else 0.0 |
| Safety / Constraint / Risk-Aware Reward | safety_gate | reward -= collision_penalty if min_distance < safe_distance else 0.0 |
| Safety / Constraint / Risk-Aware Reward | safety_gate | reward -= collision_penalty if min_distance < safe_distance else 0.0 |
| Safety / Constraint / Risk-Aware Reward | safety_gate | reward -= collision_penalty if min_distance < safe_distance else 0.0 |

## Risks And Reward Hacking
- Proxy rewards can dominate true task success.
- Safety penalties should be hard-gated where violations are unacceptable.
- Dynamic or generated rewards require regression checks against baseline controllers.
