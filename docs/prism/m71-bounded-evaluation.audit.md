# M71 Agent 审计

2026-10-08T16:22:40.882981+08:00；工程实现交付；本地 ALL 任务 `2431d2bd-8035-4352-bc77-928acc1ae974`。

## 身份与范围

基线 `9899749188f35c838c85c5b3530049bd5dcbd105`；分支 `m61-alpha-balance-ab`；混合脏工作树。
源码身份以 [verification.json](../../local-artifacts/prism/m71-bounded-evaluation/verification.json) 的逐文件 SHA 和同目录 source 副本为准。
这是所用 Python 模块的副本，不冒充完整仓库/正式执行来源。
M70 原结果 SHA `9c46ebba921d372f55b59a4096e6779f9ee41d42269f898a8fa2420b7e05ee6b`；保存事故前缀 SHA `93e8ba01e140851150712b7c9bd74b32d5cc9e3872206d09e5b1a4a24b5cc452`。
本次未刷新 DSW 状态；M70 完成判断来自此前已取回的绑定回执。

## 实际验证

`python -m unittest scripts.tests.test_prism_bounded_eval scripts.tests.test_prism_eval_failure_guard -v`
最终 exit0，48 测试，9.952 秒；其中 24 有界评测、18 旧失败隔离、6 导入的原 fixed-evaluator 测试。
完整终轮控制台日志和 SHA 见 verification.json；前期失败仍保留在迭代记录。
对局产物均为合成 fixture；真实 Windows 正常进程/父子进程超时清理使用无游戏 Python 子进程。
保存事故数据仅结构与动作计数复算；未重跑 Rust 规则审计、模型前向或合法机会分析。
前次 47 测试有一项 `next(list)` 测试夹具错误，已修为索引取值；失败保留在迭代记录。

## 判定边界

终局验证报告/回放身份、数量、结果、hash 链；截断验证 seed/cap/hash/分数格式，拒绝任何伪终局结果。
进程命令独立重建；CPU 计数有限非负并从逐局 process-result 复算；未知失败保守预留全部剩余预算。
只有正常 exit0 且无资源停止的有效步数截断才允许继续；超过截断容忍数立即停止，超限触发局仍保留。
资源扫描/Windows CPU 限制沿用既有 ProcessTree；Windows Job 的 CPU 时间限制以 user CPU 为主，user+kernel 在终局后计账并检查。
Linux relay 为进程组/软 RSS 观测，非独立 cgroup；本次未运行 Linux 实机验证。
规则复演未由 Python 验证替代，rule_replay_audit 保持 NOT_RUN_INDEPENDENTLY。
formal_grid_eligible 仅表示网格完整，不代表竞技晋级或规则全部通过。

## 交付限制

模型 policy_effectiveness=NOT_EVALUATED；0 新对局/前向/远端修改，未发布/部署/提交/推送。
HTML 使用 answer-me-with-html 既有渲染模板；未做像素或 DOM 交互验收，按工程合同非强制项。
真实来源/命令/预算/保存数据绑定见 verification.json；静态链接及 hash 验证写入同目录 delivery-checks.json。
