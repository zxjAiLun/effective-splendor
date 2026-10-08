# M62 Prism Beta 基建路线：同起点 outcome-only 对照

当前状态：COMPLETED / VERIFIED；2026-10-04保存数据奖励研究亦VERIFIED / REVIEWED。2026-10-05用户另行授权后，M62 Beta最终c4在[M65](m65-prism-version-release.md)登记为 **Prism Beta v0.1.0** 固定研究版本；实际画像偏混合，尚未证实比Balance更偏基建。Control仍未发布。历史Control保留门PASS、Beta研究判定NOT_ACCEPTED_BUILDING_CANDIDATE均保持；下方未发布/NOT_RUN措辞属于其注明日期的历史阶段。
基线：`9899749188f35c838c85c5b3530049bd5dcbd105`；工作分支 `m61-alpha-balance-ab`
负责人/日期：Zixuan Tang / 2026-10-04
授权：用户「okay 开始做基建beta路线吧！基模采用balance还是alpha？以及顺便把新一版表现提升的用版本号更新来记录」。授权范围包括M61新只读审计修订、实验版本记录、有限Beta/同起点对照开发与评测；不包含Denial、部署、Git提交或push。

## Problem and evidence

M61两臂均通过原保留门、A/B INCONCLUSIVE；Alpha大牌AUC24增强有校正下界证据，整体棋力提升未确认。Balance比Alpha仅多0.117折扣/局、0.0195贵族/局，尚未形成基建风格。M61训练报告曾因replay无game_id失败，后续运行补丁未绑定，复用候选须先完成新的可追溯只读审计。原合同/失败/报告/统计不覆盖。[M61解释复核](m61-prism-alpha-balance-ab.md#2026-10-03-结果解释复核与路线建议当前更正)。

## Initial design

基模选M61 Balance最终c4，SHA `225daf49e8746576b1edc3508ca0454715e5454529fea53dc7dfeb9043cf01f1`；其关闭大牌辅助目标，适合可归因的新基建奖励对照。复审通过后登记为 **Prism Balance v0.1.0**，不混入通用 Prism v0.1.2谱系。M61 Alpha最终c4另登记 **Prism Alpha v0.1.4**；原父版 Prism Alpha v0.1.3保持不变。版本号表示可追溯实验权重，提升证据、保留门、风格验收和部署状态分别记录，未证明提升不虚称提升。

新轮从同一固定Balance权重构造两候选：outcome-only控制（β=0/style-value=0）与基建Beta（β=0.3/style-value=0.5）。相同新AdamW、policy/value/style初值、run RNG、对手日程、有限预算；仅系数和run/job身份不同。两臂均配置相同building效用合同；对照不提取或优化style。唯一取最终c4，不以开发选检查点。

首个基建版本预留 **Prism Beta v0.1.0**；尚未训练、NOT_RUN。控制可预留 **Prism Balance v0.1.1**，须先通过自身保留门。Beta风格验收失败时保留具名候选/负结果，不能写成已接受基建版本。

## Scope and non-goals

- 新只读M61审计r1，保存脚本、测试、源码pin、argv、资源及输入/输出哈希；原目录/receipts不改。
- 两臂各4×256=1,024训练局，串行cloud1；有限2,048训练，不自动延长、不重试。
- 基建目标为早期低VP投资的后续真实购卡折扣使用，不奖励所有0VP牌/终局折扣堆积。
- 保持96/80输入和Rust在线推理结构；不加温度覆盖、搜索或隐藏信息。
- 不执行Denial，不改默认/共享池/Studio，不提交/push。

## Contracts and invariants

### 基建效用（采样前设计）

前K=12个自身Main真实购入的印刷VP≤1牌构成早期投资。新增bonus的同色序号q由购卡前公开己方永久折扣+1确定；对获得后的真实己方购卡、且自身Main≤H=24，当目标卡原成本该色≥q，计一单位适用折扣使用。每投资最多3次，全局最多24单位，终局效用=单位数/24∈[0,1]。新增bonus不能抵扣购入自身的动作。原成本适用是结构性使用代理，不是没有该牌的反事实token节省。

只用玩家可见购卡目标/己方bonus/动作；自身预留购买允许，未知对方预留/牌堆不可读。ChooseNoble属于此前Main，不新增Main、不奖励。短局不虚构使用、不padding奖励；所有早败/未兑现投资保留。另描述早期全bonus曲线（12个Main平均折扣数量，短局终局保持仅作统计）、未兑现率与Main25..32真实得分购卡分，不以胜局/活到窗口过滤。

风格主验收须含**不直接进入reward的早期全bonus AUC12**（所有VP牌永久折扣），最小实质差异0.25折扣；同时验证效用差0.015。辅助静态同局面策略面板/晚期兑现只作诊断；不增加事后门。

### 训练和资源

两臂4周期，256局/周期。对手greedy：通用 Prism v0.1.1占50%，固定研究父 Prism Balance v0.1.0占25%，初代 Prism v0.1.0与Heuristic v0.3.1各12.5%。run RNG 62041001，opponent seeds 62041002/62041003。环境seed拟9631000..9631511，正式冻结前完整查冲突；开发9636000..9636031，独立9641000..9641511。action RNG62042001，bootstrap RNG62049999。控制先运行，成功提交停止后才创建Beta，等待不消耗Beta deadline。

每臂MemoryMax8GiB、CPU200%、8h、40,000CPU-s、storage32GiB、0retry；串行控制器1GiB/CPU20%/17h。新轮必须用race-safe storage snapshot，M61旧源保留。新style/coordinator产生新的package/numerical身份，绝不宣称等于旧M61；source-before账本位于local-artifacts/prism/building-beta-m62。

### 开发、独立和九项冻结门（待机器合同逐项固化）

开发：父、control、beta × Heuristic v0.3.1 greedy/初代 Prism v0.1.0 greedy/通用 Prism v0.1.1 T=1 ×32seed×2seat=576局，仅描述。

独立：三模型共同三锚点各256双座块，共4,608局；control和beta分别对研究父各512双座块，共2,048；beta对control512块=1,024；beta对固定 Prism Alpha v0.1.4 T=1另512块=1,024。合计独立8,704，评测9,280，连训练物理总11,328局，0retry。共同锚点parent只跑一次。所有补充direct标签均需无重复匹配验证。

9项单侧同时下界，family α=.05，20,000配对双座seed块bootstrap、q=.05/9；同长度向量共享draws。Beta发布/风格接受须其所有7门通过；控制须2自身保留门通过，否则cohort参照未合格，不放宽Beta门。

| 门 | 目的 | 校正下界阈值 | 单位 |
| --- | --- | --- | --- |
| control/strength_pool | outcome-only参照保留 | ≥−0.05 | 相对父共同锚点半平得分率差 |
| control/direct_parent | 参照对父竞争力 | ≥0.45 | 半平得分率 |
| beta/strength_pool | 基建代价控制 | ≥−0.05 | 相对control共同锚点差 |
| beta/general_anchor | 防均值掩盖关键对手退化 | ≥−0.075 | 相对control对通用 Prism v0.1.1差 |
| beta/direct_control | 同轮直接竞争力 | ≥0.45 | 半平得分率 |
| beta/direct_alpha | 与大牌路线保持竞争力 | ≥0.45 | 对固定 Prism Alpha v0.1.4半平得分率 |
| beta/direct_parent | 防cohort共同退化 | ≥0.45 | 对研究父半平得分率 |
| beta/building_utility | 早期投资兑现信号 | ≥+0.015 | 相对control归一化效用差 |
| beta/early_bonus_auc12 | 非reward风格信号/实质差异 | ≥+0.25 | 相对control前12Main平均永久折扣差（个） |

失败保留原种子/门/候选，不自动多训或扩样本。保留门通过不等于总体提升；新版本分别标记confirmed enhancement、style verdict、acceptance和发布/部署。

## Implementation plan

1. M61 r1只读复审，固定显式版本身份/本地权重与完整版本对战表。
2. building提取器、coordinator通用style摘要、新轮prepare/serial/audit/eval/report；测试真实字段与边界，冻结新package/source身份。
3. 冲突检查、零局preflight与初始化tensor/RNG一致性；cloud1新root有界串行训练。
4. 最终c4产物/来源/parity审计，freeze evaluation，开发+独立一次执行。
5. 完整双方/双座/七动作/时钟/风格表与九门；按原门版本记录，更新milestone/handoff。

## Iteration log

- 2026-10-04（研究收口）：Luna由只读审阅进一步受主代理明确分派实现两个新profile诊断/测试文件；主代理独立提取完整训练轨迹、开发同状态策略面板、审查并修正统计边界、独立重算六个共同锚点画像/相关性。保留Gemini调用失败、初版profile诊断与回执；原数据未改。全量18,560双方profile与2,048训练actor轨迹/55,149决策完成，12,288来源文件hash通过；八cycle重算mean/std与sealed记录误差≤1e-12。新22项有意义测试PASS，HTML26项检查PASS且桌面/手机截图目视核验。结论及新单变量提议详见下方追加研究节；0新对局/优化/门重开，未开启M63。
- 2026-10-04：用户「okay 开始研究吧」授权保存数据上的基建奖励/学习信号诊断；之后允许必要时用GPT-6 Luna辅助。Gemini 3.8 Flash High两次子代理调用均因当前lead封装任务的账户兼容限制失败，未执行研发；改用一次Luna只读奖励审阅，由主代理提取/开发/核验。新研究只读原训练和评测工件，在独立目录生成描述性统计与同局面概率面板，不训练、不比赛、不重开九门、不发布/提交。新采样仍NOT_RUN。
- 2026-10-04：确认授权与HEAD/worktree，M61复审/版本/基建提取器分工开始。历史非测试engine33份来源（包含3份M61文件）预存source-before/hash账本；原M61机器config/report不变。无新训练或评测。
- 2026-10-04：基建风格提取器完成并入库测试。`training/prism_portable/engine/ppo/building.py`（sha256 `7b57fd996ec497b8e7332e62f8a466e4a4d04f77a883b5c768c3f59b4399d8b8`）、`style.py` 分发（`99176794467a9da38ed9f87973c6d197888e2294259b1d1c2e097fefbf6bea91`）、`test_building_style.py`（`10dbf3e62a6753e9b59d559eee206fb0f2e5285f5e096a3e0ded0be2feeda12e`）。`default_building_config()` 与冻结奖励合同一致（early 12 / horizon 24 / VP≤1 / 单投资3次 / 全局24 / terminal-only / choose_noble不计Main）。测试：`pytest training/prism_portable/tests/test_building_style.py` 75 PASS；另对8局M54已审计真实replay双座220决策抽取通过；`test_building_coordinator.py`+`test_rush_style.py` 集成20 PASS（合成交易，style_return=1/24，30/32优化器槽位按style开关），合并回归95 PASS。无新对局。
- 2026-10-04：M61复审r1在cloud1实际执行并PASS（此前一次预执行回归失败已按新执行修订保留证据，见`reaudit-r1/preexecution-failure/`与`original-failure-provenance.json`）。`/home/ubuntu/splendor-ppo-m61/reaudit-r1/completion.json`：`m61-reaudit-r1-execution-receipt-v1`，`status=PASS_M61_REAUDIT_R1`，exit 0，wall 857.47s，failures=[]，`execution_sha256=61f12c166a02212d324227205fda15e1cad866086d04c73670e18e031aed56ae`。两臂均`PASS_TRAINING_ARTIFACT_AUDIT`：alpha候选`d3a31309…b53b2d9`（parity max_abs 0.0001527441406210528）、balance候选`225daf49…3cf01f1`（parity max_abs 0.0001047607421895691），各1024局，manifest sha `91574608…`/`1cf63831…`。远端未改动，原始M61字节保持固定。本地抓取回执（execution/completion/审计产物/候选权重+`unfetched_inputs`清单）由独立代理补齐后版本注册才启动。
- 2026-10-04：M62原生投影工具在cloud1隔离构建并冒烟PASS。源快照：M57冻结workspace 305文件逐字节核对0漂移（canonical sha `e2fc29ff…663be66a`，manifest `9e327458…1762`），新增导出器`crates/splendor-cli/examples/prism_building_projection.rs`（sha `ad08c55d…7817b`）。`cargo build --frozen --release` exit 0（wall 208.1s，MemoryMax 4GiB，RuntimeMax 900s，new_games 0），二进制`/home/ubuntu/splendor-ppo-m62-projection-source/projection-target/release/examples/prism_building_projection` sha `a6fd9690…729a1`。冒烟：对3局M61冻结terminal replay（alpha 001、balance 001、alpha 014盲预留）一次运行，150条own决策逐条与replay steps的ply/actor/action一致，双方actor齐全，observation无decks/log/输入泄露，replay sha/terminal/result/seed一致；panel `NOT_RUN`。回执本地化于`local-artifacts/prism/building-beta-m62/projection-{build,source}-receipt.json`、`projection-smoke-receipt.json`（含输出sha `82de222b…2bb16`）。零新对局。
- 2026-10-04：M62正式冻结（`FROZEN_BEFORE_FIRST_GAME`，frozen_at 2026-10-03T18:18:55Z）。前置全部真实通过：r1本地抓取回执+注册器check-only VERIFIED→实际登记两实验版本；准备组/评测组测试套件交付（39+111sub、85、95、16+1skip+24sub、22+1skip全部PASS，编译OK），`helper-readiness.json`绑定7条实际命令与28个源哈希（sha `0fdcfad33cae15a2ff6f31af2203df0115efe3e2c6d113070a1ff6cdd241cf8c`）。冻结产物：config sha `4f3ff90c89b017ad4b1fdb0f344b1ca84bc55ea641d5a1aee3b0bb50463eb408`、blueprint control `48d58866…`/beta `c0f98b64…`、package `7eb7206b…`、code identity `45bbe61b…`、numerical identity `98045fa2…`、init parity PASS（36张量等值、seed 62041001）、种子冲突检查PASS（10,700历史范围0重叠）。首次freeze尝试在`registered_inputs`处因prepare少传fetch-receipt参数失败（0写入，接口漂移即时修复为4参调用并重新生成readiness；prepare sha `1babd407…`）。零新局。
- 2026-10-04：部署cloud1新root `/home/ubuntu/splendor-ppo-m62`并启动串行训练。上传portable包（174,570B）/frozen config/双blueprint/5个inputs（逐字节哈希核对一致）+host.json（code_identity绑定冻结值，assets含M62新增alpha pin）。零局preflight PASS：package/numerical identity一致、37源文件0漂移、host资产与engine/metrics绑定一致。18:24:58 UTC启动`prism-m62-training-serial-9k2f.service`（1GiB/20%/17h），serial控制器无重试：control先行，STOPPED_COMMITTED且进程死后才创建beta；初始36张量/RNG两臂必须等值；进度校验cycle4/1024 attempts/4 consumed。控制臂已RUNNING（心跳内存~0.82GiB在8GiB上限内）。
- 2026-10-04：串行训练与独立审计完成。Control 臂（1,024 局，c4 sha `1ea1f493…`）与 Beta 臂（1,024 局，c4 sha `69a885b2…`）均达到 `STOPPED_COMMITTED`，累计 2,048 局，0 重试，0 OOM，cgroup 内存/CPU 合规。产物审计 PASS（32/36 槽位与 68 边界 parity 全部在 1e-4 容限内），生成绑定 `training-artifact-audit.json`。
- 2026-10-04：独立双座验收评测全量执行完成。在 cloud1 上运行 9,280 物理局（576 开发 + 8,704 独立验收），0 重试、0 崩溃。九门 Bootstrap 单侧下界计算完成，Control 两项保留门 PASS，Beta 臂 3 项 PASS / 4 项 FAIL，裁决 `beta_acceptance: NOT_ACCEPTED_BUILDING_CANDIDATE`。
- 2026-10-04：报告与展示产物生成。全量 Markdown 报告（7.8 MB，含双方全部指标、时钟、七动作分布及完整审计回执）落盘于 `docs/prism/m62-prism-beta-building-evaluation.md`；独立 HTML 对照报告落盘于 `docs/prism/m62-prism-beta-building-comparison.html`（97 张表格，支持交互折叠展开与视觉标识）。两模型均不登记版本号、不发布、不部署。
- 2026-10-04：重新接手后只读复核。实际分支 `m61-alpha-balance-ab`、HEAD `9899749188f35c838c85c5b3530049bd5dcbd105`，附件中的 main/b9f8148 已过时。cloud1 的142份冻结执行输入0漂移；已保存576开发+8,704验收的完整种子/双座账本及结果/完成回执绑定重新通过，未重跑Bootstrap。两臂STOPPED_COMMITTED、无M62存活进程。独立保存接手证据和16份hash核验的候选权重、companion、逐臂审计与训练表到 `local-artifacts/prism/m62-reception-2026-10-04/`，原M62目录/回执未覆盖。详见下方当前更正。
- 2026-10-04：交互HTML显示纠错，不改变机器结果或原97表报告。修复百分比差被再乘100、投资兑现率单位、共同锚点比例的总分母、动作次数汇总、胜率/得分率CI标签和完整候选版本名；保留修订前文件于接手目录。浏览器首次检查发现表头仍用旧简写，修复后通过；另独立以原JSON总计数核对624个已渲染数值。原报告SHA仍为80fc912e…，九门和负结果不改。

## Final implementation

- **冻结配置**：`benchmarks/m62-prism-beta-building.config.json`（SHA `4f3ff90c89b017ad4b1fdb0f344b1ca84bc55ea641d5a1aee3b0bb50463eb408`），状态 `FROZEN_BEFORE_FIRST_GAME`。
- **训练蓝图**：Control 臂 `benchmarks/m62-prism-control-building.train.json`（SHA `48d58866…`），Beta 臂 `benchmarks/m62-prism-beta-building.train.json`（SHA `c0f98b64…`）。
- **代码与数值身份**：Code identity `45bbe61bb2eb9c3d55d5aabd007444b304e2d1e6155a9efb68a55a6ffcada2ce`，Numerical identity `98045fa2a13a6e65fae0d0aed1b87dce4e2c5e879ca3d764955619f4a595319a`。
- **两臂训练产物**：各 1,024 局 / 4 个 cycle / 256 局，累计 216/220 次更新，0 重试。
  - Control 臂（outcome-only，$\beta=0, w_{style}=0$）：导出权重 SHA `1ea1f493993f6930464baf942c0b36cb1f1db025109f458d9d42f746aba5e19f`。
  - Beta 臂（基建风格，$\beta=0.3, w_{style}=0.5$）：导出权重 SHA `69a885b20527dda2e43fad9c00d7cc36537b45a0f5ccbaef4320001bef8836fb`。
- **产物审计与绑定**：两臂 32/36 槽位与 68 边界 parity（atol=rtol=1e-4）全过；`training-artifact-audit.json` 状态为 `PASS_TRAINING_ARTIFACT_AUDIT`，实际SHA为 `a6e1d53eefdab050179cccc75bd54ccc28dd1312ab2ddabba4ac2690ded3b0de`（此前把状态字符串写成SHA，更正于接手复核）。
- **独立评测执行**：执行合同 `evaluation/execution.json`（SHA `b65daae1148a1467df4d64d51a0fbf3fa62bb9a9400060d07fcc3f4666f22cfd`），在专用 cgroup unit `prism-m62-evaluation-b65daae1.service`（8 GiB / 200% CPU）中运行完成全部 9,280 物理局（576 开发 + 8,704 验收），0 重试、0 中断。结果落盘于 `evaluation/result.json`（SHA `4306fcff0eb53bbeca9113f58e5b05c97a9bf22d2d6e7fe67999ac563a790ede`），收据 `evaluation/completion.json`（SHA `266d433e…`）。

## Validation and evidence

独立双座验收数据（8,704 局），九项单侧同时下界（family $\alpha=0.05, q=0.05/9$，20,000 次配对双座 Bootstrap 抽样，种子 62049999）：

| 门 | 目的 | 指标 | 冻结阈值 | 点估计 | 普通配对 95% CI | 九项同时单侧下界 | 判定 |
|---|---|---|---|---|---|---|---|
| `control/strength_pool` | Control 总体保留 | 相对 Balance v0.1.0 半平差 | 下界 $\ge -0.05$ | +1.3021 pp | [-1.53 pp, +4.13 pp] | -2.3763 pp | **PASS** |
| `control/direct_parent` | Control 对父胜率 | 对 Balance v0.1.0 得分率 | 下界 $\ge 0.45$ | 52.0508% | [49.12%, 55.03%] | 48.1497% | **PASS** |
| `beta/strength_pool` | Beta 总体代价控制 | 相对 Control 共同锚点半平差 | 下界 $\ge -0.05$ | +0.3906 pp | [-2.73 pp, +3.55 pp] | -3.7435 pp | **PASS** |
| `beta/general_anchor` | 关键通用锚点保护 | 相对 Control 对 Prism v0.1.1 半平差 | 下界 $\ge -0.075$ | -1.5625 pp | [-7.13 pp, +4.10 pp] | -8.8867 pp | **FAIL** |
| `beta/direct_control` | 同轮直接胜率 | Beta 对 Control 得分率 | 下界 $\ge 0.45$ | 47.9980% | [44.92%, 51.07%] | 43.9453% | **FAIL** |
| `beta/direct_alpha` | 大牌路线竞争力 | Beta 对 Prism Alpha v0.1.4 得分率 | 下界 $\ge 0.45$ | 54.9805% | [51.95%, 58.06%] | **50.9766%** | **PASS** (显著优于Alpha) |
| `beta/direct_parent` | 防共同退化 | Beta 对 Balance v0.1.0 得分率 | 下界 $\ge 0.45$ | 51.8066% | [48.83%, 54.83%] | 47.9492% | **PASS** |
| `beta/building_utility` | 真实早期投资使用信号 | Beta 相对 Control 归一化效用差 | 下界 $\ge 0.015$ | +0.003309 | [-0.0036, +0.0101] | -0.005612 | **FAIL** |
| `beta/early_bonus_auc12` | 非奖励早期 bonus 风格信号 | Beta 相对 Control 前 12 Main 折扣差 | 下界 $\ge 0.25$ | +0.018555 | [+0.0044, +0.0326] | +0.000380 | **FAIL** |

完整报告：`docs/prism/m62-prism-beta-building-evaluation.md`（SHA `80fc912e820a0f008aeeba6f2b244d0ed6640724dfc01c78422a7793087cb6c0`）。

## Result and decision

- **Control 臂判决**：`control_retention: PASS_RETENTION_FLOORS`。Control 臂保持了棋力底线，相对父代点估计微增 +1.30 pp。
- **Beta 臂判决**：`beta_seven_gates: FAIL_BETA_GATES`，`beta_style: FAIL_BUILDING_STYLE_THRESHOLDS`，最终验收结果：**`beta_acceptance: NOT_ACCEPTED_BUILDING_CANDIDATE`**。
- **决定**：
  1. 依照预设冻结规则，**`Prism Beta v0.1.0` 候选未通过风格门与通用锚点门，不予晋级、不予发布为正式版本**。
  2. `Prism Balance v0.1.1 candidate` 虽通过保留门，但依据设计仅作为同轮对照组，同样保持未发布状态。
  3. 保留完整的负结果证据与置信区间，不修改门槛、不追加样本、不挑检查点。
  4. 观察到 Beta 对大牌流 `Prism Alpha v0.1.4` 展现了明确的直接克制性（直接得分率 54.98%，单侧下界 50.98% > 50%）。

## Known limitations

1. **基建风格刺激不足**：$\beta=0.3, w_{style}=0.5$ 下，Beta 模型在 1,024 局 PPO 中仅产生了微弱的折扣使用增量（效用增幅仅 +0.0033，折扣增量仅 +0.018 个），远未达到 +0.015 / +0.25 的显著风格分化门槛。这表明在当前的稀疏奖励结构下，PPO 策略主要仍被终局胜负信号主导，未学会更激进的基础建设兑现行为。
2. **通用锚点退化**：Beta 面对通用对手 `Prism v0.1.1` 时出现了性能松动（点估计 -1.56 pp，下界 -8.89 pp），说明在未形成有效基建打法的同时，轻度干扰了通用策略的稳健性。

### 2026-10-04 接手复核与解释边界（当前更正）

以上两项机制解释保留为先前假设，以本节更正为准。原完整报告、统计和验收判定保持字节不变。

- **产物与竞技事实**：cloud1只读 `verify` / `all_grid_completed` 通过142个冻结文件和9,280局已保存完整账本；完成回执SHA `266d433e45b75690f03312589b73ed09619447f50d1a767af48ad87b34f4ca12` 绑定结果 `4306fcff0eb53bbeca9113f58e5b05c97a9bf22d2d6e7fe67999ac563a790ede`。本次未重新计算置信区间、重审逐步规则或生成新比赛。Control/Beta训练216/220更新，0对局重试；M62进程已停止。原生训练和评测服务8GiB，不能把外围流水线的1GiB限制混在其中。
- **保留工程失败**：`prism-m62-pipeline-driver.service` 为 `failed / oom-kill / MainPID=0`，MemoryMax/MemoryPeak均1,073,741,824字节；2026-10-04 04:02:01 +08在第一次训练产物审计阶段结束。它没有完成原自动流水线，后来保存的审计/评测成功不能撤销此失败。后续审计/评测结果另有完整哈希绑定；“训练/评测0重试”不能扩写为“工程流程无失败或无再次执行”。journal与现时服务状态保存在新的 `cloud-review.json`。
- **已发现、尚未修改的历史驱动器问题**：`scripts/prism_m62_pipeline_driver.py` 检查M61的 `COMPLETED_FIXED_AB_EVALUATION`，而M62真正的状态是 `COMPLETED_FIXED_BUILDING_EVALUATION`；它还读取不存在的 `arm_verdicts`，当前结果字段是 `verdicts`。实际完成的独立评测及报告另行生成，此驱动器失败不等于权重或竞技数据失败。原源码保持；未来复用须另立工程执行修订，不能直接再跑原驱动器。
- **FAIL的准确意义**：`beta/general_anchor` 点估计−1.5625个百分点、普通95%区间 `[−7.1289,+4.1016]` 跨0；校正下界−8.8867低于容忍门−7.5，因此未能确认满足该底线，不能称已证实退化或奖励导致策略受损。`beta/direct_control` 点估计47.9980%，区间 `[44.9219,51.0742]`；下界43.9453%未确认至少45%，也没有证明真实得分率低于45%。
- **风格并非完全无正向信号**：早期bonus AUC12差+0.018555个、校正下界+0.000380高于0；有限固定对照中的正向变化有证据，但远小于原实质门+0.25。building效用差+0.003309，校正下界−0.005612，增益未确认。二者合起来仍为 `FAIL_BUILDING_STYLE_THRESHOLDS`，不能放宽门后重标接受。
- **没有证实失效或克制机制**：代码采用terminal-only基建目标，将style_return减style_value后乘β加入advantage，再按合同归一化；不是给每个非投资动作施加显式惩罚。未做两类advantage/梯度贡献或新超参数对照，故“终局胜负压倒风格”“β必须增大”“早期拿卡剥夺Alpha资源”均为待验证假设。Beta对固定Prism Alpha v0.1.4的54.9805%得分率、50.9766%校正下界确实确认直接优势；不能据此宣称普遍反Alpha机制。
- **奖励辨识度值得先诊断**：共同锚点下Control/Beta早期≤1VP投资3.8613/3.8880张每局，结构性至少一次兑现比例按总计数为约99%；未截断使用16.1569/16.3294单位每局，单投资cap3后10.7871/10.8665，全局cap24前后均值相等。这些是已保存结果的描述，提示逐投资封顶与代理区分能力可先检查，未证明它们是本轮失败原因。没有理由仅根据原结果就盲目加β、多训或改门。
- **展示口径更正**：交互页的百分比输入有0..100和0..1两类，原差值统一乘100错误；投资兑现率原来把0..1按百分数直接显示错误。新交互页将比例按总计数/总分母、次数按总数、均值按局数汇总，区分纯胜率和半平得分率配对CI。冻结Markdown紧凑表中的VP/Main是三个锚点分组速度的等权均值；不能把它当汇总总VP/总Main，新页与该描述表的小差异来自聚合口径。原97表及冻结报告SHA不变，修订前交互页已归档；不是重开验收。
- **身份与资料位置**：已登记实验版本仍为Prism Alpha v0.1.4、Prism Balance v0.1.0；M62的Prism Balance v0.1.1 candidate、Prism Beta v0.1.0 candidate保持未发布。16份新本地归档见 `local-artifacts/prism/m62-reception-2026-10-04/harvest/{control,beta}/`，fetch回执明确不含完整远端回放/可恢复训练检查点，不能宣称全量本地化。Heuristic策略按v0.3.1和冻结引擎/源码识别，Hello的0.2.9不是弱旧策略的证据。

实际验证命令：`C:\Python312\python.exe -B -m pytest training/prism_portable/tests/test_building_style.py training/prism_portable/tests/test_building_coordinator.py training/prism_portable/tests/test_m62_building_audit.py training/prism_portable/tests/test_m62_building_evaluation.py training/prism_portable/tests/test_m62_building_metrics.py training/prism_portable/tests/test_m62_building_report.py training/prism_portable/tests/test_m62_building_training_report.py training/prism_portable/tests/test_m62_prepare.py -q`，exit0，201 passed / 111 subtests passed，33.29秒。新的 `review.py capture` / `fetch` 均exit0；交互页18项浏览器检查及原JSON624个渲染数值检查exit0，截图已目视核验。证据都另存 `local-artifacts/prism/m62-reception-2026-10-04/`。无新局/新优化/新版本登记/部署/提交/push。

修订后的[交互HTML](prism/prism-beta-v0.1.0-comparison.html) SHA `9a48a020076c829183ba168d9002984d04d73a5612b207dcd7c4db3dbd8d735d`；最终页面回执 `browser-verification-final.json` / `numeric-display-verification.json` 绑定同一SHA。原[完整97表Markdown](prism/m62-prism-beta-building-evaluation.md)和[静态HTML](prism/m62-prism-beta-building-comparison.html)保留；正式权重/config/result均未改变。

## Next authorized gate（2026-10-04历史阶段，后由M63/M65更新）

1. 保持当前未发布状态，不向默认/共享池/Studio 部署两候选。
2. 保存数据上的基建效用分布、逐投资cap、style/value/advantage贡献及同局面投资偏好诊断已VERIFIED / REVIEWED，授权研究范围收口。研究源码/配置/新回执另存，原M62数据只读。新奖励实现与新采样仍PROPOSED / NOT_RUN。
3. 下一提议优先旧基建目标/时点加权目标的有限A/B：两臂均启用相同style critic/β/MSE，仅改真实use的时点权重，先新合同与离线范围核验，再冻结新预算/种子/门并获得新采样授权。详见研究报告的设计；不自动续训Alpha、开Denial或M63，原M62不延长、不重算正式门。

## 2026-10-05 M65发布更正（当前身份）

用户明确指定发布“M62 的 Beta 候选＋M63 的 Alpha 路线候选”。M62 Beta最终c4现登记为 **Prism Beta v0.1.0**，精确权重仍为`69a885b20527dda2e43fad9c00d7cc36537b45a0f5ccbaef4320001bef8836fb`，训练父代仍为Prism Balance v0.1.0，没有额外训练或检查点选择。Beta名称保留研究分支来源；该发布并不宣称达成原基建目标或成为最强默认模型。新实战四个共同对手表现接近父代；直接对父半平得分46.875%，对Prism Alpha v0.1.5为43.9453125%。完整双方greedy数据、区间和物理座位见[人类报告](prism/m62-prism-beta-building-comparison.html) / [详细Markdown表](prism/prism-beta-v0.1.0-evaluation-summary.md)。

版本权重/血缘/原审计/新greedy证据绑定在`benchmarks/m65-prism-beta-v0.1.0.model.json`；当前发布状态与旧研究门独立。原九门、原采样数据及其完整报告不改，新greedy种子不与历史采样合并。M65有限DSW校准与2560局发布支持队列已完成；Control未登记、默认/共享池/Studio未替换、Git未发布。当前后续建议与验证记录见[M65收口](m65-prism-version-release.md)。

## 2026-10-04 保存数据奖励研究（VERIFIED / REVIEWED；新采样NOT_RUN）

研究由用户授权，GPT-6 Luna完成奖励代码审阅/profile诊断开发，主代理完成训练提取、同状态面板、代码复审、独立数值重算和文档收口。[可读HTML](prism/m62-building-reward-diagnostic.html)与[Markdown](prism/m62-building-reward-diagnostic.md)包含93份原比赛/时钟/身份表（原97表报告及剩余raw审计/字面seed表仍按原SHA保留），及双方逐对手诊断表。此附录不修改原九门或模型身份。

**验证范围：**开发576+验收8,704保存局的18,560双方profile，训练两臂各1,024完整actor轨迹，共55,149决策；12,288逐局来源文件hash验证。Beta重算style profiles与1,024原targets全字段相同；八cycle合成advantage均值/标准差与封存记录误差≤1e-12。没有`Run.open()`/writer lock/store写入或Arena/optimizer调用。cloud1提取exit0、209.356秒、峰值RSS408,743,936字节，4GiB/600秒/最多两CPU有界运行；HEAD、writer.lock、ledger前后无漂移。本机同状态面板512条/三模型，CPU单线程前向（PyTorch2.6.0+cu124，模型实际CPU），7.6875秒；不能冒充Arena推理延迟或跨机比赛速度。

**新增代码：**`scripts/prism_building_profile_diagnostic_m62.py`（SHA `f8adfd89bc26206562399e2d82ad8f7036556d648b918903f4252f817c725de8`）、`scripts/prism_building_training_diagnostic_m62.py`（`03248d535df9074a9e6988a5b9be7ba828525b59566d8726e4f62ea5105b1186`）、`scripts/prism_building_policy_panel_m62.py`、`scripts/generate_m62_reward_diagnostic_report.py`；实际源/报告哈希和完整argv落新目录`local-artifacts/prism/m62-building-research-2026-10-04/`。scope采诊断前固定SHA `64029b22…`，只允许保存数据/最多512状态，0新局/优化。原输入11pins及接手59历史文件独立核查保持。

**描述发现：**

- Beta训练加权style项SD/合成advantage SD约14.8%–15.6%，联合归一化相对仅outcome的平均绝对变化0.120–0.128，2.1%–4.8%中心化符号改变；风格输入有真实非零影响。它不是参数梯度占比，原outcome-only/Beta对照还混有style critic/MSE的共享表示作用，无法单独归因。
- 共同锚点验收Beta 5,972笔投资，99.464%至少1use，84.444%达3use；单笔cap截掉8,391/25,082结构性units（约33.45%），全局cap截掉0。utility与投资张数r=0.9512，与AUC12 r=0.7370；前者高度相关，不能说已证明cap导致失败。全局cap非本轮观察到的瓶颈。
- 同状态Beta低VP买卡概率比Control仅+0.4045个百分点，argmax低VP415/414，父版424。仅8/512状态有≥2VP买卡可选，不能把其余状态的条件低VP比例约99%当品质选择证据；不能推断后续收益或Alpha资源剥夺。
- 新单变量PROPOSED：保留真实后续use、early≤12/VP≤1/horizon24/cap3/global24/不补齐等约束，前3次真实use按本人Main `w(t)=(25−t)/24`计权；两臂相同style head/β0.3/MSE0.5，一臂原target，一臂新target，同一Balance父版新初始化。新数值尺度/容忍度/有限训练和验收需另行固定，不将新门套回旧结果。直接AUC奖励有囤折扣而不兑现的定义风险，未证实实际发生；单纯加β/加轮数缺乏本次证据支持。

**主代理实测验证：**`C:\Python312\python.exe -B -m pytest training/prism_portable/tests/test_m62_profile_diagnostic.py training/prism_portable/tests/test_m62_training_diagnostic.py training/prism_portable/tests/test_m62_policy_panel.py -q`，exit0，22 passed；`verify_report.py` exit0，26页面/数值检查，93原详细表、68逐对手profile组、窄屏无横向溢出、无JS错误，截图已目视查看。最终`closeout.py`独立核对原pins/历史字节、六个画像的总分母/cap/r、sealed记录、HTMLhash、链接、Git与publication；回执`closeout-validation.json`。profile初版的终局use界/缺配对校验、无依据AUC≤5界、O(n²)统计和弱总分母测试均在复审中修正；旧诊断文件保留，新最终文件不覆盖。

