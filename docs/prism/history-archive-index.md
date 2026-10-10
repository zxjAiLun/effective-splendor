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
