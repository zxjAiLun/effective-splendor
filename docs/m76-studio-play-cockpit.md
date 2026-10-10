# M76 — Studio Play 单屏对战布局

- **Status**: IMPLEMENTED / VERIFIED（本地 G1–G5 PASS；项目回报 `ALL_PENDING`，R9 外部同步 BLOCKED；未部署）。
- **Owner-date**: 2026-10-10，用户要求重绘项目 UI，重点解决对战时上下滚动查看宝石数量。
- **Baseline**: `m61-alpha-balance-ab` / `e0018fd58fb973253d16000d59bf1b1aae62046a`，index 为空，工作树含大量既有未提交工作。HEAD **不是**完整执行来源。
- **task_kind**: implementation。
- **authorized_end**: `/play` 布局与相关共享显示组件完善、针对性测试、真实 Chromium 桌面/窄屏像素检查、两层记录与实际 ALL 结果回报。
- **必交产物**: 前端代码、可重复的模拟 Host 浏览器检查、截图/几何与交互回执、本记录。
- **禁止动作**: 新训练/研究对局、变更规则或模型身份、改动现有 League 账本、重启既有服务、生产部署、Git commit/push、提交 `handoff.md`。
- **下一允许动作**: 查看本地 UI；ALL 可用时读取最新 revision、登记已有证据并回报本轮结果。

## Problem and evidence

用户反馈：对战中必须用滚轮来回查看宝石，很疲劳。当前工作树已有未完成的 cockpit 改动，不能把用户粘贴的“153 tests pass”等过程文字当成本次验证证据。

实际读取 `app/play/page.tsx`、共享资源/动作组件及 `globals.css`：

1. 桌面已有底部 hand/bank/take 区，但 `max-width:1180px` 将它恢复到 board 和完整 history 之后的普通文档流，资源再次滚出视口。
2. 市场最小高度按三色费用列估计（124px），目录中存在四色费用；预留牌与选牌预览也需要检查分数、费用、标签相交。
3. 返回宝石候选直接堆在 footer，候选增加可以把牌桌挤走；右侧 pending 高度也没有完整约束。
4. `PlayerStateStrip`、`StructuredAction` 是既有共享显示合同，不能退回私有第二套状态或从当前牌桌猜历史牌身份。

接手源码副本与差异：`local-artifacts/m76-studio-play-cockpit/initial/`、`initial-ui.diff`、`initial-status.txt`。M37A 原冻结记录不改，本轮是新的用户授权实现范围。

## Initial design

- 桌面：紧凑页头、对手资源条、三层市场；底部固定自己的宝石/永久折扣、银行、拿取确认。
- 把预留牌和公共历史放入可切换侧栏；窄屏用同一组面板切换，不把资源放回长页面末尾。
- 牌面保留可读字号和颜色/文字标识；费用按紧凑横排/换行布局，避免分数和四种费用重叠。
- 返回宝石候选留在有限可滚动操作面板，不能无限撑高固定资源区。
- 内容超过小屏时只滚动当前面板；关键资源不随之消失。

## Scope and non-goals

仅 `apps/replay-studio` 的展示/交互布局与零研究局测试。保留已有阵容过滤、base-path 跳转、人类座位/u64 seed、未知响应恢复、完成结果与 League booking 分离。

不修改 Rust/策略/数据权限/评分算法，不以 UI 检查生成比赛结果或宣称棋力提升。未授权部署到公网或启动真实计分局。

## Contracts and invariants

- 所有动作来自 Host 的 `legal_actions`；前端只选择/确认，不发明规则或推断对局终结。
- 人类资源绑定 `human_seat`，支持 P0/P1；零宝石明确显示 0，10 枚上限由共享 `TokenTotal` 呈现。
- 对手仅显示 `public_reserved` 与暗留数量；公共历史的盲留不显示牌身份。自有预留显示自己的 private projection。
- 市场/选牌展示净费用；预留牌仍显示印刷费用（M37A 后置修正规则）。
- 模拟 Host +真实浏览器只是工程 UI 验证，不是实战/Host 端到端验收。
- 使用当前安装的 Chromium，不下载依赖，不碰默认 4173/43120 服务；自建临时 UI 进程与浏览器按身份关闭。
- 截图/日志/源绑定位于 ignored `local-artifacts/`；handoff local-only。

关联合同：[架构](architecture.md)、[共享显示原轮次](m37b-replay-workbench-convergence.md)、[M37A 冻结历史](m37a-studio-ui-polish.md)、[人机对战/记账](replay-studio-league-play-v1.md)。本轮不改这些冻结结果。

## Acceptance gates

| Gate | PASS 条件 |
| --- | --- |
| G1 功能回归 | `npm test`、lint、tsc 通过；既有共享展示及人机 booking 浏览器 gate 通过或明确记录非本轮阻塞 |
| G2 桌面几何 | 1440×900、1366×768、1280×720 真实浏览器：资源/银行/确认在视口内，无整页滚动；牌面分数/费用/标签不重叠 |
| G3 窄屏可用 | 900×900、390×844、320×720：资源持续可见，无页面横向溢出；面板切换、选牌、拿取、取消可达 |
| G4 边界交互 | 两人座位、0/10/超限呈现、四费用牌、己方/对手明暗预留、返回候选、贵族/Pass、busy/未知结果/结束状态；只发送所选原动作且不误重发 |
| G5 像素 | 实际打开桌面和窄屏 PNG 检查；DOM 与截图存在不替代目视验收 |
| G6 收口 | 记录实际命令/来源 SHA、链接、`git diff --check`、handoff ignore；ALL 若不可达则保存待同步且不宣称同步成功 |

## Implementation plan

1. 保留接手时未提交改动与文件来源，冻结本轮边界。
2. 完成资源固定/面板切换与牌面几何，保持协议与已有功能。
3. 用真实目录与标注的合成局面覆盖最挤布局和动作流程；实际 Chromium 截图/几何检查。
4. 重跑相关检查、修正发现、更新两层记录及实际同步状态。

## Iteration log

- 2026-10-10 接手：branch/HEAD/空 index/ignored handoff 已核对；本机默认 UI/Host 端口无响应，仅作只读事实，不启动或重启它们。
- ALL `context splendor` 返回 `{"error":"fetch failed","status":null}`。无法读取当前 revision/项目面板合同，任务创建及回报待同步；按 Skill 不自行启动 ALL。不阻止直接授权的本地 UI 工作。

- 2026-10-10 浏览器首次接入：测试用 `test-agent` 被现有阵容过滤，造成等待资源卡超时。将测试 roster/预期原始请求改为已有可见身份 `Prism v0.1.1`，不改阵容过滤或模型注册。
- 2026-10-10 几何修正：四费用牌、320px 贵族和资源行曾发生相交；费用改横排换行，资源标签保留独立列，窄屏市场用两列。桌面保留三层牌桌完整显示。
- 2026-10-10 字体放大修正：150% 字体下，像素单位的牌脚留白不足；改为 `rem` 后，费用/牌号/BUY 无重叠。失败回执及截图保留在 `browser-1791632151337/`，最终通过不覆盖历史失败。
- 2026-10-10 操作边界修正：只有一种合法归还方案时也先显示归还内容，再由用户确认；新增真实鼠标验证。47 项归还方案保持在操作面板中滚动，最后一项仍可点击。
- 2026-10-10 最终验证：153/153 回归、37 项 Chromium UI 检查、原有人机 booking 浏览器检查、lint/tsc PASS；目视检查另存记录。浏览器 helper 补记退出信号，临时 UI/Chromium 均已退出。
- 2026-10-10 结果页目视补正：已记账状态的 STUDIO LEAGUE 与说明原来挤在同一行；只调整页面内的分行/间距，复跑 production build、153 回归、37 UI cases、booking、lint/tsc 并打开新截图通过。原 `browser-final/`、`human-booking-final/` 和旧源快照保留，最终交付证据使用 `*-delivery`。
- 2026-10-10 收口重试：ALL CLI 再次 exit 1 / `fetch failed` / `status:null`，不启动服务、不伪造 taskId/revision；实际结果与待同步描述保存到本轮 local artifacts。

## Final implementation

- [`app/play/page.tsx`](../apps/replay-studio/app/play/page.tsx) 把对手资源、内容面板、自己的资源/银行/确认分成固定 grid 行；新增 Table、Move、Reserves、History 切换。选牌打开 Move，结束打开 Result；历史与预留牌不再拉长整页。
- [`app/play/play.css`](../apps/replay-studio/app/play/play.css) 独立管理 `100dvh` 布局与牌面几何。大于 1100px 为牌桌/侧栏并排，窄屏切换内容，700px 及以下市场改两列；只允许内容面板内部滚动。保留默认字号，150% 字体下改为内容区滚动。
- 复用 [`PlayerHandCard`](../apps/replay-studio/app/components/player-state-strip.tsx) 的宝石/折扣/10 枚上限，增加实际 P0/P1 与 YOUR TURN、THINKING、CHECK SESSION、FINISHED 状态。共享 compact 盲留历史显示 tier，仍不显示牌身份。
- 归还候选进入有界操作面板；唯一归还方案同样明确展示。动作只发 Host 给定的原始对象，选择/取消不发请求；busy、未知响应、非本人回合与结束状态禁止提交。
- [`test:play-ui`](../apps/replay-studio/package.json) 使用已安装 Chromium、临时 loopback UI 和模拟 Host；保存截图、几何、原始请求及来源 SHA。增加 [`浏览器 gate`](../apps/replay-studio/tests/play-cockpit-browser.mjs)、[`fixture`](../apps/replay-studio/tests/fixtures/play-cockpit.mjs)、[`helper`](../apps/replay-studio/tests/helpers/studio-browser.mjs)，更新 [README](../apps/replay-studio/README.md) 的操作/验证入口。

以上是在接手的未提交 UI 基础上完成的增量。`app/development-card.tsx` 与 `app/components/replay-board.tsx` 对本轮接手副本逐字节不变；不能把其 Git diff 或其他页面既有工作算成本轮新增。

## Validation and evidence

所有前端命令在 `apps/replay-studio` 执行，Node `v24.18.0`。最终构建使用工作树真实源码，没有用 HEAD 替代脏源码。

| 实际检查 | 结果 | 本地证据 |
| --- | --- | --- |
| `npm test`（含 production build） | exit 0；153/153 PASS，无跳过 | `validation/tests-delivery.log` |
| `npm run lint` | exit 0 | `validation/lint-delivery.log` |
| `./node_modules/.bin/tsc --noEmit` | exit 0；无诊断 | `validation/types-delivery.log` |
| `npm run test:play-ui` | exit 0；37 cases、33 screenshots | `validation/ui-r5.log` |
| `STUDIO_COCKPIT_ARTIFACTS=<browser-delivery> node tests/play-cockpit-browser.mjs` | exit 0；最终 helper 来源下 37/37 PASS，33 PNG，0 JS exceptions | `validation/ui-delivery.log`、`browser-delivery/checks.json` |
| `PLAYER_LOOP_ARTIFACTS=<human-booking-delivery> node tests/human-play-browser.mjs` | exit 0；u64 原字节、P1 结果/记账、未知响应、409、AlreadyPresent、空 body 重试 PASS | `validation/human-booking-delivery.log`、`human-booking-delivery/browser.json` |
| 改动范围 `git diff --check`，新文件空白/链接检查，index/ignore 核验 | PASS；index 仍为空，handoff 被 `.gitignore:12` 忽略 | `closeout.json` |
| ALL `context splendor` 最终重试 | exit 1；`fetch failed`，HTTP status 未取得 | `validation/all-final.log`、`all-pending-update.json` |

证据根为 [`local-artifacts/m76-studio-play-cockpit/`](../local-artifacts/m76-studio-play-cockpit/)。最终 [浏览器回执](../local-artifacts/m76-studio-play-cockpit/browser-delivery/checks.json)、[目视记录](../local-artifacts/m76-studio-play-cockpit/pixel-review.json)、[收口回执](../local-artifacts/m76-studio-play-cockpit/closeout.json) 分开保存。

**可重建来源**：81 个前端源码/配置/测试/锁文件，1,319,769 bytes，保存到 `delivery-source/apps/replay-studio/`；清单 [`delivery-source-manifest.json`](../local-artifacts/m76-studio-play-cockpit/delivery-source-manifest.json) 的源身份 SHA256 为 `a376a2f94711295ad2ab277a26fb085d4cd6ccce8d77639a625d247d220ffac3`。最终 browser receipt 的全部 10 项源 SHA 与当前文件一致；接手副本对最终文件的增量保存在 `m76-from-initial.diff`。这是本地源码快照，不是已提交/已部署版本。

### 布局与交互验收

检查 11 种组合：1440×900、1366×768、1280×720、1101×720、1100×720、900×900、700×844、390×844、320×720、844×390，以及 1280×720/150% 字体。各组合整页高度等于视口，无页面横向溢出，资源/银行/确认在视口内；滚动牌桌或历史不移动底栏。

| 工程局面 | 接手几何 | 最终几何 | 结论 |
| --- | --- | --- | --- |
| 390×844 拥挤局面 | 整页约 4656px，自有资源顶部约 y=4332 | 整页 844px，自有资源 y=669–754 | 资源与银行/确认持续可见，牌桌在内容区内滚动 |
| 1280×720 拥挤局面 | 接手已有桌面底栏，但仍需修正牌面与侧栏 | 牌桌 client/scroll height 均 454px，整页 720px | 三层 12 张市场牌完整显示 |
| 320×720 拥挤局面 | 原布局会退回长页面 | 整页 720px，自有资源 y≈528–630 | 宝石允许内部换行，标签/总数不相交 |

交互以 CDP 物理鼠标点击及 `elementFromPoint` 命中验证；覆盖 P0/P1、零/满/超限显示、己方三张预留/对手两张明留+一张暗留、历史盲留 tier、选牌/买牌/明留/暗留/买预留、拿取/移除/取消、47 项归还列表末项、唯一归还、贵族/Pass、busy 只提交一次、未知响应只读刷新，以及结束后禁用动作。测试没有绕过遮挡使用程序 `.click()` 代替可达性；仅 busy 的负向断言对已禁用按钮调用 `.click()` 验证其不发请求。

### 真实像素检查

实际打开并检查最终截图的桌面、窄屏、放大字体、预留、选牌、归还、历史、未知响应和结束状态；选择视图与观察记录见 `pixel-review.json`，不是以“截图存在”代替目视通过。

- [桌面 1366×768](../local-artifacts/m76-studio-play-cockpit/browser-delivery/table-1366x768-scale1.png)：三层市场、对手资源和底栏同时可见。
- [手机 390×844](../local-artifacts/m76-studio-play-cockpit/browser-delivery/table-390x844-scale1.png)、[320×720](../local-artifacts/m76-studio-play-cockpit/browser-delivery/table-320x720-scale1.png)：资源固定，费用横排换行，贵族与宝石标签不相交。
- [150% 字体](../local-artifacts/m76-studio-play-cockpit/browser-delivery/table-1280x720-scale1.5.png)：费用与牌脚有独立空间，底栏仍可见。
- [预留牌](../local-artifacts/m76-studio-play-cockpit/browser-delivery/reserves-390.png)、[归还列表](../local-artifacts/m76-studio-play-cockpit/browser-delivery/return-choices-320.png)、[未知响应](../local-artifacts/m76-studio-play-cockpit/browser-delivery/unknown-response-mobile.png)：内容区可滚动，操作提示及底栏可见。

G1–G5 PASS。G6 的本地证据/记录/检查完成，ALL 项保持 PENDING；未宣称项目面板同步成功。

## Stage record

| 阶段 | 状态 | 原因 / 下一动作 |
| --- | --- | --- |
| R0 | PASS | 当前用户授权、Git/源码边界已核对；ALL 读不可达单列 |
| R1 | PASS | 零研究局 UI 范围与上述工程门确定，无实验参数适用 |
| R2 | PASS | 实现、153 回归、lint/tsc、37 浏览器交互/几何检查通过 |
| R3–R7 | NOT_APPLICABLE | 纯 UI，不运行研究/训练/竞技确认/风格画像 |
| R8 | PASS | 真实桌面/窄屏像素、交互及证据交付完成 |
| R9 | BLOCKED | 本地核验/两层记录完成；ALL 不可达，实际产物登记/结果回报待同步 |

## Result and decision

本地 UI 交付 VERIFIED：桌面三层市场与资源同时可见，窄屏只滚动当前面板，自己的资源/银行/确认持续可见。任务本地实现与验收已完成，项目回报状态 REVIEW / ALL_PENDING。模型、竞技、风格结论 NOT_APPLICABLE；本轮 0 真实对局、未部署、未 Git commit/push。

## Known limitations

- 真实 Chromium + 模拟 Host 验证的是前端渲染/交互；没有启动实际 Host、真实计分局或写入 League，不能冒充后端端到端验收。
- 窄屏为 Chromium 视口验证，未做实体手机、触摸、虚拟键盘或其他浏览器验收。844×390 横屏和 150% 字体允许牌桌内部滚动，固定资源优先。
- ALL 当前不可达，未取得 taskId/revision、未登记远端 artifact、未同步结果。待同步记录只描述实际完成，不启动 ALL 或研究执行。
- 工作区保留其他任务的未提交改动；本轮不评价或收口 M75 等其他研发/执行。

## Next authorized gate

本地可通过项目 `Splendor Studio.cmd` 启动现有服务后进入 `/play` 查看；本轮不自动运行计分对战。ALL 恢复后读取最新任务 revision、复用或创建本范围任务、登记本轮真实证据并回报结果；不重跑比赛或 UI 验证来补同步。正式部署或 Git 提交/推送不在本轮授权中。
