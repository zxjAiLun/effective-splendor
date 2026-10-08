# M71 有界评测与停滞证据保全

2026-10-08；task_kind=implementation；状态COMPLETED / VERIFIED；ALL任务done revision1。
baseline `9899749188f35c838c85c5b3530049bd5dcbd105`；已有脏工作树，执行身份不以HEAD代替。

## 问题、授权与终点

用户“M70完成了 执行修复吧”授权继续落实M69诊断后的工程修复。
authorized_end：新评测入口贯通有限对局、进程监督、截断现场保存、失败隔离、推进诊断与针对性零研究局测试、文档/ALL交付。
本次不改变策略、训练目标、编码、规则或历史M67/M70结果，不开展训练、补赛、模型发布或DSW部署。
模型等待偏好的消除需要独立有限研究；本工程不声称学会了有利推进。

## 初始设计与合同

复用Rust现有`run-rollout`，显式冻结每局ply cap（1..9999），终局照常计分，未终局保存原report及prefix，归为PLY_CAP_TRUNCATED，不转为平局或胜负。
到cap是预算截断，不证明绝对死局、重复永远持续或某方应负。
不使用相同规则hash推断相同神经输入；累计计数仍可能改变策略。

独立新入口`prism_bounded_eval.py`只接受新目录；prepare零局，run单writer且一次性，inspect只读。
政策必须显式声明网格局数、最大截断数、每局cap、绝对截止、CPU/内存/存储/进程数；自动重试恒为0。
每局由现有Windows Job Object或Linux DSW relay管理进程树，资源/未知/损坏产物失败停止。
只有exit0、无资源停止且完整绑定的截断可在有限预算内继续下一key；保留双座缺项，完整性与执行完成分栏。

全部终局/截断输出附推进描述：购牌、预留、本人连续原地拿还、双方Main与无购牌窗口。它们是观察指标，不对“等待必错”做规则裁决。
合法购牌机会没有完整合法动作输入时标NOT_MEASURED；不从动作历史推造。
缺项批次不输出正式完整网格PASS；原强度统计入口不接收缺项。没有原Rust规则复演就不宣称规则审计PASS。

## 验证计划

合成进程边界测试正常→截断→正常、失败预算、资源停止、未知退出、报告/prefix身份/计数/hash链错误、伪终局、重复运行、source/config漂移、inspect证据漂移；用保存9999步前缀复核描述计数。
本轮工程/研究对局均为0，不调用神经模型。可运行无对局的进程监督烟测。
M70只核验已有完成回执及原结果SHA，不重跑其7168局或Bootstrap。

## 开工阶段与交付（历史）

R0已定界；R1仅工程合同（无新研究采样）；R2实现/测试进行中；R3–R7不适用（未启动研究、冻结新候选或竞技确认）；R8报告、R9记录/同步待完成。
ALL读取返回fetch failed，保留待同步，不能为同步自动启动服务。
最终报告使用现有HTML说明模板，静态校验必须通过；不改UI布局，像素/DOM交互不是本实现任务强制门。

## 2026-10-08 用户“继续修复”：实现与迭代记录

接续未完成的M71，沿用已声明的工程终点。M70此前已取回完成回执，本次只核对本地记录和原结果SHA，不刷新远端或重复其7168局。
ALL本次已恢复可读；建立匹配任务`2431d2bd-8035-4352-bc77-928acc1ae974`（local/progress）。之前fetch failed为历史观察，不覆盖。

首轮42测试PASS，实际Windows无对局进程正常退出及父子进程超时清理PASS。
审阅发现只读inspect尚未独立复核process-result命令/累计CPU，进程启动耗时也未扣除绝对截止；本次补齐。
新增5项测试后，47测试首轮1项`next(list)`夹具错误，改为`jobs(...)[0]`；原失败保留在verification迭代记录。
47测试全部PASS，10.193秒；收口复核再发现JSON排序键可能改变CPU浮点加法顺序，改为按派发顺序复算，并加入未排序seed cohort回归。终轮48测试PASS，9.952秒，完整输出已保存。未用新研究局调试。

## 最终实现

- [prism_bounded_eval.py](../scripts/prism_bounded_eval.py)：新目录prepare/run/inspect；逐局run-rollout有界执行，保存terminal replay或非终局prefix及hash。
- 单writer永久once-only锁；中断后只读inspect，不能自动清锁或重试。未知/资源/证据失败保留并停止，只有核验有效的步数截断按冻结容忍预算继续。
- source/runtime/config/policy/engine/weights在启动与逐局前核验，保留所用Python模块副本；不以脏HEAD代替完整来源。
- actual command独立重建；process-result CPU必须有限非负，inspect从逐局结果复算总量。未知失败把剩余CPU全部预留，不能当未消耗额度再运行。
- 启动身份记录PID/create_time/argv/cwd/node/observed_at/manifest SHA；启动与身份落盘时间扣除绝对deadline。
- 购牌、预留、本人连续原地拿还、Main与无购牌窗口描述入逐局game.json。没有合法动作输入时机会字段NOT_MEASURED，不从购买缺失推断没有出口。
- 截断不生成胜平负或候选得分；缺项仍阻止formal_grid_eligible，双座完整性单列。formal_grid_eligible仅网格门，非规则/竞技晋级。

尚未接入旧M67/M70入口或DSW部署。本实现不热改冻结执行，不改变模型动作排名、权重或训练目标。

## 验证与证据

实际命令：`python -m unittest scripts.tests.test_prism_bounded_eval scripts.tests.test_prism_eval_failure_guard -v`，exit0，48测试。
分为24有界入口测试、18原隔离测试和6导入的fixed-evaluator测试；模拟对局为合成fixture。
覆盖正常→截断→后续唯一键、双座缺项、截断预算、资源/未知停止、部分/损坏产物、伪终局、源/配置/权重漂移、重复writer、崩溃DISPATCHED、独立命令/CPU复算、绝对截止及环境恢复。
真实Windows进程树仅运行无游戏Python命令；正常进程exit0、超时进程stop_reason=wall_deadline且其子进程已清理。Linux实机监督本轮NOT_VERIFIED，未新SSH。

保存事故prefix SHA `93e8ba01e140851150712b7c9bd74b32d5cc9e3872206d09e5b1a4a24b5cc452`核验一致。9999步结构/hash链与动作复算：本人Main P0/P1=5000/4999，购牌3/4，原地拿还4011/4977，最长本人连续原地拿还3327/4977，尾部及最长无购牌Main均9964。
本次仅复算已有动作，不重跑Rust规则或模型前向；此前规则核验仍是旧证据，不能换成新审计PASS。
M70结果SHA `9c46ebba921d372f55b59a4096e6779f9ee41d42269f898a8fa2420b7e05ee6b`保持原值。

证据：[verification.json](../local-artifacts/prism/m71-bounded-evaluation/verification.json)及同目录source副本、[终轮完整控制台日志](../local-artifacts/prism/m71-bounded-evaluation/tests-final.log)；[阅读HTML](prism/m71-bounded-evaluation.html)、[阅读Markdown](prism/m71-bounded-evaluation.md)、[Agent审计](prism/m71-bounded-evaluation.audit.md)。前期控制台未另存，失败与复测命令/退出码在迭代记录保留。

## 阶段、判定与已知限制

| 阶段 | 状态 | 本任务证据/理由 |
| --- | --- | --- |
| R0 | PASS | 用户继续授权、本地来源/HEAD/index检查、M70既有证据 |
| R1 | PASS | 工程范围/零局预算/无自动重试/停止与交付政策；非新训练合同 |
| R2 | PASS | 48针对性测试和原事故回归 |
| R3 | NOT_APPLICABLE | 未启动新正式运行；未来prepare不是本轮采样授权 |
| R4 | NOT_APPLICABLE | 0训练/探索采样 |
| R5 | NOT_APPLICABLE | 无新权重或候选冻结 |
| R6 | NOT_APPLICABLE | 无竞技确认，本次不重新判M70 |
| R7 | NOT_APPLICABLE | 无新模型画像；只有停滞动作描述 |
| R8 | PASS | 阅读/审计已交付；静态链接、10源码绑定、日志SHA、语法/空白/git检查通过；像素/DOM非强制且未验证 |
| R9 | PASS | 两层记录、ALL结果done revision1及真实产物登记完成；0新局；模型未新晋级 |

工程任务可完成；模型policy_effectiveness=NOT_EVALUATED，等待偏好尚未修复或验证；本任务不产生晋级结论。
资源隔离沿用现有监督器。Linux为relay进程组与软RSS观测，非独立cgroup；Windows Job CPU硬门主要user CPU，终局后按user+kernel计账并检查累计上限。存储检查为目录扫描与观测门，无本轮扩量吞吐承诺。
页面使用answer-me-with-html既有模板，未修改产品UI；像素/DOM交互NOT_VERIFIED，按本轮工程合同不阻塞交付。

## 下一允许动作与入口

当前实现任务终点为本地交付和ALL同步，0新对局/前向/远端修改，未发布/部署/提交/推送。
可继续只读诊断或设计新的有限策略推进修复。正式训练/竞技、接入指定执行/DSW部署须对应范围及新合同，不自动开展。

新执行需要调用者提供已冻结的完整arena config与本入口policy；policy必须显式填全部资源/截断字段，不提供通用默认研究预算。
用法（仅入口说明，本任务未运行这些比赛命令）：

```powershell
python scripts/prism_bounded_eval.py prepare --config <arena-config.json> --policy <bounded-policy.json> --output <new-directory>
python scripts/prism_bounded_eval.py run --output <new-directory>
python scripts/prism_bounded_eval.py inspect --output <new-directory>
```

policy format为`prism-bounded-evaluation-v1`，max_games必须等于候选×对手×seed×2座；max_truncated_games为允许保留的截断容忍数，首次超过即停止且保存触发局；ply_cap=1..9999；deadline_unix为绝对秒；cpu_seconds为总预算；memory_bytes/storage_bytes/max_processes明确填写；automatic_game_retries只能0。

## 交付收口验证

`python local-artifacts/prism/m71-bounded-evaluation/check_delivery.py` exit0：10源码副本SHA/终轮日志SHA/M70原结果、全部静态链接、阅读指标、Python AST与新代码尾空白均PASS；`git diff --check` exit0；`git check-ignore -v handoff.md`证明本地忽略有效，暂存区为空。
检查回执：[delivery-checks.json](../local-artifacts/prism/m71-bounded-evaluation/delivery-checks.json)。未提交/推送；既有混合工作树保持，不把他人修改纳入本任务来源。

2026-10-08 16:25:41 +08 ALL实际返回任务done revision1。历史ALL不可达与开工待同步状态由本条新增回执更正，不刷新M70或DSW运行心跳。[同步回执](../local-artifacts/prism/m71-bounded-evaluation/all-sync-receipt.json)。本实现授权终点已达到，无剩余强制工程阻塞；策略修复效果尚未评测，Linux实机和页面视觉验证未执行，均不冒充通过。
