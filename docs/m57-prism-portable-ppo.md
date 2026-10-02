# M57 Prism PPO 便携执行、跨机控制与校准

Status: **VERIFIED / PASS — 便携工程轮结束；竞技与风格晋级 NOT_RUN**
Baseline: `main@bcdaca7cb33c53cc43d5dcc9e92c07be3c1aaa57`，含既有并行工作区改动。
Owner/date: 用户“补兼容 跨机启动/终止 跨机恢复 之后进行校准”，2026-10-03（北京时间）。

## Problem and evidence

M56已固定Prism Alpha v0.1.1；其正式[结果](../benchmarks/m56-prism-alpha-v0.1.1.result.json)与[完整对战表](prism/prism-alpha-v0.1.1-evaluation-summary.md)保持。原真局监督器只支持Windows Job Objects，检查点身份又绑定OS/架构/库版本与原生二进制路径，直接拷贝到Linux不能恢复。cloud1本次SSH确认ARM64、2逻辑CPU、约12GB内存、128GiB可用磁盘及可用systemd用户服务；cloud2约1GB内存不作为本轮训练端。

## Initial design

新增独立版本的便携执行包，保留原M54～M56冻结源码与模型。复用经来源记录的同步PPO引擎快照；模型、奖励、信息边界和动作采样语义不改。Windows沿用Job Object；Linux采用专属systemd用户单元/cgroup资源控制。控制器通过本机或SSH执行同一套启动、状态、边界停止、强制终止与迁移命令。

完整检查点仅在提交边界跨机导入。迁移保留策略、两个value分支、AdamW、RNG、更新/任务/种子消费计数与剩余预算，并记录新的本机运行身份。接续是数值状态保持，不承诺不同CPU架构逐位一致。原身份核验继续有效，不通过删校验来“兼容”。

## Scope and non-goals

- 本机Windows与cloud1 Linux ARM：环境准备、原生构建、启动/停止/恢复、完整检查点往返及固定有限PPO校准。
- 每主机32局、2轮的同预算校准；12局/3轮往返接续；每主机8局的终止后恢复工程检查。最多92个完成训练局、两个预先指定的未发布尝试中断，各中断最多补一次；不追加候选筛选或正式晋级比赛。
- 未发布工程检查点不登记新模型版本；竞技晋级验收`NOT_RUN`。校准局仅用于执行吞吐和状态一致性，详细双方数据完成后追加，不能认定棋力提升。
- 不改共享池、生产默认、Studio注册、既有模型/负结果，不启动Muse/Railway付费部署或无限训练。

## Contracts and invariants

1. 新包/独立工作目录，不覆盖原76项M56冻结文件。Rust构建从本次工作区的校验快照进行，所有本地与远端二进制身份分别固定。
2. CPU、2个Torch线程；版本/架构如有变化必须明示。动作softmax T=1，对手固定greedy；玩家输入不包含seed、控制票据或来源hash。
3. 只有控制器登记的当前owner可启动该训练线。交接先停止并撤销原主机写入权，再导入、确认新owner；重复票据、活动批次、损坏对象、错误目标或语义变更均拒绝。
4. 强制停止只操作由本轮创建并验证身份的进程/Job Object/systemd单元；未提交的尝试按原保守计数恢复，已完成/已消费批次不重放。停止不自动解除共享池pause。
5. 包完整校验后才加载可信Torch检查点；拒绝路径穿越、符号链接和不受限解包。旧checkpoint/RNG及全部提交祖先留作来源；保留已消耗CPU与原墙钟截止时间。
6. 校准预算、种子、采样/优化参数与停止条件在开赛前冻结到`benchmarks/m57-prism-portable-ppo.config.json`；测试失败保留，不换seed或扩大样本弥补结果。

## Implementation plan

1. 来源快照与独立包；Windows/Linux进程树和资源监督，降低重复目录扫描频率。
2. 专属环境/原生程序准备；控制CLI、身份校验、启动和两种停止。
3. 完整检查点迁移、所有权交接和恢复，工程测试验证模型/优化器/RNG/预算。
4. 固定校准与完整可读数据，记录采样、接纳、优化、检查点、整批墙钟和资源范围。

## Iteration log

- 2026-10-03：读取AGENTS、handoff、M54/M56与实现合同；核对main/HEAD/dirty范围。cloud1只读资源与systemd用户受限进程探测exit 0，独立probe只输出123；未动已有服务。
- 原生源码快照305文件，Windows与ARM release构建均exit 0；ARM原生构建248.944秒。两端独立Python 3.12.6、NumPy 2.2.4、Torch数值版本2.6.0（本机CUDA发行包CPU模式，cloud1 CPU包）。各68条Rust/Python边界推理核验PASS；绝对/相对容差共同判定，各最大绝对误差0.0001249854与0.0001091748。
- 开赛前execution-v2将数值实现身份与执行封装身份分开。原始冻结配置保留，附加执行来源记录；训练参数、种子和预算未改。
- 两端各一次预先指定的合成父子进程中断检查PASS，强制停止后原PID不存活。各恢复完成8局、4次AdamW更新、36项非空优化器状态；attempts=9，物理决策保守计费464，retry=1，未重放已完成局。
- 首次迁移前发现独立launch-ledger也必须保留；execution-v3补充源/目标账本hash核验与物理决策/重试计数迁移。已完成16局保留，停止后升级执行封装，两端模型/优化器/RNG/进度hash均不变，数值源码身份未改，额外对局0。新增4项预算一致性拒绝测试，两端共19项测试均PASS。
- 工作期间HEAD由其他工作推进至904d6af（M58部署提交）；本轮Rust快照、冻结输入与新代码范围仍独立，不据此重建或修改校准合同。

- 校准后execution-v4修复旧PID复用：不属于原token/模块/campaign的进程记为非自有且不存活，status/start可继续，stop/kill不触碰它。两端真实非自有PID测试加入，完整21项测试各PASS（本机0.67秒、ARM0.96秒）；七个原campaign数值hash均不变，额外对局0。92局校准与往返仍明确属于v3实测。
- Git core.autocrlf=true；便携包增加局部.gitattributes保留源码原始bytes，避免Windows/Linux checkout换行转换破坏checkpoint来源身份。

- 收口时Git普通diff-check把保留的CRLF误报为尾空白；便携包限定cr-at-eol并继续检查真实尾空格/尾空行，来源bytes不变。机器结果输出固定LF，匹配benchmarks的Git eol=lf，避免入库后raw SHA改变；再次对照index bytes后收口。

## Final implementation

- 新包training/prism_portable：来源固定的PPO数值引擎、Windows Job Object/Linux systemd cgroup监督、原生绑定与68条推理核验、显式所有权和完整检查点交接。数值实现身份独立固定，运行封装与原生二进制各自记录；不修改原training/prism。
- scripts/prism_portable_control.py提供create/start/status/stop(boundary或force)/transfer/prepare/import/kill；SSH只转发有界JSON参数数组。先停止并撤销源写入权，目标验证完整对象后取得新owner；重复启动/导入与释放后的源启动被拒绝。
- 模型、训练专用style分支、AdamW、Python/NumPy/Torch RNG及已消费批次/全部任务/更新次数/原始开始时间都保留；同样保留独立launch-ledger的物理决策、重试和完成尝试。仅清除已消费批次的本机行为缓存，新主机按同合同构建下一批。
- 原CPU消耗/墙钟截止时间跨机保留；目录扫描默认5秒而非每0.1秒全量扫描。每局原保守重试和上限不放宽。迁移包保留源祖先、objects与回放，校验hash/路径后才加载可信Torch对象。
- [操作说明](prism/portable-ppo-operations.md)给出本机/SSH启动、终止与迁移命令；[校准和工程对战完整表](prism/m57-portable-ppo-calibration.md)含全部22组双方/双座位数据、模型身份、配对区间、经济/动作/时钟与来源。

## Validation and evidence

采样前冻结[配置](../benchmarks/m57-prism-portable-ppo.config.json)，SHA **8463b231464cf2b46e71c37e4b93542355c1c6faaa9df18e74b544de617ce641**。原始code_identity保留；[execution-v2](../benchmarks/m57-prism-portable-ppo.execution-v2.json)在开赛前划分数值/执行身份，[execution-v3](../benchmarks/m57-prism-portable-ppo.execution-v3.json)在首轮16个同机恢复局后、首次迁移/校准前补账本保留。训练参数、种子、预算与gate均未改；已完成16局与旧封装来源保留。[execution-v4](../benchmarks/m57-prism-portable-ppo.execution-v4.json)在全部92局后修复PID复用判断，保留全部结果和v3测量身份；不重跑或替换校准。

最终数值源码SHA **a6e502b5d54358b8a8c4122ddabfb11e949dc976a957335b15ad91c2c3f62c24**；当前控制包SHA **7159af9bc1190859195cbb282e0be32ada3bf758dd111f86b5aa9473223d2a51**；校准与往返实测包SHA **41f5942feca75c11c0e7e5248b06c2849e09818382b24c390d9709967f31d87e**；Rust源码快照305文件，逐文件SHA在local-artifacts/prism/portable-m57/rust-source.json以及结果rust_source_snapshot中。环境种子：校准9570000..9570015；往返9571000..9571005；本机终止恢复9572000..9572003；cloud1终止恢复9573000..9573003。action seed57010001，配对CI bootstrap seed57049999/20000次，仅描述性；种子与S0注册及M54–M56合同无重叠。

| 冻结工程gate / 目的 | 原阈值 | 实测结果 | 不确定性 / 失败含义 |
| --- | --- | --- | --- |
| native_parity：原生与Python输入/输出兼容 | 各68输入；atol/rtol=1e-4的math.isclose | 两端68/68 PASS；最大绝对误差本机0.0001249854、ARM0.0001091748；相对项共同判定 | 固定输入精确核验，不是棋力区间；失败禁止接纳该运行端 |
| process_control：关停自有后代、原机接续 | 两端停止并恢复，已消费局不重放 | 两端STOPPED_OPERATOR、原fixture PID消失；各8完成局/9 attempts/1 retry，4更新/36 AdamW slots | 声明的合成中断窗口；不代表所有断电窗口；失败不进入校准 |
| numeric_restore：完整数值/预算接续 | model/optimizer/RNG hash及预算计数一致 | Windows→ARM→Windows两次5类hash一致（含进度/launch-ledger）；12唯一job、6更新、3消费批次；CPU和原deadline保留 | hash精确相等；后续异构更新不保证逐位一致；失败保留源与失败导入 |
| ownership：单写者、旧源与重复票据隔离 | RELEASED源启动和重复target拒绝 | 两项拒绝PASS；重复启动拒绝PASS；非阻塞writer测试PASS | 合作式控制及本机锁；失败意味着不能安全交接 |
| calibration：同有限工作量测吞吐 | 每主机同32局/2轮/参数；**没有速度门槛** | 两端32局、856学习决策、8更新；共64校准局，无retry | 只有一次有界测量，无速度CI；速度低不等于模型失败 |
| 总预算/原来源约束 | ≤92完成局、≤2声明中断；76项原输入不改 | 92完成训练局、2个赛前合成进程中断、30新工程更新；原76/76 hash PASS | 中断不是两个完整对局；没有追加晋级比赛 |

精确执行与退出状态：

- Windows独立源码目录执行cargo build --locked --release -p splendor-cli --bin splendor --example s4_batch_metrics --target-dir ../build，exit 0。ARM通过专属systemd用户单元执行同release目标、-j 2，exit 0，248.944秒；完整argv与回执在结果/本地cloud1-evidence/build-receipt.json。
- C:/Python312/python.exe -B -m pytest -q training/prism_portable/tests：exit 0，19 PASS/0.65秒，pytest9.0.2。cloud1私有Python同命令：exit 0，19 PASS/0.96秒，pytest8.3.5。测试覆盖后代终止、存储上限、单写锁、路径/损坏归档/控制ID拒绝，以及物理预算丢失拒绝。
- v4修复后两端同一完整测试命令exit 0，各21 PASS（Windows0.67秒、ARM0.96秒），真实非自有PID被判为非自有且kill后仍存活；执行升级前后七个campaign模型/优化器/RNG/进度hash相同，新局0。
- 真实控制、两次导入、释放源/重复票据拒绝与最终状态检查：原始JSON回执进入结果engineering_evidence/transfers；原Windows与ARM运行身份、完整模型/AdamW/RNG/预算hash保留。
- C:/Python312/python.exe -B scripts/prism_portable_report.py --artifact-root local-artifacts/prism/portable-m57 --output benchmarks/m57-prism-portable-ppo.result.json --document docs/prism/m57-portable-ppo-calibration.md：exit 0；92局逐项源hash核验、44个分座manifest独立Rust回放解析、22组模型朝向与购卡/VP/动作/预留守恒全部PASS。
- 原M56冻结来源76项再次核对PASS，单独回执original-frozen-final.json；无活跃M57 worker。逐推理/决策耗时 **NOT_MEASURED**。
- 主机/环境与完整数据：[结果](../benchmarks/m57-prism-portable-ppo.result.json) SHA **d13d2ceaaac9dc2fc5134758575fadfdecc437faf8b22f543bda9b0891f0606f**；[可读对战表](prism/m57-portable-ppo-calibration.md)。所有本地生成数据、压缩包和handoff保持忽略规则。

## Result and decision

**便携工程合同PASS，校准完成后停止。** 实际92局按声明完成：本机/cloud1各32校准局、往返12局、两端各8终止恢复局。模型发布、竞技与风格晋级均 **NOT_RUN**，Prism Alpha v0.1.1仍固定原权重，不登记本轮工程检查点版本。

同预算32局/2轮整批监督墙钟 **本机150.437秒 → cloud1 71.862秒（↓78.575秒，当前负载快2.093倍）**。轮内流水线分别142.499/63.640秒；对局进程监督21.295/17.074秒；接纳/审计33.547/6.221秒；优化阶段40.037/22.461秒。launch含ingest，不叠加这些重叠时钟。两端32个匹配job的胜负、双方VP、ply与动作类型计数相同；整批提速范围是同步CPU流水线，而非逐推理速度。

本机开始前CPU26.8%、可用约2.24GiB；cloud1 CPU约0%、可用约10.90GiB。当前使用习惯下cloud1可以承担夜间独占PPO，白天本机接续也已验证；这次速度比不代表空闲本机/硬件峰值比较，不直接外推大规模轮次。环境下载与ARM编译为首次准备成本，不包含在上述训练时钟中。

## Known limitations

- 两端32个policy/value张量初始化相同，optimizer/RNG初态相同；两个训练专用style_head初始张量hash不同（观察到的前8元素差约1e-9..1e-8，未据此概括全张量误差）。本次是相同推理权重、配置与种子的匹配调度，完整学习器并非逐位相同；原初态与差异说明保留。两次跨机导入则复制并核验完整状态，包含该分支。
- 每组仅1或4种子块，训练采样数据不可替代固定greedy/T=1发布评测。bootstrap区间可能退化；对局数量/无错/训练更新不证明棋力增强。
- 本轮从固定推理权重建立新工程优化器，验证新便携检查点。原M54～M56严格身份的历史检查点未自动转换；历史训练预算不重置。
- 当前支持Windows/Linux CPU、匹配Python/NumPy/Torch数值版本；Linux依赖systemd用户管理器/cgroup权限。Muse对话agent的持久进程能力未验证，Railway/cloud2未做PPO对照。
- 强制终止后跨机需先在原机恢复到提交边界；转移失败保留RELEASED源和CLAIMED/IMPORTING目标，不自动回滚。启动确认前controller崩溃可能残留STARTING，需要检查自有单元/日志；本轮不宣称覆盖所有系统重启/断电窗口。
- 2小时原墙钟预算跨休息/转移继续消耗；整夜轮需预先冻结合适期限。原始归档/祖先额外占用主机目录空间；2GiB/4GiB是所声明campaign监督边界。不同OS内存统计口径不同。
- 没有独立外部代码review或云CI；Windows与ARM均实际运行，作为本轮执行证据。

## Next authorized gate

用户授权的兼容、跨机控制/恢复和校准已完成。下一步沿此前大牌冲分方向，使用本次便携执行层设计新的有限PPO合同，优先明确更强对手的训练配比、全程预算和独立验收种子；保持当前风格奖励为主要对照。新模型续训属于后续轮，本轮不以校准代替晋级、不自动追加训练。[操作说明](prism/portable-ppo-operations.md)给出交接方式。
