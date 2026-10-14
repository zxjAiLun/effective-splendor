# Prism 历史归档索引

用户要求（2026-10-10）：完整历史数据保存在私有魔搭，按需取用。本机保留必要模型、配置、结果、报告、索引和校验回执，不默认保留完整历史包或下载缓存。

## M67 原始历史数据包

- 仓库：`sparxie1/test1005`，类型 `dataset`，私有。
- 路径前缀：`splendor/history/m67/20261010/65a85004230576ce889ea6f67541d472974d4d378dec8205adb9630f0e03a072/`。
- 清单：前缀下 `manifest.json`；26个原字节分片 `part-000.bin` 至 `part-025.bin`，顺序及offset以清单为准。
- 原归档名：`splendor-m67-alpha-repeat.data-bundle-r2.zip`。
- 原归档大小：`26203087576` 字节。
- 原归档SHA256：`65a85004230576ce889ea6f67541d472974d4d378dec8205adb9630f0e03a072`。
- 本地小型清单：`local-artifacts/prism/m75-continuation/modelscope-manifest.json`；完整性回执：同目录 `cloud-history-integrity.json`；清理回执：同目录 `history-local-cleanup.json`。是否核验和清理完成以实际回执为准。

## 按需恢复

使用现有ModelScope登录配置读取私有数据集，不把token或签名URL写进索引、日志或Git。先读取 `manifest.json`，核对原归档SHA和字节数；按清单顺序下载需要的分片，逐片核验大小与SHA。完整恢复时按offset拼接，核验完整归档大小与SHA后再解压。分片是原ZIP的字节范围，本身不一定是可单独解压的ZIP。

需要少量历史数据时，优先使用已有小型结果/报告或ZIP范围读取；只有完整恢复需要下载全部分片。新的历史包复用此规则，追加精确身份与证据，不覆盖旧归档。

## 当前核验状态

2026-10-10T20:11:08.7383016+08:00：私有魔搭26片大小/SHA、新鲜manifest和完整原归档字节流SHA均PASS；本机重复历史数据清理PASS，释放26.112GiB。回执位置如上。历史下载回执中的缓存路径已删除，后续从魔搭按需读取。


## 2026-10-12 已结束归档包的私有迁移与清理

仓库均为私有dataset `sparxie1/test1005`。以下包已按原审计回执核对SHA，上传后以新客户端完整读回核验，DSW原ZIP已删除；manifest另有新鲜字节读回绑定。原blob ZIP须使用本机/DSW保留的 `restore-original-files.py` 按 `__archive_manifest__.json` 恢复，不能把blobs目录当原文件树。

| 历史包 | 云端前缀（下含archive.zip与manifest.json） | 原ZIP字节 | ZIP SHA256 |
| --- | --- | ---: | --- |
| splendor-m63-dsw-r2 | `splendor/history/splendor-m63-dsw-r2/20261012/29f3cc642b5b69b0dcacf2e6706a2de09b5d31c0b45fe4b123d75f8ab8b09cd7` | 180338425 | `29f3cc642b5b69b0dcacf2e6706a2de09b5d31c0b45fe4b123d75f8ab8b09cd7` |
| splendor-m70-b-continuation | `splendor/history/splendor-m70-b-continuation/20261012/c34fbeb681cf2805c5da5a9bf2e34dcbf2e0d566ec470c3203dbd929f1a0f64e` | 1443945437 | `c34fbeb681cf2805c5da5a9bf2e34dcbf2e0d566ec470c3203dbd929f1a0f64e` |
| splendor-m66-alpha | `splendor/history/splendor-m66-alpha/20261012/f266b7a6536651763905a174bf2f6394baa2678cebe30505993adc31bb8c4740` | 1642093253 | `f266b7a6536651763905a174bf2f6394baa2678cebe30505993adc31bb8c4740` |

本机回执：`local-artifacts/prism/m79-mainline/existing-archives-migration-completion.json`、`existing-archives-final-integrity.json`；DSW小型恢复脚本仍位于 `/mnt/workspace/.prism-history-archives/20261009/restore-original-files.py`，本机副本 `local-artifacts/prism/m73-storage-cleanup-20261009/restore-original-files.py`。释放3266377115字节（3.04GiB），模型/配置/结果/报告独立保留。


## 2026-10-12 已结束目录的流式归档与清理
以下完整历史目录已迁移到私有dataset `sparxie1/test1005`，全部分片、重建整包SHA、成员索引和manifest新鲜读回核验通过后删除大数据。云端保存原字节历史，DSW仅保留必要权重、配置、结果与报告。M75恢复额外逐一核验云端解压后的原成员SHA，不重新打包；原失败记录保留。
| 目录 | 云端前缀（下含manifest.json和shards/） | 归档字节 / 分片数 | 整包SHA256 | 清理后实测占用 |
| --- | --- | --- | --- | --- |
| splendor-m73-repeat-r4 | `splendor/history/splendor-m73-repeat-r4/20261012/dc92f591d10e4357a1520290b0c9aceb` | 4189231141 / 32 | `f670952168d7a2f2c6025be4565b2d629f48db51f1839bfb2490f5234e2ed009` | 213.11 MB |
| splendor-m75-continuation-r1 | `splendor/history/splendor-m75-continuation-r1/20261012/87c8c4c6f2e7461f9380cf2701124307` | 13146434302 / 98 | `3859c3b769436d3351da7cbda03198472c96ea98f3b0b2d6c191c610fff4cb32` | 230.01 MB |

本机完整回执：`local-artifacts/prism/m79-mainline/m73-m75-archive-cleanup-completion.json`，及逐目录 `*.archive-cleanup.receipt.json`。

这些分片是同一连续tar.gz的字节区间，不能逐片解压。按manifest的index顺序下载，每片核验大小与SHA后拼接，核验整包大小和SHA，再以tar解压到独立恢复目录。包内`目录名/.__prism_archive_members__.jsonl`绑定各原文件SHA，解压后按索引复核；已有必要结果可直接使用，不默认恢复完整历史。成员索引的mtime/ctime、原失败、原科学结论均保留，清理不改变模型身份。


### M74 补齐与本轮历史清理验收（2026-10-12T18:04:52.608881+08:00）

M74完整历史也已归档、核验并清理：私有dataset `sparxie1/test1005`，前缀 `splendor/history/splendor-m74-scaleup-r1/20261012/96c2a048ab944771a938c7e1bbbaa7f5`；`manifest.json` SHA `51c57784fde22462420a9ecd51a8513273c25c2dc2c236752bef208f604453a7`，97个连续tar.gz字节分片，整包 12903736534 字节 / SHA `add730df183918905adcac2a007e1ae91e5be8b999f1badcd68489f7168b782b`。恢复方法与上节相同；没有单独可解压的分片。

DSW实际allocated占用：M74由25.937GB降到229.347MB，M73由10.932GB降到213.111MB，两项释放 36.427GB；M75保留230.011MB。三项已结束历史共释放 62.691GB，另有507321960字节完全一致的重复索引核验后清理。所有保留项在删除后再次逐文件SHA复核PASS，云端manifest及全部分片元数据身份复核PASS；所有删除quarantine已消失。

最新磁盘实测：DSW已用 17.867GB，空闲 81.217GiB；当前训练会继续生成本轮数据，这些是本次验收时点的值。完整回执 `local-artifacts/prism/m79-mainline/history-all-three-final-closeout.json`，各目录 `*.archive-cleanup.receipt.json`；完全相同的旧索引副本已删，回执指向的唯一有效成员索引保留，历史失败回执保留。


## 2026-10-12 M80 本地清理更正

M80 按用户明确授权删除了 Prism 之前的本地原始历史负载，并清理 JEV、旧 Studio 模型名册和本地对战数据；这批 pre-Prism 负载没有新建云端历史包，tracked 文档、benchmark 结果和 M72 画像导出的 Git 副本保留。清理细节与删除清单见 [M80 记录](../../docs/m80-local-history-cleanup.md)。

更正：本轮误删了 `evaluation/reference`、`evaluation/a-direct`、`evaluation/b-direct`、`evaluation/b-common`、`evaluation/a-common-recovery-r3` 与根 `continuation-r3`、`continuation-r3b`、`continuation-r4`（Prism/M67–M75 小型本机证据，约 91.8 MB）。本索引中的 M67 私有包（`splendor/history/m67/20261010/65a85004…`，26 分片）是 M67 级恢复入口；`continuation-r3*` 没有已知独立云端包，本地恢复状态为 UNKNOWN。恢复时仍按本页规则先核验 manifest、分片大小/SHA 和完整原归档。
