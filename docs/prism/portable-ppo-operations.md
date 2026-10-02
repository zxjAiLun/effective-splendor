# Prism PPO 跨机运行说明

状态：M57 Windows / Linux ARM 实测通过。竞技与风格晋级验收 **NOT_RUN**；未发布检查点的[完整双方对战表](m57-portable-ppo-calibration.md)另列。固定发布模型仍为 Prism Alpha v0.1.1，模型身份与推理权重保持。

## 能做什么

从本机启动、查看、边界停止或强制终止本机/cloud1训练，再把已提交的完整检查点交给另一主机。交接保留策略、两种价值分支、AdamW动量、Python/NumPy/Torch RNG、已消费批次、任务/更新/物理决策计数、CPU消耗和原始墙钟截止时间。

正常换机器采用 **边界停止 → 交接 → 目标启动**。源端先持久撤销写入权，目标导入成功后才取得新权；不要两台机器同时写同一条训练线。已结束的M57预算不能通过重新启动或搬机器扩大。

已实测 Windows第1轮 → cloud1第2轮 → Windows第3轮。两次导入的模型/优化器/RNG/进度和启动账本hash相同。跨架构恢复后的下一次数值更新不承诺逐位相同。

## 已准备的环境

| 项目 | 本机 | cloud1 |
| --- | --- | --- |
| 工程目录 | E:/AUbuntuProject/project/splendor | /home/ubuntu/splendor-ppo-m57 |
| 产物目录 | local-artifacts/prism/portable-m57 | /home/ubuntu/splendor-ppo-m57 |
| Python | C:/Python312/python.exe，3.12.6 | /home/ubuntu/splendor-ppo-m57/venv/bin/python，3.12.6 |
| Torch / NumPy / psutil | 2.6.0+cu124（CPU） / 2.2.4 / 7.0.0 | 2.6.0+cpu / 2.2.4 / 7.0.0 |
| 原生程序 | 独立build/release/splendor.exe | ARM build/release/splendor |
| 进程所有权 | Windows Job Object | systemd用户服务 / 专属cgroup slice |
| 控制配置 | local-artifacts/prism/portable-m57/profiles.json | 本机配置通过SSH cloud1引用 |

cloud1已确认Linger=yes，SSH命令退出后有界worker继续运行；当前M57 worker已停止。Linux要求systemd用户管理器、CPU/内存/任务数cgroup权限和持久目录。仅能对话的云端agent沙箱尚未验证。cloud2未参与PPO校准；本轮未部署Muse/Railway。

## 日常命令

以下以已经冻结**新**预算/种子的训练线为例。填写实际campaign绝对路径；profiles.json绑定专属目录、解释器和SSH别名，host.json固定权重及原生二进制hash。默认配置就是本轮已建立的配置。

~~~powershell
$ppoCampaign = '新训练线的绝对campaign路径'

# 有界启动，重复启动被拒绝
C:\Python312\python.exe -B scripts/prism_portable_control.py --host local start --campaign $ppoCampaign --cycles 1
C:\Python312\python.exe -B scripts/prism_portable_control.py --host local status --campaign $ppoCampaign

# 本轮完整提交后停止，等状态 STOPPED_BOUNDARY
C:\Python312\python.exe -B scripts/prism_portable_control.py --host local stop --campaign $ppoCampaign --mode boundary

# 回执给出目标机新的target路径
C:\Python312\python.exe -B scripts/prism_portable_control.py --host local transfer --campaign $ppoCampaign --to cloud1
~~~

将target填入新变量：

~~~powershell
$ppoCloudCampaign = '/home/ubuntu/splendor-ppo-m57/campaigns/回执中的训练线'
C:\Python312\python.exe -B scripts/prism_portable_control.py --host cloud1 start --campaign $ppoCloudCampaign --cycles 1
C:\Python312\python.exe -B scripts/prism_portable_control.py --host cloud1 status --campaign $ppoCloudCampaign
C:\Python312\python.exe -B scripts/prism_portable_control.py --host cloud1 stop --campaign $ppoCloudCampaign --mode boundary
C:\Python312\python.exe -B scripts/prism_portable_control.py --host cloud1 transfer --campaign $ppoCloudCampaign --to local
~~~

transfer的PASS表示状态导入成功，此时新对局/更新数均为0；目标start才开始接续。源campaign已RELEASED不能再次start；不要手工解除其pause冒充接续。共享池pause与这些独立campaign无关。

## 需要立即终止时

~~~powershell
C:\Python312\python.exe -B scripts/prism_portable_control.py --host cloud1 stop --campaign $ppoCloudCampaign --mode force
~~~

专属supervisor关闭自有进程树。等STOPPED_OPERATOR且alive=false后，可在原主机start接续。已完成/已提交局不重放；未发布中断按原合同保守计费，受重试上限约束。若不在完整一轮提交边界，需在原主机先完成剩余这一轮才能迁移。kill是身份核验后的supervisor终止兜底，本轮对局验证的是force请求路线。

## 新训练线与新主机

新训练线需要新的预先冻结blueprint，包含有限cycle/job/seed/对手/奖励/预算。create建立新目录；原prepare脚本只用于首次冻结M57，不能重跑覆盖历史合同：

~~~powershell
C:\Python312\python.exe -B scripts/prism_portable_control.py --host cloud1 create --line new-alpha-trial --blueprint /home/ubuntu/splendor-ppo-m57/新冻结计划.json
~~~

新主机准备同版Python、Torch/NumPy及原生程序，再用training.prism_portable.provision绑定主机并核验68条边界输入，其help列出路径参数。Windows/ARM分别固定原生身份。当前跨机恢复限CPU、同Python/NumPy/Torch基础版本、相同线程/dtype/批形状/AMP/TF32；Torch的CPU/CUDA发行后缀可不同。

本轮从 Prism Alpha v0.1.1 推理权重建立**新的工程优化器**，验证这些新检查点的完整恢复。M54～M56严格身份的历史检查点未自动转换，历史预算未重置，旧代码/产物保留。未知Torch对象不是此接口的输入。

## 失败记录与运行边界

原数据、提交祖先、迁移压缩包、imports来源和transfer-registry保留。campaign的control目录保存状态/日志；resource-ledger保存预算；本机transfers保存交接日志。导入先验证压缩包和成员hash，拒绝不安全路径与重复票据，再加载可信检查点。

传输失败时源端保持RELEASED；压缩包已生成时，可按日志SHA完成复制后显式import。已CLAIMED但失败的导入不自动重试或恢复源写入权，应先保留并核对失败阶段。启动确认前controller崩溃可能留下STARTING记录，需核验自有PID/unit和日志后处理；本轮未宣称云机重启/断电或每个启动失败窗口均可自动恢复。

当前每campaign内存2GiB、CPU3600秒、原墙钟7200秒、存储4GiB；轮数/任务/更新另有上限。休息会消耗原墙钟期限，换机器不会重新获得两小时；整夜训练应在新有限合同里预设足够期限。

实测吞吐、负载与双方数据见[M57校准报告](m57-portable-ppo-calibration.md)；设计与修订见[M57里程碑](../m57-prism-portable-ppo.md)。
