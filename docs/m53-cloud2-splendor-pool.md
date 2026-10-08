# M53 Splendor Arena Pool Deployment (Cloud2)

Status: IMPLEMENTED / VERIFIED (historical Cloud2 deployment); M54 trial-v2 CLOSED_DEVELOPMENT_ONLY_WITH_BOUNDARY_FAILURE / NOT PROMOTED  
Owner / Date: 2026-09-30  
Target Node: `cloud2` (`instance-20260916-2344`)  
Service Path: `/home/ubuntu/splendor-pool`  
Web Port: `8720` (Loopback only: `127.0.0.1:8720`)

---

## 1. Problem & Context

在参考 `simpool`（天凤四麻 CPU 自对战联赛）的架构基础上，用户需要在 `ssh cloud2` 服务器上建立 Splendor 的自主对战池系统。

### 核心差异与要求对比

| 特性维度 | Simpool (Tenhou 4-Player) | Splendor Pool (当前第一版) |
|---|---|---|
| **游戏规则** | 天凤日麻原生裁判引擎 | `splendor run-match` (Splendor-base-v1) |
| **对局形式** | 四人半庄同桌 | 2人 1v1 单桌竞技，随机轮换先/后手 (Seat 0/1) |
| **分池规则** | 凤凰池 / 特上池 (双桌分段) | **单一对战池 (单桌)**，全部活跃模型同池竞技 |
| **分数结算** | 天凤段位 PT + Rate | **标准 Elo 结算系统** (初始 1500，K=32，胜 1 / 平 0.5 / 负 0) |
| **数据统计** | 局收支、和牌率、立直率等 | **项目规范指标** (VP/Turn, VP/Ply, 购卡, 预留兑现率, 贵族, 两两矩阵) |
| **看板展示** | 仅 Web 看板 | **SSH 终端 Rich 看板 + 纯 Web 现代看板** 双模支持 |

---

## 2. Architecture & Contracts

### 2.1 目录结构 (`/home/ubuntu/splendor-pool` & `apps/splendor-pool`)

```text
apps/splendor-pool/
├── config.example.toml       # 默认配置
├── config.toml               # 运行配置 (data_dir, engine_exe, initial_elo, elo_k, port)
├── start.sh / stop.sh        # 一键后台守护脚本
├── splendor_pool/
│   ├── __init__.py
│   ├── __main__.py           # CLI 管理入口 (`splendor-pool status/dashboard/worker/serve/model`)
│   ├── config.py             # 配置解析器
│   ├── elo.py                # 标准 Elo 计算引擎
│   ├── models.py             # 模型规范与适配器 (Heuristic, Aran/M50 Policy, Custom)
│   ├── stats.py              # 项目标准战术数据抽取与累计器
│   ├── store.py              # SQLite WAL 事务持久化账本
│   ├── worker.py             # 单桌排局与子进程调度执行器 (OS flock 互斥)
│   ├── dashboard.py          # SSH 终端 Rich/ASCII 看板
│   ├── web.py                # 零依赖 HTTP REST API 与静态服务
│   └── static/               # 前端静态看板 (index.html, style.css, app.js)
└── tests/
    └── test_pool.py          # 本地单元测试 (4/4 PASS)
```

### 2.2 Elo 结算公式

- 期望胜率：$E_A = \frac{1}{1 + 10^{(R_B - R_A)/400.0}}$
- 实际得分：胜 $S_A = 1.0$，负 $S_A = 0.0$，平 $S_A = 0.5$
- 积分更新：$\Delta R_A = K \times (S_A - E_A)$，$\Delta R_B = K \times (S_B - E_B)$
- 写入 `elo_history` 历史流水，并原子更新 `models.elo`。
### 3.1 入池当前最新高强模型阵容 (6 Models)

1. `prism-v01` (★ Prism v0.1 Entity Policy-Value Network, 54.3% vs v0.3.1)
2. `aran-v0.2.2` (★ Aran v0.2.2 Mortal Actor-Critic, 51.4% vs v0.2)
3. `s3-rollout` (S3 Rollout 官方强搜索模型)
4. `heuristic-v032c` (★ Two-Ply v0.3.2c 预读两步强启发式搜索, 67.6% vs S3)
5. `heuristic-v031` (★ Heuristic v0.3.1 5模块重构最强启发式教师, 76.6% vs S3)
6. `heuristic-v030` (Heuristic v0.3.0 冻结对比基线)

### 3.2 运行与落盘验证

- **Worker 进程**：持续在后台以约 1.2 秒/局 的速度进行自主抽样对战。
- **数据落盘**：
  - SQLite WAL: `/home/ubuntu/splendor-pool/data/pool.sqlite3`
  - Replay / Report: `/home/ubuntu/splendor-pool/data/matches/<match_id>/`
- **Web 看板**：监听 `127.0.0.1:8720`，支持端口转发访问。
- **终端看板**：SSH 到 cloud2 后直接运行 `splendor-pool status` 或 `splendor-pool dashboard` 即可查看。

## 4. 2026-10-01 M54隔离T=1候选接入（开发轮已完成，历史过程如下）

原六模型和10,854局历史不删除、不改配置、不清零Elo。M54新增不可变binary和weight身份，旧全局引擎SHA785fa765…保持不变。部署根 `/home/ubuntu/splendor-m54-trial-v1`，Rust `agent-prism-sample` 正常T=1学得分布抽样；没有人工风格logit/probability覆盖。Web/worker进程保持运行。

独立fixed runner不写SQLite/Elo，128个开发seed9420000..9420127双换座、2冻结greedy对手、父代与c1/c4/c8均T=1、同action seed54010001。父代512局和c1 512局已正常完成；总体score39.2578125%→44.23828125%、配对Δ+4.98046875pp，95%CI[+0.1953125,+9.67041015625]pp，**开发对照/NOT PROMOTED**，不代替独立验收。每个对手各256局的CI与座次、hash、原replay/report见M54和本地trial/cloud2。

父代混池matches10855..11111共257（256阈值后单在途收尾），身份7参赛69局36–0–33/Elo1500→1561.90；c1区间11112..11368共257，身份8参赛62局32–0–30/Elo1500→1517.17。这是随机混池诊断，两区间对手构成与已有Elo变化，不直接拿checkpoint/父代区间末Elo作学习强弱差值。

控制器保存原mixed_start_id/deadline、保留完成局，不在重启时重开256局额度；新增error立即pause。当前云端controller361405/prepare361104等待c4/c8，等待/固定期间池暂停。后续trial候选仅disable早期trial身份（历史保留），原六模型与T=1父代仍参与；完整运行记录以 [`m54-prism-continuous-ppo-design.md`](m54-prism-continuous-ppo-design.md) 和tracked trial result为准，本段不是c4/c8完成结论。

### 4.1 2026-10-01 c4区间完成

c4固定512局正常完成，241–3–268/47.36328125%，同T=1父代共同seed配对Δ+8.10546875pp、95%CI[+3.125,+13.0859375]pp，仅开发证据。c4混池matches11369..11625总257局、候选62局30–0–32，Elo1500→1554.43；原六模型配置/权重/历史不变，c1身份保留且disabled。controller继续等待c8，等待期pool paused，无error；不把跨区间Elo变化当作固定棋力提升。完整结果见M54与 `benchmarks/m54-prism-ppo-trial-v1.result.json`，后者本次才实际补建进行中快照，旧文档引用不代表先前文件已经存在。

### 4.2 2026-10-01 c8完成与最终只读核验

本节为trial-v1收口时的历史状态，最新trial-v2见§4.4，§4/4.1中的等待记录是历史快照。父代/c1/c4/c8固定各512局均完成，共2,048局固定评测（不写Elo）；同128seed双换座、T=1/action seed54010001，c8总体280–1–231/54.78515625%，相对同T=1父代配对Δ+15.52734375pp、bootstrap95%CI[+9.765625,+21.2890625]pp。分对手heuristic-v031 138–0–118/53.90625%（CI[47.65625,59.765625]%）、prism-v01 greedy142–1–113/55.6640625%（CI[49.21875,62.109375]%）；相对父代正向开发信号不等于已确认强于greedy对手或独立晋级，NOT PROMOTED。

c8混池matches11626..11882，整个池257局（256阈值加单在途收尾）、候选身份10实际63局38–0–25，Elo1500→1573.61。四段累计1,028新增mixed，原10,854历史保留，pool completed11,882、paused，无pending/running/error；controller complete/error null，c1/c4仅disabled且历史保留，父代/c8身份及旧六模型仍在。区间末Elo不直接作学习强弱差值，固定评测数据不回灌本地PPO。

实际`python -B <scratch>/m54_remote_verify_driver.py --final` exit0：只读SQLite核对1,028mixed记录/report/replay/每局2条Elo history；2,048固定产物hash、结果/aggregate复算；旧六模型name/type/weight/enabled/config、程序/权重hash与历史不减少，新不可变部署及旧全局引擎hash不变。没有DB写入/新派局/规则重放。证据`local-artifacts/prism/ppo-trial-v1/cloud2/remote-evidence.final.json` SHA `b48250314e2d39d28af4719cdc0466f88f3c8958df37477374ccebff54f8f6bd`，controller最终state SHA `520f10478542d49c95eb590f2b95ef7af68d942d4e61c388fc4c7a4c4c788237`。c8 fixed result SHA `46f688f8da6bb433b35d45a9031c76999dcf36ada60362c88352cb992ea22c12`，weights SHA `cb7c4fb33ac7666706213ca4138f80104dacc5151b2385b9532bfebbe82025ac`。

完整训练/逐轮指标、限制和最终tracked摘要见M54及`benchmarks/m54-prism-ppo-trial-v1.result.json`。本轮结束不自动恢复无限混池或新增评测/训练预算；下一合同另定，Web/原池资产未替换，未stage/commit/push。

### 4.3 2026-10-01 trial-v2 bounded continuation — fixed-only, no pool games

用户再次要求继续训练。M54 Stage IV冻结从最终c8保留model/AdamW/RNG的新8×256局本地outcome-only续训；cloud2本轮只执行独立固定开发对照，不恢复mixed worker、不登记新候选身份、不写SQLite或Elo。新目录 `/home/ubuntu/splendor-m54-trial-v2`，复用已核对的不可变Rust release与两个冻结greedy对手；不重编译、不部署Torch、不替换全局引擎。

`start.py`实际exit0，启动fixed watcher389487。启动前只读DB检查paused=true、completed11,882、无pending/running/error；完整model rows保存 `pool-baseline.json`，资产程序/权重SHA与旧全局binary785fa765…一致。新的c8父代与预设c1/c4/c8均T=1/common action seed54020001、128新seed9440000..9440127、双换座、两greedy对手；每模型512局、最多2,048固定局，比较新checkpoint对本轮c8父代，不拿旧父代39.2578%或旧c8不同seed54.7852%替代。fixed观察器有12h持久化deadline，完成局缓存不重打，无数据回灌。

2026-10-01T12:03Z实际观察：父代512局产物已完成，c1已不可变发布（SHA `c68f7cf00aa922d67715a3221a2a8d1e24cab53183c86a27e038f8e6407ef8d5`，training commit `ef7413725c307bda49c8e825a11d82643898525f1114758f1856319665dcc28e`），c1固定评测超过半数。本轮新mixed/Elo **0局（有意不启动）**；此前区间末Elo1573.61等仍仅历史诊断。完整合同、初始化验证、固定结果及最终对账以M54 Stage IV和 `benchmarks/m54-prism-ppo-trial-v2.config.json` 为准；当前IN PROGRESS / NOT PROMOTED，不宣称新棋力提升或所有固定局完成。

12:08Z父代与c1已各完成512局，watcher等待c4。父代278–2–232/54.4921875%，c1 287–3–222/56.34765625%，同seed配对+1.85546875pp、95%CI[-2.734375,+6.54296875]pp，尚未确认相对父代提升。原始report/replay/progress及bootstrap在本地只读核验exit0（M54所列verified-progress证据），本轮累计1,024fixed、0mixed。递归scp超时后改单archive取回，未影响云端比赛；本地训练的外部进程中断已同run恢复，云端watcher/固定已完成局未重启或重赛。

15:10Z追加：新c4固定512局已完成，297–3–212/58.30078125%，同本轮c8父代配对+3.80859375pp、95%CI[-1.5625,+9.1796875]pp；c1/c4区间均跨零，尚未确认相对本轮父代提升。c4对heuristic147–2–107/57.8125%，对Prism greedy150–1–105/58.7890625%。完成包改单archive取回，remote/local SHA一致，未重赛。watcher389487直接观察存活、stderr0/error null，等待预设c8；共1,536 fixed/0 mixed，后续局及最终资产对账未完成。本地前5轮已提交、第6轮采样中；不根据中期结果更改合同或启动池。c4 result SHA `de8421ec4af3ed471799a6110faf89511ef057476f526dbff11eee2c65702ae9`，weights SHA `ab5d3ab96b867d3d996fd732060918209c2bdd6d18bf9f1c4a18cf7588c55b63`；完整进度与核验范围见M54 Stage IV。


### 4.4 2026-10-02 trial-v2 final fixed evidence and manual unpause clarification

trial-v2原定parent/c1/c4/c8固定开发评测均完成512局，共2,048局，无重赛或数据回灌。四模型score54.4921875%/56.34765625%/58.30078125%/63.4765625%；c8 323–4–185，相对本轮父代paired+8.984375pp、95%CI[+3.515625,+14.453125]pp。共同新seed9440000..9440127、双座、两个greedy对手、学得T=1，仍development-only/NOT PROMOTED；没有独立holdout或选择校正。c8 result SHA `3a80c824763641e4fbf1aa538c5f46d414eae129f030305afcabdb7bfb284825`；weights SHA `a2301f0878f9c342a61b83fd45412f72ba95acfca895dafbe7ceca0360f34a85`。

最终strict collection exit1：2026-10-01T17:39:43.614418Z（北京时间2026-10-02 01:39:43）只读快照发现pool未paused、14,490 completed+1 running，相对11,882基线新增2,608 completed+1 running，id11883..14491。模型Elo/stats行改变，身份/config/enabled及资产/旧global binary仍未改变。此快照不代表当前live状态，旧§4.2/§4.3的暂停与11,882状态只在当时成立。本pipeline派0mixed/写0DB-Elo不等于整个共享池新增0局；额外全局对局没有进入v2训练或paired统计。

**2026-10-02 owner更正**：用户直接说明pause是自己手动解除，当时不知道对战验证在用共享池。当前归因`OWNER_REPORTED_MANUAL_UNPAUSE`（用户陈述，精确时间未知、未独立审计操作日志）；不记为自动解除pause缺陷。trial-v1确有mixed阶段，trial-v2为fixed-only，不能混淆。保留当时报告UNKNOWN原文以及总gate `FAILED_SHARED_POOL_BOUNDARY`/`all_original_gates_passed=false`，不因已知人工原因而事后改变门槛。本次没有暂停、恢复、回滚或修改池。取证快照 `local-artifacts/prism/ppo-trial-v2/cloud2/remote-actual-state.final.json` SHA `6ba348b28f0209405391e0e8f4d34da768b821404cd2eec0d1bdf18ee850fcb4`。

[最终索引](../benchmarks/m54-prism-ppo-trial-v2.result.json)与[M54最终收口](m54-prism-continuous-ppo-design.md)含完整分项、资源限制和校验命令。当前结果索引校验exit0/1,080断言/54文件hash；这不是重新跑比赛或独立review。当前轮到文档收口为止，后续训练/独立验收需新的有限scope，未自动重新开mixed或替换模型。
