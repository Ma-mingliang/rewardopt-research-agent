# F_residual_aware_reward: Residual-Aware Reward / Residual RL / Classical Controller Residual

## Category Definition
base controller residual action, residual magnitude penalty, residual smoothness penalty, classical controller is not modified, RL learns correction only

## Typical Reward Formula
`u = u_base + u_residual; R = R_task - lambda * ||u_residual||^2`

## Representative Papers
| Year | Paper | Venue | Score |
| --- | --- | --- | --- |
| 1730712292908 | [Learning Discrete World Models for Heuristic Search](https://openreview.net/forum?id=1DGP543oHN) | OpenReview | 0.333 |
| 1199145600000 | [EXAM: An Environment for Access Control Policy Analysis and Management](https://openreview.net/forum?id=82vBpvHEgR) | OpenReview | 0.333 |
| 1727793680555 | [Improving Generalization in Visual Reinforcement Learning via Conflict-aware Gradient Agreement Augmentation](https://openreview.net/forum?id=DPkAk1oh3X) | OpenReview | 0.75 |
| 1748209083247 | [Accelerating Residual Reinforcement Learning with Uncertainty Estimation](https://openreview.net/forum?id=HUSLmVdg5K) | OpenReview | 0.333 |
| 1751328000000 | [Residual Reward Models for Preference-based Reinforcement Learning](https://openreview.net/forum?id=IsxDQZVhoX) | OpenReview | 0.583 |
| 1740787200000 | [Transfer Learning for LQR Control](https://openreview.net/forum?id=JY750IH1y0) | OpenReview | 0.333 |
| 1704067200000 | [Meta-learning linear quadratic regulators: A policy gradient MAML approach for model-free LQR](https://openreview.net/forum?id=L8PjfrpUUQ) | OpenReview | 0.333 |
| 1746833099373 | [Certifying Stability of Reinforcement Learning Policies using Generalized Lyapunov Functions](https://openreview.net/forum?id=N67DlqK5C4) | OpenReview | 0.333 |
| 1778353082751 | [What Makes Value Learning Efficient in Residual Reinforcement Learning?](https://openreview.net/forum?id=Pech3Gfc9D) | OpenReview | 0.333 |
| 1672531200000 | [An Efficient Off-Policy Reinforcement Learning Algorithm for the Continuous-Time LQR Problem](https://openreview.net/forum?id=aR9uZ1TmsZ) | OpenReview | 0.333 |
| 1704067200000 | [RESPRECT: Speeding-up Multi-Fingered Grasping With Residual Reinforcement Learning](https://openreview.net/forum?id=dZmD1PbTc5) | OpenReview | 0.333 |
| 1672531200000 | [Policy Evaluation in Distributional LQR](https://openreview.net/forum?id=mjarXZkE30) | OpenReview | 0.333 |
| 1199145600000 | [Policy Management across Multiple Platforms and Application Domains](https://openreview.net/forum?id=tcz7UWKrTT) | OpenReview | 0.333 |
| 1704067200000 | [Residual Policy Learning for Perceptive Quadruped Control Using Differentiable Simulation](https://openreview.net/forum?id=vK9j25HI1O) | OpenReview | 0.333 |

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
| balance_control | unknown |
| path_tracking | unknown |
| safety_gate | unknown |

## Agent-Executable Modification Templates
| Method | Layers | Template |
| --- | --- | --- |
| Residual-Aware Reward / Residual RL / Classical Controller Residual | lqr_residual, stanley_residual | u = u_base + u_res; reward -= lambda_res * dot(u_res, u_res) + lambda_smooth * norm(u_res - prev_u_res) |
| Residual-Aware Reward / Residual RL / Classical Controller Residual | lqr_residual, stanley_residual | u = u_base + u_res; reward -= lambda_res * dot(u_res, u_res) + lambda_smooth * norm(u_res - prev_u_res) |
| Residual-Aware Reward / Residual RL / Classical Controller Residual | lqr_residual, stanley_residual | u = u_base + u_res; reward -= lambda_res * dot(u_res, u_res) + lambda_smooth * norm(u_res - prev_u_res) |
| Residual-Aware Reward / Residual RL / Classical Controller Residual | lqr_residual, stanley_residual | u = u_base + u_res; reward -= lambda_res * dot(u_res, u_res) + lambda_smooth * norm(u_res - prev_u_res) |
| Residual-Aware Reward / Residual RL / Classical Controller Residual | lqr_residual, stanley_residual | u = u_base + u_res; reward -= lambda_res * dot(u_res, u_res) + lambda_smooth * norm(u_res - prev_u_res) |
| Residual-Aware Reward / Residual RL / Classical Controller Residual | lqr_residual, stanley_residual | u = u_base + u_res; reward -= lambda_res * dot(u_res, u_res) + lambda_smooth * norm(u_res - prev_u_res) |
| Residual-Aware Reward / Residual RL / Classical Controller Residual | lqr_residual, stanley_residual | u = u_base + u_res; reward -= lambda_res * dot(u_res, u_res) + lambda_smooth * norm(u_res - prev_u_res) |
| Residual-Aware Reward / Residual RL / Classical Controller Residual | lqr_residual, stanley_residual | u = u_base + u_res; reward -= lambda_res * dot(u_res, u_res) + lambda_smooth * norm(u_res - prev_u_res) |

## Risks And Reward Hacking
- Proxy rewards can dominate true task success.
- Safety penalties should be hard-gated where violations are unacceptable.
- Dynamic or generated rewards require regression checks against baseline controllers.
