# M64 DSW SSH 通用对战工具实机烟测

**产物结论：两台均完成8局，0重试，原生运行、规则回放验核、完整双方指标与HTML生成通过。**

**竞技结论：IMPLEMENTATION_SMOKE / DEVELOPMENT_ONLY_NOT_PROMOTED。**16次执行是同8个固定逻辑对局的两台部署复现，不合并成16局棋力样本；独立正式验收NOT_RUN，M63未启动，模型未发布。

**风格结论：NOT_RUN。**少量对局只检验工程，不能给M63 Beta c4赋予新的风格/版本身份。

## 两台执行对照

| 主机 | 有效CPU | 有效内存 | 配置workers / 实际shard并发上限 | 完成局 / 独特双座种子 | 活动墙钟秒 | 已测RSS和峰值MiB | 原生/报告判定 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dsw | 4核 | 15.35GiB | 3 / 3 | 8 / 每对手2个种子 | 3.4687 | 140.42 | PASS（工程） |
| dsw2 | 8核 | 28.00GiB | 6 / 4 | 8 / 每对手2个种子 | 5.5670 | 181.60 | PASS（工程） |

墙钟包含派发、比赛监督、保存回放审计及离线报告，排除下载/构建/SSH传输；RSS是采样进程树和，可能重复计共享页。DSW2配了6 workers，但此8局只有4个双座shards，最多4路，未校准满6路吞吐。微型烟测被启动/负载噪声影响，不能据此排名批量速度或宣称2倍加速。

独立本地抓取核验：两归档SHA、全部逐局终局/回放/计时/配置hash、完整网格、14表/主机和双方经济守恒通过；两机逐局终局行完全一致。source-ledger和完整回放在ignored资产目录，下面是原阅读件全文。所有未发布训练检查点按其真实身份展示。

## 来源与历史例外

先前ARM运行时在两台均Exec format error，0局，已保留；DSW2 Rust下载过慢已停，WSL默认cc包装器/新glibc链接也未作为有效运行时。最终引擎由当前308份Rust/Cargo文件（0漂移）构建，Rust 1.94.1 + Zig目标glibc2.31，required max GLIBC2.30；指标工具GCC构建、required max GLIBC2.34；两台version与实战均通过。

`smoke-v5`是工程执行编号，不是模型版本。原状态中`new_games: 0`是未更新的遗留字段，真实完成数以`completed_games: 8`及逐局回执为准；原文件保持，当前v6工程补丁移除冗余字段，30测试与两台零局prepare/verify通过。v5实际运行源码已保存在每个run的runtime-snapshot及归档中；新代码没有覆盖原结果或回执。

| 资产 | SHA256 |
| --- | --- |
| bin/splendor | 6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f |
| bin/s4_batch_metrics | 39c630d5e0a9e0611ca4ec8c8b2e4a78817bf971c7bdc7446b614035aedbcb37 |
| dsw 完整归档 | 70edf862c7cc6ca59b78bbe408301f8dc93c189e83238dad49fedc6d44a53194 |
| dsw2 完整归档 | 726b21a7355e68c7da76d887a1f66d5fde1a596101a8731642e39556f3dbd629 |

## dsw 完整结果（原生成阅读件）

## Prism 通用对战结果（DSW / SSH）



**产物：已完成全部固定网格，Rust规则回放验核与双方指标守恒通过。**



**竞技：DEVELOPMENT_ONLY_NOT_PROMOTED。**这是独立通用开发测量，没有执行任何里程碑正式晋级门。



**风格：描述性数据。**不凭单一更高/更低经济指标授予风格身份。



候选按用户声明的完整模型名及导出SHA识别，未发布检查点仍须在名称中明确标注。每对手恰好双座种子块；个人表按模型身份归并，物理P0不总是候选。



### 候选匹配比较



| 候选 | 共同对手 | 本人指标 | 单位 | 首候选基线 | 候选 | 候选−基线 |
| --- | --- | --- | --- | --- | --- | --- |
| M63 Beta c4 (unpublished training checkpoint) | Heuristic development snapshot (agent-heuristic-v02; greedy) | 半平得分率 | 百分点 | 75.0000 | 25.0000 | **↓ -50.0000** |
| M63 Beta c4 (unpublished training checkpoint) | Heuristic development snapshot (agent-heuristic-v02; greedy) | 本人最终VP | VP/局 | 14.5000 | 12.7500 | **↓ -1.7500** |
| M63 Beta c4 (unpublished training checkpoint) | Heuristic development snapshot (agent-heuristic-v02; greedy) | 本人得分速度 | VP/Main | 0.5472 | 0.4857 | **↓ -0.0615** |
| M63 Beta c4 (unpublished training checkpoint) | Heuristic development snapshot (agent-heuristic-v02; greedy) | 本人永久折扣 | 个/局 | 10.5000 | 11.7500 | **↑ +1.2500** |


↑/↓仅为方向标记，不表示更好或差异显著。下面CI为逐对手描述性双座bootstrap；不做多门验收或发布。若只有一个种子块，CI退化，不能据此确认稳定性。



### 总体执行与来源



| 字段 | 记录 |
| --- | --- |
| 固定局数 | 8 |
| 并发进程 / 每进程库线程 | 3 / 1 |
| 累计已测活动墙钟秒（至报告前监测点） | 2.4583 |
| 首次派发至报告生成秒（包含暂停） | 2.9266 |
| 时钟范围 | standalone arena dispatch, saved replay audit and descriptive reports; excludes build/download |
| 资源监控 | observed process-tree soft limits; shared platform cgroups are not owned |
| 已测负载 | {'observed_processes': 2, 'peak_observed_rss_bytes': 147238912, 'process_tree_cpu_seconds': 4.06, 'process_tree_rss_sum_bytes': 33075200, 'scope': 'sampled live tree plus OS-accounted waited child CPU; RSS sum may double count shared pages'} |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |
| 配置SHA256 | 0e407f24f7a5bfb6d7e0b77e32d333457eb4fa28f83dcff248ff4e0d1d256cc8 |
| plan SHA256 | 266cebd35c203b725d3bdf784e8dbf354f1430d959afbdd57f341f1d1037fcf2 |
| engine SHA256 | 6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f |
| metrics SHA256 | 39c630d5e0a9e0611ca4ec8c8b2e4a78817bf971c7bdc7446b614035aedbcb37 |
| Git基线 / 源码dirty | NOT_AVAILABLE / None |
| Bootstrap | {'kind': 'descriptive paired seed blocks, not acceptance', 'samples': 20000, 'seed': 64049999} |
| 种子 | [64000000, 64000001] |
| 完整逐局来源 | source-ledger.json |
| 冻结源码SHA | {'scripts/prism_cloud_storage_snapshot.py': 'b417e62c6aa2ce56ad2968ab0ac4c952b4a954514128a6923efc272129f5eb8c', 'scripts/prism_dsw_arena.py': '172b6f9edbb69b2d0fc139cd3ac4678d5f0392f97b59ebd09164467beda7b399', 'scripts/prism_match_details.py': '0f7fb79de0a65e60dfcb914716c99562fa44dd7673e6c1c0ea5ee4916ba11bc4', 'scripts/prism_notebook_arena.py': 'c2aa76f7b7cc50501d4fb3880dbe6b1cac85cb50c03dee0a1bf90da3933fa8a0', 'scripts/prism_notebook_report.py': 'bc7dd35146d795c28c8f8a7fb3910cfe3b832e88884de32b93a0d010ff6fd9ec', 'scripts/prism_ppo_fixed_eval.py': 'fb6683d0f0d91d92efafef1d136545b3dabf376e014e066b19beb43fe78aeacb'} |




### Prism Balance v0.1.0 (registered experimental model) 对阵 Heuristic development snapshot (agent-heuristic-v02; greedy)



被测模型模式：sample（sample=T=1）；对手模式：greedy。下表个人指标分别属于模型/对手，整局指标另列。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 4/2 | 3/0/1 | 75.0000% | 75.0000% | 50.0000% / 100.0000% | 50.0000% / 100.0000% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 2 | 1/0/1 | 50.0000 | 50.0000 | 14.0000 | 14.5000 |
| P1（后手） | 2 | 2/0/0 | 100.0000 | 100.0000 | 15.0000 | 12.5000 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 14.5000 | 13.5000 |
| VP/本人全部决策 | 0.5472 | 0.5094 |
| VP/本人Main | 0.5472 | 0.5094 |
| VP/全局ply | 0.2736 | 0.2547 |
| 永久折扣/购卡每局 | 10.5000 | 11.5000 |
| 贵族/局 | 0.2500 | 0.5000 |
| 获得贵族的对局% | 25.0000 | 25.0000 |
| 预留获取/局 | 3.2500 | 3.2500 |
| 预留买回/局 | 1.7500 | 0.7500 |
| 终局未买回预留/局 | 1.5000 | 2.5000 |
| 预留买回/获取%（总分母） | 53.8462 | 23.0769 |
| 购入0 VP卡/局 | 4.0000 | 6.2500 |
| 购入1 VP卡/局 | 3.0000 | 1.2500 |
| 购入2 VP卡/局 | 1.5000 | 2.2500 |
| 购入3 VP卡/局 | 1.0000 | 1.0000 |
| 购入4 VP卡/局 | 0.2500 | 0.5000 |
| 购入5 VP卡/局 | 0.7500 | 0.2500 |
| White折扣/局 | 0.7500 | 2.5000 |
| Blue折扣/局 | 2.7500 | 1.2500 |
| Green折扣/局 | 2.5000 | 4.0000 |
| Red折扣/局 | 2.0000 | 1.7500 |
| Black折扣/局 | 2.5000 | 2.0000 |


| 动作 / 占本人全部决策 | 模型次数 / % | 对手次数 / % |
| --- | --- | --- |
| buy_market | 35 / 33.0189% | 43 / 40.5660% |
| buy_reserved | 7 / 6.6038% | 3 / 2.8302% |
| take_tokens | 51 / 48.1132% | 47 / 44.3396% |
| reserve_market | 13 / 12.2642% | 13 / 12.2642% |
| reserve_deck | 0 / 0.0000% | 0 / 0.0000% |
| choose_noble | 0 / 0.0000% | 0 / 0.0000% |
| pass | 0 / 0.0000% | 0 / 0.0000% |


| 整局 / 两人共同指标 | 值 |
| --- | --- |
| 总 / 均ply | 212 / 53.0000 |
| legacy决策轮：均 / 最小 / 中位 / 最大 / 总体SD | 26.5000 / 24.0000 / 26.0000 / 30.0000 / 2.2913 |
| Main轮均值 | 26.5000 |
| 绝对终局分差 | 2.0000 |
| 分差≤2对局% | 75.0000 |
| 对局监督墙钟秒：累计 / 均 / P95 | 0.6231 / 0.1558 / 0.1837 |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |


单局时间含启动、比赛、输出；累计单局秒数包含并行重叠，不等于整批墙钟。

| 身份 | 源码绑定的完整descriptor |
| --- | --- |
| 模型 | {'args': ['agent-prism-sample', '--weights', '/mnt/workspace/splendor-dsw/models/balance.json', '--seed', '64010001'], 'files': [{'path': '/mnt/workspace/splendor-dsw/models/balance.json', 'sha256': '225daf49e8746576b1edc3508ca0454715e5454529fea53dc7dfeb9043cf01f1'}], 'program': '/mnt/workspace/splendor-dsw/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |
| 对手 | {'args': ['agent-heuristic-v02', '--seed', '20260926'], 'files': [], 'program': '/mnt/workspace/splendor-dsw/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |




### M63 Beta c4 (unpublished training checkpoint) 对阵 Heuristic development snapshot (agent-heuristic-v02; greedy)



被测模型模式：sample（sample=T=1）；对手模式：greedy。下表个人指标分别属于模型/对手，整局指标另列。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 4/2 | 1/0/3 | 25.0000% | 25.0000% | 0.0000% / 50.0000% | 0.0000% / 50.0000% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 2 | 0/0/2 | 0.0000 | 0.0000 | 10.5000 | 15.0000 |
| P1（后手） | 2 | 1/0/1 | 50.0000 | 50.0000 | 15.0000 | 15.0000 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 12.7500 | 15.0000 |
| VP/本人全部决策 | 0.4857 | 0.5660 |
| VP/本人Main | 0.4857 | 0.5714 |
| VP/全局ply | 0.2417 | 0.2844 |
| 永久折扣/购卡每局 | 11.7500 | 13.5000 |
| 贵族/局 | 0.0000 | 1.2500 |
| 获得贵族的对局% | 0.0000 | 75.0000 |
| 预留获取/局 | 2.7500 | 1.7500 |
| 预留买回/局 | 1.5000 | 0.7500 |
| 终局未买回预留/局 | 1.2500 | 1.0000 |
| 预留买回/获取%（总分母） | 54.5455 | 42.8571 |
| 购入0 VP卡/局 | 5.2500 | 7.2500 |
| 购入1 VP卡/局 | 3.0000 | 2.5000 |
| 购入2 VP卡/局 | 1.7500 | 2.5000 |
| 购入3 VP卡/局 | 1.0000 | 1.2500 |
| 购入4 VP卡/局 | 0.5000 | 0.0000 |
| 购入5 VP卡/局 | 0.2500 | 0.0000 |
| White折扣/局 | 1.2500 | 3.2500 |
| Blue折扣/局 | 2.2500 | 3.5000 |
| Green折扣/局 | 3.0000 | 3.2500 |
| Red折扣/局 | 2.7500 | 1.0000 |
| Black折扣/局 | 2.5000 | 2.5000 |


| 动作 / 占本人全部决策 | 模型次数 / % | 对手次数 / % |
| --- | --- | --- |
| buy_market | 41 / 39.0476% | 51 / 48.1132% |
| buy_reserved | 6 / 5.7143% | 3 / 2.8302% |
| take_tokens | 47 / 44.7619% | 44 / 41.5094% |
| reserve_market | 11 / 10.4762% | 7 / 6.6038% |
| reserve_deck | 0 / 0.0000% | 0 / 0.0000% |
| choose_noble | 0 / 0.0000% | 1 / 0.9434% |
| pass | 0 / 0.0000% | 0 / 0.0000% |


| 整局 / 两人共同指标 | 值 |
| --- | --- |
| 总 / 均ply | 211 / 52.7500 |
| legacy决策轮：均 / 最小 / 中位 / 最大 / 总体SD | 26.5000 / 25.0000 / 26.5000 / 28.0000 / 1.1180 |
| Main轮均值 | 26.2500 |
| 绝对终局分差 | 3.2500 |
| 分差≤2对局% | 50.0000 |
| 对局监督墙钟秒：累计 / 均 / P95 | 0.5473 / 0.1368 / 0.1658 |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |


单局时间含启动、比赛、输出；累计单局秒数包含并行重叠，不等于整批墙钟。

| 身份 | 源码绑定的完整descriptor |
| --- | --- |
| 模型 | {'args': ['agent-prism-sample', '--weights', '/mnt/workspace/splendor-dsw/models/beta-m63-c4.json', '--seed', '64010001'], 'files': [{'path': '/mnt/workspace/splendor-dsw/models/beta-m63-c4.json', 'sha256': '3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12'}], 'program': '/mnt/workspace/splendor-dsw/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |
| 对手 | {'args': ['agent-heuristic-v02', '--seed', '20260926'], 'files': [], 'program': '/mnt/workspace/splendor-dsw/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |


## dsw2 完整结果（原生成阅读件）

## Prism 通用对战结果（DSW / SSH）



**产物：已完成全部固定网格，Rust规则回放验核与双方指标守恒通过。**



**竞技：DEVELOPMENT_ONLY_NOT_PROMOTED。**这是独立通用开发测量，没有执行任何里程碑正式晋级门。



**风格：描述性数据。**不凭单一更高/更低经济指标授予风格身份。



候选按用户声明的完整模型名及导出SHA识别，未发布检查点仍须在名称中明确标注。每对手恰好双座种子块；个人表按模型身份归并，物理P0不总是候选。



### 候选匹配比较



| 候选 | 共同对手 | 本人指标 | 单位 | 首候选基线 | 候选 | 候选−基线 |
| --- | --- | --- | --- | --- | --- | --- |
| M63 Beta c4 (unpublished training checkpoint) | Heuristic development snapshot (agent-heuristic-v02; greedy) | 半平得分率 | 百分点 | 75.0000 | 25.0000 | **↓ -50.0000** |
| M63 Beta c4 (unpublished training checkpoint) | Heuristic development snapshot (agent-heuristic-v02; greedy) | 本人最终VP | VP/局 | 14.5000 | 12.7500 | **↓ -1.7500** |
| M63 Beta c4 (unpublished training checkpoint) | Heuristic development snapshot (agent-heuristic-v02; greedy) | 本人得分速度 | VP/Main | 0.5472 | 0.4857 | **↓ -0.0615** |
| M63 Beta c4 (unpublished training checkpoint) | Heuristic development snapshot (agent-heuristic-v02; greedy) | 本人永久折扣 | 个/局 | 10.5000 | 11.7500 | **↑ +1.2500** |


↑/↓仅为方向标记，不表示更好或差异显著。下面CI为逐对手描述性双座bootstrap；不做多门验收或发布。若只有一个种子块，CI退化，不能据此确认稳定性。



### 总体执行与来源



| 字段 | 记录 |
| --- | --- |
| 固定局数 | 8 |
| 并发进程 / 每进程库线程 | 6 / 1 |
| 累计已测活动墙钟秒（至报告前监测点） | 3.5793 |
| 首次派发至报告生成秒（包含暂停） | 5.2739 |
| 时钟范围 | standalone arena dispatch, saved replay audit and descriptive reports; excludes build/download |
| 资源监控 | observed process-tree soft limits; shared platform cgroups are not owned |
| 已测负载 | {'observed_processes': 2, 'peak_observed_rss_bytes': 190418944, 'process_tree_cpu_seconds': 1.99, 'process_tree_rss_sum_bytes': 64753664, 'scope': 'sampled live tree plus OS-accounted waited child CPU; RSS sum may double count shared pages'} |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |
| 配置SHA256 | ce376ebd98f31a209747db272b3a246e93534cb4dcf81bb99efea7069c6c7c23 |
| plan SHA256 | 02aaa57ede757bf6218b0b169c90e74fb5ad73359327d739da34eba955bae51b |
| engine SHA256 | 6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f |
| metrics SHA256 | 39c630d5e0a9e0611ca4ec8c8b2e4a78817bf971c7bdc7446b614035aedbcb37 |
| Git基线 / 源码dirty | NOT_AVAILABLE / None |
| Bootstrap | {'kind': 'descriptive paired seed blocks, not acceptance', 'samples': 20000, 'seed': 64049999} |
| 种子 | [64000000, 64000001] |
| 完整逐局来源 | source-ledger.json |
| 冻结源码SHA | {'scripts/prism_cloud_storage_snapshot.py': 'b417e62c6aa2ce56ad2968ab0ac4c952b4a954514128a6923efc272129f5eb8c', 'scripts/prism_dsw_arena.py': '172b6f9edbb69b2d0fc139cd3ac4678d5f0392f97b59ebd09164467beda7b399', 'scripts/prism_match_details.py': '0f7fb79de0a65e60dfcb914716c99562fa44dd7673e6c1c0ea5ee4916ba11bc4', 'scripts/prism_notebook_arena.py': 'c2aa76f7b7cc50501d4fb3880dbe6b1cac85cb50c03dee0a1bf90da3933fa8a0', 'scripts/prism_notebook_report.py': 'bc7dd35146d795c28c8f8a7fb3910cfe3b832e88884de32b93a0d010ff6fd9ec', 'scripts/prism_ppo_fixed_eval.py': 'fb6683d0f0d91d92efafef1d136545b3dabf376e014e066b19beb43fe78aeacb'} |




### Prism Balance v0.1.0 (registered experimental model) 对阵 Heuristic development snapshot (agent-heuristic-v02; greedy)



被测模型模式：sample（sample=T=1）；对手模式：greedy。下表个人指标分别属于模型/对手，整局指标另列。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 4/2 | 3/0/1 | 75.0000% | 75.0000% | 50.0000% / 100.0000% | 50.0000% / 100.0000% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 2 | 1/0/1 | 50.0000 | 50.0000 | 14.0000 | 14.5000 |
| P1（后手） | 2 | 2/0/0 | 100.0000 | 100.0000 | 15.0000 | 12.5000 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 14.5000 | 13.5000 |
| VP/本人全部决策 | 0.5472 | 0.5094 |
| VP/本人Main | 0.5472 | 0.5094 |
| VP/全局ply | 0.2736 | 0.2547 |
| 永久折扣/购卡每局 | 10.5000 | 11.5000 |
| 贵族/局 | 0.2500 | 0.5000 |
| 获得贵族的对局% | 25.0000 | 25.0000 |
| 预留获取/局 | 3.2500 | 3.2500 |
| 预留买回/局 | 1.7500 | 0.7500 |
| 终局未买回预留/局 | 1.5000 | 2.5000 |
| 预留买回/获取%（总分母） | 53.8462 | 23.0769 |
| 购入0 VP卡/局 | 4.0000 | 6.2500 |
| 购入1 VP卡/局 | 3.0000 | 1.2500 |
| 购入2 VP卡/局 | 1.5000 | 2.2500 |
| 购入3 VP卡/局 | 1.0000 | 1.0000 |
| 购入4 VP卡/局 | 0.2500 | 0.5000 |
| 购入5 VP卡/局 | 0.7500 | 0.2500 |
| White折扣/局 | 0.7500 | 2.5000 |
| Blue折扣/局 | 2.7500 | 1.2500 |
| Green折扣/局 | 2.5000 | 4.0000 |
| Red折扣/局 | 2.0000 | 1.7500 |
| Black折扣/局 | 2.5000 | 2.0000 |


| 动作 / 占本人全部决策 | 模型次数 / % | 对手次数 / % |
| --- | --- | --- |
| buy_market | 35 / 33.0189% | 43 / 40.5660% |
| buy_reserved | 7 / 6.6038% | 3 / 2.8302% |
| take_tokens | 51 / 48.1132% | 47 / 44.3396% |
| reserve_market | 13 / 12.2642% | 13 / 12.2642% |
| reserve_deck | 0 / 0.0000% | 0 / 0.0000% |
| choose_noble | 0 / 0.0000% | 0 / 0.0000% |
| pass | 0 / 0.0000% | 0 / 0.0000% |


| 整局 / 两人共同指标 | 值 |
| --- | --- |
| 总 / 均ply | 212 / 53.0000 |
| legacy决策轮：均 / 最小 / 中位 / 最大 / 总体SD | 26.5000 / 24.0000 / 26.0000 / 30.0000 / 2.2913 |
| Main轮均值 | 26.5000 |
| 绝对终局分差 | 2.0000 |
| 分差≤2对局% | 75.0000 |
| 对局监督墙钟秒：累计 / 均 / P95 | 0.9383 / 0.2346 / 0.2531 |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |


单局时间含启动、比赛、输出；累计单局秒数包含并行重叠，不等于整批墙钟。

| 身份 | 源码绑定的完整descriptor |
| --- | --- |
| 模型 | {'args': ['agent-prism-sample', '--weights', '/mnt/workspace/splendor-dsw2/models/balance.json', '--seed', '64010001'], 'files': [{'path': '/mnt/workspace/splendor-dsw2/models/balance.json', 'sha256': '225daf49e8746576b1edc3508ca0454715e5454529fea53dc7dfeb9043cf01f1'}], 'program': '/mnt/workspace/splendor-dsw2/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |
| 对手 | {'args': ['agent-heuristic-v02', '--seed', '20260926'], 'files': [], 'program': '/mnt/workspace/splendor-dsw2/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |




### M63 Beta c4 (unpublished training checkpoint) 对阵 Heuristic development snapshot (agent-heuristic-v02; greedy)



被测模型模式：sample（sample=T=1）；对手模式：greedy。下表个人指标分别属于模型/对手，整局指标另列。



| 局数/双座种子块 | 胜/平/负 | 纯胜率 | 半平得分率 | 纯胜配对95%CI | 半平配对95%CI |
| --- | --- | --- | --- | --- | --- |
| 4/2 | 1/0/3 | 25.0000% | 25.0000% | 0.0000% / 50.0000% | 0.0000% / 50.0000% |


| 模型物理座位 | 局数 | 胜/平/负 | 纯胜% | 半平% | 模型VP/局 | 对手VP/局 |
| --- | --- | --- | --- | --- | --- | --- |
| P0（先手） | 2 | 0/0/2 | 0.0000 | 0.0000 | 10.5000 | 15.0000 |
| P1（后手） | 2 | 1/0/1 | 50.0000 | 50.0000 | 15.0000 | 15.0000 |


| 个人指标 | 被测模型 | 对手 |
| --- | --- | --- |
| 最终VP/局 | 12.7500 | 15.0000 |
| VP/本人全部决策 | 0.4857 | 0.5660 |
| VP/本人Main | 0.4857 | 0.5714 |
| VP/全局ply | 0.2417 | 0.2844 |
| 永久折扣/购卡每局 | 11.7500 | 13.5000 |
| 贵族/局 | 0.0000 | 1.2500 |
| 获得贵族的对局% | 0.0000 | 75.0000 |
| 预留获取/局 | 2.7500 | 1.7500 |
| 预留买回/局 | 1.5000 | 0.7500 |
| 终局未买回预留/局 | 1.2500 | 1.0000 |
| 预留买回/获取%（总分母） | 54.5455 | 42.8571 |
| 购入0 VP卡/局 | 5.2500 | 7.2500 |
| 购入1 VP卡/局 | 3.0000 | 2.5000 |
| 购入2 VP卡/局 | 1.7500 | 2.5000 |
| 购入3 VP卡/局 | 1.0000 | 1.2500 |
| 购入4 VP卡/局 | 0.5000 | 0.0000 |
| 购入5 VP卡/局 | 0.2500 | 0.0000 |
| White折扣/局 | 1.2500 | 3.2500 |
| Blue折扣/局 | 2.2500 | 3.5000 |
| Green折扣/局 | 3.0000 | 3.2500 |
| Red折扣/局 | 2.7500 | 1.0000 |
| Black折扣/局 | 2.5000 | 2.5000 |


| 动作 / 占本人全部决策 | 模型次数 / % | 对手次数 / % |
| --- | --- | --- |
| buy_market | 41 / 39.0476% | 51 / 48.1132% |
| buy_reserved | 6 / 5.7143% | 3 / 2.8302% |
| take_tokens | 47 / 44.7619% | 44 / 41.5094% |
| reserve_market | 11 / 10.4762% | 7 / 6.6038% |
| reserve_deck | 0 / 0.0000% | 0 / 0.0000% |
| choose_noble | 0 / 0.0000% | 1 / 0.9434% |
| pass | 0 / 0.0000% | 0 / 0.0000% |


| 整局 / 两人共同指标 | 值 |
| --- | --- |
| 总 / 均ply | 211 / 52.7500 |
| legacy决策轮：均 / 最小 / 中位 / 最大 / 总体SD | 26.5000 / 25.0000 / 26.5000 / 28.0000 / 1.1180 |
| Main轮均值 | 26.2500 |
| 绝对终局分差 | 3.2500 |
| 分差≤2对局% | 50.0000 |
| 对局监督墙钟秒：累计 / 均 / P95 | 0.8729 / 0.2182 / 0.2293 |
| 逐决策 / 推理延迟 | NOT_MEASURED / NOT_MEASURED |


单局时间含启动、比赛、输出；累计单局秒数包含并行重叠，不等于整批墙钟。

| 身份 | 源码绑定的完整descriptor |
| --- | --- |
| 模型 | {'args': ['agent-prism-sample', '--weights', '/mnt/workspace/splendor-dsw2/models/beta-m63-c4.json', '--seed', '64010001'], 'files': [{'path': '/mnt/workspace/splendor-dsw2/models/beta-m63-c4.json', 'sha256': '3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12'}], 'program': '/mnt/workspace/splendor-dsw2/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |
| 对手 | {'args': ['agent-heuristic-v02', '--seed', '20260926'], 'files': [], 'program': '/mnt/workspace/splendor-dsw2/bin/splendor', 'sha256': '6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f'} |
