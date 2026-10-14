# M75 · Balance v0.2.3 后继长程训练

2026-10-11 20:26+08 DSW2实例替换恢复r5已实际RUNNING：旧节点dsw-2246104…变为dsw-2246854…，原协调102954消失，原19:54 WAIT_FINAL-INPUT已存证；768开发早已全部完成/0截断，4096基线保留。新的wait-resume-r5 PID4335/create1791721579.66已核验实际存活/新鲜WAIT_FINAL-INPUT心跳，等待DSW c20后继续原256开发+5120候选，未重打已完成局。新节点347 pin/八核原runtime与12完整分片逐原字节/配置/网格验核PASS；本地及节点各4项针对性恢复回归PASS。原CPU385.750827秒计入，原r4来源/政策不变，r5独立SHA1ebe6f4c…c3236/policy e76e8894…d49e4。DSW原训练relay21760/worker21761及协调93803不控制不回退，当前5112/5120物理=5111正常+1保留截断，c20/1046更新，仍采集/stop_reason=null，盘25.89GiB。实例重建具体平台原因UNKNOWN；原脱离SSH进程不能跨实例替换自动复活，当前已从成功阶段守卫恢复，未声称实现平台级自启动。完整结果暂估22–23点/23点查看，截止02:50:30不变。证据wait-resume-r5/launch-closeout.json；scripts/prism_m75_wait_resume.py、benchmarks/m75-prism-continuation.wait-resume-r5.json。ALL fetch failed待同步，原实验IN_PROGRESS/最终棋力未评测，无下一轮/发布部署/提交推送。

2026-10-11 18:49+08 后续评测重新分配r4已实际RUNNING：用户明确要求评测交DSW2、保留DSW训练。DSW新协调93803/create1791715613.28，原训练relay21760/worker21761不变；旧r3协调48618仅暂停防重复后续派局。当前4668/5120物理=4667终局+1截断、c19/992更新，无stop_reason。DSW2协调102954/create1791715630.95，8实际评测worker，已读297完成开发局（逐分片原子/全局非原子快照）；先固定c5/10/15共768开发，c20在DSW审计冻结后自动接256开发和5120独立，既有4096父代基线复用。1024/9216固定网格、模式/seed/门/最终c20/总CPU/截止不变；开发前三点提前仅描述，不反馈训练。两节点独立有限私有魔搭传输/调度，不依赖本机；传输上传最多6次，研究0重试。7+7+7零局检查/347原pin/host/runtime/PID预检PASS；实际新对局证明接续开跑。预计训练20:15–20:45，完整评测/报告22:00–23:00，建议23:00查看；02:50:30为原停止上限。证据eval-handoff-r4/launch-closeout.json，scripts/prism_m75_eval_handoff.py、benchmarks/m75-prism-continuation.eval-handoff-r4.json。M75实验R4 IN_PROGRESS/最终棋力未评测；本次分配启动范围完成，ALL待同步，无下一轮/发布部署/提交推送。

2026-10-11 18:09+08 分工核验：DSW2于16:42完成4096物理独立尝试（4095终局+1有效截断），16:57打包，18:07实际无研究进程。r3只分父代基线给DSW2，未配置后续自动接续；DSW仍承担串行训练、审计、1024开发及5120候选评测，该静态分工导致第二节点提前空闲，不能称持续双机满载。DSW同worker21761/relay21760及协调48618仍RUNNING，4471/5120物理、c18/938更新，盘29.63GiB可用，stop_reason=null。上传原16:57 RateLimitError保留；仅恢复已完成证据传输，4次最多/300秒/原截止，首试成功，私有魔搭44,561,857字节SHA核对，18:09已到DSW inbox并再次核验原ZIP SHA2fbe5ad6…24968fd。未重打研究局、未更改训练/科学合同或实际任务分配；完整网格审计/候选结果仍未完成。证据dual-node-r3/allocation-status-20261011.json、current_status_remote-*.json、delivery_status_remote-dsw2.json、inbox_status_remote-dsw.json。ALL fetch failed待同步。

最新核验（2026-10-11 16:19 +08）：用户授权双节点r3实际RUNNING。DSW训练relay21760/worker21761保持，3909/5120物理尝试=3908终局+1截断、c16/828更新；新后续调度48618防重复，DSW2基线21392/8worker已完成983终局。原9216独立网格拆为DSW2父代4096+DSW候选5120；开发1024及finalc20不变。基线/必要证据经私有魔搭中转；最终汇合尚未执行。预计20:00–23:00完整结果，22:00查看。详见文末r3合同/启动回执及独立`dispatch-handoff-r1`入口；以下保留r2启动快照。

当前状态（2026-10-11 14:54:44 +08核验）：用户授权恢复r2实际RUNNING / R4 IN_PROGRESS；3416物理尝试=3415正常终局+1保留截断，finalc20与评测尚未执行。原r1在10月10日21:33停止的失败完整保留。启动基线分支 `m61-alpha-balance-ab`，HEAD `e0018fd58fb973253d16000d59bf1b1aae62046a`；启动工作树含其他未提交改动，实际执行以独立源码快照为准。

## 问题与证据

M74新增5120训练局后共同池提升4.51pp、直接父代半平56.79%，两个主要增强门通过；最新Alpha覆盖仍缺一局，实际风格时点/兑现不足。用户本次“继续迭代？”授权建立一个新的有限后继轮，重点是继续获得更强模型并观察随训练量的棋力变化。

task_kind=experiment；authorized_end=单条5120训练局/20周期、最终c20审计、1024阶段开发局、9216独立确认尝试和报告交付。下一轮、自动重试、发布版本、默认冠军/应用部署及Git提交推送不在本轮范围。

## 初始设计与合同

精确父代 **Prism Balance v0.2.3 / M74 final c20**，SHA256 `e16bfe0d30168d6ef7ceb067ca4357900f1c09e09d35f5759832dd3d6a9258ad`。fresh AdamW/RNG warm-start，保留父权重，优化器与随机状态新建，非full-state resume。单条实用后继轨迹，不据此推断架构绝对上限或算法总体可复现性。

正式可执行合同：[config](../benchmarks/m75-prism-continuation.config.json)，SHA `e78ac59ba81315b5c03e95c529f813c4596fb76972d1f1b448cd668946e3c32a`；[训练蓝图](../benchmarks/m75-prism-continuation-a.train.json)，文件SHA `85ca6c268b5eb35295f499ba366146a37e4649c1d61ce267038382dab522e11b`。训练run seed 75010001，环境13001000–13003559双座；20×256=5120局，父代/General/Alpha v0.2.0/Balance v0.2.1各25%。沿用M74 PPO：lr3e-5、2 passes、clip0.2、entropy0.01、KL0.02、GAE0.95，无额外风格奖励。规则/信息边界/数值核心保持原冻结实现。

阶段曲线固定c5/c10/c15/c20，各对父代128个双座环境seed（13040000–13040127），共1024局，双方greedy。在最终c20审计冻结后回测四个导出，描述趋势；不选择检查点、不反馈调参。曲线与独立集种子完全分开。缺失双座时不生成完整配对区间；截断不算平局。

最终候选固定c20。独立确认沿用M74六共同对手、两最新路线及直接父代网格，全部使用新的1301xxxx/1302xxxx/1303xxxx种子，共9216物理尝试。双方greedy、512ply上限、4并发、0重试。20k配对bootstrap/RNG75029999；两主要端点family、lower quantile0.025；共同增益点估计≥2pp且下界>0、直接父代点估计≥52%且下界>50%；保留容忍及逐最新对手代价按config。不追加样本到显著。描述风格，首张大牌/兑现缺项继续标未测，不自动改路线。

## 资源与停止边界

训练存储32GiB、全轮38GiB、整盘额外8GiB预留，启动要求空闲至少46GiB；训练18h/150000CPU秒，全轮26h/240000CPU秒，RSS8GiB，研究重试0。达到预算、截止、审计失败或基础设施异常停止并保留现场。当前M74匹配负载11h32训练、全管线12h27；本轮预计12–16h训练，加1–3h审计/开发/独立评测，实际时长随局长与累计账本变化。

历史存储维护：M67已结束数据ZIP 26203087576字节，SHA `65a85004230576ce889ea6f67541d472974d4d378dec8205adb9630f0e03a072`，完整复制并独立读回SHA相等后，从workspace归档目录移至 `/tmp/prism-history-preserved-20261010/splendor-m67-alpha-repeat.data-bundle-r2.zip`。训练盘空闲53119889408字节（49.47GiB）。新位置为独立磁盘临时保存，持久性NOT_VERIFIED，完整本地取回尚未完成；不可删除该副本。原历史归档回执保留，新的迁移回执 `/mnt/workspace/m75-history-relocation.json`。

## 实现与验证

M75独立prepare/run/audit/evaluate/report/reading/curve脚本，重用已验证数值、存储适配、进程树监督和greedy评测核心。新执行根 `/mnt/workspace/splendor-m75-continuation-r1`，从M74已pin的337文件逐SHA复制，再覆盖10份M75来源；不修改M74执行树。overlay SHA `58f6486785110d84c06bbde6a7e1b69e6b4ecaa06689832d4312bff8331f13b3`，成员manifest保存在本地 `local-artifacts/prism/m75-continuation/`。

已运行 `python -B -m unittest scripts.test_prism_m75_contract -v`：9/9 PASS，0新局；覆盖父代漂移、唯一双座5120调度、旧小存储限额、整盘预留、缺局、重试、9216网格、阶段预算和种子串用。Linux依赖/CPU/337来源、68输入parent parity与新调度检查待R3执行。沿用同数值核心/二进制/四CPU环境的既有工程证据，工程新对局预算0。

## 交付与阶段

后台有限管线：train→全部训练回放与state/export审计→最终c20冻结→阶段曲线→独立greedy→结果/完整Markdown/阅读HTML/Agent审计。新报告绑定result/config/Markdown SHA；实际桌面与窄屏像素检查留待取回时执行，生成不记视觉PASS。完成后更新报告索引、核验全部缺项、ALL及handoff，才收口实验。

当前R0/R1/R2 PASS（既有核心工程复用+新合同检查）；R3 IN_PROGRESS；R4–R8 NOT_RUN；R9 IN_PROGRESS。没有模型提升/发布结论。ALL本轮读取fetch failed，事实待同步，未启动服务或自动化。没有常驻本地观察器/自动取回保证；DSW有限管线启动后独立运行，实际启动回执与ETA随后追加。

## 迭代记录

- 2026-10-10：用户授权一轮后继训练；冻结预算/候选和开发、独立集分离。优先利用已有DSW，归档逐字节转存释放训练盘24.40GiB；完整本地备份因链路约0.46MiB/s预计15h，未冒充已完成备份。

### 2026-10-10 实际启动与源核验

DSW启动于2026-10-10T16:06:43.170000+08:00；PID50219/create_time1791619603.17，execution SHA `dcd984cb40eed2bfc68ede654d1a83b2387233de090a2c2d267167909b23a44a`。2026-10-10T16:07:39.583521+08:00只读核验：同PID/create_time/argv/cwd，pipeline TRAIN_a/RUNNING，首周期实际采样56/5120、更新global_step0，stop_reason=null。父代32张量逐值一致，optimizer槽0、新run RNG；没有模型提升结论。实际截止2026-10-11T18:06:44.054077+08:00，本轮不重置截止或扩大预算。

本地9/9、DSW9/9零局合同检查PASS，68输入parent parity PASS（atol/rtol1e-4，max_abs_error0.0001102490）。347执行来源在DSW逐SHA核验，并从本地保留原包+两轮overlay+精确输入逐SHA重建全部347份，missing0；本地7脚本语法与阶段表完整/缺配对合成输入渲染检查PASS，0研究局。来源/启动/preflight/初始化/磁盘回执保存在 `local-artifacts/prism/m75-continuation/`。实际空闲49.25GiB，额外整盘预留8GiB、全轮38GiB保持。

预计10月11日04–08点训练完成，06–11点审计/开发曲线/独立评测完成；建议10月11日10点查看。依据M74同规模实测及新父代局长不确定性，首分钟采样速度不用来推断全轮ETA。26h截止10月11日18:06附近，非预计完成时间。

M67归档完整本地取回已作为有限后台传输启动：本机PID15384、SCP36272，0重试/24h超时；实际已运行，结束须尺寸与SHA均匹配后才能改名为完整ZIP。源副本不自动删除。本机或链路退出会使下载失败，DSW训练管线独立。后台下载不是持续研究观察器，未创建automation或保证自动取回M75结果。

当前R0–R3 PASS；R4 IN_PROGRESS；R5–R8 NOT_RUN；R9 IN_PROGRESS/任务progress。下一允许动作是现有有限管线推进并只读取回结果、交付视觉检查。ALL读取fetch failed，进度/证据仅写待同步记录，不称已同步；未启动服务。无新版本发布、默认替换、其他应用部署或Git提交推送。

- 2026-10-10T16:10:24.921583+08:00 同execution新鲜核验：222/5120局，cycle1采集中、global_step0；RUNNING/无stop_reason，磁盘48.82GiB。347文件身份再次PASS；后台归档本地partial约47.5MiB，仍未完成全量备份。该事实仅更新观察时间，不改变预算、ETA或启动任何额外研究。

### 2026-10-10 归档传输改用魔搭

用户指出应使用魔搭中转，已将本轮历史备份传输改为DSW直传→现有私有ModelScope数据集`sparxie1/test1005`→本机直取。核验本机与DSW现有SDK/登录配置、真实仓库visibility=PRIVATE(1)，在独立`splendor/history/m67/20261010/<archive SHA>/`命名空间保存原字节分片与manifest。第一片64MiB供新鲜客户端取回验证，其余最大1GiB，按offset拼接完整ZIP后须核验26203087576字节与原SHA。2上传/3下载并发，有限2h截止、源文件不删、凭据不落进回执；传输脚本与记录在本地m75-continuation，DSW传输临时目录位于/tmp，与pin的训练树隔离。

18:05已启动DSW上传进程PID97052/create_time1791626727.04与本机下载PID21844；当前准备分片，尚未宣称备份完成。旧SCP/Python实际PID均已不在，本机partial2876047360字节保留；旧RUNNING回执为过期观察，新的history-scp-switch-receipt.json记录实际状态。切换没有控制训练进程或更改科学合同。18:06只读核验M75仍PID50219、同execution dcd984cb…、347pin来源一致、1915/5120局、7周期提交/第8采集/386更新，无stop_reason。ALL当前fetch failed，另存真实待同步记录。

魔搭链路实际验收：源26.20GB完整SHA PASS，26个原字节分片的offset/总字节覆盖PASS；首64MiB经DSW上传、新鲜客户端读回、魔搭→本机下载与本机独立SHA PASS。全部ZIP仍在后台传输，未标完整备份；modelscope-switch-verification.json绑定真实进度，原/tmp副本保留。

18:12后续观察：本机4个分片已完整SHA核验（3136MiB，约3.06GiB），DSW16/26上传提交；首批有效本机速率约27MiB/s，对原约0.45MiB/s约60倍。预计18:30–18:45下载与完整SHA验收，按早期实测估算；整体仍IN_PROGRESS，不据此删除源归档。

### 2026-10-10 云端完整性确认与本机历史包清理

用户明确授权：魔搭完整性确认后清理本机不必要的历史包，以后历史数据留魔搭按需取用。本次task_kind=implementation/maintenance，authorized_end=补齐云端M67归档、完整SHA校验、本次本机重复历史包/缓存清理和保存位置规则登记；不修改M75固定研究执行。

发现上一上传器RateLimitError导致缺part-024.bin（原26片只提交25片），此前18:30–18:45全量下载ETA未达成。原失败与清单保留；本次仅补交缺片，现有LFS字节复用。新鲜客户端核验私有仓库、manifest、全部26片大小与SHA；对此前魔搭下载的25片逐字节重新hash，对缺片新鲜流式读取，并按原offset计算完整归档SHA。原大小26203087576字节、SHA65a85004…a072完全一致，cloud-history-integrity.json=PASS_CLOUD_COMPLETE_BEFORE_LOCAL_CLEANUP。没有再生成完整本机ZIP。

已核验并停止仅负责本机全量下载的PID21844，所有本机删除目标绝对路径限定m75-continuation/archives，拒绝reparse point，保存完整文件清单与完整性回执SHA后才执行原生PowerShell删除。2026-10-10T20:11:08.7383016+08:00删除28个文件（魔搭缓存、两份SCP残片），实际释放26.112GiB；history-local-cleanup.json=PASS_LOCAL_DUPLICATE_HISTORY_REMOVED，目标不存在读回PASS。魔搭和DSW原归档保留；模型/配置/结果/报告/清单与校验回执保留。

未来保存位置规则已写AGENTS.md，云端索引与恢复说明docs/prism/history-archive-index.md。本次维护完成，M75训练实验仍按原合同推进；ALL fetch failed，维护完成回执另存待同步，不称已更新远端看板。0训练控制/发布部署/提交推送。

### 2026-10-11 结果查询：训练被256ply截断停止

用户“看看结果”；本次task_kind=status，authorized_end=核验实际进程、停止原因、已有产物与身份，只读取回必要证据并更新记录。没有启动/恢复训练、清锁、改合同或追加采样。本机接手分支m61-alpha-balance-ab/HEAD a9a0037d82b05af0c55782f6dc2c0e2e72e6f6bd，index与受跟踪工作树初始为空；该本机新HEAD不是M75执行来源。

2026-10-11T14:07:42.566049+08:00直接读取DSW：原execution SHA dcd984cb40eed2bfc68ede654d1a83b2387233de090a2c2d267167909b23a44a匹配，347个pin文件逐SHA PASS；没有该执行树的活动进程，pipeline明确FAILED_STOPPED_NO_RETRY，停止时间2026-10-10T21:33:21.064975+08:00。执行持续5h26m37s，当前磁盘空闲37951307776字节/35.34GiB。

不可变提交账本读回：3405物理尝试=3404 COMPLETE+1 FATAL，重试0；实际正常终局66.48%，最后完整提交c13（3328局），第14周期已提交76正常局，global_step/update_attempts=718。run保存phase COLLECTING/paused=true/cycle14/attempts3405，模型、32个optimizer槽与python/numpy/torch/cuda RNG字段可读，run/launch-ledger HEAD读取前后SHA不变。仅验证已保存状态的可读取性，尚未执行恢复兼容/预算验证。

失败为job m75-a-c14-b38-s0，environment_seed13002702，候选座位0，对手latest-alpha。arena正常退出returncode0、stop_reason=null，report.outcome.status=truncated/completed_plies256，截断时分数[8,6]，没有胜负。训练蓝图原limits.max_plies=256；config.evaluation.ply_cap=512仅适用于后续评测。engine/ppo/arena.py将训练截断写FATAL并抛出“Arena truncation/deadline/protocol failure; campaign stopped”，worker.py拒绝failed ledger直接恢复。是训练长局处理边界导致停止，当前证据未显示磁盘/内存/单局超时耗尽；不得把截断算作平局或模型退化。

现有导出c1–c13，c13 weights SHA07440e5b45b8817d9b7b5d9d94813e01916e5904cf57290bd8f100341b9956df。没有final c20、worker-completion、audit、development/curve、evaluation-completion、正式result或pipeline completion；开发曲线和独立棋力评测NOT_RUN，无新棋力/版本结论。R4 FAIL/数据INCOMPLETE，R5–R8 NOT_RUN；整体实验保留review/恢复阻塞，本次状态查询已完成。

只取回15份必要诊断文件236398字节，逐文件大小/SHA PASS，未全量下载历史包；证据local-artifacts/prism/m75-continuation/result-check-20261011/{readback.json,evidence/}，只读探针check_results.py保留。ALL context fetch failed，真实状态另存all-pending-update.json，未启动服务或声称同步成功。

下一允许动作：评审有限恢复修订。需保留原失败/已消耗预算和全部正常局，单独处理截断、full-state身份与恢复计数，原冻结执行树不热改；不能仅清锁重跑。原绝对截止2026-10-11T18:06:44.054077+08:00不变。当前已停止，无有效完成ETA；恢复方案须核算剩余1716正常局及开发/独立评测是否能满足剩余时间，再确定执行修订和授权。当前status范围与原研究重试0不包含恢复执行。

### 2026-10-11 用户明确授权修复并恢复r2

授权原文：“那你赶紧修好接着跑啊，保留之前的训练进度，别再让服务器闲着了。跑起来后告诉我预计什么时候能看结果。” task_kind=implementation+experiment recovery；authorized_end=保留完整状态，完成原20周期/固定5120物理尝试，finalc20审计、1024开发曲线、9216独立尝试与报告。0下一轮、发布、部署、Git提交推送。运行后仍须完成R5–R9，不以恢复启动关闭整个实验。

修订合同[recovery-r2](../benchmarks/m75-prism-continuation.recovery-r2.json)，SHA251e4cfb1684ecad6cc0cbdb927b71a30ace23279eeb62632908b0ce8ac550c5。新适配器[scripts/prism_m75_resume.py](../scripts/prism_m75_resume.py)单独部署到原执行根continuation-r2/resume.py，原347来源、合同、失败状态、锁和round-budget原字节保持。模型/优化器/RNG使用full-state resume，不重新warm-start，不回退c13、不丢第14周期76正常局。

行为修订：已验证的256ply截断成为TRUNCATED已处理任务，保留原FATAL不可变提交、原prefix/report/sidecar/资源与128物理决策；不编造胜负、不加入terminal PPO batch、不重打或换seed，也不补充替代局。Campaign调度和cycle summary认识TRUNCATED，seal只用真实终局，审计分别核验5120物理任务与实际正常终局。第3405次失败改分类后，剩余为1715固定任务；正常终局最终可能少于5120，必须如实报告。协议/身份/哈希错误和真实资源超额仍停止；本修订只使有效截断可继续，尚未增加其他基础设施故障的自动恢复。原自动重试0保持。

原18:06:44截止留在原round-budget；新有限恢复独立12h截止2026-10-12T02:50:30.711826+08:00，不无限循环。总CPU240000秒、训练CPU150000秒、训练活动墙钟18h均扣原已消耗29638.524859 CPU秒/19596.655291墙钟秒；训练32GiB/全轮38GiB/盘预留8GiB保持。新preflight估计训练落盘27.63GB/25.73GiB，盘35.34GiB可用，通过整盘与评测预留检查。原预算与来源SHA绑定在新policy；该恢复改变截断处理与截止，明确不是原r1未修改自动续跑。

验证：本地12项恢复回归、DSW同12项PASS，原9项合同回归PASS，审计适配锚点/语法PASS，0工程对局/前向。覆盖实际失败prefix、假平局拒绝、seed/哈希/分母漂移、真实deadline拒绝、混合终局/截断物理账本、重复job拒绝和seal只消费真实终局。DSW原347 pin文件逐SHA PASS；preflight→recover→新worker分别核验model/optimizer/RNG指纹，三项逐值hash不变；3404正常局、3405物理尝试/718更新保留。恢复账本只追加新提交，原失败commit仍可取回。中间checkpoint/最终导出身份沿用既有审计，尚未宣称模型增强。

实际启动2026-10-11T14:52:54.520000+08:00，DSW PID21751/create_time1791701574.52，argv/cwd/policy SHA匹配。14:54:44.212744+08只读核验：RUNNING/train，3416尝试=3415正常+1截断，第14周期采集中/718更新，磁盘35.296GiB；新增11正常局证明已恢复采样。后台阶段按train→audit→candidates→curve→evaluate→report推进，DSW本地有限管线写真实进度；无常驻本机观察器/自动本地取回保证。

ETA：依据M74匹配规模、M75原5h26m/3404局及后段变慢，剩余训练估3–5h，审计/开发/独立评测另1–3h；预计10月11日19:00–23:00完整结果，建议23:00查看。短暂恢复区间只确认实际工作，不替代完整负载估时。02:50为停止上限，不是预计完成时间。

证据local-artifacts/prism/m75-continuation/recovery-r2/{policy.json,tests-invocation.json,preflight.json,recovery.json,worker-resume-verification.json,launch.json,observation-latest.json,launch-closeout.json}；policy/恢复回执从DSW原字节取回并逐SHA核对。ALL context仍fetch failed，真实启动/进度另存all-pending-update.json待同步，未启动ALL或声称已同步。R0–R3 PASS/R4 IN_PROGRESS/R5–R8 NOT_RUN/R9 IN_PROGRESS；下一已授权动作是该有限管线完成后取回、审计阅读层和实际像素交付。曲线原标签cN×256表示物理训练尝试，R8取回时须明确区分正常终局数与截断，不能把缺项隐藏成正常训练局。

- 2026-10-11T14:56:49.529778+08:00 同PID/create_time/policy/347来源再次核验PASS：3430物理尝试=3429正常+1截断，c14采集/718更新；较原停止新增25正常局，0历史重赛。见recovery-r2/observation-latest.json。

### 2026-10-11 DSW2额外节点准备

用户“dsw2里也可以用”授权使用额外节点；先做零研究局环境/容量/来源检查，M75现有r2不热改。初始SSH到dsw2成功：hostname dsw-2246104-877fb6f94-kxctz，实际cgroup CPU配额8核（宿主可见64核不当作配额），内存限额28GiB/可用26.69GiB，没有发现活跃研究进程。已有splendor-arena-py312依赖numpy2.2.4/psutil7.0.0/Markdown3.8匹配，splendor和s4_batch_metrics二进制SHA均与DSW pin完全相同。

准备传送精确父权重/68固定输入做native推理检查时，DSW2后续SSH banner超时；server1可达且2223监听存在，但从server1直接读取该端口banner也3秒超时，说明转发入口存在、后端当前不可达，不能推断DSW2停机。有限准备传输本机进程已记录身份后停止，没有研究进程控制；远端部分准备文件UNKNOWN/推理parity NOT_VERIFIED。DSW2正式研究execution NOT_STARTED；没有双机评测派发或缩短ETA。证据local-artifacts/prism/m75-continuation/dsw2-preparation/{readiness.json,transport-stopped.json,prepare.py}。

M75原DSW管线不受本准备影响：15:07附近同PID21751/create_time/347来源核验PASS，3502物理尝试=3501正常+1保留截断，c14采集/718更新；已有进度继续增加。下一完成DSW2连接恢复/部分传输和推理验证后，再单独绑定不重复派发的评测执行修订；现有r2仍负责原完整流程，不能声称已分流。ALL不可达，节点准备结果仅保存待同步。


## 2026-10-11 双节点调度修订 r3（用户已授权）

- task_kind: implementation + authorized M75 execution continuation；授权原文：“分配一下工作 在dsw和dsw2上同时启动 节约时间”。authorized_end仍为M75剩余5120物理训练尝试/20周期、1024开发尝试、9216独立尝试、审计与报告；不启动下一轮、不发布/部署/Git提交推送。
- 训练继续DSW原r2独立relay/worker，模型、optimizer、RNG、游标和256ply训练cap不变。只暂停旧外层串行阶段调度；新r3持续检查训练资源、原relay和训练身份，直到finalc20成功提交和relay结束后才替换外层调度。旧来源/失败/预算和r2政策保留，不原地编辑pin源码。
- DSW2接4096父代基线独立尝试（六共同+两个最新覆盖对手，每对手256双座seed），DSW接5120候选独立尝试（相同八对手4096+直接父代1024）。完整9216游戏键精确分割、不重叠，不换seed/greedy模式/actionseed/权重/cap/统计/门。唯一顺序修订：无c20的父代基线可提前跑，结果不反馈训练/最终c20选择；候选评测仍须R5冻结后启动。
- DSW2真实8核/28GiB，8分片并发，16GiB进程树软RSS/128进程、4GiB工作目录上限（含输入和转存证据），基线CPU预留60000秒，合并两节点沿原240000 CPU秒并扣原29638.524859秒。DSW训练32GiB/总38GiB，原r2绝对截止2026-10-12 02:50:30+08保持。独立截断上限8先给基线，候选只消费剩余额度，正常终局与截断分报，研究局不重试。
- 分片原字节、SHA、清单、runtime与固定源绑定验收后合并。有限本机传输桥只搬本轮4096基线必要证据（不是全量历史备份），核验SHA、目录安全与无既有dispatch后导入DSW；原历史包仍留私有魔搭按需取用。
- R2新增7项零研究局检查：9216精确键/无重复、缺局拒绝、直接父代范围、路径越界、损坏归档、既有dispatch拒绝覆盖、Linux真实SIGSTOP外层但有界relay子进程继续推进。R3另查347原pin、数值68-input parity、两节点runtime、实际资源和进程身份。此节冻结时仍未宣称启动；实际launch/进度/结果另附后续回执。
- 证据：benchmarks/m75-prism-continuation.dual-node-r3.json；scripts/prism_m75_dual_node.py、scripts/test_prism_m75_dual_node.py；local-artifacts/prism/m75-continuation/dual-node-r3/。


### r3实际启动与验证回执（2026-10-11T16:21:31.370980+08:00）

两节点实际运行：DSW新调度PID48618/create1791706738.47；原训练relay21760/worker21761不变，外层旧PID21751仅STOPPED防止后续重复dispatch。16:19核验3909/5120物理尝试=3908终局+1截断，c16采集/828更新；原模型/optimizer/RNG/历史仍同一条链。DSW2基线PID21392/create1791706359.4，8实际worker；原账本983正常终局（进行中的非原子诊断快照），已完成8/64整分片512局，0已报告截断，无新增工程局。任务分割4096父代+5120候选仍原9216，开发1024保持，候选仍固定finalc20。

启动前本地6PASS/1Linux-only skip、DSW7PASS、DSW2 7PASS、68parity、两端347原pin来源及同runtime通过。首次DSW启动前身份检查正确拒绝错误selector（取relay为worker），没有发出SIGSTOP或改变训练；另立`dispatch-handoff-r1`（SHA6518760e…）绑定真实worker21761并拒绝relay自绑，保留原r3政策与来源，之后成功启动。审计时使用此覆盖入口`dual-node-r3/handoff.py`，不能直接用原`dual_node.py start coordinator`的旧selector。新适配器来源在scripts/prism_m75_dispatch_handoff.py；绑定在benchmarks/m75-prism-continuation.dispatch-handoff-r1.json。

DSW2 reverse link发生高丢包/无banner；核对server1仅2223监听所属sshd后重连该链路，DSW训练未控。DSW2仅对150.158.50.58的SSH配置加入IPQoS none（原配置SHAe3b0c…、修改SHA4df896…，原字节留`.dsw-tunnel/network-r3/ssh-config.before`），只重连2223 tunnel PID，研究进程不杀。连接恢复后已核验983真实终局；不把SSH不可达判为训练失败。

18.63MB当前节点必要源码/模型输入经既有私有ModelScope `sparxie1/test1005`按SHA传入；无需历史全包。本轮基线证据后续DSW2→私有ModelScope→DSW，原字节ZIP清单/SHA/runtime/固定网格验收后合并，不改saved argv/结果或重打游戏。临时认证仅传入节点任务进程内存、不保存登录凭据或写入源码/回执/argv。DSW2有限云端relay PID21393、本机有限cloud bridge PID12672/create1791706480.662614已启动（至原r2截止）；当前仅WAITING，最终上传/导入/完整汇合尚NOT_RUN，不能称这些已通过。源输入有云端大小/SHA与节点读回确认。

ETA：基线及云端接收预计今天16:40–17:00，完整结果/报告预计20:00–23:00，建议22:00查看。训练约86分钟新增504次尝试，基线约6分钟983终局，包含周期更新/审计/开发/候选对局、转存及增长余量；不以单局1.21s冒充纯推理吞吐。任务“分配并双机启动”完成，原M75实验R4 IN_PROGRESS，c20/最终棋力NOT_EVALUATED；后续既有审计/评测/报告和取回已授权。ALL context再次fetch failed，更新存all-pending-update.json，未启动ALL服务。未提交/push、未发布/部署/下一轮。

回执：local-artifacts/prism/m75-continuation/dual-node-r3/launch-closeout.json、observe_remote-dsw.json、detail_remote-dsw2.json、各preflight/tests/parity/source/launch及cloud-bridge.json。


后续16:23+08实际核验：DSW仍同训练worker，3933物理尝试=3932终局+1截断/c16/828更新；DSW2已通过24/64整分片验收，1535终局+1有效PLY_CAP截断=1536尝试，仍有8个活跃worker继续下一分片，没有因这一次有效截断停止整轮。最终独立网格尚未完成；该截断不填平局，后续候选最多消费剩余7个独立截断额度。不可用此部分基线给候选棋力结论。不可变读回live-dsw-1791707012.json、live-dsw2-1791707021.json及live-launch-status.json；完整结果ETA20–23点仍为估计。


### 2026-10-11 18:09 双机分工与传输故障核验

2026-10-11 18:09+08 分工核验：DSW2于16:42完成4096物理独立尝试（4095终局+1有效截断），16:57打包，18:07实际无研究进程。r3只分父代基线给DSW2，未配置后续自动接续；DSW仍承担串行训练、审计、1024开发及5120候选评测，该静态分工导致第二节点提前空闲，不能称持续双机满载。DSW同worker21761/relay21760及协调48618仍RUNNING，4471/5120物理、c18/938更新，盘29.63GiB可用，stop_reason=null。上传原16:57 RateLimitError保留；仅恢复已完成证据传输，4次最多/300秒/原截止，首试成功，私有魔搭44,561,857字节SHA核对，18:09已到DSW inbox并再次核验原ZIP SHA2fbe5ad6…24968fd。未重打研究局、未更改训练/科学合同或实际任务分配；完整网格审计/候选结果仍未完成。证据dual-node-r3/allocation-status-20261011.json、current_status_remote-*.json、delivery_status_remote-dsw2.json、inbox_status_remote-dsw.json。ALL fetch failed待同步。


### 2026-10-11 18:44 用户授权后续评测迁移r4（启动前冻结）

用户明确要求“重新分配，把后续评测交给DSW2，保留DSW训练进度”。task_kind=implementation+experiment scheduling revision；authorized_end=原M75有限训练/开发/独立/报告完成。固定5120训练物理任务、c20最终候选、1024开发、9216独立、科学seed/模式/门/统计和原恢复截止02:50:30+08保持。无下一轮、发布、部署、提交推送。

新来源scripts/prism_m75_eval_handoff.py与benchmarks/m75-prism-continuation.eval-handoff-r4.json分别绑定原execution与r2/r3所有适配器SHA，原pin不改。DSW2接全部剩余评测：先跑固定c5/c10/c15的768开发尝试，c20在DSW审计冻结后接256开发及5120候选独立；4096父代基线直接复用。顺序修订仅提前三个固定开发检查点，不反馈训练、不选择候选或增加训练。DSW原relay21760/worker21761不停止、不迁移模型/optimizer/RNG；接手仅暂停旧r3后续协调48618，原r2外层21751继续保留以维持独立训练relay所有权。新DSW协调调用原已验证monitor_training等待5120/c20，再审计/冻结、发布精确c20、汇合已有基线与DSW2结果并生成报告。

两节点均有限独立控制器，当前必要检查点和评测证据经私有魔搭传递；不依赖本机进程，不下载完整历史。本次输入三检查点7,336,810字节ZIP，SHA b3f4f6e…18b0cb96e，权重各SHA写入政策。每次上传最多6次传输尝试并退避，读取仅至原截止重试，研究局仍0自动重试/0重复采样。DSW2八分片并发、16GiB进程树RSS/128进程、4GiB目录/60000CPU秒；既有基线1796.58CPU秒另核算，两节点总CPU仍240000且扣原29638.52秒。DSW38GiB总目录与32GiB训练上限沿前序保持。

本地7项针对性测试PASS：同字节导入、路径逃逸/损坏/既有结果覆盖/政策SHA/完整ZIP SHA拒绝、开发768+256精确不重叠。两节点各7项相同零局测试、347原pin SHA、host SHA、DSW训练与旧协调身份、DSW2八核除affinity外原数值环境完全匹配，preflight PASS。准备时缺DSW-only handoff/host元数据已按原SHA补齐；源输入下载SSH等待超时仅为传输观察失败，已核对原下载PID仍在推进，不重复创建下载或研究局。实际启动/新对局证据后附；当前本节为FROZEN，不等于已开始采样。


### r4实际启动、训练保存与下一步（18:49+08）

2026-10-11 18:49+08 后续评测重新分配r4已实际RUNNING：用户明确要求评测交DSW2、保留DSW训练。DSW新协调93803/create1791715613.28，原训练relay21760/worker21761不变；旧r3协调48618仅暂停防重复后续派局。当前4668/5120物理=4667终局+1截断、c19/992更新，无stop_reason。DSW2协调102954/create1791715630.95，8实际评测worker，已读297完成开发局（逐分片原子/全局非原子快照）；先固定c5/10/15共768开发，c20在DSW审计冻结后自动接256开发和5120独立，既有4096父代基线复用。1024/9216固定网格、模式/seed/门/最终c20/总CPU/截止不变；开发前三点提前仅描述，不反馈训练。两节点独立有限私有魔搭传输/调度，不依赖本机；传输上传最多6次，研究0重试。7+7+7零局检查/347原pin/host/runtime/PID预检PASS；实际新对局证明接续开跑。预计训练20:15–20:45，完整评测/报告22:00–23:00，建议23:00查看；02:50:30为原停止上限。证据eval-handoff-r4/launch-closeout.json，scripts/prism_m75_eval_handoff.py、benchmarks/m75-prism-continuation.eval-handoff-r4.json。M75实验R4 IN_PROGRESS/最终棋力未评测；本次分配启动范围完成，ALL待同步，无下一轮/发布部署/提交推送。

输入转运恢复：原下载PID101210/create1791715271.03在3756828字节停滞，SSH等待超时；核对身份并只终止该下载进程，保留部分原字节，以带15秒读取超时/最多6次/300秒的HTTP Range从私有魔搭恢复，7,336,810字节完整SHA PASS。未改/停止研究进程。先启动DSW协调确认接手，再启动DSW2；DSW原worker继续新增训练局进入c19，DSW2已实际完成开发局。已运行源码/政策冻结不热改。复用旧monitor中的TRAINING_DSW_BASELINE_DSW2 phase与r3 policy标签仅是历史输出字段；本次真实身份以r4 launch.json PID/create/source SHA/policy SHA核对，不能据旧phase推断DSW2仍只跑基线。其余最终冻结/完整采样/传输/汇合/报告继续原已授权有限链，尚未声称这些阶段PASS。


### 2026-10-11 20:22 DSW2实例替换后的等待恢复r5（启动前冻结）

用户报告DSW2再次断开，沿现有明确授权恢复同一有限后续评测。实际hostname从dsw-2246104-877fb6f94-kxctz变为dsw-2246854-85499cf68f-l7wkg，原协调102954不在；共享卷保留原执行、4096基线与768开发完成记录，768开发0截断，原stage PASS/385.750827CPU秒。最后旧协调WAIT_FINAL-INPUT采样约19:54；具体平台替换原因未知，不将其归因于源码故障或SSH连接断开本身。

独立恢复适配器scripts/prism_m75_wait_resume.py部署wait-resume-r5/resume.py，绑定原r4源码/政策、execution、两份开发完成/early-input回执、基线完成SHA。仅恢复已成功768开发之后等待固定c20的控制链；保留原CPU消费，不重打、不换seed、不改截止/预算/科学门。原DSW训练worker21761与协调93803继续运行，本次不控制它们。前序r4源码与政策原字节不改；r5会重用原r4 final-evaluation child与私有魔搭输出路径，已完成开发不再执行/导入。

本地4项零局回归通过：原CPU计入、缺局拒绝跳过、重复分片拒绝、失败stage拒绝。新节点须完成原pin/八核除affinity外原runtime匹配、旧PID不在/无孤儿执行、12开发分片原manifest与saved evidence grid FINISHED/64正常局验证，且final-evaluation未曾尝试，才启动等待恢复。已完成研究局不自动重试；无下一轮、发布部署、Git提交推送。实际preflight/launch/进度另附。


### r5实际恢复回执（20:26+08）

2026-10-11 20:26+08 DSW2实例替换恢复r5已实际RUNNING：旧节点dsw-2246104…变为dsw-2246854…，原协调102954消失，原19:54 WAIT_FINAL-INPUT已存证；768开发早已全部完成/0截断，4096基线保留。新的wait-resume-r5 PID4335/create1791721579.66已核验实际存活/新鲜WAIT_FINAL-INPUT心跳，等待DSW c20后继续原256开发+5120候选，未重打已完成局。新节点347 pin/八核原runtime与12完整分片逐原字节/配置/网格验核PASS；本地及节点各4项针对性恢复回归PASS。原CPU385.750827秒计入，原r4来源/政策不变，r5独立SHA1ebe6f4c…c3236/policy e76e8894…d49e4。DSW原训练relay21760/worker21761及协调93803不控制不回退，当前5112/5120物理=5111正常+1保留截断，c20/1046更新，仍采集/stop_reason=null，盘25.89GiB。实例重建具体平台原因UNKNOWN；原脱离SSH进程不能跨实例替换自动复活，当前已从成功阶段守卫恢复，未声称实现平台级自启动。完整结果暂估22–23点/23点查看，截止02:50:30不变。证据wait-resume-r5/launch-closeout.json；scripts/prism_m75_wait_resume.py、benchmarks/m75-prism-continuation.wait-resume-r5.json。ALL fetch failed待同步，原实验IN_PROGRESS/最终棋力未评测，无下一轮/发布部署/提交推送。

预检第一次105秒子进程等待不足，只有只读验核被超时中止、无任何研究采样；改用600秒有限预检后成功。stdout尾随空行曾使本机回执解析失败，远端成功preflight原文件保留，改为读取该文件后再launch，没有重复preflight或研究调度。两个管理层故障与原研究证据分开保留。恢复启动前R3零研究局；原r4 status现在由r5等待协调产生，必须联读r5 launch的PID/create/source/policy，不把原r4 launch旧PID当作当前进程。

### 2026-10-11 实例自动恢复与空闲提醒（r6–r8、monitor-v2）

用户明确授权“把实例重启后的自动恢复也修好……保留已完成的进度……dsw2空闲1h自动回收……空闲通知”。task_kind=implementation+有限实验运行恢复；authorized_end=安装持久化恢复入口、稳定节点检查、当前任务提醒，接续原 M75 并保留已完成证据。训练5120物理尝试、1024开发、9216独立、最终c20、原科学门及02:50:30+08截止保持；本次独立执行修订允许每个未完成基础设施中断局至多一次恢复，完成局0重赛，协调恢复最多6次/节点，原尝试归档、资源账合并，未授权下一轮或发布。

当前实现为 [恢复控制器](../scripts/prism_m75_reboot_resume_r8.py)、[绑定入口v2](../scripts/prism_m75_recovery_endpoint_v2.py)、[稳定观察器v2](../scripts/prism_m75_recovery_watchdog_v2.py)，合同 [r8](../benchmarks/m75-prism-continuation.reboot-resume-r8.json) 与 [monitor-v2](../benchmarks/m75-prism-recovery-monitor-v2.json)。r8主源码SHA `9d7117976c2b08218d594db6d4f7013dd92a3a68cdb51896400ea11f5037cfbf`；入口v2 SHA `467d483357f818f88742b4856b0b34bc0c58c1718cf4ade7de6237c6f375600d`。原347 pin、r2/r3/r4/r5源码与科学合同原字节保持。

两端现有持久化bootstrap接入恢复：DSW `/mnt/workspace/.dsw-ssh/bootstrap.sh`，DSW2 `/mnt/workspace/.dsw-tunnel/bootstrap.sh`；DSW入口放在既有`exit 0`之前。启动入口恢复SSH公钥后调用独立endpoint-v2，核对来源/配置/数值环境/PID-create_time/截止/完成账本，已完成分片复用，未完成分片逐局跳过已提交结果；已完成但账本落笔中断时按原产物审计收养，未完成尝试保存原目录再按固定seed恢复。不同执行修订的CPU费用按保留目录去重合并；未知阶段消耗按已测CPU加离线墙钟×核数保守预留，不当作0。

server1用户systemd服务 `prism-m75-recovery.service` 已enabled、Linger=yes，稳定节点每60秒通过专用受限SSH公钥检查两端；公钥仅允许JSON状态/有限恢复/现有凭据桥接入口，不提供任意shell。ModelScope凭据来自DSW已有SDK，只在稳定进程内存缓存，并经加密SSH stdin注入；缓存可跨DSW实例重建保留，不落盘、不进argv/日志/结果。Codex当前任务heartbeat `m75` 已ACTIVE/每5分钟，首次等待、研究等待30/45分钟、失联、恢复受阻、完成或截止时提醒。平台1h回收为用户提供政策，未读取平台真实空闲计数；研究等待计时与平台计时分报。平台回收后的实例开机仍由用户/平台完成，实例启动后的任务自动接续；server1不依赖本机保持运行，通知及时送达依赖Codex运行。

本轮保留的工程失败与修订：原审计在5119终局+1保留截断下错误要求完整双座配对，r4协调于20:39退出；独立训练诊断适配将缺配对区间写`NOT_MEASURED`，不补平局/重跑训练。r6/r7零研究审计的格式/历史CPU合并问题均保留源码、阶段目录与费用后由r8取代。系统控制Python与arena Python不一致造成恢复读取runtime失败；两端当前控制入口统一使用原arena Python3.12，并隔离快照已有ModelScope SDK及其必要依赖，数值Python/NumPy2.2.4/psutil7.0.0/Markdown3.8逐字段一致。公网pip准备两端各150秒超时，未作为研究重试；最终使用现有SDK源码快照和精确CFFI cp312 wheel，未修改arena的数值包。已有基线导入在第一次校验异常后留完整成员但无完成回执，入口v2对同SHA成员幂等复用、冲突拒绝，保留原ZIP并完成64分片核验。

截至21:21+08，训练20周期/5120物理=5119正常+1截断/1102更新已完成且审计PASS，固定c20 SHA `eaa1331b29599f239299b5a9037100ae042c6021b2195df3f675c2eb5bd62bf5`、父代SHA e16bfe0d…58ad；审计SHA5e4be743…b0321，c20输入ZIP SHA b8f115d7…b9669f已在私有魔搭确认。DSW PID137439/create1791724376.17由server1实际自动拉起（入口v2部署后约35秒），当前WAIT_EVALUATION-OUTPUT，属于研究等待/空闲，应主动通知。DSW2 PID14475/create1791724186.68，8个实际grid worker，开发已完成1024/1024且无截断；候选独立已读808/5120正常局、0新截断（非原子进度快照），4096既有基线保留4095终局+1截断。独立结果仍IN_PROGRESS，不给棋力/路线/发布结论。

验证：恢复器14项零局测试PASS（完成与截断跳过、真实文件夹中断恢复、原字节保留、费用去重/PID复用/截止拒绝/提醒边界等），稳定凭据缓存3项零网络测试PASS（DSW凭据临时消失后仍从内存恢复两端、健康节点不派活、秘密不进入状态/事件文件）。两端SDK快照451/422文件均绑定manifest并在原arena运行时实际导入PASS；启动钩子bash语法/单一入口/DSW exit前位置与专用SSH可达PASS。DSW2等待进程退出后的第一次演练包含解释器修复，历时768.66秒；这是恢复进度保留实测，不能宣传为一分钟恢复。修复后server1实际自动启动DSW，恢复服务重启后两端研究PID不变。未重启正在评测的整实例，整实例重启端到端测试NOT_RUN；HTML说明已离线打包/0未决决策，浏览器file协议被工具策略禁止，像素NOT_VERIFIED。

证据目录 `local-artifacts/prism/m75-continuation/reboot-resume-r8/`：deployment、endpoint-v2绑定、SDK snapshot、boot-verification、watchdog-v2-installation、两端live-summary、drill/verification、tests与closeout；r6/r7失败来源和回执保留。ALL context仍fetch failed，更新待同步，未启动ALL。原实验R4/R5 PASS、R6 IN_PROGRESS、R7/R8 NOT_RUN、R9 IN_PROGRESS；本次恢复/提醒部署完成，下一已授权动作仍为完成既定评测/取回/画像/阅读层与交付。按匹配实测速率预计22:00–23:00完整结果，原截止不延长。

启动身份补充：两端当前SSH host keys只在各自实例持久卷中保留（目录700/私钥600），bootstrap在恢复sshd前恢复相同主机身份，避免实例重建后的known_hosts漂移阻断server1恢复。未读取私钥到工具输出或跨机迁移；当前连接/研究进程未重启。host-identity-verification回执绑定新bootstrap SHA。

### 2026-10-11 21:44+08 r9 双节点并行候选评测（用户授权）

- task_kind=experiment execution revision；授权来源：用户要求将 DSW2 剩余评测分一部分给空闲 DSW，完成局不重跑。authorized_end=本轮固定1024开发、9216独立评测及既有报告；无下一轮训练/发布/部署/Git push。
- 科学合同不变，固定 c20/eaa1331b…62bf5、双方greedy、原seed和02:50:30截止。原DSW2 dispatcher按PID/create_time核验后仅暂停派单，8个现有worker自然完成；4096候选局完整保留，无研究局中止。原4096基线物理尝试及1024开发也保留。
- 剩余16个完整未启动分片：DSW接5片320局、4并发；DSW2接11片704局、8并发。精确标签及配置在 benchmarks/m75-prism-continuation.split-eval-r9.json。两端原347文件、candidate registry/SHA、SDK绑定和新适配器零局检查PASS；DSW五片重建manifest与DSW2完全相同，启动前无ledger。
- 资源：从原DSW2 60000 CPU秒预留中划4000给DSW子集，DSW2阶段先扣4000，结束后把DSW实耗只加回一次；旧阶段精确/保守费用账仍保留。DSW 8GiB/64进程、原38GiB根额度，DSW2原16GiB/128进程/4GiB根额度；子集最多2次有界协调启动，完成局0重赛。
- 实现 scripts/prism_m75_split_eval_r9.py：不修改已pin r4/r8，DSW子集经私有魔搭SHA绑定归并到DSW2；其父协调器持内存token执行传输，评测子进程仅等待本地导入回执。汇总所有80候选分片后仍由原交付管线送DSW生成报告。
- 自动恢复：两端持久启动hook/受限SSH端点改接独立r9适配器，server1现有稳定watchdog继续核对；DSW子集遗漏时报告NO_OWNER并恢复，DSW2按新分片规则恢复。正在进行实际启动和增量账本核验，最终状态以下方回执为准。

#### r9 启动回执与执行顺序修正

2026-10-11T21:56:06.691937+08:00 M75 r9分配已执行：候选4096旧局保留；DSW接5片320局/4worker，已完成0截断并魔搭SHA导入；DSW2接11片704局/8worker，PID60152/create1791726809.08，总候选4770/5120、0截断。对局约22:00，完整审计/归并报告预计22:20–22:45北京时间，原02:50:30截止/预算/c20不变。旧回放重验造成派发等待，独立ordering-v2让旧验证与新局并行；v3防止恢复时重复加DSW费用。两次零局启动目录错误及控制交接原始记录保留，完成局0重赛，5定向测试PASS。server1自动恢复启用；Codex提醒当前PAUSED，沿用开关，ALL待同步。证据local-artifacts/prism/m75-continuation/split-eval-r9/launch-closeout.json；详情docs/m75-prism-continuation.md，无下一轮/发布部署/提交push。

DSW子集启动两次因缺少PRISM_PPO_CONTROL_DIR在0新局处失败，源和回执保留，修正后独立入口增加2次有限协调机会（总4），未清费用或完成账本。DSW2原r8重验4096旧局串行拖住新派发，受控结束0活跃研究局的校验进程并保留保守CPU上界；ordering-v2给剩余任务先开线程，再校验完成分片，费用仍在同一ProcessTree内。独立入口协调上限8保留原6次尝试；v3未来恢复直接复用已包含DSW实耗的PASS阶段，避免重复加费。各修订源码和binding已保存；未进行整实例重启。DSW源报告协调PID137439未重启。DSW2开发与旧分片复用，不重复研究局。模型结论仍R6 IN_PROGRESS。

2026-10-11T21:57:49.178330+08:00 r9最新分片账本：候选4997/5120、0截断，DSW320已导入；DSW2实际3worker，旧证据审计并行。完整回执/报告仍未完成，ETA22:20–22:45。

### M75 完整对局结果只读核验

2026-10-11T22:06:38.869697+08:00 M75结果只读核验：候选5120/5120无截断，基线4095正常+1既有cap，开发1024完整，9216物理全结束；直接父代569W/11D/444L，半平56.10%/配对95%[53.13,59.03]、直接增强PASS。对最新Alpha/Balance比父代+11.62/+13.18pp；共同池71.15→74.22%描述值，基线Beta缺1终局使冻结共同门INCOMPLETE。对启发式/Alpha1.5分别-0.98/-0.88pp保留。DSW2 PID60152仍枚举打包、DSW137439等待原归并；正式报告/路线/版本未交付。4.46MB快照SHA及ledger/manifest/plan/weights/重复网格PASS，本机原20kbootstrap复算，0新局/0控制。预计完整报告22:20–22:45，ALL待同步。结果local-artifacts/prism/m75-continuation/result-check-r9/results.md。

本次 status 任务完成到既有结果读取/校验/报告。M75整体仍在R8交付中，完整Rust回放画像/报告receipt未读取，不据此声称正式交付完成；不启动下一轮。原共同池门输出与缺项保持，直接门与覆盖点估计分开。正式报告若随后完成，按已授权管线取回并核验。

### 22:41服务器交付完成与本机取回验证

2026-10-11T23:30:00.351302+08:00 M75最终交付只读核验：DSW在22:41:11完成RESULTS_AND_REPORTS_READY，DSW2在22:39:46完成私有魔搭57,033成员/66,594,425字节归并包交付。17对手双方pair/9215正常终局Rust回放规则审计PASS，1个旧基线cap保留；报告阶段PASS。16件必要模型/结果/报告/回执7,459,478字节取回并逐件SHA验证，原报告及统计未改；本机17组WDL/score、JSON-HTML payload、spec/result/contract/MD/HTML SHA、链接检查PASS，与上一读取直接56.10%/CI[53.13,59.03]、覆盖+11.62/+13.18pp一致。正式型号未登记、路线未定、共同配对门INCOMPLETE。报告docs/prism/m75-prism-continuation-comparison.html；索引已更新。两机无活跃研究，交付后等待约48.8/50.3分钟，DSW2一小时回收提醒已告知；平台空闲计时UNKNOWN。页面像素NOT_VERIFIED，不冒称视觉通过；ALL fetch failed待同步，Codex提醒PAUSED保留。0新局/0控制/无下一轮/发布部署/提交push。证据local-artifacts/prism/m75-continuation/report-delivery-r9/readback.json。

执行阶段资源总账63763.084331 CPU秒（原240000以内），DSW2交付8766.268969包含DSW子集408.832070一次；保守中断费用4814.675459及2719.053923保留。旧FAILED文件是历史证据，最新同execution完成回执与无研究进程为当前判断依据。

R4/R5训练与候选审计PASS；R6全部物理尝试终止，直接父代增强门PASS/共同池配对门INCOMPLETE（旧cap）；R7描述画像已交付，必要时点与兑现未测、路线undetermined；R8结果与完整报告取回/绑定验证PASS，视觉NOT_VERIFIED；R9本次status取回任务完成，ALL登记待同步。全任务视觉/ALL待办保留，不声称发布/默认晋级已完成。

### 2026-10-11 后续方向与产物归类评审（0新局）

**建议：先补有限的产物归类闭环，随后继续当前棋力主线；新路线按明确问题设小支线。** M75支持保留当前方向，流程工作优先解决每轮都重复出现的测量、参照和交付断点，避免扩成全平台重写。

本次 `task_kind=review`；授权来源为用户要求分析“继续当前方向、探索其他路线、先审计优化流程”；`authorized_end=既有证据与源码评审、方向建议、两层记录和待同步证据`。当前分支 `m61-alpha-balance-ab` / HEAD `a9a0037d82b05af0c55782f6dc2c0e2e72e6f6bd`，index初查为空，工作树已有M75与M78改动。R0及只读分析/R7适用描述/R8评审记录完成；R1新研究合同、R2实现、R3–R6新执行均NOT_APPLICABLE（本任务未请求新实现或采样）。本次本地评审完成，ALL登记待同步；原M75全任务的视觉和同步待办继续保留。下一允许继续既有证据分析，新的实现、训练或发布须有对应任务授权。

**为什么保留主线。** 已重新hash本机c20，确认 `eaa1331b29599f239299b5a9037100ae042c6021b2195df3f675c2eb5bd62bf5`；result/spec/contract/报告绑定及17组双方WDL复算通过。独立对父半平56.1035%，配对95%区间[53.1250,59.0332]%，原直接增强门通过；最新Alpha/Balance的匹配增益分别+11.6211/+13.1836pp。共同池原门仍INCOMPLETE。四点开发曲线48.63→55.47→58.98→58.20%，各256局，说明这段训练中后期的模型优于早期点估计；没有计算c15–c20配对差值区间，不能据末点小降判定平台或改选c15。单条轨迹支持继续开发，不回答方法跨训练seed是否稳定。

**需限定的覆盖面。** 最新Alpha、最新Balance、父代及General都在本轮训练对手中；独立环境seed仍是有效检验，但这些对手的改善不等于训练外泛化。其他旧锚点的增益和Heuristic/Alpha v0.1.5约−0.98/−0.88pp一并保留。后续保留固定训练外锚点；如果目标是跨对手增强，再预先冻结更广覆盖，不能看到本轮结果后重写旧门。

**现有流程的具体断点。**

| 事实与代码依据 | 对产物的影响 | 推荐的有限改进（尚未实现） |
| --- | --- | --- |
| AGENTS已有R0–R9/S1–S6；`scripts/prism_style_atlas.py`已有`classify_profiles`，`scripts/prism_style_delivery.py`已有classify入口 | 已有规则和分类能力，但每轮尚未稳定贯通 | 复用当前规程，建立候选→画像→路线建议→处置卡的共同入口 |
| atlas的`aggregate`把4项时点/兑现指标设为None，`build`只接M66/M67/M70；M75 report的progression明确DEFERRED，style结论写死为待定 | 单纯多训一轮仍会在同一位置缺项 | 把已有`prism_bigcard_metrics.rs`、历史早期投资统计接到新结果适配层；逐项核对本人Main/覆盖/兑现口径，补足确实缺少的兑现抽取；用保存回放完成描述分析 |
| `prism-style-bands-v020.policy.json`固定Balance v0.2.0；M75匹配参照是父代v0.2.3，没有v0.2.0作为被测参照的同网格结果 | 无法直接用旧固定基线分类政策认定M75路线 | 分列稳定风格锚点与本轮父代。已有父代比较只作局部描述；固定锚点缺项明确保留，新轮才预先安排所需比较 |
| `valid_observed_grid`要求所有对手共用一个seed_start/end的完整笛卡尔网格；M75是逐对手不同seed范围 | 即使补齐数值，也不能直接把M75原网格塞入旧分类输入 | 独立版本适配实际逐对手网格，保留精确对手SHA/seed/座位核验，不放松为只核对总局数 |
| 当前注册表登记正式版本，M75结果仍published=false；发布的Balance家族与行为待定并存 | 版本名容易被当作风格确认，未发布候选缺少统一浏览入口 | 候选按轮次/checkpoint/SHA登记，血缘、行为、竞技、用途、发布部署独立显示；候选登记不分配正式版本号 |
| 共同池1个基线截断使整个冻结配对门缺项；`training_seed_summary.count`取的是可计算共同增益条数，当前为0 | 运行完成、统计完整性和实际训练seed数容易混淆 | 下一schema分开实际训练seed数/有效端点数；科学门与运行完成分栏。未来采样前制定截断率、缺失结果敏感性/上下界政策，旧门保持INCOMPLETE |
| r3静态分工造成等待、r4–r9多次接续与顺序适配；已有持久启动/完成账本/预算保留 | 通用流程维护成本上升，但已有恢复能力值得保留 | 将验证过的阶段接续与产物交付契约逐步共用；计入采样、更新、审计、传输、等待的分段时钟，先处理实测最长瓶颈 |

`prism_style_history.py`已经能汇总已有bigcard/building字段，说明应优先接通现成能力；不能把“当前报告缺测”扩大成“全仓库从未实现过相关测量”。分类阈值仍是描述性工程政策。事后补齐M75回放指标可以改善画像，不能追认成采样前冻结的风格确认。

**M75目前怎样归档和解释。** 稳定候选身份为 `M75/c20@eaa1331b…62bf5`；父代为Balance v0.2.3；训练目标为无附加风格奖励的竞技训练；用途建议为下一段主线训练父候选/后续评测候选；直接增强PASS、共同门INCOMPLETE、发布UNPUBLISHED、默认/部署未执行。行为路线仍undetermined，可以附“相对父代购牌向大牌移动”的描述，不自动改名为Alpha或Balance新版本。

本次从已交付聚合结果重新计算一个**事后描述子集**：排除唯一基线有截断的整个Beta对手，留下Heuristic、General、Balance v0.1.0、Alpha v0.1.4、Alpha v0.1.5；双方各5×512=2560局。沿用原网格审计回执，本次未重新逐局审核。这个子集不替代原六对手门，也不用于风格确认。

| 描述指标（模型本人） | 父代Balance v0.2.3 | M75 c20 | 候选减父代 |
| --- | --- | --- | --- |
| 0–1VP购牌/局 | 7.2090 | 6.6391 | −0.5699 |
| 0–1VP占全部购牌 | 63.8802% | 61.4639% | −2.4163pp |
| 3–5VP牌印刷分/局 | 8.0977 | 8.5934 | +0.4957 |
| 贵族覆盖率 | 33.3984% | 27.9688% | −5.4297pp |
| VP/本人Main | 0.563988 | 0.568571 | +0.004583 |

公式：低分牌占比=Σ0–1VP购牌数/Σ全部购牌数；大牌印刷分/局=Σ(3–5VP牌数×印刷VP)/N；贵族覆盖=有贵族局数/N；VP/Main=Σ最终VP/Σ本人Main。计数由已有每对手均值×真实局数回算，购牌总量的整数一致性通过。大牌印刷分的+0.4957不应因四舍五入而冒充达到旧政策+0.5阈值；旧政策的参照也不同。差值未估新区间，方向仅描述，未推断主动偏好或奖励机制。

**推荐顺序与退出条件。**

1. 首先完成一个有限工程小轮：候选身份卡、既有回放时点/兑现指标、参照与网格适配、自动结论和缺项、原M75报告视觉待办。用M75验收：一次离线入口能生成身份/竞技/画像/路线/用途/交付状态，缺数据有明确原因；0新局，原结果hash不变。有充分描述和准确缺项即可结束，不要求本轮强制得到Alpha/Beta/Balance确认。
2. 随后继续当前主线，父候选固定M75 c20；保留已验证训练核心，先研究新增训练段的收益。保持初始化选择明确：复用当前fresh optimizer方案或选择经完整身份核验的full-state续接须在新合同说清，不混称。预算/种子/最终候选/截止尚未冻结，推荐顺序不等于启动授权。继续记录固定开发曲线与最终独立证据，不能按c15点估计回选旧候选。
3. 新路线优先处理一个具体问题：强对手覆盖改善是否以旧锚点为代价，可设计受控对手池支线；若确实要产出基建风格，再从已接通的指标出发定义Beta支线。同一轮同时换奖励、网络、对手池和优化器无法解释收益来源。当前没有支持立即把主线转向新架构的证据。
4. 事先约定重新分配研究资源的触发条件：下一有限段实际收益不足、关键锚点退步越界、或长局问题再次影响有效数据时，针对相应问题开分支；不要无限续训或追显著。跨训练seed重复用于回答方法稳定性，可在主线收益积累后单独开展，不把它当当前实用训练的唯一前置。

完整双方竞技表继续以[原M75阅读报告](prism/m75-prism-continuation-comparison.reading.md)为准。验证脚本与机器证据：`local-artifacts/prism/m75-continuation/direction-review-20261011/{review.py,evidence.json,all-pending-update.json}`。执行 `python -B .../review.py` PASS：模型及结果/配置/报告SHA、17组双方WDL/半平分、总9215终局、5对手聚合/整数计数、固定参照不匹配核验。初次脚本父目录层级错误在读取前失败，修正后通过，未触及研究执行。源码评审没有重新跑原Rust回放审计/bootstrap/模型forward；视觉仍NOT_VERIFIED。ALL context返回fetch failed，本轮未启动服务、远端控制、采样、发布、部署、提交或push。

### 2026-10-12 产物归类闭环与报告视觉收尾

本次 `task_kind=implementation/report`；授权为用户“先按你说的把产物归类流程补齐，用 M75 跑通身份、画像、路线建议和用途归档，把报告视觉验收也做完。先不启动新训练，完成后再定下一轮”，允许 `gpt-6-luna/max` 子代理协助开发。`authorized_end=一次离线入口的身份/竞技/保存回放画像/路线建议/用途归档、针对性测试、原报告独立阅读修订及桌面/窄屏像素验收、两层记录与ALL实际同步或待同步证据`。禁止新训练、补赛、模型forward、发布、默认替换、部署、研究进程/实例恢复、commit/push；下一允许动作是离线实现和核验，下一研究轮等待决定。

R0基线为 `m61-alpha-balance-ab` / HEAD `a9a0037d82b05af0c55782f6dc2c0e2e72e6f6bd`，index未stage，本工作树已有M75/M78及Replay Studio改动，未混合提交。工程预算0新局；分析只读取已完成独立评测，不取训练/开发全历史。R1新研究、R3–R6新采样为NOT_APPLICABLE（实施/报告任务）；R2与R7/R8适用，检查完成后在本节续记最终结果。原M75正式门不改。

实现计划：[离线HTML](prism/m75-artifact-workflow-plan.packed.html)，用户已授权实现，0新增决策；中文语法检查产生的英文句子启发式提示为advisory，不是页面验证结论。统一入口 `python -B -m scripts.prism_candidate_archive --spec benchmarks/reports/m75-candidate-archive.json`；候选卡按轮次/c20/SHA登记，正式版本注册表不增加条目。输入spec绑定权重、父代、训练审计、candidate-registry、原result/config、固定风格政策及保存回放清单；逐对手seed范围、实际greedy命令/权重、网格/座位与WDL在画像前核验。

保存证据只读取回回执：`local-artifacts/prism/m75-continuation/artifact-workflow-r1/transfer-receipt.json`，37,585成员、291,550,537原字节、37,378,027传输字节；manifest SHA `18caec3a5b492fa1a88a29a2b8c2d448ee3e242bf0fd61c16939dfd550056f32`。9,216计划身份、9,215正常终局及双方座位WDL复算PASS。唯一缺项 基线Beta、seed 13014181、后手 为原PLY_CAP_TRUNCATED；不虚构终局/平局。保存回放的离线Rust重放仅为规则审计与画像投影，没有启动agent或研究局。

阅读修订保留原HTML/MD/receipt与冻结生成器，通过独立 `scripts/prism_candidate_reading.py` 生成 [r4阅读报告](prism/m75-prism-continuation-comparison-r4.html)。原画像误写“每代3071局”，实际父3071/候选3072；新匹配画像为五完整共同对手、各2560局，明确事后子集/排除Beta，不替换原六对手门。Markdown保留17组完整双方表，Beta跨代差值改为配对不完整。窄屏座位表加最小滚动宽度。原曲线390px视口整页宽461px的真实缺陷已存证；[曲线r2](prism/m75-prism-continuation-curve-r2.html)增加局部滚动容器，原table字节不变，视口/页宽均390px。

工程失败保留：15项归档初测发现双方同为sampling仍会进入归类；修复明确both-greedy后15/15 PASS。真实回放第一轮因把外层Rust projection格式误当逐game字段失败（0新局），见 `attempt-1-failure.json`；修复与真实贯通结果在下文登记。ALL已读取context splendor，返回fetch failed；未启动服务或恢复automation，最终结果待同步。

#### 本地工程与视觉验收结果

**本地授权终点已完成。** [候选产物卡](prism/m75-candidate-card.html)统一交付身份、父代、原竞技门与缺项、保存回放画像、路线建议、用途及发布/部署状态；同名JSON保留逐对手、双方演员、两座位分母及证据SHA，Markdown便于离线阅读。候选c20与父代实际权重均重新核验；身份不分配新版本号。`scripts/prism_candidate_archive.py`为统一归档入口，`scripts/prism_replay_profile.py`复用已有Rust严格回放和building语义；本轮阅读适配器与原pin生成器分开。

完整实际贯通：9,216计划尝试身份、9,215终局、18,430双方演员画像、17组双方WDL/座位及本人Main/0–5VP实际购牌总数均PASS。Rust按64局批次严格重放，不调用策略forward、不派研究局。每个回放绑定SHA/seed/座位/动作；projector执行离线增量构建，回执记录二进制、Rust example、Cargo.lock、卡牌目录与building来源。完整画像验证回执为 `artifact-workflow-r1/replay-profile-verification.json`；归档receipt绑定输入及输出。固定风格参照未测，不用父代替代Balance v0.2.0，不将事后描述升级为确认。

五个完整共同对手的双方各2,560局，新增时点/兑现如下；整个Beta仍排除于这个描述子集，原六对手竞技门保持INCOMPLETE。

| 事后描述指标 | 父代Balance v0.2.3 | M75 c20 | 候选减父代 |
| --- | ---: | ---: | ---: |
| 首次4–5VP实际购入条件时点（本人Main） | 20.0690 | 19.4816 | −0.5874 |
| 首次大牌时点有值局数/全部局数 | 2129/2560 | 2207/2560 | 覆盖+3.0469pp |
| 前12本人Main的0–1VP购牌（张/局） | 3.7012 | 3.4094 | −0.2918 |
| 前24本人Main中早期投资真实折扣兑现（单位/局） | 10.2371 | 9.3020 | −0.9352 |
| 实际走到24Main兑现窗口的局数覆盖 | 95.7031% | 94.0234% | −1.6797pp |

Main只计本人主要动作，贵族选择不新增Main；reserve不当成购买。早期投资为前12Main购买的0–1VP牌；兑现是截至24Main后续真实购买中可归属的折扣贡献，沿用每投资3/每局24单位上限。终局停止窗口，保留短局截尾及兑现未观察完的投资分母；首次大牌均值仅对已实际买入局计算。这些变化支持“相对父代向大牌购入移动”的描述，未做新区间或合法机会/机制因果推断，**路线仍undetermined/INSUFFICIENT，父代比较为DESCRIPTIVE**。建议用途：下一段主线的父候选、后续评测候选、行为研究；下一轮须另外冻结有限合同，未发布/未默认替换/未部署。

针对性测试最终 **20/20 PASS、0 skip**（真实M75四局保存回放集成包含在内）：SHA漂移拒绝、重复/缺失网格、逐对手种子范围、both-greedy约束、固定参照缺失/冲突路线、归档不发布、早期投资封顶、短局、贵族Main、预留/购牌与Rust外层格式。增加双方购牌/Main复核后，合成测试fixture缺少opponent_metrics导致1项失败；补齐fixture后全通过，真实完整入口已通过同一复核。

视觉验收 **PASS**：报告r4、曲线r2与候选卡分别检查1440×1000桌面、390×1000窄屏的真实渲染像素；结论导航、模型/对手选择、展开先后手和逐对手画像实际操作通过。父代Beta显示511局及先/后手256/255，整页无横向溢出，宽表局部滚动，控制台0 error。截图与页面SHA绑定于 `local-artifacts/prism/m75-continuation/artifact-workflow-r1/visual-receipt.json`。部分浏览器截屏因视口/表面尺寸不一致出现捕获伪影，改用当前独立页面的实际viewport截图后验收，未把伪影当作页面PASS。原报告/曲线与科学结果字节保持；本轮r2/r3中间修订和原生成receipt保留，最后像素证据独立附加到r4及候选receipt。

收口证据：`local-artifacts/prism/m75-continuation/artifact-workflow-r1/closeout.json`；324个实际工作树Rust/Python/模板来源文件保存为SHA绑定 `delivery-source.zip`，未用HEAD冒充脏来源。结果/父权重/输入/页面/截图及9条交付链接复核PASS，报告payload的17组原pair逐字段不变。重新生成归档默认标视觉PENDING；已有像素结论只能经同页面SHA绑定后附加，不能沿用到改变后的页面。

R0/PASS；R1新研究、R3–R6新采样/NOT_APPLICABLE（本任务只实现并分析已有数据）；R2工程/PASS，R5已有输入身份审计/PASS，R7分析/PASS（路线证据不足如实交付），R8本地报告与视觉/PASS。R9本地记录/索引/产物检查完成，**ALL外部登记仍PENDING**：末次context splendor仍fetch failed，revision UNKNOWN，未虚构task ID/revision或启动服务，`all-pending-update.json`保存待同步摘要。原M75共同门缺项和模型未晋级保持；本次工程终点已达，下一允许动作为审阅产物、决定下一有限轮。本次0新训练/评测/forward，无发布/部署/恢复研究/commit/push。
