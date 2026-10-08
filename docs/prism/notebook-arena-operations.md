# DSW SSH 通用对战操作

M64 原 Notebook 请求已由用户改为 SSH 部署。Notebook 界面 DEFERRED，后台通用对战代码复用；历史文件名保留，不代表必须打开 Notebook。模型正式验收 NOT_RUN，M63 原失败与合同保持。

两台独立持久化目录：DSW 为 `/mnt/workspace/splendor-dsw`；DSW2 为 `/mnt/workspace/splendor-dsw2`。通过 `ssh dsw` / `ssh dsw2` 使用现有链路。本工具不修改隧道、公私钥、已有 supervisord 或实例启动钩子。

## 准备和运行

在相应目录运行 `bash scripts/prism_dsw_manage.sh profile` 检查有效 CPU、cgroup v1/v2 和内存限额。默认预留 CPU：4 核用 3 workers，8 核用 6 workers；内存软预算为有效上限的 75% 与可用内存的 80% 中较小值。不是专属 cgroup 硬隔离，不提供训练命令。

请求 JSON 只用于操作；结果会生成完整 Markdown 与 HTML。所有模型须使用完整名称，未发布检查点必须标注。示例：

```json
{
  "format": "prism-dsw-arena-request-v1",
  "engine": "/mnt/workspace/splendor-dsw2/bin/splendor",
  "metrics_program": "/mnt/workspace/splendor-dsw2/bin/s4_batch_metrics",
  "candidates": {
    "balance": {"weights": "/mnt/workspace/splendor-dsw2/models/balance.json", "display_name": "Prism Balance v0.1.0", "mode": "sample"}
  },
  "opponents": {
    "heuristic": {"kind": "heuristic", "display_name": "Heuristic 开发快照（agent-heuristic-v02，greedy）"}
  },
  "seeds": [64000000, 64000001],
  "resources": {"workers": 6, "shard_seed_blocks": 1, "wall_hours": 0.5, "cpu_hours": 2, "storage_gib": 4, "instance_hours": 8, "expiry_margin_minutes": 45}
}
```

每个候选×对手×种子恰好交换座位两局；上述是 4 局开发诊断，不是正式验收。可任意选择已导出的模型、对手及有界种子；局数由网格决定，不能奇数局或重复种子。prepare 不启动游戏：

```bash
bash scripts/prism_dsw_manage.sh prepare --request requests/my-run.json --work runs/my-run
bash scripts/prism_dsw_manage.sh start --work runs/my-run
bash scripts/prism_dsw_manage.sh status --work runs/my-run
bash scripts/prism_dsw_manage.sh stop --work runs/my-run
bash scripts/prism_dsw_manage.sh start --work runs/my-run
bash scripts/prism_dsw_manage.sh archive --work runs/my-run --output runs/my-run.zip
```

后台与 SSH/Jupyter 会话分离。安全 stop 停止新派发，完成在途 shard 后 STOPPED_SAFE；start 仅继续未派发部分，已完成回放与 hash 全复核。`stop --force` 会保留半成品并 FAILED_PARTIAL_NO_RETRY；不会为了得到结果自动重跑。日志在 `runs/my-run/attempts/`，报告在 `report.md` / `report.html`。

## DSW2 实例期限与恢复

DSW2 每 8 小时换实例是用户提供的运行条件。启用 `instance_hours: 8`，按容器 PID1 创建时间计算截止，预留至少 45 分钟；不能按宿主 `/proc/uptime` 推算实例年龄。prepare 拒绝超过剩余期限的预算，运行到截止则停止进程树。常规大任务建议最多 6 小时并先查看实例剩余时间。

实例更换后使用持久化目录里的独立 `.venv`。若平台 Python 版本改变，先重新创建该目录的虚拟环境并按 `notebooks/requirements-prism-arena.txt` 安装固定版本。依赖变化会阻止旧执行，不会悄悄换数值环境。原生工具已按 SHA 固定，不要求目标机安装 Rust。

```bash
bash scripts/prism_dsw_manage.sh recover --work runs/my-run
```

recover 只用于已死亡的自有 runner：完整但尚未记账的 shard 可验核并提交；任何已派发且无完整回执的 shard 都使整批 FAILED_PARTIAL_NO_RETRY，未完成局不得自动补跑。全部派发均已提交时才允许安全继续。它不会启动训练、杀其他进程或改已有 SSH 自愈配置。实际跨 Pod 重建验收尚未进行，不能仅因目录持久化就宣称已通过。

## 来源与下载

代码和模型运输包使用逐成员 SHA 校验及目录约束；权重、回放、日志在 publication policy 的 ignored 目录，不能加入 Git。当前实现没有 push，远端 clone 旧 HEAD 不包含新实现，已部署机器使用本地源码快照。最终原生 Linux 工具来自本机WSL的x86_64构建，按低于DSW glibc2.35的目标链接；原不兼容ARM字节及失败记录保留。二进制 SHA 与源码快照 SHA 分别记录。

例如本地抓取 DSW2 归档：`scp dsw2:/mnt/workspace/splendor-dsw2/runs/my-run.zip .`。HTML 可本地打开。双方数据表按身份合并，推理/决策延迟为 NOT_MEASURED；CI 和上下箭头都是描述性诊断，没有正式晋级含义。

已完成的双机工程烟测及完整双方数据：[Markdown](m64-dsw-arena-smoke.md) / [HTML](m64-dsw-arena-smoke.html)。它们不构成模型验收。smoke-v5保留实际源码；历史核验可运行 `.venv/bin/python -B runs/smoke-v5/runtime-snapshot/scripts/prism_dsw_arena.py verify --work runs/smoke-v5`。新代码/原生工具更新须使用新执行目录并保留旧来源，不在未完成run中换版本。

## DSW 持久化 Python 环境接入（2026-10-05 统一入口）

为避免实例更换或重启后丢失运行时依赖，两台 DSW（`dsw` 独立云盘、`dsw2` NAS）均已在 `/mnt/workspace` 建立持久化 Python 工具链与虚拟环境。完整说明见远端 `/mnt/workspace/ENVIRONMENT.md`。

### 目录结构与入口

- `/mnt/workspace/tools/`：独立 `uv`、`uvx` 二进制及 uv 托管的 Python 解释器（Python 3.12.15，不指向系统 `/usr/local`）。
- `/mnt/workspace/envs/`：隔离虚拟环境。
- `/mnt/workspace/cache/`：持久化下载缓存（uv、pip、huggingface、torch、modelscope）。
- `/mnt/workspace/env.sh`：统一环境激活脚本。

### Splendor 可用环境

| 环境别名 | 路径 | 核心依赖 | 适用场景 |
|---|---|---|---|
| `splendor` | `/mnt/workspace/envs/splendor-arena-py312` | Python 3.12.15 / NumPy 2.2.4 / psutil 7.0.0 / Markdown 3.8（无 Torch） | 纯 CPU 对战、批处理 metrics、通用评测与报告 |
| `cpu` | `/mnt/workspace/envs/cpu-py312` | Python 3.12.15 / Torch 2.13.0+cpu / NumPy 2.5.1 / psutil 7.2.2 / ipykernel | 交互式调试、Jupyter Notebook 内核、含 Torch 的前向推理 |

### 交互与脚本使用

终端交互：

```bash
source /mnt/workspace/env.sh
workspace-env list
ws-use splendor
python -c "import numpy, psutil, markdown; print(numpy.__version__)"
```

非交互与脚本调用（无需依赖 shell 激活）：

```bash
# 直接指定解释器
/mnt/workspace/envs/splendor-arena-py312/bin/python your_script.py

# 或通过 workspace-env 运行
/mnt/workspace/tools/bin/workspace-env run splendor your_script.py
```

Jupyter Notebook：在内核菜单中选择 **Workspace cpu (persistent)**。

### 与历史轮次的关系及约束

1. **已有历史任务不静默切换**：历史已冻结/已执行的任务（如 M64 通用对战使用的 `/mnt/workspace/splendor-dsw/.venv`、M66 专有安装的 `/mnt/workspace/splendor-m66-alpha/.venv`）保留原解释器与 hash 绑定，不自动替换已有启动器或执行目录。
2. **版本与数值边界**：`splendor-arena-py312` 的 NumPy（2.2.4）与 psutil（7.0.0）与历史评测环境完全对齐；但 `cpu-py312` 使用较新的 Torch 2.13.0+cpu 与 NumPy 2.5.1。若新训练任务要求严格的旧版 PyTorch 浮点对齐（如 M66 固定的 Torch 2.6.0+cpu），仍须在任务前显式检查或单独冻结，不可直接将依赖导入成功当作数值全等。
3. **实例恢复**：实例更换后，仅需 `source /mnt/workspace/env.sh` 即可继续使用持久化环境；若 shell 配置丢失，执行 `/mnt/workspace/tools/bin/workspace-env restore-shell`。这不等于已完成未竟比赛的自动重放，所有比赛恢复仍遵循本文件原有的 recover 与 0 自动重试规范。

