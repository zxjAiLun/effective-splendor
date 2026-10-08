# M70 从 M67 B-c20 开始的有限胜负 PPO 迭代

2026-10-08；task_kind=experiment（单训练seed有限迭代）。
授权：用户“修复让另一个agent在做 先继续在dsw上跑下一轮迭代？不然dsw上实例运行浪费了”。
authorized_end：工程/零局预检、一次有限训练、最终c4审计、预定独立评测、画像/完整报告和ALL交付。禁止自动重试/加训/补赛/发布/冠军替换/应用部署/Git提交。

## 问题、输入与边界

问题：M67 B-c20在完整网格取得增强后，再做一次有界outcome-only PPO是否改善其固定对手表现？
起点为未发布M67种子B最终c20，SHA `e2914425cac49f0f2272c44379e46a43525d97ced2eaac206e8600ebf73e79c4`。本轮不是模型正式发布或M67全状态resume。模型从精确权重fresh AdamW/RNG初始化，保留原Prism架构、编码和PPO数值；不接入另一agent正在做的停滞修复。

baseline HEAD `9899749188f35c838c85c5b3530049bd5dcbd105`。工作树有历史未提交文件，完整执行来源以独立源目录、source archive和execution manifest为准，不以HEAD冒充。原M67产物与失败全部保留。

## 有限预算与冻结设计

- DSW实时核验无活动Prism执行，原R4监督器正常exit0；磁盘空闲约23GiB。因此不重复双5120局规模，选用M66已验证规模的单seed有限迭代。
- 8工程局、68输入parity、工程全回放/32张量/优化器审计独立；不进研究统计。研究训练1024局、4×256、每环境seed双座，256决策/局上限，2048更新/更新尝试上限，零基础设施重试。
- 只选最终c4，不看独立结果挑中间checkpoint；不因不显著增加样本。单训练seed不证明算法总体稳健。
- 训练seed10001000–10001511；工程10000000–10000003；共同池10010000–10010255；直接父代10020000–10020511；全部与既有登记无交集。
- 共同池：Heuristic v0.3.1、General v0.1.1、Balance v0.1.0、Alpha v0.1.4、Beta v0.1.0、当前发布Alpha v0.1.5；六对手等权。父B与候选各3072局，直接父B1024局，共7168局双方greedy。
- 用当前发布Alpha v0.1.5替代历史Initial作为第六共同对手，保持预算不扩大。Initial仍用于边界parity。M67 A缺项，不作为本轮强度参照；当前Balance及非Prism锚点均覆盖。
- 主要比较相对直接父B；共同池同seed双座配对，再按六对手等权合并。半平得分为主，纯胜率另报；bootstrap 20000、RNG70029999，两个同时检验family .05，单侧下界分位.025；普通95%区间独立报告。
- 竞争力保留：共同池下界≥−5pp、直接父代下界≥45%；增强：分别>0pp、>50%。沿用前轮明确政策，逐对手代价和实际差值另报，不作默认冠军评审。
- 样本量为容量内有限估计，不保证分辨微小增益；未确认就停止。和M67训练量不同，不能归因为某一训练因素。
- 画像descriptive：大牌印刷分/购入时点覆盖、固定Main达分、0–1VP购牌、贵族覆盖、VP/本人Main及逐对手/座位。与匹配父B分报；缺少匹配Balance画像时不确认Beta/Balance路线，NOT_MEASURED不填0。

## 资源与控制

独立目录`/mnt/workspace/splendor-m70-b-continuation`；4 CPU，Torch 2.6.0+cpu、NumPy2.2.4、训练2线程/评测4workers。总墙钟6h从实际start开始；训练3h/40000 CPU秒，评测每arena2h/20000 CPU秒；进程树RSS8GiB，监督器为采样软限制，非独占cgroup。

总新目录容量16GiB；工程2GiB、训练8GiB、每arena2GiB，启动前至少20GiB空闲，保留4GiB额外空间。每局和外层监督器都检查预算；达到上限保留现场停止，不删历史腾空间或延长截止。旧大规模目录扫描不由本轮扩量；规模控制在小试范围，不由8工程局外推全程精确ETA。

所有错误仍按原稳定路径停止，零自动重试；不在运行中热替换修复。非终局不判平、不换seed，报告缺项则完整竞技门不能PASS。外层每阶段需要上一阶段exit0与审计PASS才推进；工程审计失败不进入研究训练。

## 实现与验证

新`prism_m70_{prepare,run,audit,report}.py`从原M67有限控制器/审计及M66单候选报告独立派生；源码来源SHA记录在`local-artifacts/prism/m70-b-continuation/derivation.json`。无新模型算法，复用已测无损存储与DSW进程监督器。

当前R0/R1完成，R2/R3待本地及Linux测试、真实容量/身份与parity结果。候选/竞技/画像/报告尚未运行，不能预先判PASS。R8使用原阅读层和结果SHA绑定spec；强制数值/来源/链接/DOM检查，既有模板无需新布局，像素NOT_VERIFIED须披露；最终本地取回与R9还需核验。

## 交付与下一动作

后台流水线将按工程→工程审计→训练→c4审计→父共同池→候选共同池→直接父→统计/报告顺序有界执行。本地关机会影响观测/取回，不影响已启动的DSW后台；不宣称有自动本地取回。实际启动及最后观测将另附精确PID/create_time/execution SHA。

下一已授权动作：通过预检后启动本轮；任何预算耗尽/失败先报告，不自动开下一轮。ALL任务`02855e83-53a9-43f7-a825-f59e54ae2a13`在完整证据交付前保持progress/review。

## 2026-10-08 实际启动与阶段回执

本节更新上方启动前状态，不改变已冻结合同或DSW源快照。本地8项控制器测试、Linux同8项测试PASS；零局预检68项边界parity PASS（atol与rtol均1e-4，最大绝对误差0.00013329345702572937；判据为组合容差）。R0/R1/R2/R3已完成，R4正在执行，R5–R9尚未完成。

DSW于2026-10-08 04:37:42 +08启动独立后台流水线，PID `875185`、create_time `1791405462.04`；实际命令为新目录的`prism_m70_run.py pipeline`。绝对截止2026-10-08 10:37:42 +08。执行SHA `7903c72fe549fa07c87d3dc777969b84ee19ccd2b3e66f06f67a2cbc0520e636`；源码ZIP SHA `a1d523b2415fc1eabcd1dea234784dde25f6bb00c0d91e855c64140743199258`，已取回本地并复核相同。

2026-10-08 04:38:50 +08直接SSH采样确认同PID/create_time运行，phase=`TRAIN_a`。工程8/8局已完成，8局Rust规则回放、32导出张量/优化器/初始化审计与工程导出68项parity均PASS；工程结果不进入研究。研究第一周期采集47/1024局，尚无研究更新提交（global_step=0）；本次仅确认进入训练，不声明完成或增强。

本地证据：`local-artifacts/prism/m70-b-continuation/{deployment,execution,host,linux-tests,launch-verification,round-budget,observation}.json`及`source-snapshot.zip`。原样来源快照保留启动前文档；启动后本地记录是附加观测，不回写冻结源码。后台自动推进训练/审计/评测/远端报告；本地取回、报告验证和ALL最终交付仍待执行。无持续ALL观察器，本次同步仅采用上述真实采样时间。

下一已授权动作：只读观察本轮、取回及核验最终证据；后台按冻结合同有界推进。失败/预算耗尽停机保留，不自动重试。模型仍未发布，任务保持progress。`git diff --check`通过；handoff忽略规则有效，暂存区为空。


## 2026-10-08T14:30:16+08:00 结果取回核验

用户请求“看看这轮结果吧”；本次task_kind=status，终点为只读取回与结果核验，不启动/恢复/重试研究。两次DSW SSH均在转发连接阶段报`Connection refused / stdio forwarding failed`，未执行远端采样命令。execution_state=UNKNOWN、observation_state=SSH_UNREACHABLE、delivery_state=RESULT_NOT_RETRIEVED；不可达不证明停止、失败或完成。

本地仅有启动/早期观测、冻结配置与来源ZIP，无本轮最终result JSON、c4审计或评测完成回执，无法给出竞技结论。此前04:38:50采集47/1024及另一agent04:42:34采集256/1024均为历史样本，不更新为当前进度。ALL读取返回fetch failed，本次同步待办；未启动ALL服务或实验进程，0新局。证据`local-artifacts/prism/m70-b-continuation/result-review/status.json`。下一允许动作是连接恢复后只读取回原execution证据，保持原截止与零重试政策。


## 2026-10-08 连接恢复后的完整结果核验

本次用户“现在可以获取结果了”授权只读取回与核验；延续本轮交付范围，0新局、0运行控制。直接SSH读到绑定原execution SHA的COMPLETED回执，实际于2026-10-08 05:42:01 +08完成，总流水线3857.85秒（64.30分钟），原PID875185已不存在。此前14:30连接失败是观测故障，不是执行失败；旧记录保留。

### 产物、竞技与画像结论

产物：研究训练1024/1024、最终c4、218次已提交更新/更新尝试；32张量/优化器/初始化审计及68项parity通过，DSW原审计记录1024训练回放规则核验通过。本地取回并验证最终权重SHA `f4a9a628a9a0a376a84b2bc0f3b002e652bde42d4e1e4b3170a1830e3b14238a`。所有阶段完成回执exit0/无停止原因；评测reference3072、candidate3072、direct1024，共7168/7168，无缺项、0自动重试。

竞技：两个保留门均PASS；共同池增强PASS，直接父代增强未确认，overall_enhancement=false。不能写成全部增强或已胜过父代。

| 指标 | 点估计 | 95%配对区间 | 同时单侧下界 | 增强门 |
| --- | --- | --- | --- | --- |
| 共同池相对M67 B-c20 | +2.8971 pp | [+0.7650,+5.0944] pp | +0.7650 pp | PASS |
| 直接对M67 B-c20 | 52.4414% | [49.7559%,55.1270%] | 49.7559% | NOT_CONFIRMED |

直接对局530胜/14平/480负，主指标是半平得分，纯胜率51.76%。以下共同对手也均为半平得分，不称纯胜率；每模型/每对手512局。

| 对手 | 父B | 候选c4 | 差值 |
| --- | --- | --- | --- |
| Heuristic v0.3.1 | 86.82% | 86.33% | -0.49 pp |
| General v0.1.1 | 69.24% | 71.09% | +1.86 pp |
| Balance v0.1.0 | 58.98% | 66.50% | +7.52 pp |
| Alpha v0.1.4 | 59.47% | 62.30% | +2.83 pp |
| Beta v0.1.0 | 56.45% | 60.84% | +4.39 pp |
| Alpha v0.1.5 | 57.62% | 58.89% | +1.27 pp |

画像：同cohort父B→候选，VP/本人Main 0.5519→0.5579，贵族覆盖41.11%→37.89%，0–1VP牌7.970→7.666张/局，3–5VP牌印刷分7.615→7.931VP/局。描述上更偏大牌得分，但不能从这些变化归因训练机制；没有同cohort匹配Balance画像，首次4–5VP购入时点/覆盖、固定Main轨迹及投资兑现NOT_MEASURED，正式风格证据INSUFFICIENT，保留Alpha血缘/研究分支而不登记新观察路线。单训练seed不能证明总体稳健。本轮无停滞缺项不证明停滞修复有效，因为修复未集成。

### 本地独立核验与交付

完整取回36580文件及manifest，52,684,898字节ZIP SHA `9d42d7358b1daba94dc2828f74f189f2a0cfe360298b0921638ff402c5666425`。首次传输90秒超时，按已下载字节偏移只续传剩余字节后整包SHA相同；没有研究重试。原结果SHA `9c46ebba921d372f55b59a4096e6779f9ee41d42269f898a8fa2420b7e05ee6b`，未重写统计或报告。

独立检查7168局记录身份/唯一seed双座/完整网格、全部保存回放与报告及provenance字节hash；重做20000次配对Bootstrap，两指标点估计/区间/下界/门完全一致。原报告receipt的spec/result/Markdown/HTML/审计层全部hash相符。离线DOM13组交互、双方胜平负/分母/显示半平得分、模式、footer链接与脚本错误检查PASS。未在本地重跑Rust全规则回放；该规则PASS来自绑定DSW原审计。既有页面像素NOT_VERIFIED，此项按冻结合同披露，未作为强制通过项。

正式结果：[JSON](../benchmarks/m70-prism-b-continuation.result.json)；[人类阅读](prism/m70-prism-b-continuation-comparison.html)、[完整双方Markdown](prism/m70-prism-b-continuation-comparison.reading.md)、[Agent审计](prism/m70-prism-b-continuation-comparison.audit.html)。原始证据与本地verification/DOM检查在`local-artifacts/prism/m70-b-continuation/result-review/`；报告索引已加入M70。

阶段：R4/R5/R6/R7/R8已完成适用工作，R6总体增强未确认、R7画像证据不足，均为有效结论而非执行失败。R9本地记录/产物核验完成；ALL读取仍fetch failed，注册/结果回报待同步，任务不可声称已在ALL完成，维持review待同步。已保存明确待同步载荷。没有版本发布/默认替换/部署/提交/推送。建议保留M67 B为主研究参照及M70 c4为候选，下一允许动作是既有产物评审和ALL同步；下一轮需要新有限合同，不自动加训补赛。

## 2026-10-08 用户指定固定研究版本（M72 release-r4）

M70最终c4已固定为Prism Balance v0.2.1；父权重不变，其M67 B-c20父代当前登记名为Prism Balance v0.2.0。 见[固定身份及完整SHA](prism/prism-v020-fixed-models.md) / [M72记录](m72-prism-style-atlas.md)。这是新增发布登记，原报告中的未发布状态属于当时历史；原权重/血缘/竞技门/画像证据不变，0新对局/训练，无默认替换或应用部署。
