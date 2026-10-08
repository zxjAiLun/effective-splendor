# M68 Prism 项目研究操作规程

Status: VERIFIED / DOCUMENTATION_ONLY，规程与模板文档检查通过；没有新训练或模型评测。
Baseline: `m61-alpha-balance-ab@9899749188f35c838c85c5b3530049bd5dcbd105`，45个既有tracked修改和344个untracked条目保留。
Owner/date: 2026-10-06，用户要求按项目评审建议，建立项目专属AGENTS，明确研究/风格流程及每步执行终点。

任务边界：`task_kind=implementation（文档规程）`；`authorized_end=完成规程/模板及R9文档收口，不含研究执行或Git发布`；`current_stage=R9文档收口`；必交根AGENTS、模板、M68记录、链接/原文保护检查和ALL同步。R3–R7研究执行不适用（没有训练/模型评测/实际风格判定）；R8只要求文档可读性/链接与一致性，不生成模型阅读报告或新增UI。

## Problem and evidence

既有根 `AGENTS.md` 216行主要规定文档、报告与状态措辞，缺少不同任务的默认终点、逐阶段输入/产物/出门条件、风格证据分级和异常恢复决策。[本轮之前的研发评审](prism/development-review-2026-10-06.md)指出了执行与观察脱节、报告恢复、研究种子/对手覆盖及分支名和实际风格的区分问题。

需要把可标准化的动作写为后续Agent直接遵循的规程，而不是每轮重新猜测。原有M67有限实验及历史判定不因新规则回溯改写。

## Initial design

以根 `AGENTS.md` 为唯一Agent入口，用新增的中文当前规程补齐操作边界；保留旧216行原文及更严格的详细表格/阅读要求。独立模板只负责可填写字段和场景，不把文件模板宣称为已实现的控制器或自动validator。

采用R0–R9阶段门；另设S1–S6风格流程。用户已批准的有限完整流程自动推进，不制造每步审批；研究/发布/部署越权、数据缺口和阶段失败给确定处置。

## Scope and non-goals

范围：根AGENTS新增操作规程、研究/画像/异常/收口模板、实战晋级合同当前导航、handoff与本里程碑记录、文档验证及ALL同步。

非目标：不修改PPO代码、运行器、报告器、schema接口、M67配置/预算/种子/权重/原结果；不启动/恢复/停止任何远端执行；不重跑模型测试或历史比赛；不自动Git提交/push。流程生效不等于工程优化已经实施。

## Contracts and invariants

- 规则版本 `prism-research-workflow-v1`，用户直接授权创建；系统/开发者约束仍优先。
- 任务终点、产物/竞技/风格/发布/部署分别记录；有效负结果可完成实验任务。
- R1冻结科学问题、预算/种子/候选选择、统计门、风格政策及交付要求；R2/R3工程/零局预检；R4/R5训练与候选；R6独立确认；R7画像；R8/R9交付收口。
- 风格路线按实际匹配画像，不按训练目标。描述性事后归类允许且不阻碍实战价值；确认性风格必须有冻结的正向定义。mixed/undetermined是有效结果，不强迫三选一。
- 默认新方法探索优先至少3训练seed，是设计建议不是超预算开训命令；已有1–2 seed合同保持有限重复，不宣称普适稳健。
- 报告/监控失败不重跑研究；恢复保持身份、尝试预算与失败历史。新规程不能回填M67为失败或更改门。
- 原有报告全文保留；handoff继续local-only ignored。

## Implementation plan

1. 核实现有规则/主线/工作树和ALL任务。
2. 补齐根AGENTS任务终点表、R0–R9、S1–S6、工程/统计/报告/发布/恢复规则。
3. 写可填写模板及边界场景，当前实战合同链接回根规程。
4. 文档结构/相对链接/旧原文保持/冻结输入哈希/场景覆盖/diff检查，记录实际证据。
5. 两层记录与ALL交付，不启动研究。

## Iteration log

- 读取根AGENTS/handoff、M67、实战/阅读合同、指标/架构与前轮评审；实际HEAD/branch/index核验。通过ALL CLI读取本项目当前revision；M67旧心跳stale只是上下文，本任务未刷新远端状态。
- 新建独立ALL文档任务`29e102aa-2f8f-4cb8-a2dc-f4d51f858f68`，没有改动M67实验任务。
- 用Edit在根AGENTS前置当前规程，不覆写既有216行。新增10类任务终点、10阶段门、6步风格判定和3级证据，并区分研究版本与默认/部署。
- 新建模板，覆盖20个边界场景。模板没有固定研究数值或自动化能力；该轮必填参数空缺时明确停在设计/预检前。
- 明确默认风格为descriptive，阶段PASS不等于竞技增强；有效负结果继续报告收口；未产生的最终权重SHA在R5补填。进一步区分FROZEN/ACCEPTED、NOT_RUN/INCOMPLETE/UNKNOWN；多条风格政策同时成立且无预定优先时用mixed。
- 首轮102项检查有1项误报：检查器read_text将原CRLF转换为LF，再比较字节。直接raw bytes核对原9837字节完全一致；修正检查器而非改历史文件。失败回执保留`validation-attempt1-newline-check.json`，复验102/102通过。

## Final implementation

- [根AGENTS](../AGENTS.md)：后续Agent必须读取的执行入口，当前规程与旧合同同文件。
- [可填写模板](templates/prism-research-record.md)：任务边界、有限合同、阶段回执、画像卡、异常/收口和20场景。
- [实战晋级合同](prism-practical-promotion-contract.md)：保留历史，新增当前操作规程导航。

## Validation and evidence

实际命令：`C:\Python312\python.exe -B <session-scratch>/validate_prism_workflow_docs.py`，exit0，102项结构/链接/字段与场景覆盖/表格列数/旧合同保持/冻结输入保护检查通过。最终收口再以同脚本`--final`检查最终文档状态及handoff只插入新记录，回执见`local-artifacts/prism/m68-research-workflow/final-validation.json`；初始复验见同目录`validation.json`。这是一次性文档检查，不是科学合同/风格分类的运行时validator。

人工逐项核对模板C01–C20：只读范围、全流程授权、负结果收口、cN选择、风格失败转路线、缺Balance参照、非显著不等效、多路线冲突、关键对手门、报告恢复、监控失效、预算耗尽、指定研究发布、实现边界、事后指标、零覆盖、视觉缺失、有限seed、确认集污染、数值环境变化，均有明确动作与禁止动作。没有执行20次真实研究模拟或声称自动化决策测试。

`git diff --check` exit0；`git check-ignore -v handoff.md`命中`.gitignore:12`；index为空，HEAD未变。根旧216行AGENTS完整字节后缀保持、晋级合同旧字节保持；M67配置/两训练blueprint/运行及报告源码/相关coordinator SHA未变。没有重跑训练、对局、历史回放或UI像素：这些不是本次文档任务验收项。

## Result and decision

研究操作规程与模板已完成并验证，用户任务按文档范围收口。后续Agent先从根AGENTS选择任务终点，再按阶段证据推进；风格可描述、暂定、混合或不足，不凭训练目标决定，不自动发布。没有产生新模型或更改任何既有科学判定。ALL最终回报以本任务`29e102aa-2f8f-4cb8-a2dc-f4d51f858f68`的实际回执为准。

## Known limitations

这是Agent操作规程与人工可核对模板；没有实现自动状态机、风格分类器、JSON schema验证或控制器升级。具体每轮的效应阈值、样本量、对手和资源仍须在其合同填写并冻结，而非永久套用M67。

## Next authorized gate

本次文档工作到此结束，后续Agent使用根AGENTS与模板。新工程优化或新研究执行须按对应任务边界与有限合同处理；本规程不构成自动启动授权，M67原运行合同保持。
