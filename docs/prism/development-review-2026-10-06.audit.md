# Prism 当前研发评审：Agent 证据记录

Status: REVIEWED（只读项目评审，不是新模型评测轮；改进未实施）。
Baseline: `m61-alpha-balance-ab@9899749188f35c838c85c5b3530049bd5dcbd105`。评审对象为带既有修改的工作树，不把 HEAD 当作完整运行源码。
Owner/date: 2026-10-06，用户请求评价大规模 PPO、多风格路线与按实战表现归类流程。

[人类阅读报告](development-review-2026-10-06.md) / [HTML](development-review-2026-10-06.html)。当前轮次日志追加在 [M67](../m67-prism-alpha-repeat.md)；本地 `handoff.md` 保持 ignored。

## Scope and non-goals

核对 M67、M61–M66 已有结论、Prism 模型与训练/评测/报告代码。只运行零研究对局检查和只读状态查询。没有启动、暂停、恢复训练，没有改门/种子/预算/权重，没有注册模型或提交推送。新增评审报告、证据及导航记录，不重新生成原模型报告。

## Review method and strengths

主代理检查模型结构、竞技统计、风格/发布合同、报告恢复与运行状态；一个有界只读 explorer 调查 PPO 存储/采集链，返回后由主代理核实具体源码。没有第二轮泛化评审。

保留的优点：规则与玩家信息边界、实体/动作置换语义、精确导出与数值校验、冻结行为策略、完整 optimizer/RNG 恢复、尝试账本、单写者、固定最终 c20、双座配对、两训练种子分报、四项同时竞争检验、原失败记录保留、研究版本发布与默认冠军分离。不能因为有工程瓶颈就否定这些保障。

## Findings（按优先级；都不是已实施改动）

### F1 / P1：账本与容量检查的扩展复杂度不适合继续直接放量

**确认源码：**

- `training/prism_portable/engine/ppo/arena.py:62–75`：`record()` deepcopy 全量 state，保留所有 `attempts`，每个状态变化再次 commit；`:163–173` 已可见同局启动前后两次，后续生命周期还有记录。
- `training/prism_portable/engine/ppo/store.py:116–119`：每次 `torch.save(payload)` 序列化整个 payload。
- `scripts/prism_m67_storage.py:14–28,40–50`：只在 Torch ZIP `/data/` 张量边界切块；无张量的 Python 字典元数据不能享受 tensor body 去重，改变后成为新的大块。
- `arena.py:145` 每局前 `directory_bytes(self.root)`；`training/prism_portable/processes.py:13–21` 全目录 rglob/stat；`scripts/prism_dsw_ppo_process.py:85–103` wait 启动/间隔/退出再做容量检查。

**静态推导：**若每局记录大小有界，第 i 局的全量历史 payload 长度按 i 增长。累计复制/序列化工作量为 ΣO(i)，即二次级；压缩可降常数，不使原始序列化变为增量。压缩后实际磁盘字节比例仍需实测，不能严格宣称任意输入的压缩字节必为 Θ(N²)。目录对象随运行增加，全树扫描也不是常数开销。

**历史测量而非本轮 profiling：**`local-artifacts/prism/m67-alpha-repeat/failure-summary.json:10–100` 保存 c1 418.09 秒、c15 2798.29 秒导出间隔。`docs/m67-prism-alpha-repeat.md` 保留4007局附近15.92GiB/16GiB的R1容量失败。间隔包含多种开销，不能从它计算纯采集速度、每个函数占比或确定主因。

**最小后续方案：**追加事件/每局不可变对象 + 周期快照/引用；写入时增量容量记账 + 启动与周期边界全量核对。保留 pre-spawn 尝试登记、失败记录、预算和单写者，不简单删掉安全提交。用不同历史长度的合成记录验证新增字节/序列化/目录扫描次数，并做断电/崩溃边界与原字节重建测试。扩量前以阶段实测给 ETA。

### F2 / P1：串行采集与 singleton 学习器限制吞吐

`arena.py:259–266` 顺序 launch，`:169–175` 阻塞 wait；一次仅一局采集。`learner.py:140–143,184–210` 逐条前向/反向后积累梯度，minibatch256不是256状态的张量批处理。

这是明示的确定性/内存取舍，不是 PPO 算法错误。并发为1也不等于整条流水线只用一个CPU核；行为服务、对手和 Torch 内部线程仍可用额外核。本轮不采纳子调查中“多核完全未利用”或由c1总耗时推导纯游戏下界的说法。

后续在 F1 后测试有界并行局/固定微批。维持行为快照、job/seat RNG、固定提交顺序、单writer及内存上限；比较1路和多路的动作/批次/恢复身份。微批形状改变会改变浮点计算，必须预先定义等价容差并绑定新数值运行身份，不能热替换 M67。

### F3 / P1：执行、观察与文档状态脱节

**本次测量：**19:22 +08，SSH读取的R2 PID849099/create_time1791255161.13匹配且存活，phase=train-b。A审计回执PASS、5120局/c20/1065已应用更新，B3076局/c13/652更新。A `live-progress` 仍COLLECTING/RUNNING且只有1011更新，不能优先于最终审计。A权重SHA `db3e2da279d777485c4dbb3d8d2ff78ddb106d231d5c75b58bc783e4fb66acb5`。

原本机观察器PID33772本次CIM查询不存在，原因NOT_INVESTIGATED。ALL读取时最新M67心跳16:03，明确stale；不能用本次查询冒充恢复了连续心跳。`scripts/prism_m67_monitor_r2.py:43–60` 将SSH观察、ALL上传与完成取回串在一个try块；上传反复失败也会使观察器退出。`scripts/prism_m67_monitor.py:66–121` 的归档与抓取不是可断点幂等完成流程。

建议远端完成回执、观察新鲜度、交付完成分状态；ALL上传失败进入独立重试/outbox，不阻塞本地状态观察。只读观察可恢复，研究进程不得随观察重试被重启。每条状态带时间、execution身份及来源优先级。此次未恢复监控，不保证自动取回。

### F4 / P1：报告部分失败后缺少整轮恢复入口（已复现）

`prism_m67_report.py:237–239` 任何一个输出存在即拒绝；`:311–344` 先发布aggregate result/evidence，再逐臂调用阅读器。若阅读器失败，比赛结果存在而页面不完整，重新运行同一构建入口只得到already exists。

零对局故障注入复用 `scripts/tests/test_prism_m67_report.py` 的合成fixture，仅把reader.build变为RuntimeError。确实留下5项输出，随后常规重跑拒绝，原输出字节不变。现有 `test_full_common_reader_two_pages_no_mutation_or_overwrite` 验证完整成功和禁止覆盖，但没有解决中途失败恢复。

最小方案：统计结果不可变，渲染可重复；基于结果哈希验证并只补缺页，或stage整个报告包并最后发布完成清单。补每个发布点故障注入和resume测试。当前正式M67尚未进入此阶段；本条是潜在交付缺口，不是宣称远端报告已失败。修复需独立执行/报告修订，不能删除已有结果或重赛。

### F5 / P2：现有竞技门是固定池平均值结论，不是普适冠军证明

`prism_m67_report.py:86–105` 正确地按共同seed聚合六对手差值；四检验family α=.05、下界分位.0125、20000次bootstrap。`checked_blocks`及`verify_identity`拒绝缺座、身份和模式漂移。不是统计实现错误。

零对局合成反例中，某对手−50pp、其余五对手+50pp，直接父代全胜，两臂仍通过全部四项增强。原门没有承诺防止这种补偿，因此它是**结论范围与后续发布判定的缺口**，不能改写原门为FAIL。

训练调度实算：Prism v0.1.1 2560局、Prism Alpha v0.1.5 1280局、Prism Alpha v0.1.4 640局、Prism Beta v0.1.0 640局。评测虽然有新环境seed及另外的对手，主体仍是同家族和已知锚点。未确认过拟合，只说明训练外泛化覆盖有限。

两个训练seed与110000评测物理局回答不同不确定性。后续采用预先固定的最小有意义增益/功效、更多训练seed的开发探索、冻结少量候选后的独立验收。默认冠军可增加少量关键对手的退步容忍门或最差对手风险审阅，数量/阈值先冻结；不要求所有指标提升。风格版本允许明确代价。保持训练采样和both-greedy发布证据独立。

### F6 / P2：风格归类仍偏人工文案，比较参照未系统化

`benchmarks/m65-prism-beta-v0.1.0.model.json:5–6` 同时保留route=beta与observed_route=mixed/scoring-leaning，诚实但语义不同。`docs/prism-practical-promotion-contract.md:51–73` 保留M63从暂定Balance到Alpha再发布的历史。`prism_m67_report.py:200–225` 主要画像比较是相对Alpha父代，未测首张大牌时点，未给统一风格置信度；不能仅凭该比较授予Beta。

建议版本化profile schema：weight hash、lineage、training objective、matched reference、mode/cohort、各指标估计/区间、primary/secondary route、confidence、reason/evidence、registration/default资格。允许mixed/undetermined，不自动将非Alpha/Beta设为“已证实Balance”。竞技门保持独立，不能看完结果后追改style原门。

保存状态的机会条件诊断用于区分“没机会买”和“主动不买”。M62已有诊断资产可复用，但历史512状态仅8状态可购≥2VP牌，属于覆盖限制，不把它当总体小牌偏好证据。当前没有发现消费者实际误用route的已发生事故，本条为设计改进，不虚构应用故障。

### F7 / P2：可追溯性有哈希，但版本收口与当前状态导航负担较重

当前45个tracked修改保留；`git ls-files --error-unmatch training/prism/model.py scripts/prism_m67_report.py docs/m67-prism-alpha-repeat.md` exit1，三路径尚未跟踪。HEAD不是它们的完整源码快照；运行来源哈希/归档有价值，不能反推缺少所有备份。建议按 coherent round 保存/提交可构建源码包与锁定依赖，不合并提交 unrelated dirty 工作。

handoff约650KB/3642行（评审前），当前与大量历史快照并存，ALL中存在源标题和实际run的不同状态。建议紧凑current-state JSON/索引与完整历史分层，当前状态由原回执派生，保留历史而非继续堆同级“当前”标题。本次只追加本轮更正，没有重构全文。

## Rejected objection / numerical clarification

只读子调查提到“GAE λ=.95而critic拟合终局BCE造成数学目标脱节”。主代理不采纳为缺陷。`docs/m54-prism-continuous-ppo-design.md:118,129,143–148` 明确γ=1、sigmoid value表示期望半平得分，BCE拟合真实终局，GAE仅用于策略信用分配；二者是合法设计组合。不得把可能越界的GAE target直接塞入BCE。MC方差、校准或共享梯度冲突可以诊断，但目前没有本轮失败证据。本轮也不采纳未经实测的“更新占几十秒”“单核完全闲置”“并行必加速3–4倍”。

## Validation and evidence

本地证据根：`local-artifacts/prism/development-review-2026-10-06/`。源码哈希、对手计数和反例详情：`review-checks.json`；可复跑证据脚本`review_checks.py`；只读SSH快照`remote-observation.json`；CIM观察器查询`local-observer-check.json`。临时fixture在session scratch，无正式新对局。

| 本次实际命令/检查 | 结果与范围 |
| --- | --- |
| `C:\Python312\python.exe -B -m unittest scripts.tests.test_prism_m67 scripts.tests.test_prism_m67_report scripts.tests.test_prism_m67_resume scripts.tests.test_prism_m67_resume_r2 scripts.tests.test_prism_model_release scripts.tests.test_prism_round_report -q` | exit0，36 tests；日志`prism-review-tests.log` |
| `C:\Python312\python.exe -B -m pytest training/prism/tests/test_model.py -q -p no:cacheprovider` | exit0，11 passed；日志`prism-model-review-tests.log` |
| scratch `prism_review_checks.py` | exit0；报告故障与池均值反例均满足预期断言，0研究局 |
| scratch `prism_review_observe.py` | exit0；SSH原回执与进程身份快照。读取审计不等于本轮重跑原始审计 |
| `git diff --check` | 独立进程exit0；已有LF/CRLF提醒，不修改用户文件修复换行 |
| `git check-ignore -v handoff.md` | 命中`.gitignore:12:/handoff.md`；未stage/commit/push |
| `am render … --no-open` | 页面生成exit0，8 panels/1 flow，STE 0 warnings（最终回执另保存） |
| BrowserPreview / Browser | 初始guest不可用；navigate后读取到标题/8段/链接，但innerWidth=0，设备尺寸CDP不允许。不能宣称实际像素或窄屏布局通过 |

两条辅助命令失败已恢复：`am help render`不支持，改查`--help`后正常渲染；混合Git shell调用exit1由未跟踪路径查询产生，独立diff-check明确exit0。文案编辑定位错误在重新Read后纠正；一次Edit因未显示行被拒绝，按完整reveal重试成功。未触碰运行源码。

## Decision and limitations

支持保留Prism架构与实战优先/事后画像路线，但不将宽松归类等同宽松证据。P1先处理可扩展存储、采集/学习吞吐、观察独立性和报告恢复；P2提高训练seed/对手覆盖、风格画像和版本收口效率。建议是PROPOSED，未实施，不能代表用户授权新训练。

M67仍按原合同继续，B、独立竞技及最终交付待完成。本轮未重新跑Rust全构建、历史全回放、全部bootstrap或函数级profiling；没有新棋力/风格验收和晋级。真实像素验收未完成。评审任务本身可完成，不把M67研究任务标done。
