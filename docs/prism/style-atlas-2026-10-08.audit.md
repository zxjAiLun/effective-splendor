# M72 Agent审计

来源18份，神经权重14份已逐字节SHA复核。新局0，训练0。

## 输入绑定

- `benchmarks/m67-prism-alpha-repeat.result.json` SHA `d394c44753cf34e7e97ea4580c696bf24e6c576af185b0bf9785eb2363c4bf0b`
- `benchmarks/m66-prism-alpha-dsw.result.json` SHA `53cbbca99085ffea003de17c9b3523331e19def7bcc7f228a2ed55793e4a8bb0`
- `benchmarks/m70-prism-b-continuation.result.json` SHA `9c46ebba921d372f55b59a4096e6779f9ee41d42269f898a8fa2420b7e05ee6b`
- `benchmarks/m66-prism-alpha-dsw.config.json` SHA `1770d3635149f5df7b4f06630457c329604971adb98afb4c81355c93027572aa`
- `benchmarks/m67-prism-alpha-repeat.config.json` SHA `cf98d10153b5a3a5c08f78c0fd000e94f53d8d553b70de710183234f35c3659c`
- `benchmarks/m70-prism-b-continuation.config.json` SHA `ecaa045f7946ef46769237fce3b779f15d56c4afb1785f7183e755acba6a8532`
- `benchmarks/prism-model-catalog-2026-10-05.json` SHA `2faee82ea8a0dbdb2055308b4472e76aa95058e8eb5bed5b29116f0170638f7a`
- `benchmarks/m54-prism-v0.1.1.release.json` SHA `bbd5f410e45885bd030dd69476f7bcc3fb6a92a18f73fe1d859b34e48d1fb7d4`
- `benchmarks/m51-prism-v01.result.json` SHA `e22af95e46d03bc83fcb0890989a5c1f6ab881ad5737ee9c43e4888895328d63`
- `benchmarks/m65-prism-alpha-v0.1.5.model.json` SHA `53558fd6bffb74b788f8cebdfc8b136aebd38b187dd721816ce7479c8109febb`
- `benchmarks/m61-prism-alpha-v0.1.4.model.json` SHA `c8476edbb6bf474cc8bfca3c09df78957c1968a061b0cf8383b96a26d45f5435`
- `benchmarks/m61-prism-balance-v0.1.0.model.json` SHA `66abd12229ad03543ae9121b12bebf36b4bf61b3f254f2284aef0dfa2e117b21`
- `benchmarks/m65-prism-beta-v0.1.0.model.json` SHA `fe146698b1745434d1492e7f96bdae2db1f24c207b6606c9a54a3766b7552630`
- `benchmarks/m66-prism-alpha-dsw.candidate.json` SHA `b3ac89ae8e102fb29acd65ffb262d2cb66a5b177161c2e5361da770af5da105b`
- `benchmarks/m55-prism-alpha-v0.1.0.model.json` SHA `1de55b15f42ab683faa44abb2f6dbfc9d3352191079475ea7a789452361a2552`
- `benchmarks/m56-prism-alpha-v0.1.1.model.json` SHA `9ea52b2ca63ae0a22eca9325a859826e4afc017e5f553c811b71d2080884d29b`
- `benchmarks/m59-prism-alpha-v0.1.2.model.json` SHA `18b31c05b9746ab4b1b06b0b23acaf4cd20ff5f90ef26ac91ae3025766ba692d`
- `benchmarks/m60-prism-alpha-v0.1.3.model.json` SHA `f38f867667533d128ce46ecc2f2a2cab08179b8c1917d3f25b8451125ae5d32e`

## 权重身份

- Prism v0.1.1: `local-artifacts/prism/v0.1.1/weights.json` SHA `a2301f0878f9c342a61b83fd45412f72ba95acfca895dafbe7ceca0360f34a85`；来源 `benchmarks/m54-prism-v0.1.1.release.json`；parent `trial-v1-c8`。
- Prism v0.1.0: `local-artifacts/prism/v01/run/weights.json` SHA `5db70b773083858b83c6e679d5641f1b78d4c5fbe34c48950cc906064f821b54`；来源 `benchmarks/m51-prism-v01.result.json`；parent `Heuristic v0.3.1 teacher BC`。
- Prism Alpha v0.1.5: `local-artifacts/prism/alpha-v0.1.5/weights.json` SHA `3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12`；来源 `benchmarks/m65-prism-alpha-v0.1.5.model.json`；parent `Prism Balance v0.1.0`。
- Prism Alpha v0.1.4: `local-artifacts/prism/alpha-v0.1.4/weights.json` SHA `d3a313090bb2ccae678d3b9cf1216f0a60527ec330432c5c2dcdddd85b53b2d9`；来源 `benchmarks/m61-prism-alpha-v0.1.4.model.json`；parent `Prism Alpha v0.1.3`。
- Prism Balance v0.1.0: `local-artifacts/prism/balance-v0.1.0/weights.json` SHA `225daf49e8746576b1edc3508ca0454715e5454529fea53dc7dfeb9043cf01f1`；来源 `benchmarks/m61-prism-balance-v0.1.0.model.json`；parent `Prism Alpha v0.1.3`。
- Prism Beta v0.1.0: `local-artifacts/prism/beta-v0.1.0/weights.json` SHA `69a885b20527dda2e43fad9c00d7cc36537b45a0f5ccbaef4320001bef8836fb`；来源 `benchmarks/m65-prism-beta-v0.1.0.model.json`；parent `Prism Balance v0.1.0`。
- M66 c4: `local-artifacts/prism/m66-alpha-dsw/harvest/campaigns/training/cycle-4-export/weights.json` SHA `d392a5d13e070173a3c80406acbe2f7028d52e3bbdc34a59864ab84f546588f8`；来源 `benchmarks/m66-prism-alpha-dsw.candidate.json`；parent `Prism Alpha v0.1.5`。
- Prism Alpha v0.1.0: `local-artifacts/prism/alpha-v0.1.0/weights.json` SHA `b5e68e008d5d462aff19c67b8eed063139a5c500a020a48031e8938b44618f0a`；来源 `benchmarks/m55-prism-alpha-v0.1.0.model.json`；parent `prism-v0.1.1`。
- Prism Alpha v0.1.1: `local-artifacts/prism/alpha-v0.1.1/weights.json` SHA `d57ebe2407b5d061ae890f3d2586924754e0d2d8e502e1f3f32d12c1fc9af4ff`；来源 `benchmarks/m56-prism-alpha-v0.1.1.model.json`；parent `Prism Alpha v0.1.0`。
- Prism Alpha v0.1.2: `local-artifacts/prism/alpha-v0.1.2/weights.json` SHA `faada9ba7f862c14f5a8ca19b5788f044aa08f550b03e1e360a04cb1f2318618`；来源 `benchmarks/m59-prism-alpha-v0.1.2.model.json`；parent `Prism Alpha v0.1.1`。
- Prism Alpha v0.1.3: `local-artifacts/prism/alpha-v0.1.3/weights.json` SHA `7f6cdbc2acdff129b0ef6a3417e79d4b8f27bf59f40be53ae2892bf00b5e1544`；来源 `benchmarks/m60-prism-alpha-v0.1.3.model.json`；parent `Prism Alpha v0.1.2`。
- M67 A-c20: `local-artifacts/prism/m67-alpha-repeat/r2-failure-harvest-20261007/campaigns/a/cycle-20-export/weights.json` SHA `db3e2da279d777485c4dbb3d8d2ff78ddb106d231d5c75b58bc783e4fb66acb5`；来源 `benchmarks/m67-prism-alpha-repeat.result.json`；parent `Prism Alpha v0.1.5`。
- M67 B-c20: `local-artifacts/prism/m67-alpha-repeat/r2-failure-harvest-20261007/campaigns/b/cycle-20-export/weights.json` SHA `e2914425cac49f0f2272c44379e46a43525d97ced2eaac206e8600ebf73e79c4`；来源 `benchmarks/m67-prism-alpha-repeat.result.json`；parent `Prism Alpha v0.1.5`。
- M70 c4: `local-artifacts/prism/m70-b-continuation/result-review/harvest/campaigns/a/cycle-4-export/weights.json` SHA `f4a9a628a9a0a376a84b2bc0f3b002e652bde42d4e1e4b3170a1830e3b14238a`；来源 `benchmarks/m70-prism-b-continuation.result.json`；parent `M67 B-c20`。

## 统计审计范围

每对手双方W+D+L=N、半平和纯胜、VP/Main、动作总数与座位计数复算；已有置信区间照录，没有重算研究bootstrap或Rust规则。原source/config SHA验证。购牌总量由完整精度均值×N还原，不从显示值复算。缺项不作为平局。画像percentile仅25模型×cohort快照内的midrank，单个cohort最多6模型。大样本局数不能充当独立模型样本数。

## 原结果与失败

M67 A共同池29995/30000，缺5（原2安全错误+3孤立缺项），其共同池正式门未确认；B完整40000局增强门通过。M70双保留通过，共同池增强通过，直接对父增强未确认；总体增强未确认。M66原保留通过、增强未确认。历史Alpha0.1.0未达旧Rush目标仍保留注册研究身份。任何分类器输出均不改变这些原门。

## 适配边界

本轮不是新竞技轮，未修改pin evaluator或使用空模型结果。独立prism-style-delivery-v2适配现有三份result；原报告/结果只读。完整双方表留在人类Markdown，本审计集中完整SHA与技术来源。v1政策为事后设计，不设旧验收PASS。

## 检查回执

分类测试、Excel公式/原生图表、桌面与窄屏像素、DOM交互、链接和Git检查见 `local-artifacts/prism/style-atlas-20261008/closeout.json`。完成前状态IN_PROGRESS，不把HTML存在算视觉PASS。
