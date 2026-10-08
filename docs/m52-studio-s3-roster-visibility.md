# M52 Studio S3 阵容展示收敛

Status: IMPLEMENTED / VERIFIED（定向检查）；baseline `main@bcdaca7cb33c53cc43d5dcc9e92c07be3c1aaa57`；owner 授权：2026-09-30 用户请求。未提交、未发布。

## Problem and evidence

Studio 原 registry 同时包含没有同身份对 S3 正向战绩的历史模型；Play、League、榜单、研究报告、资料、Review 和实验页各自读取不同数据源。用户要求旧弱模型退出 UI，而非删除证据或重算 Elo。初始工作树已有大量并行未提交修改；本轮只核对并收口阵容相关改动。

## Initial design

冻结展示名单由 **同身份** S3 pilot 结果及受测二进制 SHA 决定，不按版本号或对其他对手的结果推断。S3 自身为基准。列表与归档/ledger 分离；不迁移数据库，不删除权重、回放或实验，不发起新对局。

## Scope and non-goals

- Play、Model-vs-Model League 的可选阵容；League/`/ratings` Elo；首页/资料页的游戏、对手、评级事件；`/ratings/reports` 的展示行与矩阵；Review 可选评审器；实验库可见配对；已标识对手的直达回放。
- 非目标：Host 原始 API 访问控制、历史文件的删除或改写、报告重新评级、生产默认/Aran/Prism 修改、重启正在运行的 Host。

## Contracts and invariants

- `benchmarks/studio-1v1.registry.json` 保留 S3 + `heuristic-v028/v029/v030/v031/v032c`。相应对 S3 战绩（胜/平/负）依次为 139/2/115、163/1/92、149/0/107、196/0/60、173/0/83，见 `benchmarks/s4-heuristic-v0{28,29,30,31,32c}-pilot-v1.result.json`。五个 registry 可执行文件的 SHA-256 均逐一核对与其 result `candidate_binary_sha256` 相同。
- Aran 旧版本、M07/M13、旧 two-ply v0.3.2 等不自动继承另一版本的成绩；证据不足被隐藏不等于已证明输给 S3。v0.3.0 有 149/256 正向样本，故不能仅因初稿遗漏而下架。
- `app/agent-visibility.mjs` 只过滤展示，Host 分页游标及历史数值不变；解码后的比赛座位仍可用于过滤。研究报告与 Studio League Elo 各自保留原口径。旧报告若无可展示选手，显示中性归档标签，不把旧模型名呈现在行或页眉。

## Implementation plan

1. 以 result JSON 和冻结二进制确定 registry 与前端名单。
2. 覆盖所有可核定模型身份的 UI 入口；直接访问旧资料页返回中性空态。
3. 增补展示过滤与服务端渲染回归测试；运行 Studio 构建、Node 测试、Rust registry 测试及差异检查。

## Iteration log

- 初稿漏了 v0.3.0，按其 149–0–107 的同身份 S3 pilot 恢复，并绑定冻结 binary SHA。
- 个人资料比赛行实际含解码 `seats`，本地 `GameItem` 类型遗漏该字段；补类型而不改解码逻辑。评级图表改为与可见事件列表一致，只取可见对手的原始 Elo 点，不推算新点。
- 旧 SSR 测试要求研究报告展示 M22，改为验证不展示旧模型，同时保留归档场次。旧报告的赛程、哈希及记录仍在磁盘和内存中。
- Review 只展示 S3 评审器；不触及既有 Review 并行工作树中的 `action_scores` 类型问题。实验索引保留仅含受支持身份的配对，过滤后深链沿现有索引校验失败关闭。

## Final implementation

名单和路径绑定在 `benchmarks/studio-1v1.registry.json`；展示过滤在 `apps/replay-studio/app/agent-visibility.mjs`。页面接入 `/play`、`/league`、`/ratings`、`/ratings/reports`、`/ratings/[participant_id]`、`/`、`/review`、`/experiments` 和 `/replay`。新增 `tests/agent-visibility.test.mjs` 并更新 `tests/rendered-html.test.mjs`、Rust `tests/studio_registry.rs`。没有改变 ledger、原始 Elo、历史结果、Prism 训练或生产默认。

## Validation and evidence

- `node --test apps/replay-studio/tests/agent-visibility.test.mjs`：6/6 PASS，exit 0。
- `npm test --prefix apps/replay-studio`：vinext build complete、153/153 PASS，exit 0；日志位于会话 scratch `studio-tests-final.log`。
- `cargo test --offline -p splendor-cli --test studio_registry --jobs 2`：2/2 PASS，exit 0（现有编译警告）。
- `tsc --noEmit --project apps/replay-studio/tsconfig.json`：exit 2，仅 `app/review/page.tsx:569` 两处原有 `action_scores` 属性错误；本轮报告页隐式 any 已排除。
- 对 registry 五条冻结可执行文件逐一 `Get-FileHash -Algorithm SHA256`，全部等于各自 result JSON 的 `candidate_binary_sha256`；胜平负逐一读取确认。
- scoped `git diff --check`：exit 0；`git check-ignore -v handoff.md` 确认为 `.gitignore:12:/handoff.md`。

## Result and decision

**VERIFIED（上述定向检查）**：Studio 当前可选阵容和可核定身份的可见列表已收敛；历史证据保留。没有赛事晋级结论，未提交、推送或重启服务。

## Known limitations

- 这不是 Host API 授权层。已运行的 Host 若尚未重载 registry，原始 `/agents` / 对战 API 仍可能接受旧身份；UI 会在客户端过滤返回的 roster，但需在下一次正常服务启动时载入新 registry，不能声称线上即时切换。
- 没有模型身份元数据的旧 content-addressed 回放无法从 hash 安全判断对手；仍可用直接地址读取证据。标注旧对手的回放被 UI 拒绝。Review 的 3/4 人旧 M07 默认评审从 UI 隐去后，没有可用的当前阵容评审器。
- `tsc` 的既有 Review 属性错误未纳入本轮修复；UI 验收测试/构建通过不等于全量类型检查通过。

## Next authorized gate

用户若要求 Host 层强制拒绝旧 agent、清理历史回放可见性，须另行授权其数据/接口契约与存量会话迁移；不可据本轮展示过滤删除证据或重算评级。