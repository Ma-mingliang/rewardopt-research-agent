# A_potential_based_reward: Potential-Based Reward Shaping

## Category Definition
gamma * Phi(s_next) - Phi(s), policy invariance, shaping reward, potential function, tracking improvement reward

## Typical Reward Formula
`R'(s,a,s') = R(s,a,s') + gamma * Phi(s') - Phi(s)`

## Representative Papers
| Year | Paper | Venue | Score |
| --- | --- | --- | --- |
| 2019 | [A new Potential-Based Reward Shaping for Reinforcement Learning Agent](http://arxiv.org/abs/1902.06239v3) | arXiv | 0.333 |
| 2020 | [Learning to Run with Potential-Based Reward Shaping and Demonstrations from Video Data](http://arxiv.org/abs/2012.08824v1) | arXiv | 0.5 |
| 2021 | [Subgoal-based Reward Shaping to Improve Efficiency in Reinforcement Learning](http://arxiv.org/abs/2104.06411v1) | arXiv | 0.333 |
| 2021 | [Potential-based Reward Shaping in Sokoban](http://arxiv.org/abs/2109.05022v1) | arXiv | 0.417 |
| 2021 | [Hierarchical Potential-based Reward Shaping from Task Specifications](http://arxiv.org/abs/2110.02792v3) | arXiv | 0.333 |
| 2023 | [Toward Computationally Efficient Inverse Reinforcement Learning via Reward Shaping](http://arxiv.org/abs/2312.09983v2) | arXiv | 0.333 |
| 2024 | [Potential-Based Reward Shaping For Intrinsic Motivation](http://arxiv.org/abs/2402.07411v1) | arXiv | 0.333 |
| 2024 | [On the Sample Efficiency of Abstractions and Potential-Based Reward Shaping in Reinforcement Learning](http://arxiv.org/abs/2404.07826v2) | arXiv | 0.417 |
| 2025 | [Improving the Effectiveness of Potential-Based Reward Shaping in Reinforcement Learning](http://arxiv.org/abs/2502.01307v1) | arXiv | 0.583 |
| 2025 | [Robo-Dopamine: General Process Reward Modeling for High-Precision Robotic Manipulation](http://arxiv.org/abs/2512.23703v1) | arXiv | 0.417 |
| 2026 | [Zero-Shot, Safe and Time-Efficient UAV Navigation via Potential-Based Reward Shaping, Control Lyapunov and Barrier Functions](http://arxiv.org/abs/2605.01787v1) | arXiv | 0.417 |
| 1640995200000 | [Shaping Advice in Deep Reinforcement Learning](https://openreview.net/forum?id=0iouIeL5Nm) | OpenReview | 0.417 |
| 1704067200000 | [Enhancing Embedding and Hierarchical Reward Shaping for Multi-Hop Reasoning with Reinforcement Learning](https://openreview.net/forum?id=3NAPbA3fN3) | OpenReview | 0.5 |
| 1640995200000 | [Reward Shaping Using Convolutional Neural Network](https://openreview.net/forum?id=6lm1jxxLXb) | OpenReview | 0.75 |
| 1325376000000 | [Automated Policy Analysis](https://openreview.net/forum?id=84XY6nHYsD) | OpenReview | 0.333 |

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
| Potential-Based Reward Shaping | stanley_residual, path_tracking | tracking_improvement = abs(e_t) - abs(e_t1); reward += k_phi * tracking_improvement |
| Potential-Based Reward Shaping | stanley_residual, path_tracking | tracking_improvement = abs(e_t) - abs(e_t1); reward += k_phi * tracking_improvement |
| Potential-Based Reward Shaping | stanley_residual, path_tracking | tracking_improvement = abs(e_t) - abs(e_t1); reward += k_phi * tracking_improvement |
| Potential-Based Reward Shaping | stanley_residual, path_tracking | tracking_improvement = abs(e_t) - abs(e_t1); reward += k_phi * tracking_improvement |
| Potential-Based Reward Shaping | stanley_residual, path_tracking | tracking_improvement = abs(e_t) - abs(e_t1); reward += k_phi * tracking_improvement |
| Potential-Based Reward Shaping | stanley_residual, path_tracking | tracking_improvement = abs(e_t) - abs(e_t1); reward += k_phi * tracking_improvement |
| Potential-Based Reward Shaping | stanley_residual, path_tracking | tracking_improvement = abs(e_t) - abs(e_t1); reward += k_phi * tracking_improvement |
| Potential-Based Reward Shaping | stanley_residual, path_tracking | tracking_improvement = abs(e_t) - abs(e_t1); reward += k_phi * tracking_improvement |

## Risks And Reward Hacking
- Proxy rewards can dominate true task success.
- Safety penalties should be hard-gated where violations are unacceptable.
- Dynamic or generated rewards require regression checks against baseline controllers.
