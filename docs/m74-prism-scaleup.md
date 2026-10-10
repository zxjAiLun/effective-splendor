# M74 实用长程训练与强对手池迭代

2026-10-10版本登记已完成：task_kind=release；用户授权“相对应的更新(unpublished)版本的版本号”。authorized_end为报告中M73 B父代与M74最终模型的固定研究版本登记、精确权重/companion/父代绑定及显示更新。沿既有Balance研究分支顺延为v0.2.2/v0.2.3；observed_route保持undetermined，不将命名升级为均衡风格确认。0新局/训练、默认冠军/部署/Git推送；四项权重/父代/最终周期/重复版本漂移拒绝检查PASS，发布前零输出。完成记录见文末。

状态：远端执行COMPLETED；两项主要竞技增强确认；全覆盖INCOMPLETE，实验review；2026-10-10结果取回及阅读修订已验证。源码工作树基线 `e0018fd58fb973253d16000d59bf1b1aae62046a`，新增执行源包单独绑定，不把脏 HEAD 当完整来源。

当前入口：[Prism Balance v0.2.3最终结果](prism/m74-prism-scaleup-comparison-r4.html)。5120训练局、20周期、1100更新；共同池半平66.98%→71.48%（+4.51pp），直接父代56.79%，两项主要增强门与保留门均通过。最新Alpha一局截断，完整覆盖未完成；主要网格完整，上述结论有效。c20已按本次授权登记为Prism Balance v0.2.3，直接父代为v0.2.2。下方准备/启动章节保留历史状态，当前阶段以末尾结果记录为准。

## 问题与授权边界

用户要求把闲置DSW用于持续迭代、增加数据和训练量，目标是更快得到强模型。优先级修订：不同训练seed是否复现不再作为这一轮启动前置条件。task_kind=experiment；授权终点为一条5120局/20周期训练轨迹、最终产物审计、9216局固定greedy评测及报告。禁止无限循环、覆盖旧合同/结果、发布或部署、Git提交推送。

## 冻结合同与输入

父代为M73 seed B final c4，SHA256 `15e14e118e8dd5eb45d199e643c185a382ae5d67a503d446d27eaf575de8bed5`，旧共同池描述增益约+1.97pp、直接父代半平53.32%。本轮加载精确权重，fresh AdamW/RNG warm-start，不冒充完整状态resume。PPO数值配置不变，新增5120局是前一短臂的五倍；每周期256局并保存导出。训练池General、父代M73 B、Alpha v0.2.0、Balance v0.2.1各25%。这是同时改变父代、长度与对手池的实用迭代，不归因于单因素，也不证明架构绝对上限。

合同：[config](../benchmarks/m74-prism-scaleup.config.json)，[训练计划](../benchmarks/m74-prism-scaleup-a.train.json)。训练环境seed12001000–12003559，run seed74010001；独立评测seed及256/512双座样本另行固定，已有登记区间重叠检查PASS。唯一最终候选c20，不按独立结果改选。双方greedy：父代和候选各6个共同对手3072局、各2个最新对手1024局，候选直接父代1024局，合计9216。主要统计保留/增强门、两端点单侧校正、20k配对bootstrap见JSON；风格仅描述，必要时点/兑现缺项不得填0。

## 工程与资源

使用已验证的CPU数值内核、Rust二进制和可重建原字节的存储适配器；保留M67同规模与M73 Linux已有工程证据，不重复正式采样充当调试。启动前新权重68固定输入parity、实际依赖/4核分配/源码与资产SHA、完整20周期计划与容量检查必须PASS。

M67同规模曾因16GiB单臂上限中止，5120局历史预计约26.03GiB。本轮Run/单局/外层训练统一32GiB；全目录36GiB，整盘预留8GiB，启动最少44GiB空闲。新鲜DSW初查49.24GiB空闲、没有Prism运行进程。训练18h/150000CPU秒，总轮24h/220000CPU秒，RSS软限8GiB，研究自动重试0。绝对截止以真实启动回执为准；不会复活旧deadline。

匹配历史给出训练8–14h、后续审计评测约1–3h的初始预计；实际每周期时钟用于修订估计。不是保证时间，最长预算不是预计耗时。新目录 `/mnt/workspace/splendor-m74-scaleup-r1`，旧M73目录不修改。

## 阶段与交付

R0/R1 PASS（用户本次授权与新有限合同）；R2已有内核/存储工程证据复用，新计划回归检查待记录；R3零局预检待执行；R4待启动；R5–R8 NOT_RUN，候选/棋力/路线尚无新结论；R9 IN_PROGRESS。自动管线为训练→只读审计→冻结c20→完整固定评测→共同阅读报告。每周期导出与账本保留；任何有效负结果仍报告。新报告使用既有阅读布局，像素后续取回时核验，不以远端生成当视觉PASS。

ALL当前不可达，保留待同步更新，不因仪表板不可达阻挡已经授权的DSW训练，也不启动仪表板服务。后台有限执行独立于本机会话；本轮没有新增持续ALL观察器或定时自动取回。

## 执行与验证追加

准备与实际启动回执、PID/create_time/源码绑定、首批采样和ETA修订在启动后追加；文件存在不代替实际运行。


### 2026-10-09 实际启动

DSW已于2026-10-09T18:19:43.110000+08:00启动，PID31080/create_time1791541183.11，execution SHA `337cf1fbe63f06588a6de4127ecd5ca9303ec9112d0836d6d452046d57edab36`；config SHA `1de09e34acf716413294eabd7f14388c143e0fae3e359b2b19cb4d2068221084`。2026-10-09T18:20:59.398523+08:00一发只读回查确认PID、命令、cwd、来源绑定全部匹配，训练完成80/5120局，cycle1 COLLECTING/global_step0，尚无研究更新提交证明。后台阶段自动推进；总轮绝对截止2026-10-10T18:19:43.700079+08:00，没有重置旧轮预算。

本地与DSW各7项合同回归检查PASS；68输入Rust/Python parity PASS（最大误差小于1e-4）；329旧来源逐SHA复制、8覆盖文件验证、父代32张量初始化/空optimizer验证PASS。实际训练写入进行中，R2/R3 PASS、R4 IN_PROGRESS，R5–R8未执行；任务progress，模型未评定/未发布。首批约1局/秒只作运行证据，不据此忽略历史存储/扫描增长缩短ETA。

真实回执在`local-artifacts/prism/m74-scaleup/`，来源、预检、启动、截止和运行观察均已取回。ALL本次再读fetch failed，待同步更新已保存，未声称已同步。预计训练8–14h、审计评测1–3h；推荐2026-10-10 10:00+08沟通，若届时尚未完成，按真实周期/时钟更新ETA。没有持续本地观察器或自动取回承诺。

后续只读回查：18:24:14+08实际已采256/5120局，进入首周期更新准备，global_step尚未在进度中提交；PID/来源和实际子进程资源仍RUNNING，无停止原因。运行快照running-readback-1791541454.json独立保存，不覆盖18:20:59的80局观察。337份实际执行源码/输入全部已用本机旧源快照+新overlay+精确父代重建逐SHA核验PASS，见source-readback-verification.json。


### 2026-10-09 23:55:38+08 只读进度

用户问进度，task_kind=status；终点为核对当前身份/采样/周期/资源和ETA，没有新训练授权或控制动作。DSW同PID31080/create_time1791541183.11、argv/cwd/execution SHA一致，RUNNING/无stop reason；实际3467/5120（67.71%），13周期已提交/导出、第14周期采集中，712次optimizer更新，已用5.60h。13个portable周期时钟和导出存在逐个读取；最近3周期约35.64/38.73/41.66min，按最近5个相邻周期增长中位数推算训练剩余约5.85h，预计10-10 06:00–07:00训练完成、08:00–10:00审计评测/报告。当前磁盘空闲35.00GiB，CPU与RSS未触发停止。最终c20审计与greedy评测尚未开始，不能判断棋力增益。

证据status-readback-1791561338.json及eta-update-20261009-2355.json；ALL本次再读fetch failed，真实时间待同步，不启动服务；既有后台管线与预算不变。此次status取回完成，M74实验仍progress。

### 2026-10-10 结果取回、独立复算与阅读r3

本次task_kind=status/report，授权来源为用户“看看结果”；authorized_end为既有结果/权重/账本取回、身份与统计核验、必要阅读修订及交付。0新局、0新更新；没有恢复、清锁、补赛、延长deadline、发布、部署、Git提交或推送。原执行根目录与冻结科学合同未修改。

同execution完成回执确认训练于05:52:16+08结束，最终c20为5120局/20周期/1100已提交optimizer更新，管线于06:46:44+08完成；训练约11小时32分，全轮约12小时27分。14:30:16+08只读运行核验没有属于本执行根目录的活动进程，磁盘空闲25.07GiB。完成判断来自执行SHA绑定回执，不沿用嵌套资源缓存的RUNNING字段；control/a/completion.json顶层1046更新尝试是旧缓存，最终提交state、导出与completion对象均为1100。

| 对象 | 核验身份 |
| --- | --- |
| execution SHA256 | `337cf1fbe63f06588a6de4127ecd5ca9303ec9112d0836d6d452046d57edab36` |
| config SHA256 | `1de09e34acf716413294eabd7f14388c143e0fae3e359b2b19cb4d2068221084` |
| M74 final c20 SHA256 | `e16bfe0d30168d6ef7ceb067ca4357900f1c09e09d35f5759832dd3d6a9258ad` |
| 原result SHA256 | `aa141cf1840f4f4b594836472d3ebacd687072459be829787d799c208fd40eb6` |
| 最终state commit | `36591a18c6184369ce71010d703f087685c48c87ba0a301f28fa20a0fbd13534` |
| 取回ZIP SHA256 | `7e52192883af7ea48860a16b36cd5725ee63ee445dc3ec2b3db34aeaf7c0c1e7` |

R5：全部5120训练保存回放通过原Rust批审计，32导出张量与完整state一致、32optimizer槽有效，68固定输入parity通过（atol/rtol各1e-4，最大绝对误差约1.10249e-4）。337份执行来源逐SHA核验；9216尝试绑定的82944份原文件在DSW只读SHA核验；1249取回成员的ZIP CRC/传输SHA与本机复核通过。

R6：9216次物理尝试中9215正常终局、1局PLY_CAP_TRUNCATED；截断在a-latest-alpha-12020032分片、512 ply，前缀和原字节保留，没有计作平局。六共同对手父代/候选各3072局及直接父代1024局，主要网格7168局完整。最新覆盖2047/2048，全网格INCOMPLETE。原20k配对bootstrap（RNG74029999、lower_quantile 0.025、两主要端点family）在本机独立复算一致：

| 冻结主要指标 | 点估计 | 95%区间 | 原门结论 |
| --- | --- | --- | --- |
| 六共同池相对父代增益 | +4.5085pp | +2.4089～+6.5755pp | 保留PASS / 增强PASS |
| 直接父代半平得分 | 56.7871% | 53.9063%～59.7168% | 保留PASS / 增强PASS |

共同池绝对半平66.9759%→71.4844%；直接父代577胜9平438负。六对手五个改善：Alpha0.1.4 +5.27pp、Balance0.1.0 +4.49pp、Beta0.1.0 +5.47pp、General +5.96pp、Heuristic −0.88pp、Alpha0.1.5 +6.74pp。对最新Balance v0.2.1半平52.1484%，相对父代匹配增益+4.6875pp（−0.8789～+10.2539pp），覆盖保留PASS、增强未确认；对最新Alpha v0.2.0已完成511局半平52.7397%，配对覆盖INCOMPLETE，不计算完整匹配增益或声称确认胜出。

R7：匹配六共同对手/双方greedy/seed cohort，每模型3072局。低VP购牌占比65.99%→63.91%，大牌印刷分/局7.726→8.006，贵族覆盖38.18%→33.92%，VP/Main 0.55715→0.56215。描述性购牌向大牌移动，同时贵族覆盖下降；首张大牌时点/固定Main得分/真实投资兑现NOT_MEASURED，路线undetermined、证据等级INSUFFICIENT。血缘、竞技增强与发布身份分开，不改已有Alpha/Balance版本。

R8：原冻结报告不变。r2为保留的阅读草稿；r3用独立`scripts/prism_m74_reading.py`适配器，经`scripts/prism_round_report.py --spec benchmarks/reports/m74-reading-r3.json`生成，绑定原result/config/完整Markdown SHA。修复通用模板把最新对手混入共同画像、截断显示null及父代区间与冻结统计不一致；主要统计与原始pairs不变。17组双方WDL/半平显示核对PASS，先后手展开有效；桌面1440×1000与窄屏390×1000实际像素检查PASS，文档宽度1425/375，无页面横向溢出。完整双方Markdown、审计页、训练表与原报告保留。

当前阶段：R0–R5 PASS；R6主要网格PASS/最新Alpha覆盖INCOMPLETE；R7分析PASS、风格证据INSUFFICIENT；R8 PASS；R9实验review（覆盖缺1及ALL待同步）。本次status/report取回范围完成。证据根`local-artifacts/prism/m74-scaleup/result-check-20261010/`含harvest、result-verification.json、style-profile.json、report-verification-r3.json、final-operational-readback.json和截图。ALL读取仍fetch failed，完成事实与证据保存到all-pending-update.json，未启动服务或声称已同步。

实际决策：长程强池迭代得到比M73 B更强的候选，当前没有平台证据。下一建议从精确M74 c20继续增加训练量，以阶段棋力曲线安排长度；多因素同时变化不能归因给某一项。下一轮须有新的有限授权/合同，本次只读取回不自动开跑。研究版本未登记、默认冠军及部署未执行；主要增强确认不覆盖最新Alpha缺项。实验review，本次结果查看与阅读修订完成。

### 2026-10-10 固定型号登记完成

M73 B-c4 → Prism Balance v0.2.2；M74 c20 → Prism Balance v0.2.3。两份32张量权重逐SHA、派生companion、最终周期/初始化父代/原audit及registry/result/config绑定验证通过；发布前四项漂移拒绝与零输出检查通过。发布过程在写完两份精确记录后，因相对spec路径未解析导致registry追加未执行；已保留该事实，逐项核验记录/权重/manifest/所有输入后完成registry，没有重写模型或原结果；发布器在任何写入前解析路径，修订绑定在回执。

阅读r4通过公共报告入口生成，仅改身份与发布说明；两轮全部数字payload与r3逐项相等，原统计/报告/缺项不改。固定版本目录、报告索引、M73轮次与handoff同步。两轮桌面/窄屏检查及B/A/C选择器状态见release-validation.json。发布R0/R5/R6/R7既有证据检查/R8 PASS，版本登记完成；M74实验全覆盖仍review，默认冠军/部署未执行。ALL当前fetch failed，另存待同步发布任务，不改实验缺项。0新局/训练/提交/push；下一允许动作是使用精确固定型号做已授权范围内评审，训练仍须新有限合同。
