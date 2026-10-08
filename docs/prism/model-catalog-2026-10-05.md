# Prism 固定模型清单：截至2026-10-05晚

核验时间：2026-10-07T23:48:34+08:00。这是用户指定的历史六模型与M66参照，非完整历史版本库存。

| 模型 | 路线 | 身份 | 父代 | 行为与证据限制 |
| --- | --- | --- | --- | --- |
| Prism v0.1.1 | General | ACCEPTED_MODEL_ITERATION | trial-v1-c8 | 冻结T=1通用模型迭代验收通过；不证明跨全家族最强或已部署默认冠军 |
| Prism v0.1.0 | General | VERIFIED_BASELINE_COMPLETE | Heuristic v0.3.1 teacher BC | 4000局Heuristic v0.3.1自对弈教师BC；历史锚点 |
| Prism Alpha v0.1.5 | Alpha | RELEASED_EXPERIMENTAL_MODEL | Prism Balance v0.1.0 | 相对Balance轻微大牌冲分倾向，描述性画像 |
| Prism Alpha v0.1.4 | Alpha | REGISTERED_EXPERIMENTAL_MODEL | Prism Alpha v0.1.3 | 相对Alpha v0.1.3大牌AUC24增强有原冻结范围证据；不升级为普适风格确认 |
| Prism Balance v0.1.0 | Balance | REGISTERED_EXPERIMENTAL_MODEL | Prism Alpha v0.1.3 | outcome-only训练基座；balance_style_acceptance=NOT_CLAIMED，均衡未确认 |
| Prism Beta v0.1.0 | Beta | RELEASED_EXPERIMENTAL_MODEL | Prism Balance v0.1.0 | 保留研究分支名；实际混合/偏得分，强基建偏好未确认 |
| M66 最终 c4（未发布训练检查点） | undetermined | VERIFIED_UNPUBLISHED_TRAINING_CHECKPOINT | Prism Alpha v0.1.5 | Alpha起点、outcome-only研发血缘；轻微混合变化，未发布、未确认新路线 |

## 核对后的必要说明

- 用户称Prism v0.1.1“通用最强/冠军”作为历史定位保存；源release仅验收冻结T=1对父代和两个锚点，default_replaced=false/shared_pool_deployed=false，未核验跨全家族最强或实机默认。
- General 62.0117%/61.9141%/59.9121%属于M54 T=1采样候选，不能当both-greedy。原开发共享池边界失败与后来独立acceptance-v2通过并存，不抹去历史失败。
- Alpha v0.1.5对旧Alpha 51.953125%属于M63 greedy-r3；用户提供的53.42%在已查绑定证据中未找到对应行，标UNKNOWN，不构造51.95–53.42范围。
- Alpha v0.1.5对Beta：M63 greedy-r3为48.6328125%（256局）；M65新greedy为56.0546875%（256局，143/1/112）。不同seed cohort分别保存，不取最好一项代替全部。
- Beta对Alpha v0.1.4：M65 greedy50.1953125%，M62双方T=1采样54.98046875%及原校正下界增强证据。后者仅限原模式，不能写成跨模式直接克制区间。
- Balance对Alpha v0.1.4的50.2441%来自M61双方T=1；INCONCLUSIVE，未证明等效。outcome-only不等于均衡风格通过。
- M66 c4完整SHA d392a5d13e070173a3c80406acbe2f7028d52e3bbdc34a59864ab84f546588f8；未发布、无新路线确认，不纳入已发布六模型。
- 此表列用户指定当前/固定参照，不是所有历史Alpha版本的完整清单；模型登记/发布不等于应用池、Studio或服务在役。

## 按模式和批次分别保存的战绩

半平得分=(W+0.5D)/N；下面仅复核原aggregate算术，未重新做bootstrap。

| 模型 / 对手 | cohort | 本方 / 对手模式 | N | W / D / L | 半平得分% |
| --- | --- | --- | --- | --- | --- |
| Prism v0.1.1 / Heuristic v0.3.1 | M54 acceptance-v2 | sample T=1 / greedy | 1024 | 633 / 4 / 387 | 62.0117 |
| Prism v0.1.1 / Prism v0.1.0 | M54 acceptance-v2 | sample T=1 / greedy | 1024 | 631 / 6 / 387 | 61.9141 |
| Prism v0.1.1 / trial-v1 final c8 | M54 acceptance-v2 | sample T=1 / sample T=1 | 1024 | 609 / 9 / 406 | 59.9121 |
| Prism Balance v0.1.0 / Prism Alpha v0.1.4 | M65 greedy | greedy / greedy | 256 | 124 / 3 / 129 | 49.0234 |
| Prism Balance v0.1.0 / Heuristic v0.3.1 | M65 greedy | greedy / greedy | 256 | 195 / 3 / 58 | 76.7578 |
| Prism Balance v0.1.0 / Prism v0.1.1 | M65 greedy | greedy / greedy | 256 | 160 / 2 / 94 | 62.8906 |
| Prism Balance v0.1.0 / Prism v0.1.0 | M65 greedy | greedy / greedy | 256 | 202 / 0 / 54 | 78.9062 |
| Prism Beta v0.1.0 / Prism Alpha v0.1.4 | M65 greedy | greedy / greedy | 256 | 126 / 5 / 125 | 50.1953 |
| Prism Beta v0.1.0 / Heuristic v0.3.1 | M65 greedy | greedy / greedy | 256 | 194 / 1 / 61 | 75.9766 |
| Prism Beta v0.1.0 / Prism v0.1.1 | M65 greedy | greedy / greedy | 256 | 162 / 2 / 92 | 63.6719 |
| Prism Beta v0.1.0 / Prism v0.1.0 | M65 greedy | greedy / greedy | 256 | 200 / 1 / 55 | 78.3203 |
| Prism Beta v0.1.0 / Prism Balance v0.1.0 | M65 greedy | greedy / greedy | 256 | 118 / 4 / 134 | 46.8750 |
| Prism Beta v0.1.0 / Prism Alpha v0.1.5 | M65 greedy | greedy / greedy | 256 | 112 / 1 / 143 | 43.9453 |
| Prism Alpha v0.1.5 / Prism Beta v0.1.0 | M65 greedy | greedy / greedy | 256 | 143 / 1 / 112 | 56.0547 |
| Prism Balance v0.1.0 / Prism Alpha v0.1.4 | M63 greedy-r3 | greedy / greedy | 256 | 136 / 3 / 117 | 53.7109 |
| Prism Balance v0.1.0 / Heuristic v0.3.1 | M63 greedy-r3 | greedy / greedy | 256 | 198 / 2 / 56 | 77.7344 |
| Prism Balance v0.1.0 / Prism Beta v0.1.0 | M63 greedy-r3 | greedy / greedy | 256 | 129 / 7 / 120 | 51.7578 |
| Prism Balance v0.1.0 / Prism v0.1.1 | M63 greedy-r3 | greedy / greedy | 256 | 159 / 1 / 96 | 62.3047 |
| Prism Balance v0.1.0 / Prism v0.1.0 | M63 greedy-r3 | greedy / greedy | 256 | 209 / 1 / 46 | 81.8359 |
| Prism Alpha v0.1.5 / Prism Alpha v0.1.4 | M63 greedy-r3 | greedy / greedy | 256 | 132 / 2 / 122 | 51.9531 |
| Prism Alpha v0.1.5 / Heuristic v0.3.1 | M63 greedy-r3 | greedy / greedy | 256 | 211 / 0 / 45 | 82.4219 |
| Prism Alpha v0.1.5 / Prism Beta v0.1.0 | M63 greedy-r3 | greedy / greedy | 256 | 122 / 5 / 129 | 48.6328 |
| Prism Alpha v0.1.5 / Prism v0.1.1 | M63 greedy-r3 | greedy / greedy | 256 | 158 / 2 / 96 | 62.1094 |
| Prism Alpha v0.1.5 / Prism v0.1.0 | M63 greedy-r3 | greedy / greedy | 256 | 212 / 1 / 43 | 83.0078 |
| Prism Alpha v0.1.5 / Prism Balance v0.1.0 | M63 greedy-r3 | greedy / greedy | 256 | 137 / 2 / 117 | 53.9062 |
| Prism Beta v0.1.0 / Prism Alpha v0.1.4 | M62 independent sampling | sample T=1 / sample T=1 | 1024 | 557 / 12 / 455 | 54.9805 |

## 精确权重与证据

- **Prism v0.1.1**：`a2301f0878f9c342a61b83fd45412f72ba95acfca895dafbe7ceca0360f34a85`；[模型身份](../../benchmarks/m54-prism-v0.1.1.release.json)；[权重](../../local-artifacts/prism/v0.1.1/weights.json)。
- **Prism v0.1.0**：`5db70b773083858b83c6e679d5641f1b78d4c5fbe34c48950cc906064f821b54`；[模型身份](../../benchmarks/m51-prism-v01.result.json)；[权重](../../local-artifacts/prism/v01/run/weights.json)。
- **Prism Alpha v0.1.5**：`3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12`；[模型身份](../../benchmarks/m65-prism-alpha-v0.1.5.model.json)；[权重](../../local-artifacts/prism/alpha-v0.1.5/weights.json)。
- **Prism Alpha v0.1.4**：`d3a313090bb2ccae678d3b9cf1216f0a60527ec330432c5c2dcdddd85b53b2d9`；[模型身份](../../benchmarks/m61-prism-alpha-v0.1.4.model.json)；[权重](../../local-artifacts/prism/alpha-v0.1.4/weights.json)。
- **Prism Balance v0.1.0**：`225daf49e8746576b1edc3508ca0454715e5454529fea53dc7dfeb9043cf01f1`；[模型身份](../../benchmarks/m61-prism-balance-v0.1.0.model.json)；[权重](../../local-artifacts/prism/balance-v0.1.0/weights.json)。
- **Prism Beta v0.1.0**：`69a885b20527dda2e43fad9c00d7cc36537b45a0f5ccbaef4320001bef8836fb`；[模型身份](../../benchmarks/m65-prism-beta-v0.1.0.model.json)；[权重](../../local-artifacts/prism/beta-v0.1.0/weights.json)。
- **M66 最终 c4（未发布训练检查点）**：`d392a5d13e070173a3c80406acbe2f7028d52e3bbdc34a59864ab84f546588f8`；[模型身份](../../benchmarks/m66-prism-alpha-dsw.candidate.json)；[权重](../../local-artifacts/prism/m66-alpha-dsw/harvest/campaigns/training/cycle-4-export/weights.json)。

[机器可读快照](../../benchmarks/prism-model-catalog-2026-10-05.json)绑定所有读取源hash。0新局、0新发布/部署、未提交推送。R0身份核验PASS；R1–R6研究阶段不适用（只读已有证据），R7已有画像解释，R8静态历史清单，R9同步收口。
