# G_llm_reward_generation: LLM Reward Generation / Automated Reward Design

## Category Definition
LLM generates reward code, iterative reward improvement, reward evolution, reward code search, feedback from training logs

## Typical Reward Formula
`reward_code = LLM(task, logs, feedback); R = execute(reward_code)`

## Representative Papers
| Year | Paper | Venue | Score |
| --- | --- | --- | --- |
| 1738368000000 | [Reinforcement Learning based Constrained Optimal Control: an Interpretable Reward Design](https://openreview.net/forum?id=DbUuZrhOqp) | OpenReview | 0.5 |
| 1609459200000 | [Recent Developments of Automated Machine Learning and Search Techniques](https://openreview.net/forum?id=G9YLcFd8bQ) | OpenReview | 0.333 |
| 1695491091791 | [Eureka: Human-Level Reward Design via Coding Large Language Models](https://openreview.net/forum?id=IEduRUO55F) | OpenReview | 0.417 |
| 1748210920806 | [An Empirical Study on Reinforcement Learning for Reasoning-Search Interleaved LLM Agents](https://openreview.net/forum?id=IQNZIBspz5) | OpenReview | 0.333 |
| 1758311563996 | [ARM-FM: Automated Reward Machines via Foundation Models for Compositional Reinforcement Learning](https://openreview.net/forum?id=OBpQdCWLfd) | OpenReview | 0.417 |
| 1199145600000 | [Eureka: A Framework for Enabling Static Malware Analysis](https://openreview.net/forum?id=Q01nZXiWLT) | OpenReview | 0.333 |
| 1767752224472 | [Reward Modeling for Reinforcement Learning-Based LLM Reasoning: Design, Challenges, and Evaluation](https://openreview.net/forum?id=TDfrN1TbGH) | OpenReview | 0.417 |
| 1672531200000 | [Reward Function Design for Crowd Simulation via Reinforcement Learning](https://openreview.net/forum?id=bm6MwNd9UH) | OpenReview | 0.333 |
| 1756508137534 | [Automated Reward Design for Gran Turismo](https://openreview.net/forum?id=cmN54vPKsz) | OpenReview | 0.417 |
| 1756828159274 | [Reinforcing Multi-Turn Reasoning in LLM Agents via Turn-Level Reward Design and Credit Assignment](https://openreview.net/forum?id=drP7qVUnUt) | OpenReview | 0.333 |
| 1756830321920 | [Sotopia-RL: Reward Design for Social Intelligence](https://openreview.net/forum?id=gBwovFgeK8) | OpenReview | 0.417 |
| 1609459200000 | [A General Model for Automated Algorithm Design](https://openreview.net/forum?id=sVMCdIqO2I) | OpenReview | 0.333 |
| 1704067200000 | [Eureka: Evaluating and Understanding Large Foundation Models](https://openreview.net/forum?id=u07FUAQgcT) | OpenReview | 0.333 |

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
| path_tracking | high |
| safety_gate | high |

## Agent-Executable Modification Templates
| Method | Layers | Template |
| --- | --- | --- |
| LLM Reward Generation / Automated Reward Design | path_tracking | reward_fn = load_candidate_reward_code(); reward = reward_fn(obs, action, next_obs, logs) |
| LLM Reward Generation / Automated Reward Design | safety_gate | reward_fn = load_candidate_reward_code(); reward = reward_fn(obs, action, next_obs, logs) |
| LLM Reward Generation / Automated Reward Design | path_tracking | reward_fn = load_candidate_reward_code(); reward = reward_fn(obs, action, next_obs, logs) |
| LLM Reward Generation / Automated Reward Design | path_tracking | reward_fn = load_candidate_reward_code(); reward = reward_fn(obs, action, next_obs, logs) |
| LLM Reward Generation / Automated Reward Design | path_tracking | reward_fn = load_candidate_reward_code(); reward = reward_fn(obs, action, next_obs, logs) |
| LLM Reward Generation / Automated Reward Design | path_tracking | reward_fn = load_candidate_reward_code(); reward = reward_fn(obs, action, next_obs, logs) |
| LLM Reward Generation / Automated Reward Design | path_tracking | reward_fn = load_candidate_reward_code(); reward = reward_fn(obs, action, next_obs, logs) |
| LLM Reward Generation / Automated Reward Design | path_tracking | reward_fn = load_candidate_reward_code(); reward = reward_fn(obs, action, next_obs, logs) |

## Risks And Reward Hacking
- Proxy rewards can dominate true task success.
- Safety penalties should be hard-gated where violations are unacceptable.
- Dynamic or generated rewards require regression checks against baseline controllers.
