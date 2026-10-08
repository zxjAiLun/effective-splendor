# M72 Prism 历史统计画像、自动分类与模型身份

Status: VERIFIED_LOCAL_DELIVERY；ALL收口回执见本轮closeout；owner-date: 2026-10-08；baseline: `9899749188f35c838c85c5b3530049bd5dcbd105`。

## Problem and evidence

用户指出 M67 A/B 的实际购牌画像不同，要求统计历史模型、分组柱状图、明确区间的自动分类，并考虑统一进入 v0.2.0 代际。A/B 是训练重复身份，实际行为可以不同。已有 `scripts/prism_style_atlas.py`、v1 政策、25 行分组统计及 24 图 Excel 尚未形成完整的身份与报告交付。

## Initial design

本轮建立可追溯的模型×cohort×对手×座位统计，独立保存权重、血缘、研究目标、实际画像、路线建议和发布状态。复用历史结果，不为缺项追加对局。区间政策是事后描述性工程政策；百分位只针对固定模型名单，不是总体风格分布或置信区间。

## Scope and non-goals

| 任务字段 | 本轮边界 |
| --- | --- |
| task_kind | report + implementation：历史统计与离线分类/身份方案 |
| authorization_source | 用户提供的前序统计请求，以及本次“继续打造统计数据+模型身份的这一轮” |
| authorized_end | 现有数据审计、分类器与身份方案、HTML/完整Markdown/Excel/JSON、实际像素和R9收口 |
| ALL task | `9fc21d3a-70a7-49ab-8dff-34008bc86cb6`，实际执行local |
| branch / index / worktree | `m61-alpha-balance-ab`；index初查空；大量原有未提交/未跟踪工作，单独记录本轮文件 |
| 禁止动作 | 新训练/研究对局、远端控制、改冻结结果/门、正式发布/默认替换/部署、push、混合提交用户工作 |
| next_allowed_action | 补齐已有统计来源、身份与分类验证，生成并检查交付 |

## Contracts and invariants

- 0–5VP 表示卡牌印刷分，不是宝石费用；实体牌层级为1–3。
- 同轮同模式同对手集合分别统计；同权重跨cohort各有一行，不能合成唯一固定风格值。按模型身份聚合，P0/P1不能混称候选。
- 比率从真实分子分母合并；A原5缺项保留。缺失时点/兑现不填0。
- Beta参照为精确Balance权重且匹配cohort；Alpha还列Alpha历史参照。当前数据不足时给部分方向与缺项，不强制三选一。
- DESCRIPTIVE不升级CONFIRMED_IN_SCOPE；旧型号、训练标签、原科学负结果保留。v0.2.0是绑定SHA的代际方案，不是已发布版本。
- 每条路线独立检查必需指标；一个维度缺失不掩盖其他已测方向。身份/网格不匹配则停止数值分类。

## Implementation plan

完善已有统计脚本和测试；初始计划10份神经权重，核验后补入4个早期已登记Alpha版本，共14份；补每对手/座位明细与分类缺项；保留已有Excel并增加模型身份/座位页；交付结论优先页面、完整表与审计、桌面/窄屏验证；登记ALL并更新handoff。

## Iteration log

- 接手核验：三份M66/M67/M70结果均双方greedy；当前自动分类没有匹配Balance/时点证据，不能仅凭B小牌更多便正式登记Beta。前序24图和8测试为已有产物，须本次重核。
- 核验发现早期Alpha0.1.0–0.1.3已有登记记录，补入身份，旧sampling不混入greedy；首次10份覆盖说明由此扩至14份，不声称穷尽所有中间checkpoint。
- 旧Excel标题裁切、纵轴截短；改标题高度、加入明确零基线刻度参照；身份页长枚举换可读状态并扩大/换行画像组列。
- 分类输入只比seed范围不足：新增实际网格完整性、重复/缺局与digest复算、精确对手身份/指标语义检查。未知其他路线时，已命中的路线仅放provisional_hits，不隐式优先Alpha。
- 导出验核首轮假设`xl/charts`路径、内嵌chart缓存存在而失败；实际包为`xl/drawings/charts`，绑定单元格数值缓存完整。修正验证器解析真实路径及源单元格，未修改工作簿来制造PASS。
- 浏览器视口变更的首帧存在重排延迟；重新观察后取像素，最终两页1440桌面/390窄屏均验核。原版结果和旧Excel副本保留在source-before。

## Final implementation

[`prism_style_delivery.py`](../scripts/prism_style_delivery.py)只读绑定18份来源/14权重；`prism-style-delivery-v2`含6组25模型×cohort快照、92条双方actor-match、184条actor-seat。完整双方Markdown含46对战组的WDL/胜率/原配对CI/六档购牌/五色折扣/贵族/预留/七类动作/时钟。未测推理或画像时点不填0。

[`prism_style_atlas.py`](../scripts/prism_style_atlas.py)实现相对精确Balance的三路线区间和失败拒绝；CLI：`python -B -m scripts.prism_style_delivery --classify-input profile.json`，输入candidate/reference含实际observed_grid、其SHA、规则/权重/模式/指标语义和数值字段，参见[政策](../benchmarks/prism-style-bands-v1.policy.json)。必须与冻结证据连接，不能把手填完整元数据当原始证据审计；本CLI是离线分类器，不是训练/发布控制器。

Excel保留六统计组/24原生图，补为9页；公式变更-复算-恢复检查PASS，降序为导出时排序快照，手改后图值更新但不自动重排。人类入口：[互动统计报告](prism/style-atlas-2026-10-08.html) / [完整表](prism/style-atlas-2026-10-08.md)；技术来源单独放[Agent审计](prism/style-atlas-2026-10-08.audit.md)。配套流程图使用answer-me-with-html技能生成，两页均经像素检查。

## Validation and evidence

- `python -B -m unittest scripts.tests.test_prism_style_atlas -v`：13测试exit0，含缺失/NaN/布尔、真实兑现要求、边界重叠、不同seed网格、重复式grid，即使重算digest也拒绝；反序grid同一身份有效。
- `python -B -m scripts.prism_style_delivery`：14权重和18来源SHA；92双方记录/184座位的WDL/半平/纯胜/Main/动作与座位计数复算PASS。未重跑Rust规则或研究bootstrap。
- `node scripts/tests/prism_style_dom.test.cjs`：6组/25行/46组比赛/184座位/14身份/7本地链接及零JS错误PASS。
- `node local-artifacts/prism/style-atlas-20261008/build.mjs`：9页/24图导出、公式值校验和修改后复算/恢复、错误扫描PASS。9页渲染像素实际查看，原生Excel应用NOT_VERIFIED。
- `python -B local-artifacts/prism/style-atlas-20261008/verify-export.py`：24图系列/分类引用、18零基线、单元格缓存和3原结果字节不变PASS。原生图表动态刷新未在Microsoft Excel应用实测。
- CUA实际浏览器：1440×1000桌面及390×844窄屏，两页像素、分组/排序/展开对战与座位、无顶层横溢PASS，临时viewport已恢复。9页Excel渲染也实际查看。
- `git diff --check` PASS；`git check-ignore -v handoff.md`命中`.gitignore:12`；index空。本任务无commit/push。
- 回执集中：`local-artifacts/prism/style-atlas-20261008/{data-validation,dom-validation,xlsx-validation,closeout}.json`及`previews/`。ALL真实完成/失败以closeout与receipt为准，不借用旧run心跳。

| 阶段 | 本任务判定与原因 |
| --- | --- |
| R0 | PASS：report+implementation，用户继续授权，0新局 |
| R1 | PASS：描述性v1政策和身份设计已说明；非新研究采样合同 |
| R2 | PASS：针对性分类/来源/报告/导出验证 |
| R3–R4 | NOT_APPLICABLE：无新研究运行或采样 |
| R5 | PASS：已有14精确输入权重逐字节核验，不重新选中间checkpoint |
| R6 | NOT_APPLICABLE：原实战证据只读，不补赛或重新判原门 |
| R7 | PASS：S1身份、S2参照缺项、S3实际画像、S4不足/描述、S5暂定建议、S6独立身份方案均有记录；证据不足是分析结论 |
| R8 | PASS：HTML/完整Markdown/JSON/Excel/CSV、链接/DOM及强制像素完成 |
| R9 | 收口回执记录ALL同步与本轮完成；无模型发布或部署 |

## Result and decision

本轮既有数据统计与身份方案交付达授权终点。A相对父低VP占比−2.57pp、大牌印刷分+0.840VP/局、贵族覆盖−5.61pp；B相对A低VP占比+2.13pp、贵族覆盖+8.05pp，但相对父低VP占比−0.44pp，不能据此确认Beta。

[身份提案](../benchmarks/prism-v020-identity-proposal.json)：Alpha v0.2.0绑定A SHA `db3e2da279d777485c4dbb3d8d2ff78ddb106d231d5c75b58bc783e4fb66acb5`的命名提案；Beta v0.2.0为B SHA `e2914425cac49f0f2272c44379e46a43525d97ced2eaac206e8600ebf73e79c4`的条件提案；Balance v0.2.0未指定。M70 c4 SHA `f4a9a628a9a0a376a84b2bc0f3b002e652bde42d4e1e4b3170a1830e3b14238a`单独保存为B后代。六种事实分开；旧型号不覆盖，未正式登记新release、冠军或部署。

原竞技结论保持：B原增强通过；A缺5项的共同池正式增强未确认；M70共同池增强通过但直接父代增强未确认；M66未确认增强。任务完成不能推导模型路线确认或晋级。

## Known limitations

统计覆盖六当前历史固定版本、M66/M67/M70四候选及Heuristic；另核验早期4Alpha登记身份。14权重并非所有中间checkpoint。当前三轮汇总缺新候选的匹配Balance、首大牌时点/覆盖、早期投资及真实兑现；未本地重跑Rust或新前向。百分位每组最多6模型，不是大模型总体分位；v1分区为工程起点，未经独立校准。工作簿在artifact工具渲染/导出和XML绑定层核验，Microsoft Excel应用未测。

## Next authorized gate

评审已交付画像与精确身份方案。用户指定研究版本发布可依既有证据说明局限；若要求正式Beta/Balance风格确认，应另冻结匹配政策。当前不自动追加训练/对局、发布、默认替换、部署或push。


## 2026-10-08 distribution-r2：用户指定分布图

授权来源：用户给出账户统计直方图参考，明确“类似这种的，有分布图”。继承M72 `report + implementation`，终点为现有数据分布统计、模型位置交互、完整统计/CSV/JSON、实际桌面/窄屏检查及ALL收口。禁止新训练/比赛、正式登记型号或改原门。原交付和closeout保持为历史；修订前页面/模板/记录保存于`local-artifacts/prism/style-atlas-20261008/distribution-r2/source-before/`。

### 实现与数据口径

- [画像页](prism/style-atlas-2026-10-08.html#distributions)新增四指标经验直方图；灰柱真实频数、白线当前模型、金虚线参照均值，显示N、位置百分位、P10/中位/P90。支持模型/cohort切换、指针或点按查看区间人数/局数及占比。
- 模型均值分布：6cohort、25快照，每组模型等权。M67 A/B/父只有3模型点，因此保留稀疏离散形状，数万局不能代替大规模模型总体。M67 A原5缺项保持。
- M70逐局分布：B/c4各3,072共同池完整比赛，精确权重、相同六对手/seed/双座和greedy命令绑定。只读保存回放统计本人Main、实际购牌数、最终VP与逐局VP/Main。每局是观察单位，不是独立模型重复；原始seed双座相关性未作为新的独立检验。
- 逐局VP/Main等权均值与ΣVP/ΣMain分别列出，避免将两个口径混用。逐局视图的“均值位置”是在参照对局分布的位置，不是模型排行榜。
- 分位位置为midrank，分位点线性插值。12个模型分布箱、24个对局箱，绘图域两侧加7%空白（常数样本按5%或0.01）。原始零值保留，缺值拒绝；未拟合正态曲线。模型/对局分布均为DESCRIPTIVE。
- [完整分布统计](prism/style-distributions-2026-10-08.md)、`benchmarks/prism-style-distributions-2026-10-08.json`及`outputs/01a11805-prism-style/prism-distribution-observations.csv`已生成。原Excel保持24张柱状图；新增分布原始观测CSV可导入Excel。未声称Excel已有新直方图。

### 核验与迭代

1. `python -B -m scripts.prism_style_distributions`：6,144局回放/报告SHA、match-config规范化SHA、分片候选精确权重/双方实际命令、完整seed/座位/对手网格PASS；逐对手VP/Main/购牌总量与原冻结结果一致。M70模式与已绑定原执行一致；未重跑Rust规则。
2. 首次检查把match-config规范化SHA误当文件字节SHA而拒绝；依原执行的canonical_hash定义更正独立适配，分别保存规范化SHA与实际文件SHA。原文件没有改动。
3. `python -B -m unittest scripts.tests.test_prism_style_distributions scripts.tests.test_prism_style_atlas -v`：17测试PASS；含直方图最大值、零值、常数分布、插值、同值midrank与缺项拒绝。后续图域更正后分布4测试再次PASS。
4. `node scripts/tests/prism_style_dom.test.cjs`：29分布组合、各四指标频数和当前值，6组/25行/46比赛/184座位/14身份/10本地链接、18原来源SHA与14权重SHA、零JS错误PASS。
5. CUA真实1440×1000桌面/390×844窄屏：两种视图、数字/坐标/分位点、点按区间、无顶层横溢PASS。发现大牌轴整数显示使刻度重复，改两位小数并重新检查。四张最终截图保留；临时viewport与浏览器已恢复/关闭。
6. 原始三轮结果SHA不变（DOM验证覆盖）；原身份方案、竞技门和路线判定不变。`git diff --check`与handoff忽略检查结果见r2回执；没有stage/commit/push。

### 阶段及结论

R0/R1/R2/R5/R7/R8：PASS；R3/R4/R6：NOT_APPLICABLE（现有资料统计，不采新局/训练/重新验收）。R9按`distribution-r2/closeout.json`记录本修订检查与ALL回报，原closeout不覆盖。

任务完成与模型路线分开：本修订交付真实分布与位置；A大牌描述倾向、B Beta/Balance证据不足，均保持。下一允许动作仍为评审现有画像和精确身份方案；风格确认、正式版本登记各需对应授权。

## 2026-10-08 history-r3：纳入早期模型实际统计

用户明确要求参考早期Balance及更早模型的实际数据，并归纳进对比。`task_kind=report+implementation`，`authorized_end=既有历史统计、分组分布/对照、完整统计/CSV/JSON、实际桌面和窄屏验收、ALL与两层记录收口`。禁止新训练/对局、改冻结结果/原门、正式版本登记、默认替换、部署或push。修订前页面/模板/记录保存在`local-artifacts/prism/style-atlas-20261008/history-r3/source-before/`；不覆盖前两版回执。

### 新增资料与口径

- [历史统计与对照](prism/style-history-2026-10-08.md)及`benchmarks/prism-style-history-2026-10-08.json`新增10组29份数值画像，连同原6组25份合计16组54份。已核验的14份神经权重均有实际数值覆盖；初代、通用、Alpha v0.1.0–v0.1.3及Balance/Beta不再只有身份记录。并非穷尽全部中间/未登记control检查点。
- `scripts/prism_style_history.py`只读M55/M56/M59/M60/M61/M62/M63/M65及已绑定M66/M67/M70资料。新增21份来源SHA与14权重字节核验，原来源/结果保持不变。M55/M56模式来自保存anchors配置，M59/M60来自冻结evaluation合同及完成结果，M61/M62来自execution与完成结果；M63/M65保存greedy配置/plan/结果SHA一致。未重新执行历史Rust回放，未把旧合同NOT_RUN字段解释为当前运行状态。
- 历史T1资料按原共同池分别展示，本方greedy/对手T1的初代资料另组；不同模式、对手实现、seed或轮次不混为统一百分位。M62未登记control不纳入本固定版本比较，保留在原结果。
- 默认历史分布选择同一精确Alpha v0.1.5对手、双方greedy的10个模型/策略，各精确身份仅选一cohort。旧模型数据来自M67父代对战的opponent侧；A/B使用完整直接父对战candidate侧，M66/M70使用各自对应记录。不同seed/轮次的差值仅作描述，不能当同seed确认。
- 每组保留0–5VP实际购牌张数、0–1VP占比、大牌印刷分、贵族覆盖和VP/Main；早期资料另补首4–5VP本人Main及购入覆盖，M62补前12本人Main低VP购牌。条件时点按实际购入局数加权，无购入覆盖为0而时点未测；数据缺失保持未测。新候选的必要时点/真实兑现不足仍保留。
- 互动页新增历史表格/模式与模型筛选，统计图和分布纳入新增分组；青色点线标历史Balance，白线为当前模型、金线为组均值，并显示当前−Balance差值。原Excel仍为9页24柱状图；新增`outputs/01a11805-prism-style/prism-historical-profiles.csv`可导入Excel，不声称原工作簿已含这些新增记录。

### 验证与交付

- `python -B -m scripts.prism_style_history`：来源/精确身份/模式审计、10组29份画像及统计导出PASS；0新局/训练。
- `python -B -m unittest scripts.tests.test_prism_style_history -v`：3项PASS，覆盖按购入局而非全部局加权、缺时点不填0、无购入条件均值未测。
- `node scripts/tests/prism_style_dom.test.cjs`：77项新增历史分组/分布/筛选组合PASS，原29分布组合、46比赛/184座位/14身份、13本地链接、18原来源SHA核验PASS，零JS错误。新回执写history-r3，旧distribution-r2回执保留。
- CUA实际1440×1000桌面/390×844窄屏：历史同对手表、13行早期T1表、Balance参照及差值、分布数字/坐标、窄屏表格内横向滚动和图表像素PASS；无顶层横溢、无控制台错误/警告。五张实际截图与`browser-validation.json`保存；临时viewport恢复，临时浏览器tab/本机HTTP验收服务关闭。
- 完整双方Markdown保留并加历史导航，`docs/prism/reports.html`更新入口。git/index/publication检查和ALL实际回执见`history-r3/closeout.json`；没有stage/commit/push。

### 阶段、结果与下一动作

R0/R1/R2/R5/R7/R8为PASS；R3/R4/R6为NOT_APPLICABLE（既有资料补统计，无新采样或独立研究确认）。R9按本修订closeout及ALL实际回执收口。原模型竞技判定、旧型号及身份提案保持。

同一精确对手的历史描述中，A−Balance低VP占比−3.12pp、大牌印刷分+1.1314VP/局、贵族覆盖−5.56pp；B−Balance低VP占比−0.92pp、大牌+0.5074VP/局、贵族覆盖+2.63pp。A更偏大牌的描述证据一致；B比A重小牌/贵族，但并未表现为比旧Balance更多小牌。正式Beta/Balance确认仍不足，不强行改路线。任务完成表示历史统计和对照交付，不表示模型发布/晋级。

下一允许动作是评审已交付历史画像与身份方案；正式风格确认或指定研究版本发布分别按对应授权执行。当前范围没有剩余新训练/比赛待办。

## 2026-10-08 release-r4：A/B/M70固定研究版本与Balance基线

当前阶段R0 PASS / R5身份核验IN_PROGRESS。task_kind=release；用户原文“那先给B的设置成balance的数据基线吧 A大牌 之后固定版本 以及给M70的也相对应固定版本”。authorized_end=指定三版本登记、B数据基线绑定、可读身份/已有实战与画像及来源审计、页面更新/实际桌面窄屏验收、两层记录与ALL收口。0新局/训练，禁止默认冠军/池/Studio部署、改原门、Git push。

版本规则：M67 A-c20 → Prism Alpha v0.2.0；M67 B-c20 → Prism Balance v0.2.0（当前数据基线）；M70 c4 → Prism Balance v0.2.1（B后代，独立精确权重）。这是用户指定的研究路线和版本，不把统计风格证据升级为CONFIRMED。旧提案/型号/冻结结果保留；新登记与父血缘分别保存。

实施预检：旧M65发布器限定c4及旧结果schema，不修改已pin发布器；独立适配M67/M70并复用其张量/manifest校验。M70原导出没有companion manifest，允许从已绑定精确权重及原c4审计派生新的发布伴随清单，标明新派生来源，不能冒充原执行manifest。发布前先核验全部三版本及目标碰撞；必须通过来源/父权重/最终周期/模式/原负结果检查。新增登记核验、现有页面数值/交互和真实像素为强制交付项；R3/R4新研究运行不适用。

### 固定版本与数据基线：已完成

三版本均为`RELEASED_EXPERIMENTAL_MODEL`，按用户指定的研究路线登记：

| 型号 | 原检查点 | 父代 | 权重SHA |
| --- | --- | --- | --- |
| Prism Alpha v0.2.0 | M67 A-c20 | Prism Alpha v0.1.5 | `db3e2da279d777485c4dbb3d8d2ff78ddb106d231d5c75b58bc783e4fb66acb5` |
| Prism Balance v0.2.0 | M67 B-c20 | Prism Alpha v0.1.5 | `e2914425cac49f0f2272c44379e46a43525d97ced2eaac206e8600ebf73e79c4` |
| Prism Balance v0.2.1 | M70 c4 | Prism Balance v0.2.0 | `f4a9a628a9a0a376a84b2bc0f3b002e652bde42d4e1e4b3170a1830e3b14238a` |

独立发布适配器`scripts/prism_generation_release.py`绑定最终周期、父权重、原artifact audit、result/config和双方greedy来源；在任何版本写入前校验全部三模型及目标碰撞。M67的20份result/config/plan/completion从已保存报告tar显式取出，并逐项比对原top result保存的SHA；未解压/修改其他实验目录。M70无原companion，新的发布manifest从不可变权重及原c4训练审计派生，明确新来源；不声称重审.pt或重跑Rust。

记录：`benchmarks/m72-prism-{alpha-v0.2.0,balance-v0.2.0,balance-v0.2.1}.model.json`。固定导出分别位于`local-artifacts/prism/{alpha-v0.2.0,balance-v0.2.0,balance-v0.2.1}/`；每版weights/companion逐SHA及32 finite float32张量核验。原export provenance、训练血缘、竞技负结果和5缺项保持。

当前[版本目录](../benchmarks/prism-v020-model-registry.json)与[B数据基线](../benchmarks/prism-balance-data-baseline-v0.2.0.json)单独保存；旧v0.1.x及`prism-v020-identity-proposal.json`不覆盖。B基线按M67-main、M70-main、同Alpha v0.1.5历史对手三个cohort分开存数字，不平均为全局阈值。`prism-style-bands-v020.policy.json`绑定B精确SHA并继承未校准描述性区间；分类CLI默认新B基线，可用`--policy benchmarks/prism-style-bands-v1.policy.json`重现旧参照。缺项仍拒绝，不因版本已发布而返回CONFIRMED。

互动页、完整Markdown、索引及M67/M70轮次记录显示新型号与真实父代；包含B的组以Balance v0.2.0画青色参照线，早期无B组保留历史Balance。原统计JSON和CSV不改名/改值；原Excel保留发布前快照。新固定三模型包`outputs/01a11805-prism-style/Prism-v0.2-fixed-models.zip`含13文件，CRC与每文件精确字节核验PASS。

### 实际检查与剩余交付限制

- 发布预检`python -B -m scripts.prism_generation_release --spec benchmarks/m72-prism-generation-release.publication.json --check-only`：PASS，3模型；随后已授权发布同命令去掉`--check-only`：RELEASED_THREE_EXPERIMENTAL_MODELS，0新局/训练。
- `python -B -m unittest scripts.tests.test_prism_generation_release -v`：8 PASS，正常三版本/负结论保留、最后一个输入漂移/版本碰撞仍零输出、父代、周期、重复目标、权限和路径逃逸拒绝。
- `python -B -m unittest scripts.tests.test_prism_style_atlas -v`：15 PASS，含新B基线接受/旧Balance拒绝与必要时点缺失不填0；其余原分类回归通过。合计23项。
- `node scripts/tests/prism_style_dom.test.cjs`：PASS，3新型号/父代来源SHA/原检查点、3基线cohort/3当前参照分布组、77历史组合、29原分布组合、46比赛/184座位、16本地链接及18原来源SHA不变；零JS错误。首次显示别名转换会覆盖original_checkpoint元数据，已在独立阅读层保留该键并添加断言，原结果未改。
- 发布后再次核验三份已登记记录/导出、96张量、父权重/来源SHA、27 Markdown链接、基线政策绑定和13文件ZIP：PASS。回执`release-validation.json`、`publication-receipt.json`、`bundle-receipt.json`、`test-validation.json`及`dom-validation.json`。
- 本次新版像素为`NOT_VERIFIED`：浏览器安全策略拒绝访问当前`file://`页面（仅允许http/https），未用其他浏览器表面/CDP/执行入口绕过。原history-r3五张截图属于上一revision，不冒充新版视觉PASS。已请求用户刷新当前页做显示复核。新页面视觉强制项未满足，报告交付保持REVIEW；版本发布和数据基线本身已完成。
- 本次Git/来源/输出/ALL实际登记回报见`release-r4/closeout.json`。没有stage/commit/push或默认/池/Studio部署；ALL产物登记不等于模型冠军。

### 阶段与下一动作

R0/R1/R2/R5/R6既有证据检查/R7为PASS；R3/R4为NOT_APPLICABLE（0新研究局/训练）。R8数值/来源/DOM/链接完成，强制新版像素因工具策略BLOCKED，报告状态REVIEW；R9记录和同步完成情况见实际回执，不将任务整体done。模型状态分别为三固定研究版本已发布，Balance统计风格仍未确认。

下一允许动作仅为补当前页面的实际视觉复核/用户明确接受该显示限制并收口报告。固定权重、路线及B基线已满足用户指令，不重复发布/追加对局；新训练、冠军或应用部署需要对应范围授权。
