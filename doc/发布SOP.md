# 发布 SOP

`hls-downloader` 的发布流程：确定版本号 → 同步版本号文件 → 打 tag 并推送 → GitHub Actions 并行构建 CLI / Portable / Portable Slim 并发布 release（附 SHA256 校验清单）。

发布产物（自动生成，无需手动打包）：

| 产物 | 内容 |
|------|------|
| `hls-downloader-cli.zip` | CLI 独立包（内置 ffmpeg + ffprobe） |
| `hls-downloader-portable.zip` | CLI + GUI 共享运行时组合包（内置 ffmpeg + ffprobe） |
| `hls-downloader-portable-slim.zip` | 同上的精简版（不内置 ffmpeg，运行时用 PATH / `FFMPEG_LOCATION`） |
| `SHA256SUMS.txt` | 以上三个 zip 的 SHA256 清单（`<hash>  <文件名>`） |

> 自 v1.12.1 起不再单独发行 `hls-downloader-gui.zip`：`hls-downloader-portable.zip` 已完整包含 GUI + CLI + ffmpeg，独立 GUI 包与它重复 98.8 MB。需要单独 GUI 构建的用户仍可本地用 `build_gui.spec`（见 `BUILDING.md`），CI 不再产出。

---

## 0. 前置条件

- 有仓库 push 权限（`git@github.com:libai4hao/hls-downloader.git`）。
- 本地 `main` 分支已与 `origin/main` 同步，工作区干净。
- 触发规则：**只有 push tag（`v*`）才会发 release**；手动 `Run workflow`（workflow_dispatch）只构建 + 上传 artifact，不发 release。

## 1. 确定版本号

采用语义化版本 `主.次.修订`（`X.Y.Z`），与 `doc/迭代计划.md` 的 V 路线对应：

| 变化类型 | 版本号变化 | 示例 |
|---------|-----------|------|
| 修复 bug / 小改动 | 修订位 +1 | `1.6.1` → `1.6.2` |
| 新增功能（向后兼容） | 次位 +1，修订归 0 | `1.11.0` → `1.12.0` |
| 破坏性变更 / 大版本 | 主位 +1，其余归 0 | `1.x` → `2.0.0` |

## 2. 同步版本号文件

`version_info.txt` 里版本号写死了 4 处，发布前必须同步成新版本号：

| 位置 | 字段 | 示例（1.12.0） |
|------|------|--------------|
| `FixedFileInfo` | `filevers=(1, 12, 0, 0)` | 元组 4 位，末尾固定 0 |
| `FixedFileInfo` | `prodvers=(1, 12, 0, 0)` | 同上 |
| `StringStruct` | `FileVersion` | `u'1.12.0'` |
| `StringStruct` | `ProductVersion` | `u'1.12.0'` |

> `OriginalFilename`、`CompanyName`、`FileDescription`、`ProductName` 无需改动。

同时更新 `doc/迭代计划.md`：把本次已完成的内容补进对应版本小节；发行物或构建方式有变化时，同步 `README.md`、`BUILDING.md`、`doc/代码地图.md`。

## 3. 提交并打 tag 推送

```bat
git add -A
git commit -m "chore: 发布 v1.12.0"
git tag v1.12.0
git push origin main --tags
```

> tag 名必须 `v` 开头（工作流触发条件是 `push: tags: ["v*"]`），且与版本号一致。

## 4. 自动构建与发布（无需干预）

推送 tag 后 GitHub Actions（`.github/workflows/release.yml`）按以下依赖关系执行：

1. **test** 与 **prepare-ffmpeg** 并行（两者互不依赖）：`test` 安装 `requirements-build.txt` 锁定依赖 → 跑 `pytest -q`；`prepare-ffmpeg` 下载固定版本 FFmpeg（gyan.dev essentials，**先校验 SHA256**）→ 解压成 `ffmpeg-*/bin/` 结构 → 作为短期 artifact `verified-ffmpeg` 上传（保留 1 天）；
2. 三个构建 job **并行**（各自独立 `windows-latest` runner 与独立 `--workpath`），三者都依赖 `test`，含 ffmpeg 的两个还依赖 `prepare-ffmpeg`：
   - **build-cli** / **build-portable-full**：复用 `verified-ffmpeg`，`HLS_BUNDLE_FFMPEG=1`，跑 CLI `--help` 与 GUI 启动冒烟；
   - **build-portable-slim**：只依赖 `test`，不下载 FFmpeg，`HLS_BUNDLE_FFMPEG=0`，构建后断言产物里不含 `_internal/ffmpeg`；
   - 各自 `Compress-Archive` 压 zip，上传 artifact `release-*`；
3. **release**（仅 tag 触发，依赖三个构建 job）：合并 artifact → 校验恰好 3 个 zip 且解压非空 → 生成 `SHA256SUMS.txt` → `softprops/action-gh-release` 用 tag 名创建 release（附三个 zip + 校验清单，自动生成 release notes）。

## 5. 验证

- 打开仓库 **Actions** 页，确认 `test` / `prepare-ffmpeg` / 三个 build job / `release` 全绿（无 Node 20 弃用 warning）。
- 打开 **Releases** 页，确认新 tag 对应 release 已出现，附 3 个 zip + `SHA256SUMS.txt`。
- 下载 `hls-downloader-portable.zip`，解压后双击 `hls_download_gui.exe`：图标正常、启动秒开、进度条走动；同目录 `hls_download.exe --help` 正常。
- 下载 `hls-downloader-portable-slim.zip`，在装好 ffmpeg（PATH 或 `FFMPEG_LOCATION`）的机器上跑一次 `hls_download.exe <m3u8地址>`，确认能下载；在没装 ffmpeg 的机器上确认报错文案提示三种解决办法。
- 抽查校验清单：

```powershell
Get-FileHash .\hls-downloader-portable.zip -Algorithm SHA256
Select-String SHA256SUMS.txt -Pattern "hls-downloader-portable.zip"
```

---

## 常见问题

**Q：手动 Run workflow 后没生成 release？**
A：正常。手动 dispatch 只构建 + 上传 artifact，不发 release；要发 release 必须 push tag（见第 3 步）。

**Q：tag 打错了 / 想删掉重发？**
```bat
git push origin :refs/tags/v1.12.0      # 删除远端 tag
git tag -d v1.12.0                       # 删除本地 tag
# 在 GitHub Releases 页手动删除对应 release，再重新走第 3 步
```

**Q：构建失败怎么办？**
A：到 Actions 失败 job 看日志，常见原因：FFmpeg 下载地址或 SHA256 变动（`prepare-ffmpeg` 会直接 throw）、`requirements-build.txt` 里的 yt-dlp/pyinstaller 版本不兼容、`HLS_BUNDLE_FFMPEG=1` 时 spec 找不到 `ffmpeg*/bin/ffmpeg.exe`（硬失败）。修好后重新 push 一个新 tag 即可（不要复用已存在的 tag）。

**Q：Node 20 弃用 warning 是什么？**
A：GitHub 2025-09 起弃用 Node 20，旧 action 会提示。当前工作流已升级到 `checkout@v7` / `setup-python@v7` / `upload-artifact@v7` / `download-artifact@v7` / `action-gh-release@v3`，均切 Node 24，不会再报。

**Q：本地重新打包会不会丢数据？**
A：spec 会先清空 `--distpath` 下的同名产物目录（防新旧构建叠加）再输出，而数据文件（`config.json` / `download_history.log` / 输出目录）默认落在 exe 旁、即该目录内——重打包前把数据复制出去，或平时就把数据存在包目录外（详见 README 打包节的 ⚠️ 说明）。
