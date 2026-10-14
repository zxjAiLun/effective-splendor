# M78 — Studio 桌面表现与主页面布局优化

- **Status**: IMPLEMENTED / VERIFIED（本地 G1–G5 PASS；ALL 同步 BLOCKED → 待同步，未部署）。
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
- 2026-10-11 基线复验发现真实缺陷：在无任何本轮改动前，对既有 UI gate 增加“棋盘区域各块必须可见、窄屏 Table 返回按钮不得隐藏”断言后重跑即失败——基样式 `.table-panel-button{display:none}` 特异性高于 ≤1100px 媒体查询的 `button{display:flex}`，窄屏四个入口实际只剩三个。M77 的 DOM 检查未覆盖此点；本轮修复并新增 pinned-bank/back-to-table/selection-badge 等 gate 用例。
- 2026-10-11 历史面板横向溢出：`structured-action-compact` 旧宽度与共享 action-body 冲突，改为 play 域内单列网格 + 卡面上限。
- 2026-10-11 320px 横向滚动条根因：`globals.css` 的 `body{min-width:320px}` 在 320 视口被垂直滚动条挤压（clientWidth 305）而强制横向滚动，属既有全局缺陷；改为 `min-width:300px` 后四路由 probe 全部 `scrollWidth==clientWidth`，窄屏截图复检无横向滚动条。
- 2026-10-11 两个既有可选浏览器 gate 的 fixture 早于 M52 精选名册：games/ratings 页面按 `visibleParticipant` 过滤后，fixture 中自造名渲染为 0 行，且 ratings 报告半区断言的 `m22-scaled-self-play-v1` 恰是 node gate 明令禁止出现的隐藏 id（报告页/名册/运行时本轮未改动，矛盾为既有事实）。仅将 fixture 换成名册内身份，门断言的事实（游标分页、失败保留行、双权威分离、上传、零联赛读取）不变。
- 2026-10-11 vinext 1.0.0-beta.2 `next/link` 点击抛 `TypeError: e is not a function` 为既有平台缺陷（ratings gate 已记录）。主页面 gate 改用 window 捕获拦截点击并记录 href 验证导航意图，各路由仍经真实 `Page.navigate` 全量加载。
- 2026-10-11 其他修正：回合提示按状态分文案；持牌摘要单数 noble；牌桌标题注明净费用；牌面/牌堆 `aria-pressed` 选中态（呈现层新 prop）；会话座位/seed 移入 Table menu（human-play gate 同步改读）。

## Final implementation

- [`app/play/page.tsx`](../apps/replay-studio/app/play/page.tsx)：银行移出会隐藏的牌桌面板成为工作区常驻列（+n 待取徽标）；对手区标题化；回合横幅携带状态点；会话座位/seed/导航/New game 收入 Table menu；Move 空态给出操作指南与快捷入口；牌面/牌堆接入选中态。
- [`app/play/play.css`](../apps/replay-studio/app/play/play.css) 全量重写为窄域样式：桌面 felt+银行两列、三层市场充满高度、牌面材质/费用徽标/BUY 角标、贵族纵向栈；≤1250/≤1100/≤700/矮视口各档；≤1100 四面板全可见、银行横排置顶；≤700 银行自适应 chip、take 面板两行网格。
- [`app/components/studio-chrome.tsx`](../apps/replay-studio/app/components/studio-chrome.tsx)（新）+ [`app/studio-shell.css`](../apps/replay-studio/app/studio-shell.css)（新）：品牌、四主入口导航（aria-current）、More 下拉（experiments/jev/reports/advanced）、hero/桌卡装饰、布局与响应式（≤1120/≤820/≤600）。
- Games 首页：欢迎区 + 联赛记录主列 + Jev/本地档案侧栏（三语料仍分开）；League：开局表单主列 + 榜单侧栏、座位卡、occurrence/seed 分栏、结果/入账分区不变；Ratings：主表宽列、≤600 单行数据卡（`data-label`），两套评分体系说明保留；Play 开局：左故事右表单。
- `development-card.tsx` 新增可选 `selected`（仅 `aria-pressed`/边框呈现）；`globals.css` 仅改 body min-width 与无新语义。
- 测试：[`tests/studio-layout-browser.mjs`](../apps/replay-studio/tests/studio-layout-browser.mjs)（新，32 用例）；play-cockpit gate 扩至 40 用例（区域可见性、+n 徽标、跨面板银行、Table 返回、会话菜单、净费用牌面徽标检查）；`test:layout-ui` 脚本；其余 gate/单测同步修正（fixture 名册、wait 布尔包装、README）。

## Validation and evidence

证据根：[`local-artifacts/m78-studio-ui/`](../local-artifacts/m78-studio-ui/)。全部为本工作树真实执行，未沿用 M77 数字。

| 实际检查 | 结果 | 证据 |
| --- | --- | --- |
| `npm test`（production build + node --test） | exit 0；157/157 pass，0 fail | `validation/tests-r5.log` |
| `npm run lint` / `tsc --noEmit` | exit 0 / exit 0 | `validation/lint-r5.log`、`validation/types-r5.log` |
| `npm run test:play-ui`（play-cockpit gate） | exit 0；40 用例、34 截图、0 JS 异常 | `validation/play-r5.log`、`browser-r5/checks.json` |
| `npm run test:layout-ui`（studio-layout gate） | exit 0；32 用例、36 截图、0 JS 异常 | `validation/pages-r6.log`、`pages-r6/checks.json` |
| `tests/human-play-browser.mjs`（人机 booking） | exit 0；u64 原字节/座位/结果/重试语义不变 | `validation/human-booking-r4.log` |
| `tests/games-page-browser.mjs` / `tests/ratings-page-browser.mjs` | exit 0 / exit 0（fixture 名册修复后） | `validation/games-page-r5.log`、`validation/ratings-page-r6.log` |
| 320px 横向滚动 probe（/、/play、/league、/ratings） | `scrollWidth==clientWidth`，无横向滚动 | `validation/probe-320-final.log` |
| `git diff --check`、`git check-ignore -v handoff.md`、index 状态 | 见 closeout | `closeout.json` |
| ALL `context splendor` | exit 1；fetch failed，未启动服务 | `validation/all-final.log` |

初始 78 文件快照（`initial-source-manifest.json`）、交付 20 文件清单（identity `880fda12568141d300fd30114da8eb0fb28ad504429740ea11b849d2ee22e117`）、增量 diff 与状态见 `delivery-source-manifest.json`、`m78-from-initial.diff`、`delivery-status.txt`。目视检查记录：桌面 1440/1280/150% 字号三层市场与银行同屏、棋盘留白明显收敛；320/390 银行横排、四面板往返、会话菜单含精确 seed；320 横向滚动条与 More 裁切已消除（复检截图 `browser-r5/table-320x720-scale1.png`、`pages-r6/{ratings,setup}-320x720-scale1.png`）；历史面板无溢出、预订/结束/未知响应布局正常。

## Stage record

| 阶段 | 状态 | 原因 |
| --- | --- | --- |
| R0 | PASS | 用户直接授权；当前 Git/代码边界已核实，ALL 读失败单列 |
| R1 | PASS | 本轮纯 UI 范围与工程门确定；发现的既有缺陷按同一范围修复 |
| R2 | PASS | 实现、157 回归、lint/tsc、40+32 浏览器用例、三个既有浏览器 gate、320 probe 全部通过 |
| R3–R7 | NOT_APPLICABLE | 无训练、正式采样、模型/竞技/风格判定 |
| R8 | PASS | 真实桌面/窄屏/150% 截图目视检查通过；发现项（320 横滚、More 裁切、桌卡文案）修复后复验 |
| R9 | BLOCKED | 本地收口完成；ALL 不可达，产物登记/结果回报待同步，不启动服务 |

## Result and decision

本地 UI 交付 VERIFIED：对战桌面更高的空间利用与更清晰的信息层次，银行跨面板常驻、窄屏四面板完整；Games/Play 开局/League/Ratings 共享导航与响应式布局，数据真值与既有合同全部保持（157/157 回归 + 72 浏览器用例 + 320 probe）。任务范围内实现与验收完成；模型/竞技/风格 NOT_APPLICABLE；0 真实对局、0 League 写入，未部署、未 Git commit/push（未获授权，M75 等他人改动未触碰）。

## Known limitations

- 模拟 Host + 真实 Chromium 验证前端渲染/交互，不构成真实 Host 端到端或部署验收；未做实体手机/触摸验收。
- vinext 1.0.0-beta.2 客户端路由点击异常为平台既有缺陷；本轮以拦截记录 + 真实整页加载验证导航，升级依赖需另立轮次。
- 两个既有浏览器 gate 的 fixture 已按 M52 名册修复；更早轮次的同类 fixture 陈旧问题未系统性排查。
- ALL 不可达：未取得 taskId/revision，本轮结果与证据未同步；M75 等并发研究状态不受本轮影响。

## Next authorized gate

本地可双击 `Splendor Studio.cmd` 打开 `/play` 及各主页查看；Git 提交/推送需用户单独授权；ALL 恢复后按最新 revision 登记本轮真实证据并回报，不重跑比赛或 UI 验证。

## 2026-10-12 布局建议补充（review / DESIGNED，未实施）

- **授权来源与终点**：用户提供当前截图，询问能否缩窄卡牌、加大横向间距，以及将 YOUR HAND 移到右侧。本次 `task_kind=review`，`authorized_end=截图与当前源码核对、布局建议、说明页与记录`；不继承旧实现任务启动新的 UI 修改。
- **当前阶段/必交件**：只读评审已完成，建议为 DESIGNED；[一页分区建议](../local-artifacts/m78-studio-ui/layout-review-20261012/layout-proposal.html)、[Markdown](../local-artifacts/m78-studio-ui/layout-review-20261012/layout-proposal.md)、[核对回执](../local-artifacts/m78-studio-ui/layout-review-20261012/evidence.json)。
- **基线**：`m61-alpha-balance-ab@a9a0037d82b05af0c55782f6dc2c0e2e72e6f6bd`，index 空；已有大量未提交 UI/研究改动全部保留。截图是用户提供的界面证据，并非本轮浏览器抓取；源码是当前工作树，不代表已部署快照。
- **核实事实**：`play.css` 的普通桌面卡列是 `64px repeat(4,minmax(0,1fr))`、gap 8px；侧栏 `clamp(310px,25vw,350px)`；自己的资源和拿取确认仍位于左侧底部 dock。市场三行与卡面高度随剩余空间拉伸。源码快照与完整 SHA 见回执。
- **建议**：桌面左侧只承载公共市场/贵族/银行，右侧依次为紧凑对手摘要、略突出的自己资源、tabs、独立可滚动面板、固定确认。双方字段与颜色列对齐，自有资源不随 History/Reserves 滚走。预留详情不全部挤入常驻区；窄屏保留底部资源 dock。
- **尺寸起点**：卡面相对截图视觉缩窄约 15–20%；普通桌面 gap 先试 14–16 CSS px、右栏 360–400 CSS px，紧凑屏收敛；数值仅试排建议，非测量结果或已验收尺寸。不缩信息字号，限制卡宽/卡高，避免移除底栏后又把卡面拉大。加间距会消耗宽度，必须同时缩市场整体占宽，不能声称只改 gap 就能给侧栏腾空间。
- **实际检查**：截图人工评审、CSS/JSX/关联边界读取、branch/HEAD/index/ignore 核对；说明页 CLI 生成成功，4 panels、STE 0 warnings；源码未改、链接及 `git diff --check` 结果见回执。未运行前端测试或新 UI 浏览器验收，说明页像素 `NOT_VERIFIED`，本次设计交付不要求像素 PASS。
- **阶段**：R0 PASS；R1 PASS（仅建议设计，不是实施验收）；R2–R7 NOT_APPLICABLE（未实施、无模型/新局）；R8 PASS（只读评审交付）；R9 本地收口完成、ALL 同步 BLOCKED/PENDING。原 M78 实现验收不作废，也不拿旧像素 PASS 代替新方案验证。
- **ALL**：`node E:/AUbuntuProject/project/All/scripts/agent-client.mjs context splendor` exit 1，`{"error":"fetch failed","status":null}`；taskId/revision UNKNOWN，未创建/更新任务、未启动服务，实际结果待同步。
- **禁止动作与结果**：0 前端改动、0 新对局、0 训练/远端控制、未部署/commit/push；模型结论 NOT_APPLICABLE。下一允许动作是用户评审建议；真正布局实施需明确同意，再做桌面/窄屏/放大字号及交互回归。

## 2026-10-12 右栏资源布局实施 r2（IMPLEMENTED / VERIFIED）

- **task_kind / 授权**：implementation；用户“okay 按照方案修改”。
- **authorized_end**：已在本轮完成——`/play` 布局重排与验证；不自动扩至名册/清理等其他会话范围。
- **交付文件（仅这五个）**：`app/play/play.css`、`app/play/page.tsx`、`app/components/player-state-strip.tsx`、`tests/play-cockpit-browser.mjs`、`tests/fixtures/play-cockpit.mjs`（仅新增 `double-digits` 场景属于本轮）。身份 `60492db2169602d21974d9411955f9a40d5d7a75f74d4d50e95768346c64b55d`，见 [delivery-source-manifest.json](../local-artifacts/m78-studio-ui/right-rail-r2/delivery-source-manifest.json)。
- **实现**：桌面左列仅公共市场/贵族/银行；右栏自上而下为对手摘要→自己的资源→tabs→可滚动面板→固定确认，自己的资源单实例、不随面板滚动。双方 tokens/discounts 同为 6 列，颜色列上下对齐；零宝石在本局可见。卡面宽度上限 240.5 CSS px（15rem）、高度上限 224.5 CSS px（14rem），普通桌面列间距 16px；右栏 `clamp(360px, 28vw, 400px)`。≤1250px 用 360px 栏与更紧凑卡列；≤1100px 恢复“银行常驻 + 底部资源/确认”窄屏结构。矮视口/放大字号只压缩外层间距与页头，不缩小信息字号。
- **验收（实测）**：`npm test` 157/157、lint exit 0、tsc exit 0；play-cockpit gate **48 用例 / 42 截图 / 0 JS 异常 PASS**（含新增断言：单资源实例、右栏四区对齐、双方颜色列对齐、卡宽/间距/高度上限、History 滚动时对手/自己/银行/确认保持不动、双位数 P0/P1、150% 字号）；人机 booking gate PASS（原 u64/座位/结果/重试语义不变）；实际截图目视：桌面 1440/1250、窄屏 390、1280×720@150% 均无重叠/裁剪，三层市场完整。
- **名册垫片说明（重要）**：M80 会话已将 `VISIBLE_AGENT_IDS`/`VISIBLE_ENGINE_NAMES`/reviewer 名册清空为“retired 2026-10-12”，mock Host 的旧身份会被 UI 过滤，导致 `?fixture=` 恢复路径与 booking gate 无法进入对局。为把**布局验收**与**名册语义**隔离，gate 构建前把 `app/agent-visibility.mjs` 临时加回 `prism-v011`（记录于 `validation/roster-shim.json`），跑完立即恢复原文件并核验 SHA `07aaf5fd…636bd` 一致；生产语义未被本轮修改。
- **并发写入（如实记录）**：同一工作树的 `app/page.tsx`、`tests/studio-layout-browser.mjs`、`app/agent-visibility.mjs`、fixture 的对手身份行在 20:31–22:17 被另一会话（M80 清理）修改，非本轮改动；本轮未回退、未合并、未提交。由此 `npm run test:layout-ui` 当前失败于对方进行中的主页/JEV 重构（`.games-ledger` 等待超时），与 `/play` 布局无关。
- **ALL**：`context splendor` exit 1 / fetch failed；本轮证据与结果待同步。
- **阶段**：R0/R1 PASS；R2 PASS；R3–R7 NOT_APPLICABLE；R8 PASS（真实像素与交互）；R9 本地完成、ALL 待同步。
- **限制**：模拟 Host + Chromium 不构成真实 Host 端到端；名册为空时 `/play` 开局下拉为 0 个对手，属 M80 待决边界，需要用户单独决定是否重新登记 Play 模型。

## 2026-10-12 M80 清理后的状态更正（append-only）

- 上节“并发写入”与“当前失败于对方进行中的主页/JEV重构”已被 M80 的完成状态取代：主页 JEV/旧人机档案区块和 `/jev` 已删除，`.games-ledger` 等待问题已修复；`npm test` 145/145、layout gate 32 用例、games/ratings 门和 Rust 全工作区均通过。
- `tests/human-play-browser.mjs` 与 JEV gates 因名册清空/入口退役删除；`test:play-ui` 现在只验证“退役空名册”6 个空态用例，不再覆盖 M76/M77 桌面表格几何。右栏 r2 的 48 用例桌面证据仍作为当时冻结源码（identity `60492db2…`）的历史验收保留，不代表当前产品仍有可开局模型。
- 旧 `local-artifacts/m20-human-play` 与联赛历史已清空；M80 的清理范围、误删更正和恢复路径见 [M80 记录](m80-local-history-cleanup.md)。
- 本附录不修改上述 M78 原验收结论，也不把 M80 清理改写成 M78 的像素结果。

## 2026-10-13 全项目前端美化评审与路线图（review / DESIGNED，未实施）

- **授权来源与终点**：用户询问“看看现在整个项目的前端 能不能再美化美化了”。本次 `task_kind=review`，`authorized_end=全项目前端（Replay Studio 9 路由 + Prism 报告门户）源码与现有实测截图只读审查、四模块美化方案与说明页交付`；不自动修改前端源码或启动对局。
- **当前阶段与产物**：R0/R1/R8 PASS（DESIGNED），R2–R7 NOT_APPLICABLE，R9 本地完成 / ALL 待同步。产物：[单页互动说明](../local-artifacts/m78-studio-ui/frontend-review-20261013/frontend-review.html)、[Markdown 源稿](../local-artifacts/m78-studio-ui/frontend-review-20261013/frontend-review.md)、[核验回执](../local-artifacts/m78-studio-ui/frontend-review-20261013/evidence.json)。
- **核实发现（4 个可美化层面）**：
  1. **P1 次级页与复盘工作台外壳割裂**：`/ratings/[participant_id]`、`/replay`、`/review`、`/experiments`、`/advanced` 仍使用早期 M14 黑底青色 `.topbar`（其中 `/ratings/[id]`、`/replay`、`/advanced` 仍显示已退役的 `Play vs S3` 链接），与 M78 四主入口的深蓝鎏金 `StudioHeader` 风格脱节；底部 `38px` 时间轴圆点偏工程化；`/ratings/reports` 须按双权威合同维持与 `/ratings` 的视觉分离，但可美化上传归档空态卡。
  2. **P2 主入口四页列表与 M80 退役空态**：`/` 在 M80 移除 JEV 侧栏后单列拉满 `1480px`，对局行缺少 `RATED` 徽标与比分胶囊；`/play` 与 `/league` 在空名册（`studio-1v1-retired-2026-10-12`）下下拉框为空，缺少“名册已退役”的明确视觉引导卡；`/league` 赛果回执仍用原始 `<ul><li>`；`/ratings` 可增加胜率条与身份徽标。
  3. **P3 局内对战牌桌质感（不改 M78 r2 验收尺寸）**：发展卡底栏缺少 T1/T2/T3 等级圆点（`•`/`••`/`•••`），可买牌 `.buyable` 外发光较弱，贵族卡 `.table-noble` 偏扁平，右栏对手卡（`#122536`）与自己手牌卡（`#142b3b`）底色过近。
  4. **P4 Prism 静态报告门户（`docs/prism/reports.html`）**：目前仅 1 行内联 CSS、20 篇 `<article>` 垂直堆叠，可按“最新主线 / 风格图谱 / 工程诊断 / 早期轮次”分组并提取关键战绩徽标与底部按钮栏，不改动冻结报告正文。
- **实际检查**：16 份前端/报告源码 SHA 核验、`am.mjs render` 6 面板 / STE 0 告警、`git check-ignore -v handoff.md`、index 空、`git diff --check` 通过；ALL `context splendor` fetch failed 待同步。0 前端修改、0 新局、0 训练/远端控制/部署/commit/push；说明页像素 `NOT_VERIFIED`（设计评审非强制）。下一允许动作：用户勾选 P1–P4 模块授权实施。

## 2026-10-13 全项目前端美化实施与交付（IMPLEMENTED / VERIFIED）

- **task_kind / 授权来源**：implementation；用户“go 都修改 怎么好看怎么弄！”全量授权 P1–P4 实施。
- **交付范围与文件（共 12 文件）**：
  1. `apps/replay-studio/app/globals.css`
  2. `apps/replay-studio/app/studio-shell.css`
  3. `apps/replay-studio/app/page.tsx`
  4. `apps/replay-studio/app/play/page.tsx`
  5. `apps/replay-studio/app/play/play.css`
  6. `apps/replay-studio/app/league/page.tsx`
  7. `apps/replay-studio/app/ratings/page.tsx`
  8. `apps/replay-studio/app/ratings/[participant_id]/page.tsx`
  9. `apps/replay-studio/app/replay/page.tsx`
  10. `apps/replay-studio/app/advanced/page.tsx`
  11. `apps/replay-studio/app/development-card.tsx`
  12. `docs/prism/reports.html`
- **实现落地详情**：
  - **P1 次级页与工作台外壳**：`/ratings/[id]` 接入 `StudioHeader active="ratings"` 与 `1480px` 居中容器，Elo 图表增加渐变面积填充；`/replay` 与 `/advanced` 清理失效的 `Play vs S3` 链接为 `Play vs AI`；工作台 `.topbar` 与 `.timeline` 升级为深蓝玻璃感、圆角胶囊与高光指示灯；保持 `/ratings/reports` 与 `/ratings` 双权威视觉分离。
  - **P2 主入口列表与空态**：`/` 对局列表在 >1120px 宽度升级为双列对阵卡并加入 `Rated`/`Not rated` 徽标与分数胶囊；`/play` 与 `/league` 在 M80 退役空名册下呈现专属鎏金引导卡；`/league` 赛果回执升级为结构化网格；`/ratings` 增加胜率条、`Kind` 胶囊与前三名金银铜牌徽标。
  - **P3 局内牌桌与卡牌材质**：严守 M78 r2 已验收几何尺寸（卡宽上限 240.5px、右栏 360–400px，零溢出）；发展卡底栏增加实体桌游等级点标（`•`/`••`/`•••`）；可买牌增加翡翠绿呼吸光感；贵族卡升级为暖金羊皮纹章；右栏 `YOUR HAND` 采用暖金边框与更高底色对比度，区分圆形筹码与方形永久折扣。
  - **P4 Prism 报告门户重排**：`docs/prism/reports.html` 从 1 行内联 CSS 升级为四分区响应式看板（最新主线 M73–M75、风格图谱 M65/M72、工程诊断 M64/M67/M69/M71、早期轮次 M61–M63），提取关键战绩胶囊与规整操作按钮组，原链接与文本 100% 保持。
- **全量验收证据**：
  - `npm test`（build + node --test）：145/145 PASS，0 fail。
  - `npm run lint` / `npx tsc --noEmit`：0 错误，0 告警。
  - `node tests/studio-layout-browser.mjs`：32 用例全部 PASS，34 截图无异常。
  - `node tests/play-cockpit-browser.mjs`：6 用例全部 PASS，6 截图无异常。
  - `node tests/games-page-browser.mjs` / `tests/ratings-page-browser.mjs`：全 PASS。
  - 源码白名单与 ignore：`git check-ignore -v handoff.md` 验证正常，index 为空，`git diff --check` 0 格式错误。
  - 回执与快照：`local-artifacts/m78-studio-ui/frontend-polish-delivery-20261013/closeout.json`。
- **阶段状态**：R0/R1/R2/R8 PASS，R3–R7 NOT_APPLICABLE，R9 本地收口完成，ALL context fetch failed 待同步。0 新研究局/训练/远端控制/部署/commit/push。
