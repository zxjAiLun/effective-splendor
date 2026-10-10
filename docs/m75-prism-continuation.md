# M75 · Balance v0.2.3 后继长程训练

状态：RUNNING / R4训练中。日期：2026-10-10。基线分支 `m61-alpha-balance-ab`，HEAD `e0018fd58fb973253d16000d59bf1b1aae62046a`；工作树含其他未提交改动，实际执行以独立源码快照为准。

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
