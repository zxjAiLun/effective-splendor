# M37B — Replay Workbench Convergence (Replay/Review shared components)

```ini
MILESTONE = M37B
STATUS = IMPLEMENTED / VERIFIED / PENDING_REVIEW
BASE_COMMIT = f70b642
SCOPE = Replay Studio front-end only (apps/replay-studio). Two small front-end
        rounds executed as one tracked convergence record:
        (1) /review keyboard navigation repair; (2) Human replay audit and
        review-page convergence onto the shared board/timeline components with
        honest optional referee reveal and neutral timeline semantics.
        No Arena, no model, no replay/engine semantics, no promotion.
UI = /, /review, /play in apps/replay-studio
PROMOTION = N/A (GUI-only; champion unchanged = M07)
DECISION = IMPLEMENTED + VERIFIED for contracts 1 & 2; workbench/route and
           session-driven URL explicitly DEFERRED (reopen conditions below).
```

## 提交记录

按逻辑拆分为两个提交（外加本轮文档提交）：

| 提交 | SHA | 内容 |
|---|---|---|
| fix 提交 | `1e15488` | `/review` 接入共享 `usePlyNavigation` + 时间轴中心滚动联动 + `/play` token chip 视觉打磨（`globals.css` table-gem） |
| refactor 提交 | `45a6b0d` | `HumanReplayAudit` 移除手写棋盘/银行/市场/时间轴，收敛到 `BoardSurface` + `ReplayTimeline` + `usePlyNavigation`；`BoardFrame.referee_reveal` 可选化；时间轴中性着色 |
| 文档提交 | （本提交） | 本文件；`handoff.md` 保持 local-only 不入库 |

`handoff.md` 按仓库发布规则保持 local-only（`git check-ignore -v handoff.md` →
`.gitignore:12:/handoff.md`），所有提交均未包含它。

## Problem and evidence

### 轮次 1：`/review` 键盘导航未生效（用户实测报告）

用户在 `http://127.0.0.1:4173/review?session=...&reviewer=...&seat=1` 页面发现
左右方向键无法切换上一步/下一步，但页面 UI 明确印有 `← → keyboard navigation`
提示（`app/review/page.tsx:321` 原行号）。

调查结论（根因，非监听失效）：

- 共享 hook `usePlyNavigation` 已存在于
  `app/components/replay-board.tsx:388-397`（监听 window keydown，
  ArrowLeft → -1 / ArrowRight → +1）；
- 其他两个回放页面均已接入且工作正常：
  `app/experiments/page.tsx:310`、`app/page.tsx`（内联 useEffect）；
- **`app/review/page.tsx` 从 `replay-board.tsx` 只导入了渲染组件
  `BoardSurface`，从未导入 `usePlyNavigation`，文件内也没有任何 keydown
  监听代码**——页面只是把提示文字画了出来。这是 M37A 把 `BoardSurface`
  从 `BoardPanel` 拆出来供 review 路由复用时遗漏导航 hook 的纯遗漏；
- 已排除：条件卸载、iframe、focus、事件吞掉（无 stopPropagation/
  preventDefault/tabIndex 陷阱）、状态过期（按钮路径 `changeFrame` 正常）。

### 轮次 2：Replay/Review 两套 UI 实现漂移（用户主导的架构判断）

用户判断：**两套「模式」合理，两套独立 UI 不合理**——`Replay`（忠实播放已
验证对局，无 AI 评价）与 `Review`（同一 replay 上叠加 reviewer 分析）业务
语义不同，但棋盘、玩家区、市场、贵族、时间轴、逐步导航本质是同一个
「回放工作台」，不应分别实现。核查证实漂移存在：

- `app/page.tsx` 的 `HumanReplayAudit` 手写了棋盘、银行、市场、时间轴
  （M36A 拆分时遗留的旧实现）；
- `/review` 已使用标准 `BoardSurface`；
- `docs/m36a-experiment-replay-library.md:43` 已明确「共享组件、不要第二套
  棋盘」——Human replay 是漂移，不是值得保留的产品边界。

同时识别出三个不能糊弄过去的合同问题：

1. `HumanReplayFrame` 没有 `referee_reveal`，而 `BoardFrame` 把它设为必填——
   不能靠类型断言伪装；
2. 纯 replay 没有 agreement 语义，所有时间点套 `agreed` 类属视觉误导；
3. `/?humanReplay=1` 依赖 `sessionStorage`，刷新/分享链接会失效（最终应
   session 驱动，但需后端配合，本轮不动）。

## Scope and non-goals

**做**：两个小轮次的前端收敛与修复，全部落在共享组件与既有页面内。

**不做（DEFERRED，明确记录）**：

- 统一 `ReplayWorkbench` 抽象与 `/replay?session=...` 独立路由拆分；
- 纯 Replay 的 session 驱动持久化 URL（脱离 `sessionStorage`，需要 Studio
  Host 后端支持已保存 replay 的按 session 读取，属独立授权轮次）；
- 不改 Arena / 模型 / replay 校验 / 引擎语义 / promotion。

## Contracts and invariants

1. **`referee_reveal` 可选化**：`BoardFrame.referee_reveal?: RefereeReveal`
   （`replay-board.tsx:73`）。`BoardSurface` 在无 reveal 时安全隐藏暗抽牌
   与牌堆顶揭示（`reveal && frame.referee_reveal` 守卫，行 197/302-303），
   无类型断言、无伪造数据。`HumanReplayAudit` 显式禁用 reveal 按钮
   （"Referee reveal unavailable in player audit"）并传 `reveal={false}`。
2. **时间轴语义诚实**：`ReplayTimeline` 无 `isCandidatePly` prop 时一律使用
   中性圆点 `neutral`（`replay-board.tsx:375`），不再假涂 `agreed` 绿色。
   有 review 候选判定的调用方（`app/page.tsx` 的 analysis 视图）继续显式
   传入 `isCandidatePly`，着色语义不变。
3. **键盘导航复用共享 hook**：`/review` 与 `HumanReplayAudit` 均调用
   `usePlyNavigation(frames.length, delta -> clamped functional setState)`，
   clamp 边界与按钮路径一致，不引入第二套监听实现。
4. **分析 trace 的 `referee_reveal` 仍为必填合同**：`trace-runtime.mjs` 的
   V1/V2 trace 校验（行 188-195、466-473）未改动——analysis trace 必须带
   reveal；可选化只发生在 UI 组件层，不放松数据合同。

## Implementation plan

轮次 1（fix）：
- `app/review/page.tsx`：导入 `usePlyNavigation`，函数式更新 + clamp；
  时间轴当前帧中心滚动联动（与 `HumanReplayAudit` 同款 effect）；
- `app/globals.css`：`/play` 的 `.table-gem` token chip 视觉打磨
  （同批用户反馈，纯 CSS，无语义变化）。

轮次 2（refactor）：
- `app/components/replay-board.tsx`：`referee_reveal` 可选 + reveal 守卫降级
  + `ReplayTimeline` 中性默认着色；
- `app/page.tsx`：`HumanReplayAudit` 内部手写棋盘/银行/市场/时间轴全部替换
  为 `BoardSurface` + `ReplayTimeline` + `usePlyNavigation` + 中心滚动联动。

## Iteration log

1. 轮次 1 实现（干活 agent）：接入 `usePlyNavigation`；lint + 27/27 测试通过。
   审阅（本 agent）：核实代码与验证属实，判定 IMPLEMENTED + VERIFIED。
2. 轮次 2 设计对齐：用户提出「消灭重复实现、保留模式差异」的收敛方案与
   三个合同问题；审阅方确认方向并指出 `sessionStorage` 深链为遗留。
3. 轮次 2 实现（干活 agent）：声称「彻底移除 HumanReplayAudit 私有实现」。
   **审阅纠正**：`HumanReplayAudit` 组件壳仍在（`page.tsx:400`），实际完成
   的是其内部 UI 全量收敛到共享组件；合同 1、2 落实；合同 3
   （sessionStorage 深链）明确未动。文档按实际完成范围记录，不照抄交付
   声明。
4. 最终验证（本 agent 独立重跑）：lint clean；build + 27/27 测试通过；
   `cargo fmt --all -- --check` 0；`git diff --check` 0。

## Final implementation

- `apps/replay-studio/app/review/page.tsx`：`usePlyNavigation` 接入
  （行 14 导入、行 243-245 绑定）+ 时间轴中心滚动 effect（行 248-256）。
- `apps/replay-studio/app/page.tsx`：`HumanReplayAudit`（行 400-494）改为
  复用 `BoardSurface`（行 465，`reveal={false}`）+ `ReplayTimeline`
  （行 485-491）+ `usePlyNavigation`（行 408-410）+ 中心滚动
  （行 412-419）；reveal 切换按钮显式禁用并说明原因（行 462）。
- `apps/replay-studio/app/components/replay-board.tsx`：
  `referee_reveal?: RefereeReveal`（行 73）；reveal 守卫（行 197、302-303）；
  `ReplayTimeline` 无候选判定时 `neutral` 着色（行 375）。
- `apps/replay-studio/app/globals.css`：`/play` token chip（`.table-gem`）
  视觉打磨，纯样式。

## Validation and evidence

在 `apps/replay-studio` 下执行（Windows 11，2026-09-01，本 agent 独立重跑，
非转述交付声明）：

| 检查 | 结果 |
|---|---|
| `npm run lint` | 通过，无告警 |
| `npm test`（= `vinext build` + node --test 5 个套件） | 构建成功；**27/27 pass, 0 fail**（含 `server-renders the M23 one-click review route`、`server-renders the Replay Studio product shell`） |
| `cargo fmt --all -- --check`（仓库根） | 0（工作区含 M40A 未提交 Rust 改动，与本轮无关） |
| `git diff --check` | clean |
| `git check-ignore -v handoff.md` | `.gitignore:12:/handoff.md`（保持 local-only） |

键盘导航修复（轮次 1）的浏览器实测由用户在原始报告 URL 上确认问题存在；
修复后的实机确认建议用户重访同 URL 验证（本地 dev server 由
`Start Splendor Studio.cmd` 启动，端口 4173）。

## Result and decision

- **轮次 1（`/review` 键盘导航）**：IMPLEMENTED + VERIFIED——根因为页面
  从未注册 keydown 监听（纯遗漏），接入共享 hook 后与
  `/`、`/experiments` 行为一致。
- **轮次 2（工作台收敛）**：IMPLEMENTED + VERIFIED——`HumanReplayAudit`
  的手写棋盘/银行/市场/时间轴全部消除，两个合同问题（可选 reveal、
  中性时间轴着色）按「显式建模、不伪装」原则修复。
- **DEFERRED（两项，均需另立授权轮次）**：
  1. 统一 `ReplayWorkbench` 抽象与 `/replay` 独立路由——本轮完成的是
     「两处复用同一套共享组件」，尚未抽出单一工作台组件与双模式路由
     （`/replay?session=...` / `/review?session=...&reviewer=...&seat=...`）；
     重开条件：用户需要「Open replay 立即打开、不触发昂贵分析」与
     「Review this game 启动 reviewer」的路由级区分时。
  2. 纯 Replay 的 session 驱动持久化 URL——`/?humanReplay=1` 仍依赖
     `sessionStorage`（`page.tsx:258-260`），刷新/复制链接/换标签页失效；
     重开条件：Studio Host 后端提供已保存 replay 的按 session 读取 API 后，
     将 `/play` 的 openReplay 改为跳转持久 URL。
- M07 冠军不变；无 Arena、无 promotion、无引擎/replay 语义改动。
- 本文档状态为 IMPLEMENTED / VERIFIED / PENDING_REVIEW——如需正式
  ACCEPTED 需一次独立复审。

## Known limitations

- `sessionStorage` 深链失效问题仍在（DEFERRED 2），`/play` 的
  「Open replay」按钮行为不变；
- 键盘导航为 `window` 级监听，页面内无可聚焦元素拦截场景未逐一实测；
- `tsc --noEmit` 基线错误（M37A 记录为 9）未在本轮重测，本轮未新增类型
  断言或 `any`。

## Next authorized gate

- 用户在实机确认 `/review` 键盘左右键与时间轴滚动联动行为正常；
- 若需正式关闭本轮：一次独立复审（对照本文档的合同与验证声明）；
- DEFERRED 两项各自另立轮次，不随本轮自动授权。
