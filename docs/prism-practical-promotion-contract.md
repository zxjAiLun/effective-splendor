# Prism 实战优先晋级与风格归类

Status: AUTHORIZED / effective 2026-10-05
Owner instruction: 实战提升是晋级主依据，Alpha/Balance/Beta是观察到的风格方向；未实现训练时指定风格，不应将有效模型整体判为失败。

## 当前操作规程（2026-10-06）

新轮统一按[根AGENTS研究规程](../AGENTS.md)的R0–R9阶段门与S1–S6风格流程执行，填写[研究/画像模板](templates/prism-research-record.md)。该规程明确任务终点、独立确认、描述性/范围内确认/证据不足分级、mixed/undetermined、发布与默认/部署边界。它补齐操作顺序，不追溯修改下方历史判定、M67冻结合同或已发布型号。M63早期Balance暂定及后续Alpha发布只作为历史；不得将旧实验语境直接套给新候选。当前无新采样或自动发布授权。

## Problem and evidence

此前M63读页把“未通过基建研究门”直接组织成“模型未接受，先诊断奖励再继续Beta”的发布结论。这把奖励方案的研究问题当成所有版本的晋级问题，遗漏了候选在其他路线的用途。用户要求现在修正这一决策口径。

## Initial design

每轮从实战表现判断候选价值，再按实际行为分到适合的路线。训练目标是实验来源，不预先锁定最终风格；风格描述与实战发布结论分开。一个模型可以没有实现Beta的预期，同时成为下一代Balance候选。

## Scope and non-goals

本次修订M63阅读报告、记录同权重Balance路线候选的研究归类，并更正后续晋级流程。不启动新对战、不重训、不篡改历史验收门或原结果、不自动分配发布版本号、注册默认模型或部署。用户本次授权的是改这版处理口径，并未要求现在完成注册发布。

## Contracts and invariants

1. **实战是主要依据。** 看对当前代表版本的直接对战、固定多对手的共同评测、双方实战数据与不确定性。显著对父增强是有效证据，不能被风格指标一票否决；但单个对手胜率不等于总体实力。
2. **核对提升是否有覆盖面。** 检查相对父代及其他代表对手的变化，识别明显仅针对父代的退化模式。并不要求每个对手和每项描述指标都上涨，也不从几个锚点推断“完全没有过拟合”。多对手均改善的点估计是覆盖面证据，各项是否显著须分别说明。
3. **根据实际行为归类。** Alpha偏大牌购入/冲分时点与得分轨迹；Balance兼顾实际竞争表现，未呈现更突出Alpha或Beta特征时可先作为Balance路线候选；Beta相对匹配Balance参照更偏早期基建、折扣投资及兑现。风格是相对画像，可为混合或暂定，不是给模型设置一组全部必须为正的经济门。
4. **风格目标未实现是诊断结论。** 它可以说明训练假设不成立、归类变化或需要后续诊断，不自动等于模型不可晋级。不能仅因“Beta训练出来”就只能按Beta发布。
5. **保留研究合同和原记录。** M63原十门/result保持，旧`NOT_ACCEPTED_BUILDING_CANDIDATE`只回答旧基建候选合同是否达成。当前的实战优先评审是用户新增的产品决策，另有来源记录，不能伪装成本轮预注册统计验收已经通过。
6. **身份始终绑定权重。** 候选归类、正式版本登记和默认模型替换是不同动作。M63 c4权重不变；原`Prism Beta v0.1.1 candidate`作为实验标签保留，当前人类界面可称“M63 c4 · Balance路线候选（未发布）”。不得因此写成已有正式`Prism Balance v0.1.1`版本。
7. **后续先冻结竞技评测，再评审路线。** 在采样前明确代表对手、动作模式、种子、实战提升及可接受退步的判断方法；风格作为画像与路线推荐，只有明确要求检验某个风格训练假设时才设置相应研究门。禁止事后扩样、挑checkpoint或改原门获得“原验收PASS”。

## Implementation plan

给报告增加“实战覆盖面”和“当前路线建议”独立层。以保存的共同锚点数据展示父代/对照/候选，不新增区间计算。原基建门移到折叠的历史研究检验中，前台不以其FAIL标记模型整体。

## Iteration log

- 2026-10-05：用户指出实战主导晋级、风格应按结果归类；M63归类重新评审，不改冻结实验。

## Result and decision

M63原Beta目标c4可保留为**Balance路线的下一代候选（暂定画像，待版本晋级决定）**。对父半平55.0781%，原校正下界51.1230%；三个共同锚点相对父点估计均改善，平均+2.8646个百分点。不呈现“只胜父代、其余全劣”的观察模式；仍不能证明没有过拟合或宣称所有对手增强显著。相对同轮对照总体+2.1159个百分点区间跨0，直接对照49.6582%、对上一Beta46.8750%也须保留，不能忽略。

画像上折扣、贵族、旧/新基建效用均低于同轮对照，大牌印刷分与得分速度略高；没有证明成为更强Beta，也没有充分证据将其改称更突出Alpha，先纳入Balance路线候选是研发归类，而非已经验证了“均衡风格”。本轮的奖励机制诊断仍有价值，但不再是候选晋级评审的前置条件。

## Known limitations

现有比较只覆盖固定池、模式和一个训练实例，未穷尽对手，也未验证所有随机训练重复。当前路线为暂定，不更换模型权重或正式版本身份；具体版本登记未执行。

## Next authorized gate

先完成本次报告和流程修订。后续优先实战晋级评审/相应版本记录，按模型已有对战证据评估是否发布；若需更多验收，另预先固定范围，不因风格研究门未达盲目加训练。机制诊断并行或后置。


## Owner R3 / actual behavior and greedy evidence correction

Current policy: the human default is both-greedy. The earlier 55.0781% direct-parent result belongs to T=1 sampling and is not a greedy claim. Preserve it on the historical page; different modes are never pooled.

Building-route evidence must include low-VP purchase behavior relative to Balance, scoring efficiency and noble coverage. Higher discount utility/AUC/terminal discounts can reflect better utilization in any route and cannot alone establish a small-card preference. More or fewer cards, reserves and actions are descriptive directions, not universal quality scores. Route labels remain provisional unless independently registered.

M63 supplementary greedy result: direct parent 53.90625% over 256 games; five common-opponent score changes versus parent are +4.6875pp Heuristic, +1.171875pp initial, -0.1953125pp general, -1.7578125pp Alpha, -3.125pp previous Beta. The unweighted common-opponent mean is +0.15625pp; it is a descriptive comparison, not proof of broad enhancement. VP/Main rises from 0.54880827 to 0.55159113; noble coverage declines from 37.34375% to 34.84375%; 0–1 VP purchase share declines from 67.36208% to 66.60872%. This supports retaining the candidate with tradeoffs; no new promotion/registration occurred, and a stronger building identity is not established.

Evidence: `benchmarks/m63-greedy-report-supplement.result.json`, full readable per-opponent actor tables in `docs/prism/m63-prism-beta-timed-building-evaluation.reading.md`, complete source/runtime in its separate audit report. Greedy supplement is fixed independent development measurement, not an old-gate relabeling or sampling-mode superiority test.

## Owner R5 / Alpha-route checkpoint correction / 2026-10-05

Current assignment supersedes the earlier provisional Balance assignment; the earlier decision remains above as history. The owner identified the actual big-card/rush direction and requested reassessment. Absence of Beta-style building gains is not positive evidence of Balance identity. Compare actual card classes, printed scoring, noble dependence and scoring trajectory against a matched reference before choosing the research route. A candidate may branch into Alpha even when its training parent belongs to Balance; route and lineage are separate facts.

M63 final c4 is now **M63 c4 · Alpha路线候选检查点（未发布）**. Its training parent remains **Prism Balance v0.1.0**. The original experiment label and unchanged weight remain pinned in `benchmarks/m63-practical-candidate.review.json`; the previous route rationale is retained in `route_history`. It is not a continuation of Prism Alpha v0.1.4 and is not registered as a new released version.

The decision is to retain an Alpha-route research starting point, not to claim a clearly distinct style or a stronger Alpha successor. Changes relative to the matched Balance parent are small: fewer 0VP cards, slightly more 4VP cards and 3–5VP printed score, slightly better scoring efficiency, less noble coverage; a read-only replay extraction finds slightly earlier first 4–5VP purchases and a slightly higher 8VP-by-20Main rate. Some early big-card scoring points decline. Against current Alpha, greedy half-draw score is 51.953125%; the candidate's 8VP-by-20Main rate is 28.90625% versus Alpha's 29.6875%, so it is not uniformly faster than Alpha.

Both-greedy competitive evidence is primary in the current human report. Historical T=1 evidence, original Beta gates and verdict remain separate and unchanged. No new games, training, version registration or default replacement were performed for this correction. The next research choice may use this Alpha-route checkpoint; an actual new campaign still needs a bounded execution contract before launch.

## M65 owner-directed fixed research publication / 2026-10-05

Owner explicitly selected M62 Beta and M63 Alpha for release. Current names are Prism Beta v0.1.0 and Prism Alpha v0.1.5; the prior unregistered labels are historical. Release denotes fixed versioned research artifacts, not automatic strongest/default promotion. M62 greedy behavior is mixed/scoring-leaning; its Beta research-branch name is retained with an explicit warning that more building than Balance is not established. M63 retains its modest Alpha-route direction and exact Balance parent. New direct Alpha-vs-Beta score56.05% is separate from old cohorts. Complete honest opponent tables and existing research negatives remain.
