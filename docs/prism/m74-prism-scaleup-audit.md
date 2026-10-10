# M74 结果阅读与审计索引

本轮最终c20在六共同对手与直接父代两项主要指标上增强确认：共同池+4.51pp（95%+2.41～+6.58pp），对父代半平56.79%（53.91%～59.72%）。主要网格7168局完整；最新覆盖2047/2048局，一局对最新Alpha在512步截断。

最终权重SHA256：`e16bfe0d30168d6ef7ceb067ca4357900f1c09e09d35f5759832dd3d6a9258ad`；父代M73 B：`15e14e118e8dd5eb45d199e643c185a382ae5d67a503d446d27eaf575de8bed5`。原结果SHA256：`aa141cf1840f4f4b594836472d3ebacd687072459be829787d799c208fd40eb6`。

5120训练局/20周期/1100更新，0自动重试。32导出张量、32optimizer槽、最终68输入Rust/Python parity（绝对与相对容差各1e-4）、全部5120保存训练回放验证PASS。最终最大绝对误差约1.10249e-4，按组合容差判定通过，不写成单纯绝对误差小于1e-4。

337份源码与输入SHA再次核验；全部9216尝试的82944份绑定文件SHA在DSW只读核验。1249归档成员/ZIP CRC/传输SHA，本机9215行与144份分片账本、WDL/双座/分母、20k bootstrap、报告来源绑定复核PASS。

原报告和原统计不变，r2保留为阅读草稿，r3为交付修订：画像只合并六个完整共同对手，直接父代区间使用冻结主统计，截断显示配对不完整。17组双方明细及桌面1440/窄屏390像素检查通过。主要增强与完整覆盖分开：latest-alpha保留INCOMPLETE，latest-balance保留通过、提升区间仍跨0；全部网格INCOMPLETE。2026-10-10现已登记为Prism Balance v0.2.3，父代v0.2.2；冠军/默认/部署未执行。

R7描述画像：在相同六共同对手/模式/匹配seed下，低VP占比降低，大牌印刷分上升，贵族覆盖下降。时点与真实投资兑现NOT_MEASURED，路线undetermined，证据等级INSUFFICIENT；不影响上述竞技价值。完整formula与画像卡保存在本轮本地产物。

[原完整双方Markdown](m74-prism-scaleup-evidence.md) · [原阅读报告](m74-prism-scaleup-comparison.html) · [新版阅读报告](m74-prism-scaleup-comparison-r4.html) · [训练对战Markdown](m74-prism-scaleup-training.md) · [轮次记录](../m74-prism-scaleup.md)
