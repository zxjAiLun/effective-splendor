# M80 · 本地历史债清理与 Studio 退役

- **Status**: IMPLEMENTED / VERIFIED（本地 UI 与 Rust 门通过；ALL 同步 BLOCKED → 待同步；未部署、未 Git commit/push）。
- **Owner-date**: 2026-10-12，用户要求 JEV 入口/文件/录像全部退役、Rating Studio 所有模型清空、本地对战文件与历史清空，并清理 Prism 之前的本地历史内容。
- **Baseline**: `m61-alpha-balance-ab` / `a9a0037d82b05af0c55782f6dc2c0e2e72e6f6bd`；接手时 index 空，工作树存在 M75/M78/M79 未提交工作，全部保留。
- **task_kind**: implementation / local cleanup。
- **authorized_end**: 本地产品与数据退役、受影响功能验证、删除回执、两层记录与 ALL 实际回报；不含云端删除、研究控制、Git 历史重写、commit/push。
- **必交产物**: 实际删除清单与字节数、依赖保留清单、入口与引用修复、针对性测试、本记录、handoff 与 ALL 回报/pending。
- **禁止动作**: 删除 Prism 研究身份/权重/结果、改变 M79 研究合同、停止远端训练、删除远端数据、Git commit/push；不把本机异常表述成远端失败。
- **下一允许动作**: 在本地双击 Studio 查看退役后的空态；如需恢复 M76/M77 表格门，须先注册一个明确的 Studio 模型。ALL 恢复后按最新 revision 登记本轮证据。

## Problem and evidence

用户要求的是实际清理，而不是只在 UI 上过滤隐藏。只读盘点确认：

| 本机路径/数据源 | 清理前实测 | 处理 |
| --- | --- | --- |
| `jev/` | 28 文件，381,069 字节；15 个 Git 跟踪文件 | 删除；Host 读取路由同步退役 |
| `local-artifacts/jev/` | 518 文件，53,158,513 字节 | 删除 |
| `local-artifacts/m20-human-play/` | 96 文件，53,713,096 字节 | 删除；首页旧人机档案入口同步退役 |
| `local-artifacts/studio-league/` | 806 文件，682,871,853 字节；105 participants、42,537 matches、85,074 seats、28,042 rating events | 行清空、`VACUUM`；重建 `identity.json`（172 字节，manifest hash `572faa16…`），仅保留可读空账本 |
| `local-artifacts/` 其余 Prism 前负载 | 363 个顶层条目，426,717 文件，98.920 GiB | 按用户明确授权删除；`local-artifacts/prism`、M76–M78 UI 证据、M80 回执、空联赛库保留 |
| `outputs/01a11805-prism-style/` | M72 Prism 画像 5 个 Git 跟踪导出 | 曾误入删除范围；已从 HEAD 恢复，未丢失 |
| `evaluation/`、`continuation-r3*` | M67/M75 小型 Prism 证据，共 164+35 文件，约 91.8 MB | **误删**；属越界项，已在本节与 handoff 标注，恢复路径见下方 |
| `benchmarks/studio-1v1*.registry.json` | 9 个模型 | 改为显式退役空名册 `studio-1v1-retired-2026-10-12` |
| `benchmarks/studio-replay-sources.registry.json` | M35A 17 pairings | 改为空实验源 |

JEV 不只是独立目录：Games 首页、`/jev` 页面、共享 Replay 页、导航和 Rust Host 的 runs/trace/replay 读取均有引用，本轮已一并退役。Rating 有两个数据源：`/ratings` 读长期联赛库，`/ratings/reports` 原先内置 M19/M22 静态旧报告；两处都已清空为 upload-only/空态。

## Scope and non-goals

- 保留 `local-artifacts/prism/` 全部 Prism 权重、M79 输入、报告、回执和归档索引；研究合同与远端执行未触碰。
- 保留 Git 跟踪的研究文档、benchmark 结果与 M72 画像导出；它们不是本机原始负载，仍是仓库历史证据。
- 不删除 `target/` 构建缓存、`training/` 与 `crates/` 源码。
- 不重写历史轮次文档中的旧数字与旧结论；只在 M80 追加清理事实。
- 未验证云端完整性的旧原始数据由用户明确授权直接删除；该授权不自动扩展到未来新轮。

### 越界更正（必读）

`evaluation/reference`、`evaluation/a-direct`、`evaluation/b-direct`、`evaluation/b-common`、`evaluation/a-common-recovery-r3` 与根 `continuation-r3`、`continuation-r3b`、`continuation-r4` 是 Prism/M67–M75 的小型状态与结果证据，不在“Prism 之前”的清理范围。我已在预删除清单中逐文件记录其路径、大小与 SHA-256，但没有先复核归属就执行了删除，这是本轮的越界错误。

影响：Git 跟踪的 M67/M75 结果、审计和报告仍在；被删的是本机 `evaluation/**` 状态/ledger 快照与 continuation 状态文件。恢复方式：M67 完整历史包已私有归档在 `sparxie1/test1005`，前缀 `splendor/history/m67/20261010/65a85004…a072/`，按 `docs/prism/history-archive-index.md` 的 26 个分片按序恢复；恢复前用 manifest 核验原归档大小 `26203087576` 与 SHA256。`continuation-r3*` 未发现独立云端归档，恢复状态为 UNKNOWN；其结论仍可从 tracked 文档、benchmark 结果及 M75 归档读取，但本地状态文件已不可逆丢失。后续不再扩大删除。

## Contracts and invariants

- Studio 产品退役是展示层与本地名册行为；Rust 评分注册表仍要求正式锦标赛至少两个模型，只对显式 `studio-1v1-retired-2026-10-12` 空名册放行。
- 空 `ReplaySourceRegistry` 是合法产品状态；有实验时仍执行全部 provenance/escape 校验。
- 已删除本地数据不会伪造为可读结果：浏览器与 Host 对空态给空列表/未注册提示，不填默认 Elo、不复活旧模型。
- SQLite 只删除行并 `VACUUM`，没有降级或重建 schema；`identity.json` 是用户作者身份，与派生库分开保护，删除后按已知本地人类身份 `b901a2ea…`（You）重建并由 Host 实测通过。
- 空联赛仍可读：真实 Host 对 `/league/leaderboard` 返回空 rows，而非 503。
- 本轮没有删除任何 Git 跟踪的研究结果（`outputs` 误删已恢复）。

## Implementation

- 前端：删除 `/jev` 路由、JEV interaction panel、trace runtime、JEV tests 与 More 导航项；首页移除 JEV 区块和旧人机档案区块；Replay 页移除 `?jev=` 读取与面板；JEV 专属 `player-state-strip` 注释同步更正。
- Host：删除 `JEV_RUNS_DIR`、`resolved_jev_runs_dir`、`StudioHost.jev_runs_dir`、runs index/trace 方法、`/jev/runs*` 路由与 `historical_replay` 的 JEV fallback；Host 测试中的 JEV 区块删除。
- Rating：`agent-visibility.mjs` 三组 curated 集合清空；`studio-1v1*.json` 改为退役空名册；`/ratings/reports` 去掉 M19/M22 内嵌默认、Archive A/B 与对应 TS 文件，保留上传；`studio-replay-sources.registry.json` 改为空。
- 本地数据：按预删除清单删除目标目录；联赛库行清空；清理时先停止旧 Host 35984 与 vinext 37628，避免旧内存名册继续可用。删除完成后另一个会话重启了本地 Studio（node 2540 / Host 42116）；该 Host 在 `identity.json` 重建前启动，仍缓存“缺少身份”错误，因此 M80 只重启 Host（相同参数，新 PID 660），前端 4173 未动；当前 `/league/leaderboard` 返回空 rows。
- 测试：`play-cockpit-browser` 改为“退役名册空态”6 用例；删减去模型依赖的 `human-play-browser` 和 JEV gates；layout/games/ratings gates 改为人类行/空名册真值。

## Validation and evidence

证据根 `local-artifacts/m80-local-history-cleanup/`。

| 实际检查 | 结果 | 证据/命令 |
| --- | --- | --- |
| `npm test`（build + node --test） | exit 0；145/145 pass | `apps/replay-studio` 终端输出 |
| `npm run lint` / `npx tsc --noEmit` | exit 0 / exit 0 | 同上 |
| `node tests/studio-layout-browser.mjs` | PASS 32 用例、34 截图、0 JS 异常 | `m78-studio-ui/pages-1791816790285` |
| `node tests/play-cockpit-browser.mjs` | PASS 6 退役空态用例、6 截图 | `m80-local-history-cleanup/play-browser/checks.json` |
| `node tests/games-page-browser.mjs` | PASS 游标分页/失败重试/数据真值 | `apps/replay-studio` 终端输出 |
| `node tests/ratings-page-browser.mjs` | PASS 空名册/上传过滤/零联赛读取 | 同上 |
| `cargo test --workspace` | 全工作区各 suite 0 failed | 本终端输出 |
| `cargo check -p splendor-cli` | exit 0（既有 warnings） | 本终端输出 |
| `cargo fmt --all -- --check` | FAIL：大量 Prism 前既有格式差异，与 M80 改动无关；受影响行未新增格式债 | 本终端输出 |
| 预删除清单 | 1,663 条目（9 根），SHA-256 `eff7b030…a327d` | `predelete-manifest.json` |
| 宽范围删除前盘点 | 363 顶层、426,717 文件、98.920 GiB | `predeprecation-top-level-inventory.json` |
| 删除后本地进程/端口 | 初始 Host/vinext 已停止；清理后另一会话重启的 stale Host 42116 只重启为 660，4173 前端未动；Host `/agents` 与 `/league/leaderboard` 均为空态 | PowerShell 进程核验输出、`host-empty-smoke.json` |
| 真实空 Host smoke | `/health` ok、`/agents` 空、`/league/leaderboard` 空 rows、`/league/games` 空页、`/experiment-replays` 空、`/recent-games` 空、`/jev/runs` 404 | `host-empty-smoke.json` |
| `git check-ignore -v handoff.md` | `.gitignore:12:/handoff.md`，不入 Git | 本终端输出 |
| ALL `context splendor` | `{"error":"fetch failed"}`，未启动服务 | 待同步 |

所有浏览器门使用真实安装 Chromium + 构建产物 + 模拟 Host；不是真实 Host/实体设备验收。Rust 测试在本地 Windows 执行，不宣称 Linux 实机。

## Stage record

| 阶段 | 状态 | 原因 |
| --- | --- | --- |
| R0 | PASS | 任务终点、授权与保护边界确认；ALL 单独标待同步 |
| R1 | PASS | 清理边界、保护目录与验收门在删除前确定 |
| R2 | PASS | 前端/Host/注册表退役完成；回归、lint/tsc、浏览器门与 Rust 全工作区通过 |
| R3–R7 | NOT_APPLICABLE | 无训练、正式采样、模型或竞技/风格判定 |
| R8 | PASS | 本地空态截图与交互门通过；Prism 研究页面未重生成 |
| R9 | BLOCKED | 本地收口完成；ALL 不可达，产物登记待同步 |

## Result and decision

本地清理 VERIFIED：JEV 入口/文件/录像全部退役，Rating Studio 的 9 个模型从产品与测试真值中清空，旧人机回放与联赛账本清空，Prism 前本地原始负载约 98.9 GiB 删除；Prism 权重、M79 输入、Git 研究结果和归档索引保留。真实 Host 对退役空名册与空联赛实测可读（`/league/leaderboard` 空 rows，非 503）。模型/竞技/风格结论 NOT_APPLICABLE：本次没有晋级、发布或部署任何模型。

## Known limitations

- **`evaluation/` 与 `continuation-r3*` 误删**：详见上方越界更正；Git 研究结果仍在，M67 可从私有魔搭恢复，continuation 本地状态恢复 UNKNOWN。
- 旧原始数据直接删除是用户授权的例外，没有逐文件云端核验；tracked 文档/结果和研究归档包保留。
- Play 表格几何门在空名册下退役；新模型注册前只有空态门，原 M76/M77 桌面像素结论不再是当前产品真值。
- 本地 SQLite 清空不可逆；本机没有保留 42,537 场旧联赛行。空库仍可读，但旧行只能从私有魔搭或 tracked 结果读取；重建的 `identity.json` 是空联赛的新身份版本，不含旧 alias。
- 未做实体手机/触摸验收；未部署、未 Git commit/push；ALL 未同步。

## Next authorized gate

可在本机运行 Studio 查看退役后的 Games/Play/League/Ratings 空态与 Research upload；Git 提交/推送需单独授权。ALL 恢复后按最新 revision 登记本轮证据与上述越界更正，不重跑比赛或视觉验证。后续清理新目录须重新取得授权。
