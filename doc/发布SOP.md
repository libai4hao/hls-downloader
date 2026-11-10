# 发布 SOP

`hls-downloader` 的发布流程：确定版本号 → 同步版本号文件 → 打 tag 并推送 → GitHub Actions 自动构建 cli + gui 并发布 release。

发布产物（自动生成，无需手动打包）：
- `hls_download.zip` — CLI 版（onedir 文件夹压缩包）
- `hls_download_gui.zip` — GUI 版（onedir 文件夹压缩包）

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
| 新增功能（向后兼容） | 次位 +1，修订归 0 | `1.6.2` → `1.7.0` |
| 破坏性变更 / 大版本 | 主位 +1，其余归 0 | `1.x` → `2.0.0` |

## 2. 同步版本号文件

`version_info.txt` 里版本号写死了 4 处，发布前必须同步成新版本号：

| 位置 | 字段 | 示例（1.7.0） |
|------|------|--------------|
| `FixedFileInfo` | `filevers=(1, 7, 0, 0)` | 元组 4 位，末尾固定 0 |
| `FixedFileInfo` | `prodvers=(1, 7, 0, 0)` | 同上 |
| `StringStruct` | `FileVersion` | `u'1.7.0'` |
| `StringStruct` | `ProductVersion` | `u'1.7.0'` |

> `OriginalFilename`、`CompanyName`、`FileDescription`、`ProductName` 无需改动。

同时更新 `doc/迭代计划.md`：把本次已完成的内容补进对应版本小节。

## 3. 提交并打 tag 推送

```bat
git add version_info.txt doc/迭代计划.md
git commit -m "chore: 发布 v1.7.0"
git tag v1.7.0
git push origin main --tags
```

> tag 名必须 `v` 开头（工作流触发条件是 `push: tags: ["v*"]`），且与版本号一致。

## 4. 自动构建与发布（无需干预）

推送 tag 后 GitHub Actions 自动执行 `build` 工作流：

1. `windows-latest` runner 上装 Python 3.11 + pyinstaller + yt-dlp；
2. 下载 ffmpeg（gyan.dev essentials）解压成 `ffmpeg-*/bin/` 结构；
3. `build_cli.spec` / `build_gui.spec` 各自打 onedir 包（含图标 + 版本信息）；
4. `Compress-Archive` 压成 `hls_download.zip` / `hls_download_gui.zip`；
5. 上传 artifact；
6. `softprops/action-gh-release` 用 tag 名创建 release，附两个 zip，自动生成 release notes。

## 5. 验证

- 打开仓库 **Actions** 页，确认 `build` 工作流绿色通过（无 Node 20 弃用 warning）。
- 打开 **Releases** 页，确认新 tag 对应 release 已出现，且附 `hls_download.zip` + `hls_download_gui.zip`。
- 下载 `hls_download_gui.zip`，解压后双击 `hls_download_gui.exe`，确认：图标正常显示、启动秒开、下载进度条走动。

---

## 常见问题

**Q：手动 Run workflow 后没生成 release？**
A：正常。手动 dispatch 只构建 + 上传 artifact，不发 release；要发 release 必须 push tag（见第 3 步）。

**Q：tag 打错了 / 想删掉重发？**
```bat
git push origin :refs/tags/v1.7.0      # 删除远端 tag
git tag -d v1.7.0                       # 删除本地 tag
# 在 GitHub Releases 页手动删除对应 release，再重新走第 3 步
```

**Q：构建失败怎么办？**
A：到 Actions 失败 job 看日志，多数是 ffmpeg 下载地址变动（gyan.dev essentials URL）或 yt-dlp 版本不兼容；修好后重新 push 一个新 tag 即可（不要复用已存在的 tag）。

**Q：Node 20 弃用 warning 是什么？**
A：GitHub 2025-09 起弃用 Node 20，旧 action（checkout@v4 等）会提示。当前工作流已升级到 `checkout@v7` / `setup-python@v7` / `upload-artifact@v7` / `action-gh-release@v3`，均切 Node 24，不会再报。
