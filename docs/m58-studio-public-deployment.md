# M58 Studio 公网部署 — pearllover.site/splendor

Status: IMPLEMENTED / VERIFIED（部署与真机功能验证完成；非竞技实验，0 新评测局入正式证据）
Baseline: `main@bcdaca7` + 既有 dirty 工作树（v0.3.1 快照即该状态，见 S4.11）
Owner-date: 2026-10-03（agent 执行，用户授权："给域名下建立 /splendor，允许 play、play后review、elo 三个功能"）

## Problem and evidence

用户要求在 server1（腾讯云 VM-0-10-ubuntu）上以 `https://pearllover.site/splendor` 发布
Studio 的三个功能：

1. **Play**：与 Heuristic v0.3.1、Prism v0.1、Prism v0.1.1、Prism Alpha v0.1.0 对战；
2. **Play 后 Review**：以三个 Prism 模型（v0.1 / v0.1.1 / Alpha v0.1.0）作为审查员；
3. **Elo**：Studio League 天梯，初始 1500。

证据：三个功能此前只在本地（127.0.0.1:4173/43120）可用；`apps/replay-studio` 的
`API_BASE` 硬编码 `http://127.0.0.1:43120`，host 的 CORS 只允许本地 UI origin，
Windows 注册表命令均为 `.exe` 路径；server1 无 cargo。

## Initial design

- 复用现有栈，不新写对局/审查/Elo 逻辑：Rust `splendor studio-host`（API，仅绑
  127.0.0.1:43120）+ vinext 生产构建 UI（127.0.0.1:4173）+ nginx 同源反代。
- UI 挂在 `/splendor` 子路径：vinext 支持 `basePath`（`config/next-config.js` 读取
  `config.basePath` 并派生 assetPrefix）；API 走 `/splendor/api/` 前缀剥离反代到 host，
  同源请求不触发 CORS，host 的单一 ACAO 头由 nginx `proxy_hide_header` 隐藏。
- Linux 构建在本地 WSL Ubuntu 24.04（与 server1 同 glibc）完成后直接投递二进制，
  不在 2 核/1.9GB 内存的服务器上编译。
- 注册表新建 `*.linux-public.json` 变体：agent ID、显示名、种子、权重路径逐字保留，
  仅 program 换成 Linux ELF 路径；不改动任何冻结注册表/实验文件。

## Scope and non-goals

- 范围：上述三个功能的公网可用性；部署持久化（systemd + league 落盘）。
- 非目标：多会话/多玩家并发（host 为单桌单会话架构，保持原样）；认证/注册；
  正式竞技评测、模型晋级、共享池变更；本地 Windows studio 流程改动；
  `apps/splendor-pool`（未部署，用户未要求）。

## Contracts and invariants

- 部署的模型身份逐字节不变：三个 Prism 权重 SHA 与冻结注册表 `checkpoint_hash`
  一致（`5db70b77…` / `a2301f08…` / `b5e68e00…`）；Heuristic v0.3.1 按当前工作树源码
  构建（S4.11 记载 v0.3.1 = main@bcdaca7 + dirty 快照；`heuristic_v02/` 模块目录即
  其源码，冻结候选 exe `6a02b2ab…` 为该源码的 Windows 构建）。
- agent seeds 逐字保留：`heuristic-v031 --seed 20260926`、`prism-v01 --seed 51000001`、
  `prism-v011 --seed 54030001`、`prism-alpha-v01 --seed 55010001`。
- UI 改动全部环境变量门控，默认值保持本地行为：`VITE_STUDIO_BASE_PATH`
  （next.config basePath + `BASE_PATH` 导出）、`VITE_STUDIO_API_BASE`（API_BASE）。
- League 数据持久化于 `/home/ubuntu/splendor/local-artifacts/studio-league/`
  （identity.json + league.sqlite3），由 `--project-root` 锚定。

## Implementation plan

1. WSL 构建 Linux release 二进制；两端冒烟（run-match 真局）。
2. 打包源码/注册表/权重/二进制 → server1 `/home/ubuntu/splendor`。
3. server1 npm ci + `vinext build`（带 basePath env）→ systemd 双服务。
4. nginx 443 server 块追加 `/splendor` locations。
5. 首跑身份初始化；端到端验证 play→elo→review。

## Iteration log

- **WSL 命令注入问题**：`wsl -- bash -c "...$VAR..."` 被 Git-Bash 预展开破坏；
  全部改为脚本文件经 `bash /mnt/e/...` 执行（配 `MSYS_NO_PATHCONV=1`）。
- **reviewer 注册表校验失败**：首版仅裁到 s3+3×Prism，host 拒启
  （`no reviewer defaults for 3-player replays`）；按原注册表补回
  `m07-determinization-champion`（`default_for_player_counts: [3,4]`，无 artifacts），
  UI 可见性过滤使其不出现在下拉中。
- **人类身份缺失**：`POST /games` 返回 `human identity authority is missing`；
  host 要求已存在的 identity manifest（`IdentityManifestV1::load`，不自动铸造）。
  按 `new()+ensure_local_human()` 的首跑语义在服务器铸造
  `local-artifacts/studio-league/identity.json`（UUIDv4，display "You"）；
  league.sqlite3 由首次 booking 的 `open_completion_league → open_league` 自动建库。
- **E2E 脚本状态词**：review job 终态为 `completed`（脚本初版轮询
  `ready/complete/done` 漏判）；实际 job 早已完成。
- **跨机非逐位一致**：同一冒烟种子 20261003 在 WSL（11:16/58 ply）与
  server1（8:16/50 ply）比分不同 —— rollout/浮点跨 CPU 非逐位确定，属预期；
  不影响模型身份（权重 SHA 唯一），记录为已知限制。

## Final implementation

- **服务器**：`/home/ubuntu/splendor`（源码树 + `target/release/splendor` +
  注册表 + 权重 + `apps/replay-studio` 构建产物）。
  Linux 二进制 SHA-256 `f76f51283c6fa99450e4079900c01fcb0c5aa9041402e53b81f7cf6ee876c1ab`
  （WSL Ubuntu 24.04 cargo release；投递包 SHA-256 `57f94c0afe628ae30300f7c467bb09d32b5e98a44ace26900e7dcfa27e1837f7`）。
- **systemd**：`splendor-host.service`（studio-host，registry
  `benchmarks/studio-1v1.linux-public.json`、reviewer-registry
  `benchmarks/studio-reviewers.linux-public.json`、`--port 43120 --project-root
  /home/ubuntu/splendor`，Restart=on-failure）、`splendor-ui.service`
  （`vinext start --hostname 127.0.0.1 --port 4173`）。均 enabled+active。
- **nginx**：`/etc/nginx/sites-available/pearllover.site`（备份
  `pearllover.site.pre-splendor-20261003`）443 块内追加：
  `location /splendor/api/ → proxy_pass http://127.0.0.1:43120/`（前缀剥离、
  隐藏 ACAO、120s 超时）、`location = /splendor → 301 /splendor/`、
  `location /splendor/ → proxy_pass http://127.0.0.1:4173`。
- **仓库改动（本 round；随本 round 提交或保留于工作树）**：
  - `apps/replay-studio/next.config.ts`：`VITE_STUDIO_BASE_PATH` 门控 basePath（已提交）；
  - `apps/replay-studio/app/api-base.mjs`：`API_BASE` 支持
    `VITE_STUDIO_API_BASE` 构建期覆盖 + 导出 `BASE_PATH`（已提交）；
  - `apps/replay-studio/app/play/page.tsx`：两处 `window.location.assign`
    （/replay、/review）改走 `BASE_PATH` 前缀（next/link 之外的裸跳转）；
    该文件同时承载 M55/M56 Studio 接入的既有未提交改动，为避免混入他人
    未提交内容，保留在工作树不单独提交（server1 部署使用工作树实际文件）；
  - `benchmarks/studio-1v1.linux-public.json`（4 agents）、
    `benchmarks/studio-reviewers.linux-public.json`（s3 + m07 + 3×Prism，
    m07 仅为满足 host 对 3 人局默认审查员的校验，UI 不可见）（已提交）。

## Validation and evidence

- **冒烟（run-match 真局）**：WSL `v031 vs prism-v011` seed 20261003 →
  11:16/58 ply，exit 0，replay final hash `75a9b8cf…`；server1 同配置 →
  8:16/50 ply，exit 0，hash `30d5d4dd…`。
- **端到端（公网 https，脚本 `local-artifacts/studio-deploy/e2e-verify.py`）**：
  `POST /splendor/api/games`（prism-v011，human_seat 0，seed 20261003001）→
  真机整局 30 手后 `0:16 prestige_threshold` 结束；booking `inserted`，
  **Elo：You 1500.0→1484.0（−16），Prism v0.1.1 1500.0→1516（+16）**（K=32，
  双方均从初始 1500 起步）；`/league/leaderboard` 返回两条记录（provisional）。
  `POST /reviews {session, reviewer_id: prism-v011-review}` → job `review-1`
  **completed，60/60 decisions**，bundle 2,486,050B，帧含
  `review_result.recommended_action / action_scores / decision_path /
  n1_proposal / m07_proposal`。
- **浏览器真机（ZCode IAB）**：`/splendor/play` 渲染完整牌桌与 booking 面板
  （"You: 1500.0 → 1484.0"）；"Review this game" 选择器显示 S3 默认 +
  三个 Prism 审查员；点击 Prism v0.1.1 Review 跳转
  `/splendor/review?session=…&reviewer=prism-v011-review&seat=0`（BASE_PATH
  修复生效）并渲染逐帧 logits/概率/推荐；`/splendor/ratings` 显示
  Prism v0.1.1 1516（1-0-0）、You 1484（0-0-1），档案链接在 /splendor 下。
- **无回归**：`npm test --prefix apps/replay-studio` **153/153 PASS**（exit 0，
  2026-10-03）；`curl https://pearllover.site/splendor/play` 200，
  `/splendor/api/health` `{"status":"ok","mode":"studio_host"}`，
  `/agents` 恰为 4 个目标模型，`/reviewers` 5 个（3 Prism + s3 + m07）。

## Result and decision

三个功能在 `https://pearllover.site/splendor` 全部上线并经真机验证：
Play（4 对手）、Play→Review（3 Prism 审查员）、Elo（Studio League，
初始 1500，K=32，人类与引擎同场记账）。部署为独立运行实例，未改动任何
本地冻结实验、正式证据、默认模型或共享池状态；未进行竞技晋级判定。

## Known limitations

- **单桌单会话**：host 一次仅持一局、一个人类会话（架构既定）；多人同时访问
  会互相占用/拒绝。所有访客共享同一 "You" 身份与同一天梯（无账号体系）。
- **跨 CPU 浮点非逐位一致**：rollout 类 agent 在不同 CPU 上同种子可产生不同
  比分（见迭代日志）；模型身份由权重 SHA 保证。
- 服务器仅部署二进制与产物，无 Rust 工具链；更新需在 WSL 重构建并重投。
  node/cargo 均不在 server1（node 22.22.2 已存在，cargo 未装）。
- 服务器磁盘 82%（8.5G 余量）；部署占 43MB，无膨胀风险但需留意整盘水位。
- host 无认证，公网任何人可开局/审查（Elo 天梯为公共可写）；nginx 层无限流。

## Next authorized gate

无自动后续。若需多会话/账号/限流或 splendor-pool 上线，需用户另行授权。
