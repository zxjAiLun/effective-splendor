# Splendor 规则与模型接入平台

使用同一套璀璨宝石规则，自行设计和训练模型，再通过标准 Agent 协议参加对战评测。模型可以使用任意框架、输入编码和权重格式。

本分支提供 2–4 人基础版规则、Python 训练环境、Rust/Python Agent SDK、外部程序裁判、回放和 1v1 评级工具。

## 安装

需要 Rust 稳定版与 Python 3.10 或更新版本。Windows 原生构建需要 MSVC C++ 构建工具。

```sh
cargo build --locked --release -p splendor-cli
python -m pip install -e .
```

将构建目录加入当前终端的 PATH。Linux/macOS：

```sh
export PATH="$PWD/target/release:$PATH"
```

Windows PowerShell：

```powershell
$env:PATH = "$PWD\target\release;$env:PATH"
```

```sh
splendor version
splendor catalog
```

也可以直接传入二进制路径，例如 `SplendorEnv("target/release/splendor")`；Windows 文件名为 `splendor.exe`。

## 使用自己的训练算法

```python
import random
from splendor_env import SplendorEnv

rng = random.Random(1)
with SplendorEnv() as env:
    catalog = env.catalog()
    state = env.reset(seed=42, player_count=2)
    for _ in range(600):
        if state["terminated"]:
            break
        observation = state["observation"]
        history = state["visible_history"]
        legal_actions = state["legal_actions"]
        action = rng.choice(legal_actions)
        state = env.step(action)
    if state["terminated"]:
        print(state["result"])
    else:
        print("达到采样上限，本局截断")
```

把随机选择替换为自己的策略，并自行收集轨迹、定义奖励和更新参数。`step` 推进一步语义动作；选择贵族时仍可能是同一玩家行动。返回值为字典，字段见 [训练环境](docs/environment.md)。

## 将模型交给裁判评测

Agent 是一个独立程序。输入为玩家观察、可见历史和合法动作，输出为其中一个动作。Python 入口示例：

```python
# my_agent.py
from splendor_env import run_agent


def choose_action(decision):
    # 在这里调用自己的模型，返回 decision.legal_actions 中的一个对象。
    return decision.legal_actions[0]


run_agent(choose_action, name="my-model", version="1.0.0")
```

将其注册为 `{"program":"python","args":["my_agent.py"]}`，即可与任意实现相同协议的程序对战。模型作者同时提供推理入口、权重和运行依赖；权重留在评测机器上。

运行 Rust 随机代理与 Python 随机代理的示例对局：

```sh
mkdir -p outputs
splendor run-match --config examples/match.json --report-out outputs/match.report.json --replay-out outputs/match.replay.json
splendor verify-replay --input outputs/match.replay.json
```

PowerShell 可用 `New-Item -ItemType Directory -Force outputs` 创建输出目录。每次运行使用新的输出文件名。配置中的 `python` 应指向安装了本包的解释器；如果使用虚拟环境，可写绝对路径。

批量交换座位评测：

```sh
splendor eval --plan examples/evaluation.json --out-dir outputs/evaluation
```

1v1 循环赛与 Elo：

```sh
splendor rating-plan --registry examples/registry.json --config examples/rating.json --out outputs/rating-plan.json
splendor rating-run --plan outputs/rating-plan.json --out-dir outputs/rating
```

## 代码结构

| 目录 | 职责 |
|---|---|
| `crates/splendor-catalog` | 90 张发展卡、10 个基础贵族与规则参数 |
| `crates/splendor-core` | 合法动作、状态推进、玩家视角、终局与名次 |
| `crates/splendor-protocol` | NDJSON v0.5 消息 |
| `crates/splendor-agent` | Rust Agent 运行时与随机基线 |
| `crates/splendor-arena` | 独立程序对战、超时与故障记录 |
| `crates/splendor-replay` | 裁判回放与逐步校验 |
| `crates/splendor-eval` | 座位轮换、评测汇总与 1v1 评级 |
| `crates/splendor-cli` | 规则环境与命令行入口 |
| `python/splendor_env` | Python 规则环境与 Agent SDK |
| `fixtures/` | 固定规则与协议测试样例 |

进一步阅读：[规则与数据](docs/rules.md)、[训练环境](docs/environment.md)、[Agent 协议](docs/protocol.md)、[评测与交付](docs/evaluation.md)。

## 开发验证

```sh
cargo test --locked --workspace --all-targets
cargo build --locked -p splendor-cli
python -m unittest discover -s python/tests -v
```

Python 测试默认使用 `target/debug/splendor`，Windows 使用同目录下的 `.exe`。可通过 `SPLENDOR_EXECUTABLE` 指定其他构建。CI 在 Linux、Windows 和声明的最低 Rust 版本上运行验证。

## 使用边界

Python 环境通过持久子进程传输语义 JSON，适合作为通用训练入口；大规模训练可在同一规则 API 上实现原生批量绑定。它不是 Gymnasium 接口，奖励与采样截断由训练程序定义。

Arena 提供进程隔离与协议校验，不是操作系统沙箱。仅运行你信任的参赛程序，或在独立受限环境中执行。程序只能从玩家协议获取对手信息；裁判完整回放应在比赛结束后用于分析。
