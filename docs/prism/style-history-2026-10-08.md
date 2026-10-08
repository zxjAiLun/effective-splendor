# M72 早期模型历史画像与当前A/B对照

产物：早期Balance、初代、通用版及Alpha v0.1.0–v0.1.3均有实际数字并纳入对比。竞技：沿用冻结结论。风格：描述性参考，不用不同模式/seed历史范围证明路线确认。

## 与同一Alpha v0.1.5对手比赛：历史位置

每个精确模型仅选一组记录。双方greedy、同一精确对手，seed和轮次不同。旧模型采用M67父代与其对战中的opponent侧，A/B采用M67直接父对战的candidate侧；M66/M70使用各自对应记录。无需把不同对手池百分比硬合并。

| 模型 | 来源轮 | N | seed范围 | 低VP占比 | 大牌VP/局 | 贵族覆盖 | VP/Main |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: |
| Prism v0.1.0 | M67 | 5000 | 9830000–9832499 | 77.04% | 4.3394 | 42.10% | 0.4602 |
| Prism v0.1.1 | M67 | 5000 | 9830000–9832499 | 72.25% | 5.7718 | 39.86% | 0.4893 |
| Prism Alpha v0.1.4 | M67 | 5000 | 9830000–9832499 | 68.76% | 6.9474 | 37.64% | 0.5052 |
| Prism Balance v0.1.0 | M67 | 5000 | 9830000–9832499 | 68.85% | 6.8066 | 37.66% | 0.5204 |
| Prism Beta v0.1.0 | M67 | 5000 | 9830000–9832499 | 68.20% | 7.0098 | 36.68% | 0.5253 |
| Heuristic v0.3.1 | M67 | 5000 | 9830000–9832499 | 76.88% | 4.3792 | 42.76% | 0.4609 |
| M66 c4 | M66 | 1024 | 9711000–9711511 | 67.86% | 7.0635 | 37.30% | 0.5290 |
| M70 c4 | M70 | 512 | 10010000–10010255 | 67.08% | 7.3945 | 40.82% | 0.5418 |
| M67 A-c20 | M67 | 10000 | 9840000–9844999 | 65.73% | 7.9380 | 32.10% | 0.5302 |
| M67 B-c20 | M67 | 10000 | 9840000–9844999 | 67.93% | 7.3140 | 40.29% | 0.5405 |

| 当前−历史Balance | 低VP占比pp | 大牌VP/局 | 贵族覆盖pp | VP/Main |
| --- | ---: | ---: | ---: | ---: |
| M70 c4 | -1.77 | +0.5879 | +3.16 | +0.0214 |
| M67 A-c20 | -3.12 | +1.1314 | -5.56 | +0.0098 |
| M67 B-c20 | -0.92 | +0.5074 | +2.63 | +0.0201 |

A在这个相同对手视角下，小牌占比低于历史Balance而大牌印刷分更高；B小牌占比也略低，贵族覆盖和效率更高。B比A更重小牌/贵族，但仅凭这些终局数据仍不能确认Beta或Balance。

## M55早期共同池 · 本方T1

本方T1，按该轮共同池汇总；不同轮seed/对手实现可能不同，不是greedy路线确认。

对手：Heuristic v0.3.1 · greedy / Prism v0.1.0 · greedy

| 模型 | N | 本方模式 | 低VP张/局 | 低VP占比 | 大牌VP/局 | 贵族覆盖 | VP/Main | 首4–5VP本人Main | 购入覆盖 | 12Main低VP张/局 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Prism v0.1.1 | 1024 | T1 | 8.3145 | 67.92% | 7.2969 | 38.48% | 0.5510 | 未测 | 未测 | 未测 |
| Prism Alpha v0.1.0 | 1024 | T1 | 8.1611 | 67.58% | 7.7783 | 38.96% | 0.5563 | 未测 | 未测 | 未测 |

| 模型 | 0VP张/局 | 1VP | 2VP | 3VP | 4VP | 5VP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Prism v0.1.1 | 6.2305 | 2.0840 | 1.9717 | 0.8613 | 0.7559 | 0.3379 |
| Prism Alpha v0.1.0 | 6.1826 | 1.9785 | 1.8564 | 0.8525 | 0.8096 | 0.3965 |

## M55最初代与启发式 · 本方greedy

本方greedy，对手是通用版/Alpha初版的T1模式；与双方greedy分开。

对手：Prism v0.1.1 / Prism Alpha v0.1.0

| 模型 | N | 本方模式 | 低VP张/局 | 低VP占比 | 大牌VP/局 | 贵族覆盖 | VP/Main | 首4–5VP本人Main | 购入覆盖 | 12Main低VP张/局 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Heuristic v0.3.1 | 1024 | greedy | 10.0449 | 75.82% | 5.2832 | 49.71% | 0.5008 | 未测 | 未测 | 未测 |
| Prism v0.1.0 | 1024 | greedy | 9.9902 | 75.28% | 5.2100 | 46.29% | 0.4988 | 未测 | 未测 | 未测 |

| 模型 | 0VP张/局 | 1VP | 2VP | 3VP | 4VP | 5VP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Heuristic v0.3.1 | 7.4502 | 2.5947 | 1.7412 | 0.7764 | 0.4785 | 0.2080 |
| Prism v0.1.0 | 7.3740 | 2.6162 | 1.8242 | 0.8096 | 0.4561 | 0.1914 |

## M56早期共同池 · 本方T1

本方T1，按该轮共同池汇总；不同轮seed/对手实现可能不同，不是greedy路线确认。

对手：Heuristic v0.3.1 · greedy / Prism v0.1.0 · greedy / Prism v0.1.1 · T1

| 模型 | N | 本方模式 | 低VP张/局 | 低VP占比 | 大牌VP/局 | 贵族覆盖 | VP/Main | 首4–5VP本人Main | 购入覆盖 | 12Main低VP张/局 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Prism Alpha v0.1.0 | 1536 | T1 | 8.2617 | 67.96% | 7.5254 | 38.48% | 0.5467 | 20.7005 | 78.91% | 未测 |
| Prism Alpha v0.1.1 | 1536 | T1 | 8.1823 | 67.78% | 7.7194 | 39.71% | 0.5496 | 20.4940 | 81.58% | 未测 |

| 模型 | 0VP张/局 | 1VP | 2VP | 3VP | 4VP | 5VP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Prism Alpha v0.1.0 | 6.2507 | 2.0111 | 1.8854 | 0.8555 | 0.8092 | 0.3444 |
| Prism Alpha v0.1.1 | 6.2435 | 1.9388 | 1.8411 | 0.8477 | 0.8294 | 0.3717 |

## M59早期共同池 · 本方T1

本方T1，按该轮共同池汇总；不同轮seed/对手实现可能不同，不是greedy路线确认。

对手：Heuristic portable v0.2.9 · greedy / Prism v0.1.0 · greedy / Prism v0.1.1 · T1

| 模型 | N | 本方模式 | 低VP张/局 | 低VP占比 | 大牌VP/局 | 贵族覆盖 | VP/Main | 首4–5VP本人Main | 购入覆盖 | 12Main低VP张/局 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Prism Alpha v0.1.1 | 1536 | T1 | 8.5182 | 69.42% | 7.5671 | 41.86% | 0.5465 | 20.5880 | 80.60% | 未测 |
| Prism Alpha v0.1.2 | 1536 | T1 | 8.1068 | 67.50% | 7.8809 | 38.54% | 0.5528 | 20.3812 | 81.64% | 未测 |

| 模型 | 0VP张/局 | 1VP | 2VP | 3VP | 4VP | 5VP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Prism Alpha v0.1.1 | 6.4297 | 2.0885 | 1.7480 | 0.8366 | 0.7793 | 0.3880 |
| Prism Alpha v0.1.2 | 6.1921 | 1.9147 | 1.8216 | 0.8470 | 0.8320 | 0.4023 |

## M60早期共同池 · 本方T1

本方T1，按该轮共同池汇总；不同轮seed/对手实现可能不同，不是greedy路线确认。

对手：Heuristic portable v0.2.9 · greedy / Prism v0.1.0 · greedy / Prism v0.1.1 · T1

| 模型 | N | 本方模式 | 低VP张/局 | 低VP占比 | 大牌VP/局 | 贵族覆盖 | VP/Main | 首4–5VP本人Main | 购入覆盖 | 12Main低VP张/局 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Prism Alpha v0.1.2 | 1536 | T1 | 8.0007 | 66.89% | 7.7005 | 35.29% | 0.5510 | 20.2724 | 81.51% | 未测 |
| Prism Alpha v0.1.3 | 1536 | T1 | 7.7617 | 65.90% | 7.9277 | 33.72% | 0.5559 | 20.2104 | 82.62% | 未测 |

| 模型 | 0VP张/局 | 1VP | 2VP | 3VP | 4VP | 5VP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Prism Alpha v0.1.2 | 6.0514 | 1.9492 | 1.9173 | 0.8457 | 0.8197 | 0.3770 |
| Prism Alpha v0.1.3 | 5.8555 | 1.9062 | 1.9180 | 0.8620 | 0.8366 | 0.3991 |

## M61早期共同池 · 本方T1

本方T1，按该轮共同池汇总；不同轮seed/对手实现可能不同，不是greedy路线确认。

对手：Heuristic v0.3.1 · greedy / Prism v0.1.0 · greedy / Prism v0.1.1 · T1

| 模型 | N | 本方模式 | 低VP张/局 | 低VP占比 | 大牌VP/局 | 贵族覆盖 | VP/Main | 首4–5VP本人Main | 购入覆盖 | 12Main低VP张/局 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Prism Alpha v0.1.3 | 1536 | T1 | 7.8743 | 66.62% | 8.0273 | 37.63% | 0.5551 | 19.9710 | 83.20% | 未测 |
| Prism Alpha v0.1.4 | 1536 | T1 | 7.6445 | 65.63% | 8.1589 | 34.83% | 0.5594 | 19.6582 | 84.96% | 未测 |
| Prism Balance v0.1.0 | 1536 | T1 | 7.8040 | 66.33% | 7.9395 | 36.33% | 0.5563 | 19.9196 | 81.84% | 未测 |

| 模型 | 0VP张/局 | 1VP | 2VP | 3VP | 4VP | 5VP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Prism Alpha v0.1.3 | 6.0299 | 1.8444 | 1.8210 | 0.8867 | 0.8242 | 0.4141 |
| Prism Alpha v0.1.4 | 5.8685 | 1.7760 | 1.8581 | 0.8516 | 0.8639 | 0.4297 |
| Prism Balance v0.1.0 | 5.8971 | 1.9069 | 1.8659 | 0.8633 | 0.8092 | 0.4225 |

## M62早期共同池 · 本方T1

本方T1，按该轮共同池汇总；不同轮seed/对手实现可能不同，不是greedy路线确认。

对手：Heuristic v0.3.1 · greedy / Prism v0.1.0 · greedy / Prism v0.1.1 · T1

| 模型 | N | 本方模式 | 低VP张/局 | 低VP占比 | 大牌VP/局 | 贵族覆盖 | VP/Main | 首4–5VP本人Main | 购入覆盖 | 12Main低VP张/局 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Prism Balance v0.1.0 | 1536 | T1 | 7.7949 | 66.27% | 8.0202 | 36.72% | 0.5625 | 20.1169 | 83.53% | 3.9570 |
| Prism Beta v0.1.0 | 1536 | T1 | 7.6738 | 65.86% | 8.0944 | 36.59% | 0.5645 | 20.2429 | 84.96% | 3.8880 |

| 模型 | 0VP张/局 | 1VP | 2VP | 3VP | 4VP | 5VP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Prism Balance v0.1.0 | 5.7669 | 2.0280 | 1.8587 | 0.8190 | 0.8822 | 0.4069 |
| Prism Beta v0.1.0 | 5.7161 | 1.9577 | 1.8587 | 0.8099 | 0.8848 | 0.4251 |

## M63早期Balance共同池 · 双方greedy

相同轮对手与seed；版本名称按精确SHA恢复，旧Beta实验标签没有当成发布名。

对手：Prism Alpha v0.1.4 / Heuristic v0.3.1 / Prism Beta v0.1.0 / Prism v0.1.1 / Prism v0.1.0

| 模型 | N | 本方模式 | 低VP张/局 | 低VP占比 | 大牌VP/局 | 贵族覆盖 | VP/Main | 首4–5VP本人Main | 购入覆盖 | 12Main低VP张/局 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Prism Balance v0.1.0 | 1280 | greedy | 7.9461 | 67.36% | 7.6016 | 37.34% | 0.5488 | 未测 | 未测 | 未测 |
| Prism Alpha v0.1.5 | 1280 | greedy | 7.7828 | 66.61% | 7.6680 | 34.84% | 0.5516 | 未测 | 未测 | 未测 |

| 模型 | 0VP张/局 | 1VP | 2VP | 3VP | 4VP | 5VP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Prism Balance v0.1.0 | 5.8617 | 2.0844 | 1.8367 | 0.8258 | 0.8133 | 0.3742 |
| Prism Alpha v0.1.5 | 5.6656 | 2.1172 | 1.8727 | 0.8180 | 0.8406 | 0.3703 |

## M65早期Balance共同池 · 双方greedy

相同轮对手与seed；版本名称按精确SHA恢复，旧Beta实验标签没有当成发布名。

对手：Prism Alpha v0.1.4 / Heuristic v0.3.1 / Prism v0.1.1 / Prism v0.1.0

| 模型 | N | 本方模式 | 低VP张/局 | 低VP占比 | 大牌VP/局 | 贵族覆盖 | VP/Main | 首4–5VP本人Main | 购入覆盖 | 12Main低VP张/局 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Prism Balance v0.1.0 | 1024 | greedy | 7.9727 | 67.07% | 7.4297 | 36.13% | 0.5520 | 未测 | 未测 | 未测 |
| Prism Beta v0.1.0 | 1024 | greedy | 7.7178 | 66.18% | 7.8359 | 33.98% | 0.5564 | 未测 | 未测 | 未测 |

| 模型 | 0VP张/局 | 1VP | 2VP | 3VP | 4VP | 5VP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Prism Balance v0.1.0 | 5.8926 | 2.0801 | 1.9570 | 0.7979 | 0.7598 | 0.3994 |
| Prism Beta v0.1.0 | 5.7217 | 1.9961 | 1.8926 | 0.8203 | 0.7773 | 0.4531 |

## 计算与来源

低VP占比=Σ0–1VP张数/Σ购牌数；大牌VP/局=Σ3–5VP印刷分/N；贵族覆盖=有贵族局数/N；VP/Main=Σ最终VP/Σ本人Main。首大牌Main仅在实际购入局求均值，按购入覆盖局数合并。首次时点/覆盖缺项不填0。

模式来源：M55/M56保存的实际anchors配置；M59/M60冻结evaluation模式与已完成结果，M61/M62保存execution模式与结果；M63/M65保存greedy配置/plan/结果SHA一致。模式声明审计未重新执行历史回放或Rust规则。完整双方逐对手数据仍保留在原结果，CSV为此次派生画像。

历史模式不混合成统一风格阈值。所有新分类政策仍为事后描述性；未发布/晋级任何新版本。

### 来源SHA

- `benchmarks/prism-style-delivery-2026-10-08.json` SHA `ca60cc1e6db939044c5950495cf11376b7fba8544086f7b6176001f3d9009c92`
- `benchmarks/m55-prism-rush-v0.1.0.result.json` SHA `9093d26aa1b8a31fd3874b4b79f046bf098755587a49f0eea345e03649bcac57`
- `local-artifacts/prism/rush-v0.1.0/acceptance/configs/anchors-0.json` SHA `6dc1ed8f00841a403cde1d6676dbe87e4bab71de3da12518930d3af88acad3ec`
- `benchmarks/m56-prism-alpha-v0.1.1.result.json` SHA `3e0059c627feace99eaaeb9ea5380b591ef1e5927569d33ce4e3be981ec5c37c`
- `local-artifacts/prism/alpha-v0.1.1/acceptance/configs/anchors-0.json` SHA `f9bef2ea7b9d55744a52091afdde3b90534e6c48616e5c06bfcb70d301552ab2`
- `benchmarks/m59-prism-alpha-cloud-ppo.evaluation-result.json` SHA `c4c1d4704b9bf2ad1d8a1c6502a635a8327dc9f525726eb7684143a30a2ecf37`
- `benchmarks/m59-prism-alpha-cloud-ppo.config.json` SHA `cab7dde789ffc96c20f6b22b8acb58ae3c1d48477f9b388bf19867d0ddb2f3ac`
- `benchmarks/m60-prism-alpha-cloud-ppo.evaluation-result.json` SHA `d475cf9f3409ccf735ea5f310879c4b223ce1696d3c4a19fed32dfa8058cd22b`
- `benchmarks/m60-prism-alpha-cloud-ppo.config.json` SHA `afa21fc1e588ecc80e8bab64ca08392448758d68d47544900f48b8eaa9f89c4b`
- `local-artifacts/prism/balance-ab-m61/result.json` SHA `37834fd4571503b269924f6ab62d9dd423a6b7d8e317f75a8930c1d96c46c6a4`
- `local-artifacts/prism/balance-ab-m61/execution.json` SHA `ba117541dce0350f83f0123b8f85b3388d17e5f9b85040cf314812595651171c`
- `local-artifacts/prism/building-beta-m62/evaluation/result.json` SHA `4306fcff0eb53bbeca9113f58e5b05c97a9bf22d2d6e7fe67999ac563a790ede`
- `local-artifacts/prism/building-beta-m62/evaluation/execution.json` SHA `b65daae1148a1467df4d64d51a0fbf3fa62bb9a9400060d07fcc3f4666f22cfd`
- `benchmarks/m63-greedy-report-supplement.result.json` SHA `3c75b6cc55c854b15eb93131ed4419bc20ba790475f93a21cf7981d3ce18d1df`
- `local-artifacts/prism/m63-dsw-r2/greedy-r3/common/result.json` SHA `700a90fd46ff4c81a1d776ba5bd62a663a152b7cc7f1da974f848fc6ce11dafb`
- `local-artifacts/prism/m63-dsw-r2/greedy-r3/common/config.json` SHA `bdc309afd3d2fd43b38cd5549175460e10d5f1baeebd873a8da21f5366f63490`
- `local-artifacts/prism/m63-dsw-r2/greedy-r3/common/plan.json` SHA `7e4c989d16641e5c754be96d98b09eea3ce8b12e26397af477f062387d05c17b`
- `benchmarks/m65-prism-version-release.result.json` SHA `5f9689946765d0c1d4995108ada0576ff9fe47413869dfa49a8bcf335c2a01ab`
- `local-artifacts/prism/m65-release/harvest/release-evaluation/common/result.json` SHA `0af5a1da45f06d0c9fe18de2b79f4657a5e3b8f3aee57668e8fca4b76299f691`
- `local-artifacts/prism/m65-release/harvest/release-evaluation/common/config.json` SHA `a697e5b0f710166b94c2903093ed95e18d55d95cfe5a8bdf10c4a5b72dd82cb9`
- `local-artifacts/prism/m65-release/harvest/release-evaluation/common/plan.json` SHA `cdd6277c4bf6615d8533deb0cf2d55e757d73fdd9c449396fd8110b478d0897f`
