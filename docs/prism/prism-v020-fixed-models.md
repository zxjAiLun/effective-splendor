# Prism 固定研究版本与Balance数据基线

已按用户指定固定三份研究版本；B作为Balance v0.2.0数据参照，A是Alpha v0.2.0，M70是Balance v0.2.1。路线登记与风格确认分开。

| 固定型号 | 原检查点 | 训练父代 | 用途 |
| --- | --- | --- | --- |
| Prism Alpha v0.2.0 | M67 A-c20 | Prism Alpha v0.1.5 | 大牌路线研究版本 |
| Prism Balance v0.2.0 | M67 B-c20 | Prism Alpha v0.1.5 | 固定数据基线 |
| Prism Balance v0.2.1 | M70 c4 | Prism Balance v0.2.0 | Balance后续研究版本 |

M67 A/B的真实训练父代均为Alpha v0.1.5；M70从B权重fresh AdamW/RNG初始化。给B分配Balance不会改写它的训练血缘。Beta v0.2.0本次没有分配。

## B的固定数据参照

三组均为B同一精确权重，不同对手/seed范围分别保留，不平均成一个全局阈值。

| 统计组 | N | 低VP占比 | 大牌VP/局 | 贵族覆盖 | VP/Main |
| --- | ---: | ---: | ---: | ---: | ---: |
| M67-main | 30000 | 66.48% | 7.8551 | 39.09% | 0.5625 |
| M70-main | 3072 | 67.53% | 7.6146 | 41.11% | 0.5519 |
| H-Greedy-Alpha15 | 10000 | 67.93% | 7.3140 | 40.29% | 0.5405 |

新比较应选与候选相同的greedy模式、对手、seed、双座及规则cohort。M70共同池已有匹配B参照；不同历史轮不冒充配对确认。B的首次大牌/早期投资及真实兑现缺项仍为未测，固定参照不是统计学均衡确认。

## 原结果保留

A共同池缺5项（29995/30000），正式共同池增强未确认；B原完整评测增强通过，结论限冻结池；M70保留通过、共同池增强通过，直接父代增强未确认。研究方法跨训练seed的可重复增强未建立。未默认替换/池或Studio部署。

## 精确身份与来源

- [Prism Alpha v0.2.0](../../benchmarks/m72-prism-alpha-v0.2.0.model.json)：权重SHA `db3e2da279d777485c4dbb3d8d2ff78ddb106d231d5c75b58bc783e4fb66acb5`；[固定权重](../../local-artifacts/prism/alpha-v0.2.0/weights.json)；[伴随清单](../../local-artifacts/prism/alpha-v0.2.0/weights.manifest.json)。
- [Prism Balance v0.2.0](../../benchmarks/m72-prism-balance-v0.2.0.model.json)：权重SHA `e2914425cac49f0f2272c44379e46a43525d97ced2eaac206e8600ebf73e79c4`；[固定权重](../../local-artifacts/prism/balance-v0.2.0/weights.json)；[伴随清单](../../local-artifacts/prism/balance-v0.2.0/weights.manifest.json)。
- [Prism Balance v0.2.1](../../benchmarks/m72-prism-balance-v0.2.1.model.json)：权重SHA `f4a9a628a9a0a376a84b2bc0f3b002e652bde42d4e1e4b3170a1830e3b14238a`；[固定权重](../../local-artifacts/prism/balance-v0.2.1/weights.json)；[伴随清单](../../local-artifacts/prism/balance-v0.2.1/weights.manifest.json)。

M70伴随清单是从原不可变导出及原c4审计新派生的发布文件，不冒充原执行清单。A/B原伴随清单逐字节保留。

[版本目录](../../benchmarks/prism-v020-model-registry.json) · [B数据基线](../../benchmarks/prism-balance-data-baseline-v0.2.0.json) · [基线分类政策](../../benchmarks/prism-style-bands-v020.policy.json) · [原命名提案历史](../../benchmarks/prism-v020-identity-proposal.json) · [互动统计页](style-atlas-2026-10-08.html#names)。

发布输入/输出与实际验证回执在 `local-artifacts/prism/style-atlas-20261008/release-r4/`。本次没有新对局/训练/冠军升级/应用部署/提交推送。
