# Prism 每轮报告阅读合同

Status: IMPLEMENTED / VERIFIED_OFFLINE_DOM_AND_PROVENANCE (2026-10-05)
Baseline: `9899749188f35c838c85c5b3530049bd5dcbd105`

**2026-10-05 后续用户更正（当前决策口径）：**实战提升是晋级主依据，风格按实际画像归类。原Beta目标未达不能作为模型整体否决；同一候选可转入Balance路线评审。此前本记录与读页的“未接受基建候选→先诊断Beta再推进”只描述旧研究合同，现在由[实战优先晋级合同](prism-practical-promotion-contract.md)覆盖其产品决策含义，原结果不改。M63首页已按该口径修订，并增加同父/同种子三个锚点覆盖面表；旧十门折叠为历史研究记录。

## Problem and evidence

用户明确反馈每轮输出即使是HTML也几乎不可读。M63首页把内部验收名、十门宽表、多种指标和重复比较直接作为阅读路径；8MB原报告中106张表与逐局来源清单淹没了结论。问题是组织逻辑，而非缺少颜色。

## Initial design

统一阅读入口先回答五件事：本轮想解决什么；候选来自谁、改变什么；棋力如何；目标风格是否实现；结果能支持什么决定。默认页面使用自然语言和少量关键指标，不用内部枚举作为结论。先给完整型号和“共同起点/对照/候选”的身份关系，再允许局部简称“候选”“对照”。

## Scope and non-goals

本轮重写通用离线HTML/Markdown阅读层，并回填M61、M62、M63；提供统一CLI及报告索引作为后续输出入口。已有冻结生成器和运行合同保留，用它们生成原证据后再调用新阅读层。无对战、训练、门槛调整、版本登记或部署。早期Alpha/Rush报告此次不批量重写其科学解释，避免将不同合同套入Beta。

## Contracts and invariants

- 原JSON、完整Markdown、原HTML、哈希与判定保持可访问，原HTML另存`.evidence.html`。新阅读层有独立来源回执，不冒充原冻结报告。
- 三项结论分别描述产物、竞技、风格；通过检查不等于发布。
- 强度图显示半平得分及配对95%区间，纯胜率另列；50%线只用于描述直接对战，不能替代冻结45%保留门。
- 风格的少量关键比较带单位、对照与候选绝对值、变化方向；高不自动代表好。未通过门区分点估计不足、未排除容忍外退步和未证实目标增益；保留原阈值和校正下界。
- 完整双方战绩按阶段/模型/对手选择，指标按经济、动作、座位、风格、时钟分组；颜色伴随文字/箭头；未测延迟显示NOT_MEASURED。
- 技术来源与完整原文放在折叠证据区，不把逐局清单当作正文。完整Markdown表保留在阅读版Markdown附录。
- 输出是独立本地文件，无CDN、网络请求或云端依赖；安全转义动态内容。
- 可复用的数据层支持含`development/acceptance.pairs`的结果；文案通过每轮明确的阅读spec提供，不用通用模板臆造科学结论。

## Implementation plan

统一`prism_round_report.py`读取结果、完整原文及阅读spec；模板负责浏览交互，规范保证未来每轮都有解释文案。M63先完整验收，然后M62/M61验证复用。测试围绕冻结数据不变、半平/纯胜不同口径、双方座位、阶段隔离、安全转义和交互可用性。

## Iteration log

- 2026-10-05：开始实施；M63正式结果已独立核验，当前问题仅是阅读体验，不重开验收。
- 2026-10-05 用户反馈：不仅可读性，之前把风格研究目标等同于整个模型晋级也有问题。已新增`benchmarks/m63-practical-candidate.review.json`绑定原权重与结果，暂归下一代Balance路线候选；新读页/reading MD展示实战覆盖面、实际画像和晋级评审价值，旧合同与原名称在历史区保留。Python测试扩至4项，新增归类别名不准漂移权重/伪装登记；离线DOM另核验3锚点数据和历史十门默认收起。

## Final implementation

`scripts/prism_round_report.py`只读保存的结果与完整Markdown，将每轮哈希绑定的解释spec和统一CSS/JS模板打包成无外部依赖的HTML。三轮输出已生成；M63/M62旧HTML另存`.evidence.html`、字节SHA保持，M61新增阅读页。原完整Markdown未修改。阅读版`.reading.md`开头给结论和独立对战速览，在折叠附录包含完整原文。独立`.reading-receipt.json`记录新输出与原证据绑定，不能与旧completion回执混用。

首页三项结论、模型身份、半平得分区间图、5项以内核心风格变化、下一步建议；详细战绩按阶段/模型/对手选择，七组指标默认折叠；门默认显示未通过项，展开后解释目的、估计、普通区间、原校正下界及冻结阈值。单位与双方归属标注；判定文案由每轮spec明确提供，数据视图只读JSON。`docs/prism/reports.html`是统一索引，AGENTS要求后续每轮使用同一阅读层。

命令示例：

```powershell
C:\Python312\python.exe -B scripts/prism_round_report.py --spec benchmarks/reports/m63-reading.json
```

后续轮次先按原合同完成证据报告，再创建新spec，绑定result/Markdown SHA、候选与对照身份、每个原门、最多5个关键指标和清楚的解释文案。此层拒绝缺门、漂移的阈值、错误的胜平负/半平比例、结果与原文hash漂移。当前通用数据接口是含`acceptance/development.pairs`的轮次；不同结构需要显式适配，不可猜测字段。

M63结果SHA `a3c5c4f2c48b2b7dc36fed34326236ba5bcab687718ede6fe7bac99902b1e989` / 原Markdown SHA `911d4ef90395be7a373ea23f79d921d03ebb5909ffde76c222ebd0bf70c6c341` / 原HTML SHA `2af29a90b32adf7d3ee07784a2c97cd334f1134fa421beaa7be9cfa50f9faaf5`保持；106原表完整保留。M62保留97原表，M61保留74原表。每轮新HTML哈希见其独立reading-receipt。

## Validation and evidence

- M61/M62/M63各自CLI生成exit0；原结果和原Markdown SHA与spec一致，五/九/十门逐项校验；原结果/旧固定runtime未修改。
- `C:\Python312\python.exe -B -m unittest scripts.tests.test_prism_round_report -v` exit0，3项：脚本payload安全转义、错误结果/篡改门拒绝、保留原HTML/完整原文和重复渲染。首次跨盘输出测试失败已修复为跨盘本地URI，原失败不冒充PASS。
- `node --check scripts/templates/prism-reading.js` exit0。
- `node scripts/tests/prism_reading_dom.test.cjs` exit0：3轮、66阶段/模型/对手组，所有原门/双方胜平负/半平与纯胜口径/先后手/七类动作/未测耗时/Markdown附录保留；无JavaScript执行异常。测试只在jsdom模拟DOM中运行，不打开真实浏览器或发送网络请求。
- 模拟DOM依赖装在ignored `local-artifacts/prism/report-ui-test`，不修改产品依赖；复跑先`npm install --prefix local-artifacts/prism/report-ui-test jsdom --no-audit --no-fund --ignore-scripts`。
- 浏览器工具拒绝`file://`协议；没有通过替代地址或其他浏览器绕过。真实截图、窄屏实际布局与浏览器交互 **NOT_VERIFIED**；媒体样式已实现，DOM测试不能证明视觉可读性。

## Result and decision

阅读逻辑实现并离线验证，供用户查看并继续反馈。原M61 A/B INCONCLUSIVE、M62/M63 NOT_ACCEPTED判定保持，没有新增训练/对战/发布。旧冻结报告字节与回执保持；阅读层独立版本化。

## Known limitations

可读性需用户继续反馈，尚无真实浏览器视觉验证；通用阅读层不能自动从数值推断科学机制。此次回填M61–M63，更早Alpha/Rush原报告保留。真实旧云端驱动仍输出冻结原报告，后续收口必须追加调用新阅读层，未修改正在绑定的驱动或部署到云端。新HTML是独立离线文件，但来源链接依赖原本地证据目录。Markdown附录仍较大，保留原完整证据是有意选择。

## Next authorized gate

用户查看当前实战优先报告；后续优先Balance路线的实战晋级评审，机制诊断可并行/后置。后续每轮使用同一阅读层和实战优先合同；本次没有发布、训练或加赛。


## Owner R3 correction: human/audit separation and greedy default

Status: IMPLEMENTED / VERIFIED_OFFLINE (2026-10-05). This section supersedes earlier reading-layout choices; original experiment evidence is retained.

The human HTML and `.reading.md` now show a shared-opponent, current-versus-reference matrix rather than one isolated candidate selector. For M63, the reference is the training parent Prism Balance v0.1.0. All six measured opponents are visible together; parent-against-itself is not fabricated and its absent reference row reads 未测. Detailed actors/seat ownership stay explicit. Green bold marks better directional results/efficiency (lower losses/unbought reserves included); blue bold marks descriptive magnitude. Rounded display ties have no winner. Quantities need not improve simultaneously.

Main pages contain both-greedy matches only. Historical sampling lives in `.sampling.html` and `.sampling.reading.md`. M61/M62 have no both-greedy records and their main pages say NOT_RUN; the index links their historical pages. No claim that sampling is better was tested. Current mode comes from pinned commands/plan, not a greedy opponent label.

Style prioritizes VP/Main, noble coverage, nobles/game, 0–1 VP purchase counts/share and 3–5 VP purchase/scoring behavior. Ratios use summed numerators and denominators over shared opponents. Efficiency/discount improvements do not alone establish small-card preference. The former opaque large-card AUC group is replaced by actual purchased-card printed VP and noble VP separately. Visible computed metrics carry literal formulas, without statistical tutorials.

Raw verdicts, old gates, hashes, runtime/config/replay provenance and reward-proxy formulas are now in separate `.audit.html` / `.audit.md` files. The original source Markdown and frozen `.evidence.html` remain intact. Human Markdown contains full readable per-pair actor/action/seat/duration tables, not a giant audit appendix. The audit Markdown includes the complete original plus the complete independent greedy supplement reports.

Implementation: `scripts/prism_human_report.py` projects audited data; `scripts/templates/prism-human.js` drives the human pages; `scripts/prism_round_report.py` retains the old audit view and source binding. New greedy sources require result/plan/config hashes, saved mode, effective command, candidate weight binding and a common seed/action/runtime cohort before merging. Duplicate pairs are rejected. This report projection never dispatches games.

Validation: 37 Python checks (5 report, 32 arena) pass; 77 human DOM groups (11 greedy + 66 history) and 66 independent audit DOM groups pass; JavaScript syntax and git diff --check exit0. DOM verifies high/low/display ties, matched opponent/version values, pooled Main denominators, no audit hashes/tutorials in human files, all action groups and seat identities. Browser tools reject local file URLs; no workaround used. Actual screenshot/narrow-screen visual acceptance remains NOT_VERIFIED.



## Owner R4 screenshot correction / 2026-10-05

User-provided browser screenshot establishes a real presentation defect: inline-block highlight badges contain block-level direction labels, splitting the pure-win row and making one side taller. Missing references render “未测 个百分点”. Prior offline numeric checks passed but did not catch these visual-flow defects.

Implemented: highlighted values and their single up/down marker are inline; repeated “更高/更低” sublabels are removed and direction is available in a title/legend. Each version cell has the same five lines: half-draw score, pure win, W/D/L, score interval and games/seed blocks. Fixed column proportions and a minimum scrollable table width preserve numeric alignment on narrower panels. Missing difference is an em dash without a unit. The change propagates to all actor/style tables through the shared comparison helper.

Validation: `node scripts/tests/prism_human_dom.test.cjs` exit0, 77 groups, including new computed-style checks that badge and marker remain inline, identical five-line cells, correct values and no units for missing differences. `node --check scripts/templates/prism-human.js` exit0; M61/M62/M63 regenerated exit0; `git diff --check` exit0. Actual post-change screenshot/geometry is NOT_VERIFIED; jsdom does not perform layout. The owner screenshot is the observed before state, not evidence of the final pixels. No browser-tool workaround used.

No games, training, mode/seed/weight/result changes, registration, commit or push. Original 106-table M63 source Markdown and frozen evidence HTML hashes remain unchanged; new per-page receipts bind the regenerated output. Further report feedback belongs to this same living round.

## Owner R5 / Alpha-route checkpoint correction / 2026-10-05

M63's current human identity is **M63 c4 · Alpha路线候选检查点（未发布）**, superseding the provisional Balance label. The human report explains the unchanged Balance training parent and does not invent a released Alpha version.

Added descriptive replay metrics in the shared-opponent profile and both-player detail tables: 8VP-by-20Main proportion; first 4–5VP purchase Main conditional mean; and purchase coverage. First purchase timing = sum of first qualifying purchase Main indices / number of games actually buying a qualifying card. Coverage = qualifying games / all games. Across opponents, pool the timing numerator using qualifying-game counts; do not average conditional means with equal opponent weights or divide by all games. 8VP-by-20Main proportion = games reaching at least 8 own VP by own Main20 / all games. Noble choices belong to their preceding Main. A game ending before the horizon carries its terminal prestige. Literal formulas appear next to the human tables; no opaque utility score or statistics tutorial is added.

New `greedy_trajectory` specification binds the extraction result hash to both saved source-ledger hashes, pair identities and actor game counts. The extraction replays every frozen game through the pinned rule-checking metrics binary; it never dispatches a match. Diagnostic provenance is linked in the audit report and its hash is in the reading receipt. Both actors are attached by model/seat mapping, not by assuming physical P0 is the candidate. The old metric and gate records remain unchanged.

Validation run: 6 report-provenance Python tests PASS, including rejection of a different trajectory result or replay cohort; 77 human DOM groups PASS, including conditional pooling against frozen totals, both-player trajectory values, coverage, route title and prior inline/five-line alignment; 66 audit DOM groups PASS, including original gates and superseded-route history. JavaScript syntax exit0; all three reports regenerate exit0. Real post-change pixels remain NOT_VERIFIED (offline DOM performs no layout).

## M65 version publication binding / 2026-10-05

Explicit owner publication is separate from the reader. Optional `model_releases` references require record SHA, RELEASED_EXPERIMENTAL_MODEL status, original result/candidate weight binding, installed export SHA and exact displayed full name. A route record can show released status only with that bound publication; an editorial label alone cannot register a model. Existing old-gate and source-byte guards remain. M65 uses the existing verified greedy adapter for three same-cohort grids; original M62 research evidence is explicitly historical in its Agent appendix. 11 publication/reader Python checks and119 human DOM groups PASS; no original evaluator edit or new mode pooling.

## M66 native both-greedy reading adapter / 2026-10-05

For results that are natively both-greedy, use `prism-greedy-reading-spec-v1` through `scripts/prism_round_report.py`. The independent `prism_greedy_reading.py` adapter binds the frozen round contract, result, complete Markdown, each arena result/plan/config/completion and exact candidate weights. It rejects policy/hash/completion drift and emits the established human HTML/full Markdown separately from Agent audit; no fictional sampling acceptance page. Earlier `prism-reading-spec-v1` continues on its original branch, and old output bytes remain intact. M66's local reading spec uses hash-identical harvested evidence paths; remote original spec/output/receipt remain archived. Validation: 14 Python publication/reader/statistical checks,119 existing human DOM groups,13 delivered M66 DOM groups PASS; native M66 bootstrap recomputed locally from all7168 seed/seat score projections exactly matches the frozen result. Actual pixels remain NOT_VERIFIED; no browser workaround or replay resampling.
