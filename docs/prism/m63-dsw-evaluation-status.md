# M63 DSW正式评测进度

**当前研发口径 2026-10-05T15:31:18+08:00：**实战优先。该c4对父及三个共同锚点有正向表现，暂纳入下一代Balance路线候选晋级评审；下方“未接受基建候选”仅为旧研究合同，不是模型整体不可晋级。[当前报告](m63-prism-beta-timed-building-evaluation.html)。


**最新核验 2026-10-05T13:37:55+08:00：连接已恢复，结果已取回。10304局及报告于03:14:58完成，0重试；Control2/2、Beta4/8，未接受基建候选。** [完整HTML报告](m63-prism-beta-timed-building-evaluation.html) / [完整Markdown](m63-prism-beta-timed-building-evaluation.md)。下列连接故障、运行进度和ETA均为历史记录。


### 2026-10-05T13:24:13+08:00 结果取回受阻：DSW SSH 隧道不可达

当前状态：**RESULT_RETRIEVAL_BLOCKED / REMOTE_RUN_STATE_UNKNOWN**。`ssh dsw` 返回255、`Connection refused`；跳板机SSH正常，但只读 `ss -ltn '( sport = :2222 or sport = :2223 )'` 没有监听行。ALL本次也显示DSW离线（最后可达2026-10-05 03:30:27北京时间）。这些连接证据不能判定比赛完成或失败；02:44:14最后已核验开发576、独立4647，共5223/10304，不代表现在的进度。

模型产物身份保持冻结；竞技与风格的最终结论**尚未取得（未读取，不等同于已证明NOT_RUN）**。历史03:20–04:00 ETA与02:37运行快照均已过时。没有重启任务、清除锁、修改十门或派发新对局，也未运行满核校准。原3workers实测141.907局/min（1000局7.047min）仅为历史比赛派发窗口，不能当作当前速度或最终报告总耗时。

恢复入口：DSW Web终端先确认实例运行，并执行既有 `/mnt/workspace/.dsw-ssh/bootstrap.sh` 恢复隧道；不改私钥、隧道配置或守护钩子。连接恢复后先读取 `/mnt/workspace/splendor-m63-dsw-r2/driver-completion.json`、`evaluation/completion.json`、`evaluation/status.json`、`reports/completion.json` 和日志；核验execution SHA与报告绑定后取回原Markdown/HTML和固定结果。若比赛已完成而报告失败，保留失败并单独处理只读报告兼容，禁止重新派发正式网格。

证据：`local-artifacts/prism/m63-dsw-r2/result-state-observation.json`、`jump-listener-result-check.json`、`all-context-result-check.json`。本次阻塞为取回通道故障，不是模型FAIL。

## 以下为历史运行快照（不是当前状态）

快照：**2026-10-05 02:37:00（北京时间）**。状态 **ACCEPTANCE_RUNNING**，后台所有权验证存活。此页面是观察快照，不自动刷新。

**产物：**Control与Prism Beta v0.1.1候选最终c4已固定、原训练审计通过；均未发布。**竞技结论：**正式评测进行中，验收判定NOT_RUN。**风格结论：**NOT_RUN，等全部固定比赛及原十门分析完成。

| 阶段 | 已完成 / 固定局数 | 含义 |
| --- | --- | --- |
| 开发评测 | **576 / 576** | 描述性；不替代独立验收 |
| 独立验收 | **3501 / 9,728** | 十门待全部网格完成后分析 |
| 合计 | **4077 / 10,304** | 0比赛重试，不重训或选新检查点 |

DSW持久化目录`/mnt/workspace/splendor-m63-dsw-r2`独立后台运行，断开本机SSH不停止计算。按首批独立验收吞吐并给统计/报告留余量，当前预计北京时间**03:20–04:00**完成；这是估计，尚非完整验收吞吐校准。DSW2由用户确认约1小时闲置自动停机，本轮使用DSW。

## 本次固定模型身份

| 身份 | 对战模式 | 权重SHA256 | 发布状态 |
| --- | --- | --- | --- |
| Prism Balance v0.1.0（父/共同起点） | T=1 | `225daf49e8746576b1edc3508ca0454715e5454529fea53dc7dfeb9043cf01f1` | 既有版本 |
| M63原目标对照c4 | T=1 | `965aa74777fc79ef6db592060fbdeac93836bbd1d47b1526efeddf7cde35a55d` | 未发布训练检查点，无版本登记 |
| Prism Beta v0.1.1 candidate | T=1 | `3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12` | 未发布候选，非已接受版本 |

## 固定网格与运行资源

| 项目 | 固定值 / 观察 |
| --- | --- |
| 开发种子 | 9656000..9656031，32双座块 |
| 验收共同锚点种子 | 9661000..9661255，256双座块 |
| 独立直对种子 | 9661000..9661511，512双座块 |
| 共同锚点 | Heuristic v0.3.1 greedy / Prism v0.1.0 greedy / Prism v0.1.1 T=1 |
| 直对 | Control对Prism Balance v0.1.0；Beta对Prism Balance v0.1.0、Control、Prism Alpha v0.1.4、冻结Prism Beta v0.1.0候选 |
| 并行 | DSW 3workers，继承3个CPU affinity；开发只有2分片，随后独立阶段使用3路 |
| 内存 / 停止预算 | 8GiB聚合RSS软限及单进程AS限额；8h / 40,000CPU-s / 32GiB；没有独占硬cgroup |
| 推理 / 决策延迟 | NOT_MEASURED / NOT_MEASURED |
| R2执行SHA256 | `aaa1d2a848c8de816c76c36efebfc190d5ef1f44521c30848bd966e7905946f0` |
| 原M63配置SHA256 | `c0d3de5398c724bd502d5c30f5f52ec06a848f7fe2672c28e1086c7730b21550`（原字节保持） |

## 当前配置的对战吞吐与待测满核速度

| 配置 | CPU / worker | 每分钟物理局数 | 1,000物理局 | 证据 |
| --- | --- | --- | --- | --- |
| 当前固定M63 R2 | 3 affinity CPU / 3 workers | **约142局** | **约7.0分钟** | 02:19:40–02:37:00实际新增2,460局，含分片启动与保存结果 |
| 全4核线性推算 | 4 CPU / 4 workers | 约189局 | 约5.3分钟 | **NOT_MEASURED**；仅142×4/3，不是满核测试 |
| 4/5/6 workers最优配置 | 4 CPU / 待比较 | NOT_MEASURED | NOT_MEASURED | 用户要求明天另做有限校准 |

DSW有效配额4核/约15.35GiB；当前主动将评测限制在3个CPU。8GiB是上限，不是实际占用：本轮对战阶段观察到的进程树RSS峰约0.22GiB，含共享页可能重复计数，最终回放统计峰值尚未测得。上表窗口排除最终全量回放统计和报告；单局process平均时钟不能直接当作campaign吞吐。明天用同模型/同对手/同seed网格比较3/4/5/6 workers，记录吞吐、CPU、RSS、失败与结果一致性，选接近最快且稳定的配置；不是把更多worker或更大内存直接当作更快。

## 十项原冻结门（尚未分析）

| 门 | 目的 | 本人指标 / 单位（得分差为百分点） | 冻结阈值 | 估计 | 普通配对95% CI | 十项同时单侧下界 | 原判定 | 失败含义 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| control/strength_pool | control参照总体保留 | 相对Prism Balance v0.1.0半平得分率差 | 校正下界 ≥ -0.05 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | 未能排除参照总体退步超过5个百分点 |
| control/direct_parent | control对父竞争力 | control对Prism Balance v0.1.0半平得分率 | 校正下界 ≥ 0.45 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | 未能确认参照对父得分率至少45% |
| beta/strength_pool | Beta总体代价控制 | Beta相对control共同锚点半平得分率差 | 校正下界 ≥ -0.05 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | 未能排除Beta相对control退步超过5个百分点 |
| beta/general_anchor | 关键通用锚点保护 | Beta相对control对Prism v0.1.1半平得分率差 | 校正下界 ≥ -0.075 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | 未能排除关键对手退步超过7.5个百分点 |
| beta/direct_control | 同轮直接竞争力 | Beta对control半平得分率 | 校正下界 ≥ 0.45 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | 未能确认Beta对control得分率至少45% |
| beta/direct_previous_beta | 对冻结M62 Beta直接保留 | Beta对冻结Prism Beta v0.1.0 T1得分率 | 校正下界 ≥ 0.45 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | 未能确认对冻结M62 Beta得分率至少45% |
| beta/direct_alpha | 大牌路线竞争力 | Beta对Prism Alpha v0.1.4半平得分率 | 校正下界 ≥ 0.45 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | 未能确认Beta对固定Alpha得分率至少45% |
| beta/direct_parent | 防共同退化 | Beta对Prism Balance v0.1.0半平得分率 | 校正下界 ≥ 0.45 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | 未能确认Beta对父得分率至少45% |
| beta/building_utility | 原building效用保留容忍 | Beta相对control原building归一化效用差（0..1） | 校正下界 ≥ -0.015 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | 下界低于−0.015即未保住既有building效用容忍线 |
| beta/early_bonus_auc12 | 非reward早期bonus风格信号 | Beta相对control前12Main平均永久折扣差（个） | 校正下界 ≥ 0.25 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | 未能确认非reward指标实质差异至少0.25折扣 |


## 预检与历史记录

39项原评测/R1/R2检查PASS，另7项R2含新增stdlib边界复测PASS。原50源码、305Rust/Cargo源码、6projection证据和两臂最终c4都通过绑定检查。7模型×68保存输入、8保存回放三种工具共25,748数值跨架构完全一致；额外16个双方building profiles验证通过。预检新增比赛0局。

原cloud1的审计字段错配导致prepare失败记录保留。R2独立适配字段、路径、三处潜伏执行链问题及仅用于metrics的stdlib依赖；不改权重/种子/对手/十门。正式对战前已冻结execution，工程预检失败尝试另存，不计作比赛重试。

完整双方训练表见[训练审计HTML](m63-training-audit-and-evaluation-status.html)及[Markdown](m63-training-audit-and-evaluation-status.md)；执行变更与限制见[M63里程碑](../m63-prism-beta-timed-building.md)。正式完成后云端自动生成含各对手完整双方表的Markdown/HTML，当前原十门及详细正式结果为NOT_RUN；本地需再次抓取。
