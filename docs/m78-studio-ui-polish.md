# M78 — Studio 桌面表现与主页面布局优化

- **Status**: AUTHORIZED / IN_PROGRESS。
- **Owner-date**: 2026-10-11，用户要求继续优化当前 BGA `/play` 画面及其他 UI 布局，引用 M77 本地交付页。
- **Baseline**: `m61-alpha-balance-ab` / `a9a0037d82b05af0c55782f6dc2c0e2e72e6f6bd`；index 空。接手已有 M75 文档/脚本未提交改动，全部保留、不纳入本轮。
- **task_kind**: implementation。
- **authorized_end**: `/play` 与 Games、开局、League、Ratings 主页面的显示/导航优化；针对性回归、真实桌面/窄屏像素检查、两层记录与 ALL 实际回报。
- **必交产物**: 前端源码、可复验浏览器布局/交互 gate、截图/来源绑定、本记录及待同步/同步回执。
- **禁止动作**: 训练/研究局/真实计分局、规则/模型/Host/League 账本修改、重启既有服务、生产部署、Git commit/push；不启动 ALL 来同步。
- **下一允许动作**: 核对基线，在该范围内实现与零研究局验证。

## Problem and evidence

当前代码及上次截图显示：

1. 桌面三层市场未利用可用高度，桌布下部留白较大；银行筹码受旧 `margin-left:auto` 等共享样式影响，数字偏离中心，信息层次较弱。
2. 窄屏 `.table-panel-button` 的隐藏选择器优先级高于响应式显示规则，Table 入口不可见；银行位于隐藏的牌桌内，切换 Move/Reserves/History 后丢失银行。
3. Games 导航链接堆在单行；开局/League 表单窄且孤立，排行榜宽表在手机只靠横向滚动；主页面的导航和留白没有形成一致层次。
4. 旧交付的 PASS 不代替本次工作树验证。最初源码/状态及重新执行的基线回执保存于 `local-artifacts/m78-studio-ui/`。

## Initial design

- 保留深蓝桌布与三层实体桌游布局；合理使用桌面高度，明确卡牌分数、宝石、净费用和选择状态。
- 将银行从会隐藏的牌桌内容中分离；窄屏保留四个面板入口，银行和自有资源持续可见。桌面三层市场同屏，窄屏允许当前内容面板滚动。
- 统一 Games、Play setup、League、Ratings 的品牌、主导航、更多入口、按钮与内容宽度；不改各数据源权威。
- Games 用主要联赛记录 + 独立本地档案布局；League 用配置/结果与榜单并排；Ratings 窄屏用可读的单行记录卡，不删数据。
- 使用现有 React/CSS/已安装 Chromium，不添加网络字体、外部图片、依赖或第二套游戏状态。

## Scope and non-goals

只修改 `apps/replay-studio` 展示层及其相关测试。保留 Host action/seed/body 原字节、player-view 权限、评分和研究/联赛数据区分。更多入口继续通往原回放/分析页面；不重构其分析或数据读取协议。

## Contracts and invariants

- 动作只取 Host `legal_actions`；选择不发送，确认发原对象；busy/uncertain/结束不误重发。
- 自有资源绑定真实座位；对手暗留与未来牌堆身份不暴露；净费用/印刷费用语义保持。
- Games 三语料独立；分页只遵从 Host 游标，失败不吞掉已有行。
- League occurrence/seed 与结果/入账分栏保持；排行榜不重算 Elo，不将未读数值填成默认分。
- 延续共享 `DevelopmentCard`、`PlayerStateStrip`、`StructuredAction`，新增 props 只控制呈现。
- 临时测试服务使用随机 loopback 端口，仅关闭本轮创建的进程；不触碰默认 4173/43120 或远端研究节点。
- 截图/日志/完整源快照保持 ignored；`handoff.md` 不入 Git。

关联合同：[架构](architecture.md)、[M76](m76-studio-play-cockpit.md)、[共享显示](m37b-replay-workbench-convergence.md)、[产品入口](replay-studio-product-shell.md)、[联赛请求/结果](replay-studio-league-play-v1.md)。这些文档的历史门不重写。

## Acceptance gates

| Gate | 本轮要求 |
| --- | --- |
| G1 回归 | production build、全部现有 Node 回归、lint、tsc；人机 booking 与受影响页面浏览器测试 |
| G2 对战几何 | 1440×900、1366×768、1280×720 桌面三层市场同屏；窄屏 390/320、横屏与 150% 字号无整页横向溢出，资源/银行/确认可达 |
| G3 对战交互 | 四面板可切换并可回牌桌；银行跨面板持续显示；原买牌/预留/归还/noble/pass/busy/unknown/result 流程不回退 |
| G4 主页面 | Games/Play setup/League/Ratings 桌面与手机布局、导航/更多入口可点击；真值/分页/错误保留 |
| G5 视觉 | 实际打开新版 PNG，检查文字对比、卡牌信息、裁剪、留白、交互区域与窄屏；不能由 DOM 代替 |
| G6 收口 | 来源 SHA/本轮 diff/链接/空白/ignore、两层记录与 ALL 实际结果；不可达留 PENDING，不声称同步 |

## Implementation plan

1. 保存基线、重跑当前 UI gate，记录实际失败。
2. 先修对战布局与信息层次，再统一四个主入口布局。
3. 添加针对回归并执行真实 Chromium 几何/操作/截图检查，修复本轮发现。
4. 保存源绑定与目视结论，更新本记录/handoff/ALL。

## Iteration log

- 2026-10-11 接手：branch/HEAD/index/worktree 核对完成。ALL `context splendor` exit 1，`{"error":"fetch failed","status":null}`；无法读取任务 revision，后续回报待同步，不启动服务。

## Final implementation

IN_PROGRESS。

## Validation and evidence

证据根：[`local-artifacts/m78-studio-ui/`](../local-artifacts/m78-studio-ui/)。执行后填入真实命令/结果，不沿用 M77 的测试数量或 PASS。

## Stage record

| 阶段 | 状态 | 原因 |
| --- | --- | --- |
| R0 | PASS | 用户直接授权；当前 Git/代码边界已核实，ALL 读失败单列 |
| R1 | PASS | 本轮纯 UI 范围与上述工程门确定 |
| R2 | IN_PROGRESS | 本地实现/回归 |
| R3–R7 | NOT_APPLICABLE | 无训练、正式采样、模型/竞技/风格判定 |
| R8 | NOT_RUN | 等待最终界面及真实像素验证 |
| R9 | IN_PROGRESS | 最终记录与实际 ALL 回报待办 |

## Result and decision

任务进行中；模型/棋力/风格 NOT_APPLICABLE。

## Known limitations

模拟 Host 验证不等于真实比赛或部署验收。ALL 当前不可达；未取得任务 id/revision，不影响直接授权的本地实现。

## Next authorized gate

完成上述 UI 实现与验证；不扩大到模型、训练、后端或部署。
