# H_learned_preference_reward: Learned Reward / Preference / IRL / Reward Model

## Category Definition
learned reward, reward model, preference learning, inverse RL, demonstrations, human feedback

## Typical Reward Formula
`R_hat = f_theta(s, a, preference_or_demo)`

## Representative Papers
| Year | Paper | Venue | Score |
| --- | --- | --- | --- |
| 2020 | [Safe Imitation Learning via Fast Bayesian Reward Inference from Preferences](http://arxiv.org/abs/2002.09089v4) | arXiv | 0.417 |
| 2020 | [Learning to Run with Potential-Based Reward Shaping and Demonstrations from Video Data](http://arxiv.org/abs/2012.08824v1) | arXiv | 0.5 |
| 2023 | [Infer and Adapt: Bipedal Locomotion Reward Learning from Demonstrations via Inverse Reinforcement Learning](http://arxiv.org/abs/2309.16074v1) | arXiv | 0.417 |
| 2025 | [Subtask-Aware Visual Reward Learning from Segmented Demonstrations](http://arxiv.org/abs/2502.20630v1) | arXiv | 0.417 |
| 2025 | [Robo-Dopamine: General Process Reward Modeling for High-Precision Robotic Manipulation](http://arxiv.org/abs/2512.23703v1) | arXiv | 0.417 |
| 1758259419628 | [Subgoal-Guided Reward Shaping: Improving Preference-Based Offline Reinforcement Learning via Conditional VAEs](https://openreview.net/forum?id=5T1vMQldr8) | OpenReview | 0.583 |
| 1704067200000 | [OASIS: Conditional Distribution Shaping for Offline Safe Reinforcement Learning](https://openreview.net/forum?id=7lfMNvNMFj) | OpenReview | 0.417 |
| 1686139787720 | [Robustness of Inverse Reinforcement Learning](https://openreview.net/forum?id=86r7EKxWdF) | OpenReview | 0.417 |
| 1672531200000 | [Inverse Reinforcement Learning with the Average Reward Criterion](https://openreview.net/forum?id=FxhzmAU9Ac) | OpenReview | 0.333 |
| 1695491091791 | [Eureka: Human-Level Reward Design via Coding Large Language Models](https://openreview.net/forum?id=IEduRUO55F) | OpenReview | 0.417 |
| 1751328000000 | [Residual Reward Models for Preference-based Reinforcement Learning](https://openreview.net/forum?id=IsxDQZVhoX) | OpenReview | 0.583 |
| 1612815796474 | [Leveraging multi-view learning for human anomaly detection in industrial internet of things](https://openreview.net/forum?id=KW0mzfVmb0) | OpenReview | 0.417 |
| 1715724069512 | [Robot Policy Learning with Temporal Optimal Transport Reward](https://openreview.net/forum?id=LEed5Is4oi) | OpenReview | 0.417 |
| 1483228800000 | [Improved reward estimation for efficient robot navigation using inverse reinforcement learning](https://openreview.net/forum?id=OTvXlEdYHq) | OpenReview | 0.333 |
| 1745469789760 | [HALO : Human Preference Aligned Offline Reward Learning for Robot Navigation](https://openreview.net/forum?id=PMKwnV6Azi) | OpenReview | 0.417 |

## GitHub Implementations
| Repo | Stars | Reward Files | License |
| --- | --- | --- | --- |
| [EleutherAI/gpt-neox](https://github.com/EleutherAI/gpt-neox) | 7435 | eval_tasks | Apache-2.0 |
| [InternLM/InternLM](https://github.com/InternLM/InternLM) | 7216 |  | Apache-2.0 |
| [OpenRLHF/OpenRLHF](https://github.com/OpenRLHF/OpenRLHF) | 9600 |  | Apache-2.0 |
| [Yangyi-Chen/Multimodal-AND-Large-Language-Models](https://github.com/Yangyi-Chen/Multimodal-AND-Large-Language-Models) | 759 |  |  |
| [ace-step/ACE-Step-1.5](https://github.com/ace-step/ACE-Step-1.5) | 10870 |  | MIT |
| [eureka-research/Eureka](https://github.com/eureka-research/Eureka) | 3162 | isaacgymenvs | MIT |
| [hijkzzz/Awesome-LLM-Strawberry](https://github.com/hijkzzz/Awesome-LLM-Strawberry) | 6896 |  | Apache-2.0 |
| [lucidrains/PaLM-rlhf-pytorch](https://github.com/lucidrains/PaLM-rlhf-pytorch) | 7863 |  | MIT |
| [mbzuai-oryx/Awesome-LLM-Post-training](https://github.com/mbzuai-oryx/Awesome-LLM-Post-training) | 2431 |  |  |
| [modelscope/ms-swift](https://github.com/modelscope/ms-swift) | 14414 |  | Apache-2.0 |

## HRRL Transfer
Use the method only as a local reward component and keep safety checks outside the learned residual action.

## Control Layer Fit
| Layer | Fit |
| --- | --- |
| lqr_residual | high |
| stanley_residual | high |
| balance_control | unknown |
| path_tracking | high |
| safety_gate | high |

## Agent-Executable Modification Templates
| Method | Layers | Template |
| --- | --- | --- |
| Learned Reward / Preference / IRL / Reward Model | path_tracking | reward = reward_model.predict(obs, action); reward -= safety_penalty |
| Learned Reward / Preference / IRL / Reward Model | path_tracking | reward = reward_model.predict(obs, action); reward -= safety_penalty |
| Learned Reward / Preference / IRL / Reward Model | path_tracking | reward = reward_model.predict(obs, action); reward -= safety_penalty |
| Learned Reward / Preference / IRL / Reward Model | lqr_residual, stanley_residual | reward = reward_model.predict(obs, action); reward -= safety_penalty |
| Learned Reward / Preference / IRL / Reward Model | path_tracking | reward = reward_model.predict(obs, action); reward -= safety_penalty |
| Learned Reward / Preference / IRL / Reward Model | path_tracking | reward = reward_model.predict(obs, action); reward -= safety_penalty |
| Learned Reward / Preference / IRL / Reward Model | path_tracking | reward = reward_model.predict(obs, action); reward -= safety_penalty |
| Learned Reward / Preference / IRL / Reward Model | safety_gate | reward = reward_model.predict(obs, action); reward -= safety_penalty |

## Risks And Reward Hacking
- Proxy rewards can dominate true task success.
- Safety penalties should be hard-gated where violations are unacceptable.
- Dynamic or generated rewards require regression checks against baseline controllers.
