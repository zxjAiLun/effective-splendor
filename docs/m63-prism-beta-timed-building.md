# M63 Prism Beta：真实兑现时点奖励的有限 A/B

Status: TRAINING_COMPLETED / PASS_TRAINING_ARTIFACT_AUDIT / FIXED_EVALUATION_COMPLETED。2026-10-05用户另行授权后，原Beta目标最终c4在[M65](m65-prism-version-release.md)发布为 **Prism Alpha v0.1.5**，实际路线略偏大牌冲分；原Beta研究门判定保持。原cloud1流水线FAILED_STOPPED_NO_RETRY、R1待执行与评测NOT_RUN为下方历史阶段，后来完成的DSW独立执行不覆盖原失败。Control仍未发布。
Baseline: `9899749188f35c838c85c5b3530049bd5dcbd105`；branch `m61-alpha-balance-ab`。
Owner/date: Zixuan Tang / 2026-10-04。
Authorization: 用户「okay，继续走beta路线呗 看一下这一轮效果」承接 M62 已完成研究的有限 A/B 提议，授权实现、冻结、cloud1训练、审计与固定独立评测。沿用此前允许必要时 GPT-6 Luna 辅助；主代理统筹和核验。无默认/共享池/Studio部署、Git提交或push。

## Problem and evidence

M62 两候选有效，但 Prism Beta v0.1.0 candidate 未通过基建实质门；其实际 style 项 SD 约合成 advantage 的15%，并非未进入训练。独立共同锚点下84.44%投资达到单笔3use封顶，utility/投资张数r=0.9512，全局cap未触发；512保存机会面板偏好差仅+0.4045个百分点。上述是诊断，不证明失效机制。[M62完整研究及双方对战表](prism/m62-building-reward-diagnostic.md)、[M62原判定](m62-prism-beta-building-ppo.md)保持。

## Initial design

本轮比较原目标与真实use时点加权目标，而不是从 M62 c4 恢复训练。两臂都从固定 **Prism Balance v0.1.0**（SHA `225daf49e8746576b1edc3508ca0454715e5454529fea53dc7dfeb9043cf01f1`）重新初始化相同 policy/value/style head、AdamW和RNG；β=0.3、style value MSE权重0.5等所有系数一致。Control是 **M63 原目标对照 c4（未发布训练检查点，无版本登记）**；新目标候选预留 **Prism Beta v0.1.1 candidate（未发布）**。因此新候选的训练基座是Balance，不是对上一Beta继续PPO；对冻结M62 Beta的直接比赛单独检验版本间表现。

唯一奖励改变：符合原early Main≤12、印刷VP≤1条件的投资，其原规则下前3次真实购卡适用use，按发生的本人Main时点t≤24记`w(t)=(25−t)/24`；总和按全局24截断后除24。相同use越早发生权重越大，未真实发生为0。原utility与AUC12等完整profile仍保留，不用新target取代旧指标。

## Scope and non-goals

- 两臂各4×256=1,024训练局，共2,048；cloud1按Control停止后才启动Beta，8GiB/200%CPU，0基础设施重试，不延长/选检查点。
- 开发576局，独立验收9,728局，总评测10,304局；验收在原M62结构上增加Beta对冻结M62 Beta的1,024双座局。
- 保持原Rust引擎、在线网络结构和玩家可见信息边界；不加入隐藏信息、搜索、动作温度覆盖或对手资源剥夺奖励。
- 不同时改β/学习率/对手配比/训练轮数；不转Alpha或Denial，不修改历史M62源包/config/result/门。
- 原模型NOT_ACCEPTED身份保持；本轮候选不会凭版本号或训练完成自动发布。

## Contracts and invariants

原目标为`prism-building-style-v1`；新目标使用独立严格format `prism-building-timed-style-v1`，旧building.py不改。短局不补齐真实use；购入不自兑现；choose_noble不加Main；原价颜色cost≥prebonus ordinal的结构性适用仍非反事实token节省。

训练种子拟定9651000..9651511（四cycle×128种子×双座，两臂同日程）；开发9656000..9656031；独立共同锚点9661000..9661255、直接对阵9661000..9661511。所有新范围须在首次对局之前通过历史范围冲突检查；run/init/action与bootstrap种子63041001/63041002/63041003/63042001/63049999分别绑定用途。

新门在采样前声明，10项单侧同时下界：family α=.05、q=.05/10、20,000配对双座seed bootstrap，只有最终c4，开发纯描述。风格容忍合理代价，不要求所有经济指标改善。

| 门 | 目的 / 模型本人指标 | 冻结候选阈值（校正下界） |
| --- | --- | --- |
| control/strength_pool | 原目标对照相对Balance父版共同锚点半平差 | ≥−0.05（−5pp） |
| control/direct_parent | 原目标对照对Balance父版半平得分率 | ≥0.45 |
| beta/strength_pool | 新目标相对同轮原目标总体代价 | ≥−0.05（−5pp） |
| beta/general_anchor | 相对同轮原目标对Prism v0.1.1代价 | ≥−0.075（−7.5pp） |
| beta/direct_control | 对同轮原目标竞争力 | ≥0.45 |
| beta/direct_alpha | 对固定Prism Alpha v0.1.4竞争力 | ≥0.45 |
| beta/direct_parent | 对Balance父版竞争力 | ≥0.45 |
| beta/direct_previous_beta | 对冻结M62 Prism Beta v0.1.0 candidate竞争力 | ≥0.45 |
| beta/building_utility | 原非时点utility保留容差 | ≥−0.015（0..1单位，允许小幅代价） |
| beta/early_bonus_auc12 | 不直接进入reward的早期永久折扣实质风格差 | ≥+0.25（折扣个） |

门的正式机器合同、种子、配置和源码身份在实际prepare成功时冻结。旧utility由增长门改为本轮保留容差，属于本轮新设计；不套回M62。新时点utility仅作优化目标及描述，不作独立风格接受的替代证据。原目标对照须过两保留门；Beta须过八门且对照合格。增强记录另用下界>0（差）/>0.5（直接），不得把保留PASS称为提升。失败保留结果，不自动补赛、扩样本或调整门。

## Implementation plan

1. 归档旧dispatcher字节/哈希；新timed模块、兼容分发与边界/集成测试。
2. 新prepare/blueprint/package/source/初始36张量与RNG等值、历史种子冲突检查、零局cloud preflight。
3. cloud1新root `/home/ubuntu/splendor-ppo-m63`；有界串行训练、可追溯状态与stop。
4. 固定最终c4、完整训练来源/parity审计；新自动驱动器修正旧M62状态字段和1GiB审计OOM资源缺陷，旧驱动器保持原字节。
5. 一次固定开发/独立评测；完整双方/双座/七动作/购卡/折扣/预留/时钟/来源的Markdown+HTML，分别报告产物/竞技/风格、版本身份与限制；更新handoff。

## Iteration log

- 2026-10-04：Control完成首个cycle（256物理局），串行和pipeline持续RUNNING，Beta尚未创建。新增一次性本地结果抓取器`prism_m63_result_harvest.py`（最多28h，每55s只读状态；无比赛/训练重试权限），成功后hash抓取完整报告/结果/权重/摘要，失败停止本地抓取且不动cloud服务。本机需在线才能抓取，cloud1执行独立于本机。当前live snapshot/编译/旧真实结果总分母比率算术检查PASS；未来实际抓取/浏览器目视NOT_RUN。最终阅读件会把共同锚点VP/Main汇总为总VP/总Main，原云端报告字节与流水线SHA单独保留，十门原数据不改。

- 2026-10-04：cloud1新root部署成功，50源码/8输入/4原生工具hash、package/numerical identity及两臂bind全部零局preflight通过。首个零局部署检查发现原M57 venv没有pip；失败log/脚本/receipt `.attempt1`保留，改为把SHA固定纯Python轮包解压到新root vendor，0新局/0重试训练、冻结配置未改变。
- 2026-10-04：2026-10-04T10:42:15.220717+00:00实际启动`prism-m63-training-serial-c0d3de53.service`（实测1GiB/20%/17h、PID1029412）和`prism-m63-pipeline-c0d3de53.service`（实测8GiB/200%/27h、PID1029414）。流水线已RUNNING；原目标Control物理账本截至2026-10-04T10:46:07.016293+00:00：169已启动/168已完成，失败false、重试0、4,528actor决策，心跳peak_memory_bytes=1,004,589,056；Beta未创建，需Control完成且dead后创建。启动回执和账本观察位于本轮ignored artifacts。

- 2026-10-04：首个prepare负面测试失败来自沿用M62「把control β改成0.3」的用例；M63两臂已规定0.3，修改负面输入为0.2后通过。修正测试而不是放宽合同，0新局。pipeline复审修正初稿不匹配的TIMED完成标签与不存在total_games字段，并补独立结果hash/物理预算/原失败判定保留检查。cloud缺Markdown，使用新root隔离vendor，旧venv不改。
- 2026-10-04：实际freeze时间2026-10-04T10:37:48.802023Z；10门/新种子/预算固定，结果NOT_RUN；原v1utility从旧增长门改为本轮保留容差是采样前设计，不修改M62历史判定。

- 2026-10-04：用户授权有限Beta时点A/B；cloud1实测2CPU、约12GB内存，当前约10.7GiB可用，无M62/M63活动进程，M63 root不存在。分支/HEAD保持，index空、历史工作树大量改动保留。Luna分别实现timed奖励与新评测/报告契约，主代理负责freeze、审计、部署和执行统筹。

## Final implementation

IMPLEMENTED / 配置FROZEN_BEFORE_FIRST_GAME。新timed模块独立保存v1画像和真实Main时点加权target；原building模块/learner与M62包和远端保持。通用分发器与coordinator兼容新格式，31份旧portable源归档中仅这两份指定源码变化，新增模块单独pin。

新M63 prepare/两臂raw audit/训练全量报告/固定评测/Markdown+HTML及pipeline独立于旧M62脚本。pipeline用8GiB而不是旧1GiB，并检查实际BUILDING完成状态、verdicts字段、576/9728/10304物理预算与once-only；子审计继承8GiB，评测是独立8GiB/200%单元。HTML用隔离vendor的SHA固定Markdown3.8轮包，不改历史M57 venv。

新模型训练已启动，开发与独立验收仍NOT_RUN；配置冻结不等于风格或棋力接受。

## Validation and evidence

- 主代理实际`C:\Python312\python.exe -B -m pytest`运行11个新轮/奖励模块（`test_m63_{prepare,pipeline,building_audit,building_training_report,building_evaluation,building_metrics,building_report,building_html_report}.py`及`test_building_{timed_style,style,coordinator}.py`），`-q -p no:cacheprovider`：exit0，183PASS/133subtests，11.52s；旧M62 prepare/audit/training-report/evaluation/metrics/report六模块exit0，124PASS/111subtests，12.90s。最终prepare/pipeline复测exit0，20PASS/58subtests，2.88s。Luna交付检查与主代理实际复测分开记录；没有新棋局或更新。
- `target-mapping-final.json`在2,048份既有M62训练画像上验证新target有限且`0≤timed≤old≤1`；1023/1022非零。原target均值control/Beta0.444092/0.451986，新target0.207438/0.213306；SD从0.143940/0.145788变成0.076236/0.077854；不同target数21/20→320/332。说明离散辨识度增多和整体尺度下降；不是梯度或新对战效果，β保持既定值。
- 实际`python -B scripts/prism_building_prepare_m63.py prepare`exit0；父版注册/re-audit来源复核、36初始张量等值、12,764历史种子范围冲突检查PASS，50源码pin。receipt/config/双blueprint见下面哈希；旧历史包和既有比赛不改。
- 新模型对战数据：训练RUNNING（最终c4尚未产生）、开发NOT_RUN、独立验收NOT_RUN；尚不存在最终模型完整对战表。旧模型双方完整表见[M62原固定结果](prism/m62-prism-beta-building-evaluation.md)，新轮结果随后必须生成`docs/prism/m63-prism-beta-timed-building-evaluation.{md,html}`。

| 冻结资产 | SHA256 |
| --- | --- |
| config `benchmarks/m63-prism-beta-timed-building.config.json` | `c0d3de5398c724bd502d5c30f5f52ec06a848f7fe2672c28e1086c7730b21550` |
| 原目标blueprint | `22f549b5d1a0635fb2195261e6cc7fdf0f5b79f6057af5ea6f284f3efaf433e1` |
| timed Beta blueprint | `63827485a15c7b3acfba8a9b9f6793eb30c80a8abcebc1344a9e3b8dc23b57f0` |
| portable package | `8765a445a7c3f38896e20cd0a5d43a36525cfa012defa7c96b595825ebda184f` |
| portable code identity | `c48d6fdb0db00176e4aaad1b39979cb711006bf4773fc649f71f6ffe7da72327` |
| numerical identity | `ce1bb93c9ce5e13bad1ef05845ba531cb3a0366e2de331fec9917ca211ab7303` |
| 初始36张量parity | `31d873822c7098fa15eecd0b944e5fb79aee3c8e78612a1c0e17b8d9e24da7bd` |


## Result and decision

当前更正：两臂最终c4训练产物已产生且审计PASS；原流水线在评测prepare前置检查失败，开发/独立验收0局、竞技与风格NOT_RUN。详见后文实际失败与R1修订；不宣称接受或增强。

## Known limitations

单一训练随机种子、有限局数；新target尺度改变，保留同β未保证等梯度强度。结构性use不等于反事实省token；AUC增长不自动证明棋力更强。冻结验收会为十门支付多重比较成本，底线FAIL可能只是容忍未获确认。新采样严格执行预定停止规则。

## Next authorized gate

完成兼容实现与必需检查，冻结后直接执行本轮cloud1有限训练/审计/验收；用户本条已授权，不重复请求启动许可。遇真实执行合同无法满足则停在明确失败证据，不能放宽历史门或静默重试。

当前更正：原执行已FAILED_STOPPED_NO_RETRY；禁止自动重启原pipeline。完成零局诊断与R1实现验证后，下一实际对战派发须单独授权此执行修订，原失败记录保持，训练不重跑，权重/种子/对手/十门保持。

## 2026-10-04 接手运行复核与改进审阅

REVIEWED（静态执行链及当前只读状态）；本轮仍 TRAINING_RUNNING，竞技与风格验收 NOT_RUN。本节不修改冻结训练源码、配置、种子、十门或运行资源，不触发补训/补赛/发布。

### 当前执行证据

2026-10-04T11:13:23.760591Z（北京时间19:13）cloud1只读SSH探针exit0：串行训练和pipeline均active/running，PID分别1029412/1029414。Control最新cycle边界为2/4、累计512 attempts/108 update_attempts，该边界256 jobs均COMPLETE；此文件不是逐局实时进度，后续cycle在途局数未据此计算。Beta尚未创建，独立结果文件尚不存在。证据及探针源码、执行argv、有关源码SHA保存在`local-artifacts/prism/building-beta-m63/takeover-review-2026-10-04/observation.json`。

实测训练cgroup当前内存6,942,248,960bytes（约6.47GiB）：anon约2.86GiB、file约3.49GiB，memory.events中max/oom/oom_kill均0。总占用含大量文件缓存，不能从峰值上升直接推断泄漏；当前未发生内存限额事件。保持冻结8GiB上限，后续诊断需持续区分anon与file，不能把缓存等同于模型常驻内存。

### 发现与优先级

| 优先级 / 状态 | 证据与具体影响 | 建议修订边界 |
| --- | --- | --- |
| P2 / 确认，未修复 | `scripts/prism_m63_result_harvest.py` REMOTE在campaign目录查找checkpoint-audit/parity-audit及三份训练审计文件，但实际writer输出在`audit-{control,beta}/`，前两份实际名称为checkpoint-validation/final-parity。缺文件直接跳过，PASS_FETCHED_HASHES只证明已抓取文件hash，不能证明证据集合完整。预计漏抓每臂五份审计文件；不影响云端训练或正式结果，但影响本地追溯。 | 本地抓取器另行修订，按审计binding/明确必需集合解析文件并拒绝缺项；保留旧执行源码与回执。重启本地只读抓取进程属于抓取修订，不是训练重试；本次未实施。 |
| P2 / 静态故障处理缺口，未触发 | `scripts/prism_m63_pipeline_driver.py`仅等待serial-final.json最多17h。若训练进程被SIGKILL/OOM且没有终止回执，可能长期显示等待；本地reader只观察pipeline死亡，也不能及时识别这种情况。两服务本次观测均存活。 | 下一执行修订同时观察所有权绑定的训练unit存活/退出状态，留下明确失败证据；增加无比赛的SIGKILL/无回执故障注入，不自动恢复训练。 |
| P2 / 静态抓取恢复缺口，未触发 | SSH一次失败即退出本地reader；可读报告先写Markdown再生成HTML，后者失败会留下部分输出，而后续调用拒绝覆盖，不能自行完成收尾。 | 允许有界只读网络重连、临时文件完整校验后发布、按hash幂等恢复；与冻结0训练/比赛重试分开计数。 |

上述属于源码审阅发现，不宣称已经复现OOM/SIGKILL/断网或修复通过。当前复核仅运行只读探针与源码检查，未重跑训练测试或新对局；既有测试成绩仍为前文启动前验证。

### 后续研究判断（PROPOSED，未开启新轮）

继续等待本轮固定最终c4和独立验收，先判断基建风格是否出现及竞争底线是否保留。已有旧画像映射表明timed target SD约为原目标的一半；同β并不控制残差/梯度强度，因此本轮差异不能全部归因于奖励时点。下一轮若需要辨别机制，应预先设计奖励尺度控制，测量实际style残差/advantage贡献，再确定系数，不能事后给本轮调β。若本轮出现有用方向，优先少量独立训练种子复验稳定性；众多评测种子不能替代训练重复。暂不据中途训练战绩盲目增加PPO轮次或切换风格。

## 2026-10-04 19:55 进度与预计结束时间

2026-10-04 19:55（Asia/Shanghai）只读cloud1核验：Control已STOPPED_COMMITTED，4/4轮、1,024局、216 update_attempts，用时2,933.52秒（48.89分钟）；Beta最新完成边界2/4轮、512局、108 update_attempts。合计已完成边界1,536/2,048训练局（75%），在途局未计入；串行及pipeline均active/running，开发/独立验收NOT_RUN。预计训练20:15–20:30结束，含审计、10,304评测与报告的完整结果预计21:30–22:15；这是正常负载下估算而非完成保证。依据本轮训练进度与上一M62评测实测3,084.918秒/9,280局等比例约57分钟，加审计/报告与运行波动余量。证据`local-artifacts/prism/building-beta-m63/eta-observation-2026-10-04.json`；仅观察与记录，不改冻结实验。

## 2026-10-04 实际训练完成、评测prepare失败与R1兼容修订

### 原执行与根因

2026-10-04 20:20:27 +08串行训练结束，Control/Beta均4轮、1,024局，实际更新216/218。产物审计exit0（82.1685秒），全量训练报告exit0（291.8855秒）；20:27:01 +08 eval_prepare exit1，原pipeline `FAILED_STOPPED_NO_RETRY`，不是模型棋力门FAIL。evaluation目录尚未创建，576开发与9,728独立验收对局均0局；此前完整结果ETA失效。两臂训练资源returncode0/stop_reason null、最终c4固定。

根因：`prism_building_training_report_m63.publish_binding`写入规范字段`initial_36_tensors_and_rng_equal=true`，冻结`prism_building_evaluation_m63.audit_evidence`却要求旧字段`initial_policy_value_and_rng_equal`。原启动前测试覆盖种子/门/分片但没有贯通真实writer binding和reader，不足以发现接口错配。只读在内存复制binding并做字段适配后，原校验器核验10份底层审计文件PASS，原回执hash未改变，0新对局。保留实际失败，不能用后续兼容结果把原流水线改为PASS。

### 本地证据与阅读件

显式按binding抓取21份两臂权重/companion/原始审计/账本/完整训练对战表及原失败，17项绑定SHA校验PASS；原reader路径错配未用于此次取证。首次并行scp大文件90秒超时，partial保留，改只读gzip tar流传输后完整成功；属于网络抓取，不是训练或比赛重试。原训练表原字节保存在ignored归档。

[可读HTML](prism/m63-training-audit-and-evaluation-status.html) / [Markdown](prism/m63-training-audit-and-evaluation-status.md)包含两臂完整训练双方表、描述性单位与带符号差、原故障和十门NOT_RUN。165份Markdown表与165份HTML表数量一致，两份原训练报告完整保留；浏览器目视NOT_RUN。最终c4独立结果仍不存在，候选未发布。证据目录`local-artifacts/prism/building-beta-m63/failed-evaluation-prepare-2026-10-04/`，其中cloud-evidence、alias-diagnostic、fetch-receipt、r1-diagnostic、readable-report-validation均实存。

### R1执行修订（未启动对战）

新增独立`scripts/prism_m63_evaluation_compat_r1.py`，不改原50份冻结源码、config、blueprint、权重和审计回执。要求规范format、PASS、36张量/RNG相同、2,048局/32groups；拒绝缺失、false、非布尔true及冲突旧字段；仅在内存复制规范binding并向原checker适配旧名，保留所有raw audit验证。preflight要求原pre-dispatch失败，重新核验50源码和模型身份。prepare会在原execution文件中额外绑定R1适配器SHA、原失败SHA、原audit SHA；verify/run重新核验修订且仍委托原固定网格/十门/资源和0对局重试检查。原pipeline失败回执不覆盖。

实际 `C:\Python312\python.exe -B -m pytest training/prism_portable/tests/test_m63_evaluation_compat_r1.py training/prism_portable/tests/test_m63_building_evaluation.py -q -p no:cacheprovider` exit0：33PASS，最终复测6.99秒。云端新增独立R1文件后只运行`diagnose`，exit0/PASS_READ_ONLY_COMPAT_PREFLIGHT、0新局；没有调用prepare/verify/run，没有新evaluation单元。修订状态IMPLEMENTED / VERIFIED_ZERO_GAMES；独立竞技/风格NOT_RUN。

下一实际执行待单独授权：原合同明确0基础设施重试且失败停止，不自动重启原pipeline。提议以R1修订完成原定576+9,728局（保持原种子/对手/权重/门/资源/0比赛重试），不重训、不扩赛、不重新选择c4。允许后才能冻结新execution SHA并启动`prism-m63-evaluation-r1-<execution_sha8>.service`，8GiB/200%/8h，以R1 `run --execution-sha256`执行；完成后按原报告器生成Markdown/HTML，新completion与原失败并列记录。预计获准后约60–90分钟含报告与抓取，不承诺先前21:30–22:15窗。

| 修订证据 | SHA256 |
| --- | --- |
| original_failure_sha256 | `3eaafea0b32a146f80f1918ea5bffd2fc4f3ac5524aaa713a972dd1b17c11148` |
| original_audit_sha256 | `e193b9d91faab787751dd4d299a3f2c42f50e724e079833210e6e4f72669db75` |
| config_sha256 | `c0d3de5398c724bd502d5c30f5f52ec06a848f7fe2672c28e1086c7730b21550` |
| adapter_sha256 | `50a111b1f05da7a073b1f2815d7dca56d7ec05766948289716c83a1250b2b5c1` |
| control最终c4 | `965aa74777fc79ef6db592060fbdeac93836bbd1d47b1526efeddf7cde35a55d` |
| beta最终c4 | `3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12` |


## 2026-10-05 DSW执行修订R2 — AUTHORIZED / 迁移预检中

用户明确选择「用dsw吧」，并说明DSW2约1小时未操作会自动关闭。此指令授权在持久化DSW完成原M63评测及必要的R1字段兼容/平台执行修订；不再重复询问启动许可。原cloud1失败记录保持，训练不重跑，最终c4/原配置字节/576开发+9,728独立网格/全部十门/0比赛重试保持。

执行目录为`/mnt/workspace/splendor-m63-dsw-r2`，独立于M64通用烟测和用户隧道。实测DSW为4核、约15.35GiB配额；R2固定3workers、3个继承affinity CPU、8GiB聚合RSS软限额及单进程AS限额、8h/40,000CPU-s/32GiB。没有独占systemd/cgroup内存隔离，不能声称沿用原8GiB硬cgroup；原200%/2workers资源合同另存，平台及并行度修订在首局前绑定。

原305份Rust/Cargo源码和6份projection证据与当前文件逐项SHA一致。x86 native以同冻结源码构建，保留原ARM binary SHA作为来源；已补编译bigcard/projection。启动前要求7模型×68保存输入和8份保存回放跨架构校验，0工程新增局；任何差异拒绝派发正式网格。迁移适配器为`scripts/prism_m63_dsw_execution_r2.py`，不修改原冻结源码/config/审计。

预检还发现原M63冻结执行链三个未触发缺口：`stage_run`缺`subprocess`导入；孤立replay collector把economy tool定位到source ROOT而prepare链接在collector-root；projection collector将v1 style传给要求timed wrapper的extractor。R2仅在隔离进程内适配导入/路径/对应已冻结timed wrapper，风格公式和门不变。后续必须实际贯通保存回放，不以mock检查代替。

本地原R1+M63评测33检查PASS；R2新增6检查PASS（首轮Windows路径分隔符断言失败，修正平台无关断言后6PASS/2.61s）。DSW部署587文件逐项hash PASS。正式对战当前仍NOT_RUN；尚未冻结R2 execution或启动。所有迁移/负面尝试证据位于`local-artifacts/prism/m63-dsw-r2/`。

### R2实际启动与冻结（2026-10-05 02:12 +08）

迁移已IMPLEMENTED / VERIFIED_ZERO_GAMES并实际启动。7模型×68保存输入与8保存回放的economy/bigcard/projection工具跨ARM/x86共25,748项数值完全一致，最大绝对差0；16份双方building profiles实际贯通并验证`0≤timed≤v1≤1`。原raw audit/50源码/两臂固定c4复核PASS。DSW不装训练Torch：新增`prism_m63_dsw_metrics_runtime.py`从SHA固定原io/contract AST仅提取canonical_hash/exact/integer三个stdlib函数；不暴露训练或Tensor操作，完整原源码字节不改。

原R1/M63与R2联测39PASS/3.41s；新增stdlib边界后R2七项复测7PASS/7.39s（这七项与前39有重叠，不加总）。工程preflight负面尝试保持：首次缺Torch导致离线工具链未完成；第一次profile fixture把8回放误标成同模型/座位导致duplicate key拒绝，修正测试身份后实际16profiles PASS。均发生于正式首局之前、0新比赛，失败JSON/partial目录保留，不是原pipeline或正式对局重试。

R2最终execution SHA为`aaa1d2a848c8de816c76c36efebfc190d5ef1f44521c30848bd966e7905946f0`，prepare/独立verify exit0后由launcher预先核对并传入run；中间original prepare输出2eb1a181…未用于启动，最终R2绑定才是本次执行身份。后台PID294911、UTC启动2026-10-04T18:07:35.513614（北京时间02:07:35），SSH脱离运行，库线程1。原失败与config SHA仍原值，本地四个runtime源与execution源pin逐项一致，0比赛重试。

实测02:12:46：开发576/576完成；独立验收已进入ACCEPTANCE_RUNNING，3个worker存活，当前观察记账0/9,728，总576/10,304；尚未统计原十门。峰值观察RSS约185.6MiB；CPU/时钟只说明运行状态，不是棋力证据。原预估40–70分钟未校准；睡前排程保守留自02:07启动起60–90分钟含统计报告，即约03:08–03:38，后续按固定网格进度更新，不延长8h上限。

[可读进度HTML](prism/m63-dsw-evaluation-status.html) / [Markdown](prism/m63-dsw-evaluation-status.md)保留原十门NOT_RUN；完成后driver自动使用原报告器生成全部双方/座位/风格/动作表与HTML，在reports目录落盘。报告R2资源说明替换旧200%/2worker措辞，原结果JSON/原十门不重算或改判；本地抓取仍需后续进行。本轮发布/登记/默认/共享池/Studio/Git commit或push均未执行。

本地证据：`local-artifacts/prism/m63-dsw-r2/{native-port-receipt,portability-parity,preflight-integration,evaluation-execution,launch,progress-observation-3,local-source-binding-verification,status-report-validation}.json`；远端同owned root。当前下一步是让原固定评测继续，完成后抓取并核验全量报告/原十门，再讨论下一轮；不重启已失败原pipeline或向DSW2派发。

### 02:19:40进度与ETA更新

只读核对：后台owner生存/creation time匹配，原执行SHA一致，开发576/576；独立完成1,041/9,728，总1,617/10,304，ACCEPTANCE_RUNNING、3worker、重试0。资源RSS观察峰约220.2MiB，原十门仍NOT_RUN。status心跳02:19:35为1,031局，与随后账本核对1,041局的4秒时差不构成漂移。前批独立对战约7分钟完成1,041局；计入后续统计/报告余量，当前预计北京时间03:20–04:00完成，替代前03:08–03:38粗估；8h停止预算不变。此观察仅计进度和资源，不提前分析竞技或风格结果。证据progress-observation-4.json；可读页面已更新到此快照。

### 02:37吞吐观察与用户下一步约束

实测开发576/576、独立3,501/9,728，总4,077/10,304，3worker/3 CPU affinity、owner生存、原execution一致、retry0。近期17.335分钟新增2,460独立物理局，141.907局/min、1,000局7.047分钟；末尾统计/报告另计，满核NOT_MEASURED。用户要求以后ETA同时报告并发及吞吐；要求明天另测充分使用4核和稳态最佳配置，今晚保持本正式合同不变。当前8GiB是上限、对战RSS观察峰0.219GiB，最终分析峰未测。校准计划和方法归入[M64性能记录](m64-prism-notebook-arena.md)，当前0校准新局，十门尚未分析。

### 2026-10-05T13:24:13+08:00 结果取回受阻：DSW SSH 隧道不可达

当前状态：**RESULT_RETRIEVAL_BLOCKED / REMOTE_RUN_STATE_UNKNOWN**。`ssh dsw` 返回255、`Connection refused`；跳板机SSH正常，但只读 `ss -ltn '( sport = :2222 or sport = :2223 )'` 没有监听行。ALL本次也显示DSW离线（最后可达2026-10-05 03:30:27北京时间）。这些连接证据不能判定比赛完成或失败；02:44:14最后已核验开发576、独立4647，共5223/10304，不代表现在的进度。

模型产物身份保持冻结；竞技与风格的最终结论**尚未取得（未读取，不等同于已证明NOT_RUN）**。历史03:20–04:00 ETA与02:37运行快照均已过时。没有重启任务、清除锁、修改十门或派发新对局，也未运行满核校准。原3workers实测141.907局/min（1000局7.047min）仅为历史比赛派发窗口，不能当作当前速度或最终报告总耗时。

恢复入口：DSW Web终端先确认实例运行，并执行既有 `/mnt/workspace/.dsw-ssh/bootstrap.sh` 恢复隧道；不改私钥、隧道配置或守护钩子。连接恢复后先读取 `/mnt/workspace/splendor-m63-dsw-r2/driver-completion.json`、`evaluation/completion.json`、`evaluation/status.json`、`reports/completion.json` 和日志；核验execution SHA与报告绑定后取回原Markdown/HTML和固定结果。若比赛已完成而报告失败，保留失败并单独处理只读报告兼容，禁止重新派发正式网格。

证据：`local-artifacts/prism/m63-dsw-r2/result-state-observation.json`、`jump-listener-result-check.json`、`all-context-result-check.json`。本次阻塞为取回通道故障，不是模型FAIL。

## 2026-10-05T13:37:55+08:00 重启后取回：正式评测完成，基建候选未接受

**产物结论：**训练c4身份及原审计保持；执行SHA `aaa1d2a848c8de816c76c36efebfc190d5ef1f44521c30848bd966e7905946f0`；结果SHA `a3c5c4f2c48b2b7dc36fed34326236ba5bcab687718ede6fe7bac99902b1e989`。Prism Beta v0.1.1 candidate是未发布候选，Control是无版本登记的训练检查点；没有替换默认、注册或部署。

**竞技结论：**固定开发576 + 独立9728 = 10304局，0重试，原formal分析一次。Control两门通过；Beta八门中四门通过，原判定 `NOT_ACCEPTED_BUILDING_CANDIDATE`。Beta对共同父版Prism Balance v0.1.0半平得分55.0781%，校正下界51.1230%有对父增强证据；对Alpha52.1973%的普通95%区间仍跨50%，不宣称显著更强。总体共同锚点相对Control +2.1159个百分点，区间跨0，不宣称总体增强。

**风格结论：**原building utility相对Control **↓ -0.010661**，普通95%区间[-0.016900,-0.004367]；timeweighted描述效用 **↓ -0.006718**；early bonus AUC12 **↓ -0.030273折扣**，95%区间[-0.044651,-0.015842]。本次奖励修订没有达到“更多早期基建”的冻结目标，不能仅凭胜率将其发布为合格基建版本；也不能据一轮失败证明整条Beta路线无效。

### Prism Beta v0.1.1 candidate 独立对战概要（模型本人；双方T=1，Heuristic/初代greedy）

| 对手 | 局数 / 双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 |
| --- | --- | --- | --- | --- |
| Heuristic v0.3.1 | 512 / 256 | 382/4/126 | 74.6094% | 75.0000% |
| Prism v0.1.0 | 512 / 256 | 373/3/136 | 72.8516% | 73.1445% |
| Prism v0.1.1 | 512 / 256 | 326/2/184 | 63.6719% | 63.8672% |
| Prism Balance v0.1.0 | 1024 / 512 | 559/10/455 | 54.5898% | 55.0781% |
| M63 原目标对照 c4（未发布） | 1024 / 512 | 503/11/510 | 49.1211% | 49.6582% |
| Prism Alpha v0.1.4 | 1024 / 512 | 526/17/481 | 51.3672% | 52.1973% |
| Prism Beta v0.1.0 M62（冻结未发布对手） | 1024 / 512 | 475/10/539 | 46.3867% | 46.8750% |

完整双方经济、七类动作、实体座位、配对区间、种子和身份哈希见[106张Markdown表](prism/m63-prism-beta-timed-building-evaluation.md)及[HTML报告](prism/m63-prism-beta-timed-building-evaluation.html)。以上概要不代替完整报告，开发与独立样本不合并。

### 四项未通过门的准确解释

| 门 | 估计 | 普通95%区间 | 十项同时单侧下界 | 冻结下界要求 | 失败含义 |
| --- | --- | --- | --- | --- | --- |
| 对Prism v0.1.1相对Control | -1.4648个百分点 | [-6.8359,+3.9062]个百分点 | -8.3984个百分点 | ≥-7.5个百分点 | 不确定性下尚未排除超过容忍线的退步，不是证明退步8.4个百分点 |
| 直接对冻结M62 Beta半平得分 | 46.8750% | [43.7500%,50.0000%] | 42.7734% | ≥45% | 点估计在线上，但置信下界不足，未证明保留竞争力 |
| 原building效用差 | -0.010661 | [-0.016900,-0.004367] | -0.018880 | ≥-0.015 | 点估计在容忍内，但未排除超过容忍线；普通区间显示下降 |
| early bonus AUC12差 | -0.030273折扣 | [-0.044651,-0.015842] | -0.049425折扣 | ≥+0.25折扣 | 没有达到预先要求的风格增益，且观察到下降 |

这套门允许强度/效用在声明容忍内交易，并非要求所有描述指标改善。此次不能用事后降低门槛改判；可以保留候选作研究参考。

### 时钟、恢复和只读核验

- DSW 3workers、3 affinity核、8GiB软预算；对战派发合计3754.380s=62.573min，实测 **164.672局/min，1000局6.073min**；独立派发3498.059s=58.301min。全评测含采集/分析3990.123s=66.502min，启动至报告完成约67.38min。
- 采样RSS峰0.748GiB，非8GiB已分配；决策/推理耗时仍NOT_MEASURED。4核满载未测，不能由本数据推断；M64性能任务保持planned，本次0校准新局。
- 原报告2026-10-05 03:14:58北京时间完成；owner提供实例06:18停止中、06:19:10因闲置已停止，随后重启并恢复既有隧道。此前UNKNOWN仅是连接观测限制，现在补充为已完成，并保留原取回失败记录。
- 取回18文件archive SHA `20e8638734c955a8d3be150cb7e2640978441527b85e5decba51ceebbaf52ed8`逐文件SHA核验PASS。重启后原R2 `verify_revision`、`all_grid_completed`、报告 `validate_measurements`只读调用全部PASS、new_games=0；本地校验execution/config、两阶段四证据SHA、match-details/pairs一致及报告绑定PASS；106张HTML表原样保留。
- 命令：`C:\Python312\python.exe -B local-artifacts/prism/m63-dsw-r2/harvest_results.py`、`verify_harvest.py`均exit0；证据`restarted-result-state.json`、`result-harvest-remote-receipt.json`、`post-restart-read-only-verification.json`、`harvest-validation.json`。远程零新局复核网格，未重新做bootstrap或训练；局级原始回放保存在DSW持久盘，本次未将全部回放下载到本地。

**下一步建议（尚未新训）：**先利用保存轨迹诊断奖励量级、style advantage和实际早期投资/兑现分布，弄清新目标为何下降；随后再提出一变量有界Beta修订，不盲目续训、不挑已见结果的checkpoint、不改本轮门。另行M64 4核性能校准与模型强度实验隔离。

## 2026-10-05 用户要求每轮报告逻辑重写 — IMPLEMENTED / VERIFIED_OFFLINE

用户反馈即使HTML也几乎不可读；问题定位为内部状态名、宽表、重复比较与逐局来源清单占据主阅读路径，读者无法直接判断结论。本次只重写阅读层：先给产物/竞技/风格三判断和模型身份，再给半平得分区间图、少量匹配风格变化、下一步建议；详细数据按阶段/被测模型/对手选择，七组双方指标折叠。未通过门逐项解释“点估计达到但下界不足”和“风格实际下降”的不同含义。

新入口仍为[原报告地址](prism/m63-prism-beta-timed-building-evaluation.html)，另有[阅读版Markdown](prism/m63-prism-beta-timed-building-evaluation.reading.md)及[轮次索引](prism/reports.html)。原HTML原样保存在[冻结证据页](prism/m63-prism-beta-timed-building-evaluation.evidence.html)，SHA仍`2af29a90b32adf7d3ee07784a2c97cd334f1134fa421beaa7be9cfa50f9faaf5`；原MD/result/config/执行及十门不改。新阅读回执`prism/m63-prism-beta-timed-building-evaluation.reading-receipt.json`独立记录来源，不改旧云端completion。

统一生成器`prism_round_report.py`与`benchmarks/reports/m63-reading.json`构成后续默认阅读入口；M61/M62也回填，原判定分别INCONCLUSIVE/NOT_ACCEPTED。AGENTS与[阅读合同](prism-report-reading-contract.md)规定后续每轮追加阅读层，冻结原生成器保持。此次无新对战/训练/部署/版本登记/Git提交。

验证：三轮生成exit0；Python 3项安全/来源/重复渲染测试PASS；jsdom模拟66组阶段/模型/对手及全门、双方战绩、动作、座位、未知计时和完整Markdown保留PASS；JS语法检查PASS。测试中发现的新页重复生成、跨Windows盘输出及换行比较问题已修复，保留失败日志后复跑通过。真实浏览器工具拒绝file协议，没有绕过；截图、真实浏览器窄屏及视觉可读性NOT_VERIFIED，需用户查看反馈。详细命令与限制见阅读合同。模型研究下一步仍为保存轨迹诊断。

## 2026-10-05 用户更正晋级依据 — 实战优先，同权重Balance路线候选

此前“基建原门未达→模型未接受→先诊断奖励”混淆了研究假设检验与实际版本价值。用户明确：主要看实战提升和非单对手针对的覆盖面，再按Alpha大牌冲分、Balance、Beta相对Balance基建倾向归类；风格指标不作为整个模型的一票否决。该指令覆盖前文的下一步顺序，但不将原十门/result改判为PASS。

**当前模型结论：**权重`3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12`保持。原实验名`Prism Beta v0.1.1 candidate`保留；当前研发归类为**M63 c4 · 下一代Balance路线候选（暂定，未发布）**，实战优先晋级评审候选，不是已经登记的Prism Balance新版本，也没有证明“均衡风格”。身份记录见`benchmarks/m63-practical-candidate.review.json`。

### 独立共同锚点覆盖面（各模型本人半平得分；候选均为同一c4）

| 固定对手 / 对手模式 | 父代Prism Balance v0.1.0（T=1） | M63 c4 Balance路线候选（T=1） | 候选 − 父代 | 候选 − 同轮对照 | 每模型局数 / 双座种子块 |
| --- | --- | --- | --- | --- | --- |
| Heuristic v0.3.1 / greedy | 70.4102% | 75.0000% | **↑ +4.5898个百分点** | ↑ +4.7852个百分点 | 512 / 256 |
| Prism v0.1.0 / greedy | 70.7031% | 73.1445% | **↑ +2.4414个百分点** | ↑ +3.0273个百分点 | 512 / 256 |
| Prism v0.1.1 / T=1 | 62.3047% | 63.8672% | **↑ +1.5625个百分点** | ↓ -1.4648个百分点 | 512 / 256 |
| 三对手等权平均 | 67.8060% | 70.6706% | **↑ +2.8646个百分点** | ↑ +2.1159个百分点 | 不增加或合并独立对局 |

这是新整理的描述性点估计，不新增正式验收或重做bootstrap；逐锚点/平均候选−父代配对差区间未另算。候选直接对父的55.0781%与原校正下界51.1230%仍是已有增强证据。三个锚点都比父提高，观察模式不是“只赢父代、其他全劣”；但不能证明完全没有过拟合或每项显著。相对同轮对照总体差普通区间跨0，对照直接49.6582%、上一Beta46.8750%、Alpha52.1973%均保留，不掩盖局部代价。

**实际画像：**相对匹配同轮对照，早期折扣、永久折扣、贵族与基建效用略少，终局大牌印刷分（8.080078→8.128906 VP/局）和自身Main速度（0.561913→0.564096 VP/Main）略高。它没有证明更偏Beta基建，也没有证明明显更突出Alpha；作为Balance路线候选暂存最合理，而不是仅因训练目标叫Beta就把产物淘汰。全部双方/座位/经济/动作原表仍在原完整报告与阅读附录。

**流程修订：**[实战优先晋级合同](prism-practical-promotion-contract.md)和AGENTS已写入该要求。后续优先按Balance路线评审是否值得登记版本；风格训练机制诊断可并行或后置，不作为保留/晋级候选的前置条件。当前授权仅为这版报告和口径修订，0新局、0重训、无默认替换或版本登记。

**实现/验证：**统一阅读生成器增加可选同权重实战评审记录和覆盖面表，reading MD同步追加；历史十门默认折叠，其原FAIL枚举只在历史原记录中出现。Python4项exit0、66组离线DOM+新增覆盖面/归类/旧门折叠检查exit0；JS语法exit0。权重、result、原MD/HTML SHA保持，新reading-receipt记录新评审SHA与旧研究verdict。真实浏览器视觉验证仍受file协议限制，未绕过。


## 2026-10-05 owner report R3 / separate greedy supplement

AUTHORIZED: user requires higher/better-side emphasis, current-versus-parent matched tables, greedy-only human reports, scoring efficiency/noble coverage/low-VP purchase behavior for style, and a separate agent audit page. No statistical tutorials or raw hashes/verdicts in the human page. Prior report revisions did not satisfy this scope.

The frozen M63 candidate was sampled at T=1, including against greedy opponents. It has no measured both-greedy record. Its 55.0781% direct-parent score is historical sampling evidence, not greedy evidence. Original result, runtime, weights and ten gates remain byte-identical.

Prospectively fixed supplementary development grid: `benchmarks/m63-greedy-report-supplement.config.json`; final c4 and Prism Balance v0.1.0 against five common greedy opponents (128 new seeds, both seats, 2560 games), plus c4 versus parent (256 games), total 2816. DSW, three workers, 8GiB observed RSS budget, one-hour wall and three CPU-hours per sequential run, zero retries. Descriptive paired intervals only; not a formal promotion or sampling-versus-greedy superiority test. No release, training, commit or push.

Generic Notebook/SSH arena has an explicit greedy validation adapter. It reuses pinned-asset/path/seed checks and restores the actual saved `agent-prism` command; the frozen PPO evaluator remains unchanged and sample-only. All 32 generic-arena tests passed, including saved/effective-command agreement, no config mutation, seed/asset rejection and legacy sample-only rejection.


## Owner R3 closeout: greedy supplement and readable comparison

Status: COMPLETED_FIXED_GREEDY_SUPPLEMENT / VERIFIED_REPORT_PROJECTION / NOT_REGISTERED. Original M63 sampling result and original ten research gates remain unchanged.

Fixed grid: 2816 completed games, 128 new paired seeds per matchup, candidate and parent versus five shared opponents plus direct candidate-parent. All model modes greedy; final c4 weights only. Source plan/config/result/ledger/completion receipts are in `local-artifacts/prism/m63-dsw-r2/greedy-r3/{common,direct}` and remote `/mnt/workspace/splendor-m63-greedy-report-r3`. Archive SHA256 `2c8c68556e163914891825ce985897e4ab3be91d61e88eae606b69a93ae4e0bf` verified locally after transfer.

Infrastructure deviation: initial completion-audit adapter rejected greedy descriptors, stopping three dispatched shards. 46 completed games retained without redispatch; two running game directories had no terminal replay/report and were archived, then manually restarted at the identical identity/seed/seat. Zero automatic retries; both original failed plan/status and manual repair evidence retained. New generic source hash explicitly recorded after repairing the missing completed-shard call. A sequential-driver startup race later interrupted only the driver; the owned arena continued. A separate watcher waited for verified common completion, then started direct. No weights/opponents/seeds changed, no statistical selection, no concurrent doubling of workers. These are not changes to the frozen original M63 contract.

### Both-greedy competitive summary

Candidate: M63 final c4, provisionally Balance-route (unpublished). Reference: Prism Balance v0.1.0, its training parent. Each score belongs to the named model against that row's opponent.

| Opponent | Parent half-draw score | Candidate W/D/L | Candidate pure win | Candidate half-draw score | Candidate paired 95% score interval | Candidate minus parent |
| --- | --- | --- | --- | --- | --- | --- |
| Heuristic v0.3.1 | 77.73% | 211/0/45 | 82.42% | **82.42% ↑** | 78.13..86.72% | +4.69pp |
| Prism v0.1.0 | 81.84% | 212/1/43 | 82.81% | **83.01% ↑** | 78.52..87.30% | +1.17pp |
| Prism v0.1.1 | **62.30%** | 158/2/96 | 61.72% | 62.11% ↓ | 56.05..67.97% | -0.20pp |
| Prism Alpha v0.1.4 | **53.71%** | 132/2/122 | 51.56% | 51.95% ↓ | 46.09..57.62% | -1.76pp |
| Prism Beta v0.1.0 | **51.76%** | 122/5/129 | 47.66% | 48.63% ↓ | 42.97..54.30% | -3.13pp |
| Direct parent: Prism Balance v0.1.0 | NOT_RUN (parent self-play omitted) | 137/2/117 | 53.52% | 53.91% | 48.05..59.57% | NOT_APPLICABLE |

Each row: 256 games / 128 paired seed blocks. Full human-readable both-player metrics, seat breakdown, all seven actions, cards 0..5VP, color discounts, nobles/reserves, duration and clocks: [greedy detailed Markdown](prism/m63-prism-beta-timed-building-evaluation.reading.md). No JSON-only replacement of match tables. Original sampling data is independently readable in `.sampling.html` / `.sampling.reading.md`; source hashes/formulas/raw research verdicts are in `.audit.html` / `.audit.md`.

### Actual style over the five shared greedy opponents

| Model's own metric | Prism Balance v0.1.0 | M63 c4 unpublished candidate | Change |
| --- | --- | --- | --- |
| VP/Main (total VP / total Main) | 0.5488 | **0.5516 ↑** | +0.0028 |
| Noble coverage | **37.34%** | 34.84% ↓ | -2.50pp |
| Nobles/game | **0.4398** | 0.4055 ↓ | -0.0344 |
| 0–1 VP purchase share | **67.36%** | 66.61% ↓ | -0.75pp |

Competitive interpretation: direct-parent point estimate positive, common opponents mixed and mean almost unchanged (+0.15625pp). Keep candidate value without calling old style goals a global failure; do not claim a universally stronger greedy successor. Efficiency is slightly higher but noble/small-card preference does not show a stronger building route. Retain provisional Balance identity; no release/default/registration performed.

37 Python checks, 77 human DOM groups and 66 audit DOM groups pass; JS syntax and git diff --check exit0. Original result SHA `a3c5c4f2c48b2b7dc36fed34326236ba5bcab687718ede6fe7bac99902b1e989`, complete MD SHA `911d4ef90395be7a373ea23f79d921d03ebb5909ffde76c222ebd0bf70c6c341`, frozen HTML SHA `2af29a90b32adf7d3ee07784a2c97cd334f1134fa421beaa7be9cfa50f9faaf5` unchanged; 106 original tables retained. Real browser screenshot/visual layout NOT_VERIFIED because file URLs are rejected; no workaround used. No commit or push.

Next: owner reviews greedy tradeoffs and actual profile before deciding release or further PPO. Existing DSW worker saturation calibration remains a separate unexecuted task. No extra sampling-mode superiority study or new training started.



## Owner R4 screenshot correction / 2026-10-05

User-provided browser screenshot establishes a real presentation defect: inline-block highlight badges contain block-level direction labels, splitting the pure-win row and making one side taller. Missing references render “未测 个百分点”. Prior offline numeric checks passed but did not catch these visual-flow defects.

Implemented: highlighted values and their single up/down marker are inline; repeated “更高/更低” sublabels are removed and direction is available in a title/legend. Each version cell has the same five lines: half-draw score, pure win, W/D/L, score interval and games/seed blocks. Fixed column proportions and a minimum scrollable table width preserve numeric alignment on narrower panels. Missing difference is an em dash without a unit. The change propagates to all actor/style tables through the shared comparison helper.

Validation: `node scripts/tests/prism_human_dom.test.cjs` exit0, 77 groups, including new computed-style checks that badge and marker remain inline, identical five-line cells, correct values and no units for missing differences. `node --check scripts/templates/prism-human.js` exit0; M61/M62/M63 regenerated exit0; `git diff --check` exit0. Actual post-change screenshot/geometry is NOT_VERIFIED; jsdom does not perform layout. The owner screenshot is the observed before state, not evidence of the final pixels. No browser-tool workaround used.

No games, training, mode/seed/weight/result changes, registration, commit or push. Original 106-table M63 source Markdown and frozen evidence HTML hashes remain unchanged; new per-page receipts bind the regenerated output. Further report feedback belongs to this same living round.

## Owner R5 / Alpha-route checkpoint correction / 2026-10-05

Status: IMPLEMENTED / VERIFIED_REPORT_AND_READ_ONLY_DIAGNOSTIC. Baseline remains `9899749188f35c838c85c5b3530049bd5dcbd105`, branch `m61-alpha-balance-ab`; no commit/push or release.

### Problem and corrected decision

Owner: “这一版更适合当alpha路线的新checkpoint”. Earlier provisional Balance classification relied too heavily on missing Beta building preference. That implication was insufficient. Review actual matched greedy behavior and rush timing instead. **Current identity: M63 c4 · Alpha路线候选检查点（未发布）**. The frozen artifact is still the original Beta-arm final c4 from **Prism Balance v0.1.0**; it is not trained onward from **Prism Alpha v0.1.4**. Earlier Balance interpretations above are superseded route history, not modified experimental outcomes.

### Matched behavior: own metrics, both-greedy

Five identical opponents/seeds; 1280 games per named model. All values below belong to the named model itself, pooled across shared opponents. Higher buying counts indicate magnitude, not universal quality. Differences are descriptive and were not made new acceptance gates.

| Model's own metric | Unit | Prism Balance v0.1.0 parent | M63 c4 Alpha-route candidate | Candidate minus parent |
| --- | --- | --- | --- | --- |
| 0VP purchased cards | cards/game | **5.861719 ↑** | 5.665625 | -0.196094 |
| 4VP purchased cards | cards/game | 0.813281 | **0.840625 ↑** | +0.027344 |
| 3–5VP purchased cards | cards/game | 2.013281 | **2.028906 ↑** | +0.015625 |
| 3–5VP printed score (no noble VP) | VP/game | 7.601563 | **7.667969 ↑** | +0.066406 |
| Scoring efficiency | VP/own Main | 0.548808 | **0.551591 ↑** | +0.002783 |
| Noble coverage | % games with a noble | **37.34375% ↑** | 34.84375% | -2.50000pp |
| First 4–5VP purchase (conditional mean) | own Main | 20.204975 | **20.013645 ↓** | -0.191330 |
| Bought a 4–5VP card (timing coverage) | games / total | 1005/1280 (78.515625%) | **1026/1280 (80.15625%) ↑** | +1.640625pp |
| Reached 8VP by own Main20 | % games | 32.734375% | **33.828125% ↑** | +1.093750pp |

First-purchase timing conditions on games buying that card class; coverage is shown separately. The two conditional cohorts differ, so a lower mean alone is not proof that every game plays faster. Noble decisions are attached to the previous Main; early endings carry terminal prestige. Main12 big-card printed score actually falls from 0.433594 to 0.389063 VP, and Main16 from 1.287500 to 1.282031 VP. The overall movement is slight, not a large or uniform rush gain.

### Competitive evidence and limits

Both greedy, 256 games / 128 two-seat seed blocks per opponent; score = wins plus half draws / games. These are fixed independent development measurements, not a retrospective replacement of old research gates.

| Opponent | Candidate W/D/L | Candidate pure win | Candidate half-draw score | Parent score vs same opponent | Candidate minus parent |
| --- | --- | --- | --- | --- | --- |
| Heuristic v0.3.1 | 211/0/45 | 82.42% | **82.42% ↑** | 77.73% | +4.69pp |
| Prism v0.1.0 | 212/1/43 | 82.81% | **83.01% ↑** | 81.84% | +1.17pp |
| Prism v0.1.1 | 158/2/96 | 61.72% | 62.11% | **62.30% ↑** | -0.20pp |
| Prism Alpha v0.1.4 | 132/2/122 | 51.56% | 51.95% | **53.71% ↑** | -1.76pp |
| Prism Beta v0.1.0 | 122/5/129 | 47.66% | 48.63% | **51.76% ↑** | -3.13pp |
| Direct parent: Prism Balance v0.1.0 | 137/2/117 | 53.52% | 53.91% | NOT_APPLICABLE | NOT_APPLICABLE |

The five shared-opponent score mean moves only +0.15625pp relative to parent. Direct Alpha score 51.953125% does not establish a stronger successor. Candidate versus Alpha 8VP-by-20Main is 28.90625% versus 29.6875%, while 4–5VP purchase coverage is 80.859375% versus 72.65625%; actual style has tradeoffs. Original sampling 55.0781% direct-parent evidence is retained separately.

Full per-opponent paired intervals, physical seats, both-player economy/cards/nobles/reserves, seven actions, durations and new trajectory tables: [human greedy data tables](prism/m63-prism-beta-timed-building-evaluation.reading.md). [Human HTML](prism/m63-prism-beta-timed-building-evaluation.html) now labels Alpha-route candidate and highlights both sides. [Audit](prism/m63-prism-beta-timed-building-evaluation.audit.md) contains complete original and supplementary evidence. No original dataset/mode/seed/weight was changed.

### Read-only extraction and implementation evidence

Read-only extraction revalidated all 2816 saved greedy replays and source-ledger artifacts on DSW using the already-pinned `prism_bigcard_metrics` binary. New source tree: `/mnt/workspace/splendor-m63-greedy-report-r3/alpha-route-diagnostic-r5`; local receipt: `local-artifacts/prism/m63-dsw-r2/r5-trajectory-extraction-receipt.json`. Result: `local-artifacts/prism/m63-dsw-r2/r5-trajectory-result.json`, SHA256 `b09776f2f1a04496c1f72ac381f3034af56e7d4d26658a78fa9d090d1bdaf099`. No new games or training.

Alias/lineage/current decision and old route history: `benchmarks/m63-practical-candidate.review.json`; projection: `benchmarks/reports/m63-reading.json`; modules: `scripts/prism_human_report.py`, `scripts/prism_round_report.py`, `scripts/templates/prism-human.js`. Human rows contain direct behavior and formulas; audit carries hashes and original gates. The source result/106-table Markdown/frozen evidence HTML stay byte-identical; new reading receipt binds the rendered outputs.

Validation actually run (exit0): `C:\Python312\python.exe -B -m unittest scripts.tests.test_prism_round_report -q` (6 tests); `node scripts/tests/prism_human_dom.test.cjs` (77 groups, trajectory/coverage/pooling/title assertions); `node scripts/tests/prism_reading_dom.test.cjs` (66 groups, original research gates and prior route retained); `node --check scripts/templates/prism-human.js`; render M61/M62/M63 with `scripts/prism_round_report.py --spec benchmarks/reports/mNN-reading.json` (three exit0). Original generic arena tests were not rerun for this report-only change. Actual browser layout remains NOT_VERIFIED.

### Next authorized gate（R5历史阶段，后由M65发布更新）

Retain this fixed checkpoint on the Alpha research route. No new training launched, no new official version registered, and Prism Alpha v0.1.4 remains unchanged. For a subsequent campaign, define finite PPO/selection scope and fixed representative greedy evaluation before launch; compare against this checkpoint, its Balance parent and current Alpha, preserving opponent-specific losses. DSW saturation calibration remains a separate pending task.

## 2026-10-05 M65发布更正（当前身份）

用户明确指定发布“M62 的 Beta 候选＋M63 的 Alpha 路线候选”。M63原Beta目标最终c4现登记为 **Prism Alpha v0.1.5**，精确权重仍为`3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12`。训练父代仍是Prism Balance v0.1.0，并非Prism Alpha v0.1.4续训；本次版本登记没有再训练。R3的2816局双方greedy数据完整保留：对父半平得分53.90625%、对Prism Alpha v0.1.4为51.953125%，共同对手有升有降，不能宣称全面增强。M65新种子直接对Prism Beta v0.1.0为 **143胜、1平、112负 / 256局**，半平得分 **56.0546875%**；这是另一批实战，不能与R3汇总为同一配对对照。

当前[人类HTML](prism/m63-prism-beta-timed-building-evaluation.html) / [完整双方Markdown表](prism/prism-alpha-v0.1.5-evaluation-summary.md)与`benchmarks/m65-prism-alpha-v0.1.5.model.json`绑定已发布身份；旧原Beta实验名、十门和先前Balance/未发布Alpha归类保留为历史。新直接对局的双方经济、动作、座位、区间见[M65详细数据](prism/m65-prism-version-release-comparison.reading.md)。DSW校准已经完成，后续采用4路/4核；2560局发布支持活动墙钟实测350.69局/分钟，1000局约2.85分钟。有限队列已完成，没有新PPO或默认/池/Studio替换、Git发布。进一步Alpha续训建议及发布验证见[M65](m65-prism-version-release.md)。
