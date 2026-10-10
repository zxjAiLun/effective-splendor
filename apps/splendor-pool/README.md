# Splendor Arena Pool (Splendor 对战池)

基于单桌自主调度的 Splendor 1v1 模型对战池系统，具备模型入池、适配器、自动对局、数据落盘、Elo 结算、终端/Web 双看板以及项目规范战术数据统计。

## 功能特性

1. **单桌无放回加权抽样**：
   - 所有活跃模型在同一个池中竞技（单桌），根据权重自动抽取双方并随机化座次（消除先手偏差）。
2. **标准 Elo 结算系统**：
   - 初始 Elo 1500，K=32（可配），每局结束后根据胜负与期望胜率进行原子结算，并持久化 Elo 历史走势。
3. **原生 Splendor 规则与判定**：
   - 复用仓库内置的 `splendor run-match` 引擎，由官方裁判输出 arena-report 与 match-replay 进行胜负判定。
4. **项目规范统计口径**：
   - 基础数据：胜/平/负、总胜率、先手胜率 (Seat 0)、后手胜率 (Seat 1)、局均得分、胜负分差。
   - 战术指标：VP/Turn、VP/Ply、局均回合数、局均步数、场均购卡/折扣、预留(获取/买回/烂手)与兑现率、场均贵族获取。
   - 两两对阵交叉小计 (Head-to-Head records)。
5. **双看板支持 (SSH 终端 + 浏览器 Web)**：
   - **终端看板**：SSH 连接后随时运行 `splendor-pool status` 或 `splendor-pool dashboard` 查看 Rich / ASCII 表格。
   - **Web 看板**：监听 `127.0.0.1:8720`，支持端口转发在浏览器中查看实时天梯榜与对战走势。

## 常用命令

```bash
# 1. 终端静态看板
python3 -m splendor_pool status

# 2. 终端动态看板 (按 Ctrl+C 退出)
python3 -m splendor_pool dashboard --interval 2.0

# 3. 启动对战 Worker
python3 -m splendor_pool worker

# 4. 启动 Web 看板服务 (8720 端口)
python3 -m splendor_pool serve

# 5. 模型管理
python3 -m splendor_pool model list
python3 -m splendor_pool model add-heuristic --name "heuristic-v02" --subcommand "agent-heuristic-v02"
python3 -m splendor_pool model add-m50 --name "aran-v0.2" --weights "/path/to/weights.json" --mode greedy
python3 -m splendor_pool model update <id> --weight 2.0
python3 -m splendor_pool model update <id> --disable
python3 -m splendor_pool pause on
python3 -m splendor_pool pause off
```
