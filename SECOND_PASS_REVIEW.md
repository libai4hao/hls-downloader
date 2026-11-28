# 第二轮代码审查与实施记录

本轮改动已合入 `main` 并随 **v1.12.0** 发布。审查范围：GUI 生命周期、凭据与日志安全、打包 spec 重构、CI 并行构建与发布校验。

> **后续变更（v1.12.1）**：本文记录的「四路并行构建 + 4 个 zip」已调整为「test 与 prepare-ffmpeg 并行 + 三路构建 + 3 个 zip」，独立 `hls-downloader-gui.zip` 不再发行。原因与实测数据见 `doc/迭代计划.md` V1.12.1 小节、`doc/发布SOP.md`、`BUILDING.md`。本文其余内容（代码安全改造、spec 重构）仍然有效。

## 已实施

| 改造项 | 落地方式 |
|--------|----------|
| GUI Worker 生命周期修复 | 去掉固定 30 秒关闭超时强杀；请求停止后等 Worker `finally` 清理完再销毁窗口；Worker 改为非 daemon，避免后台线程被解释器直接中止 |
| Cookie 安全清理 | 临时 cookie 文件只在 Worker 收尾后删除，关闭流程不再提前删；初始化失败路径仍保留清理 |
| GUI 日志队列限流 | 队列固定容量 5000，满时丢最旧普通日志、优先保留状态/错误等关键事件；每轮最多消费 300 条；日志框最多保留 5000 行 |
| Cookie JSON 字段校验 | `domain` 拒绝空白字符与 `/`；`path` 必须以 `/` 开头且不含制表符/换行，否则回落 `/`，防止注入额外列破坏 Netscape 结构 |
| Windows 文件名安全处理 | 新增 `_sanitize_filename`：去路径分隔符、替换 `<>:"/\|?*` 与控制字符、去尾部空格/点、规避 `CON/PRN/AUX/NUL/COM1-9/LPT1-9` 保留名；`_ensure_ext` 统一走该清洗 |
| URL 敏感参数脱敏 | 新增 `_redact_sensitive_text`：日志与日志框对 `token/access_token/auth/signature/key/password/credential` 等查询参数替换为 `REDACTED`，保留非敏感参数 |
| 控制台编码兜底 | 新增 `_ensure_console_utf8`：启动时把 stdout/stderr 切到 UTF-8（`errors="replace"`）。非中文/非 UTF-8 控制台（cp1252/cp437）打印中文帮助或报错时本来会 `UnicodeEncodeError` 直接崩掉，该问题由首个 v1.12.0 CI 运行的 `--help` 冒烟暴露，已修复 |
| CLI / GUI spec 重构 | 改用 `SPECPATH` 定位项目（不再依赖调用者 cwd）；移除 spec 内删除共享 `build/` 的副作用；保留防叠加的同名产物目录清理（改用 `DISTPATH`） |
| Portable 共享运行时 spec | 新增 `build_portable.spec`：CLI/GUI 两个 EXE 共用一个 `_internal` 运行时，依赖按目标路径去重 |
| FFmpeg 完整版 / 精简版 | 新增 `HLS_BUNDLE_FFMPEG` 开关（默认 `1` 内置）；完整版缺 `ffmpeg.exe`/`ffprobe.exe` 时构建硬失败，避免打出半成品包；Slim 版要求系统 PATH 同时存在 ffmpeg 与 ffprobe，或 `FFMPEG_LOCATION` |
| GitHub Actions 并行构建 | 拆成 `test` → `prepare-ffmpeg` → `build-cli` / `build-gui` / `build-portable-full` / `build-portable-slim` 四路并行 → `release`；依赖锁定在 `requirements-build.txt`，action 统一保留 Node 24 版本（`@v7` / `@v3`） |
| SHA256 发布校验 | `prepare-ffmpeg` 校验下载包 SHA256；`release` 校验恰好 4 个 zip 且解压非空，并生成 `SHA256SUMS.txt` |
| 构建及发布文档 | 新增 `BUILDING.md`、`requirements-build.txt`；同步 README、`doc/发布SOP.md`、`doc/代码地图.md`、`doc/迭代计划.md`；移除已废弃的 lite spec 与对应说明 |

## 验证

- `python -m py_compile hls_download.py gui.py tests/test_hls_download.py`：通过。
- `python -m pytest -q`：41 passed，1 skipped（Windows 本机，Python 3.13）。
- `PYTHONIOENCODING=cp1252 python hls_download.py --help`：修复前崩在 `UnicodeEncodeError`，修复后正常退出 0（对应 CI 上 CLI/Portable `--help` 冒烟失败的原因）。
- `yaml.safe_load` 解析 `.github/workflows/release.yml`：7 个 job、release job 依赖四个构建 job，结构正确。
- 本地实跑 PyInstaller（`HLS_BUNDLE_FFMPEG=0`，输出到临时目录后清理）：
  - `build_cli.spec`：1121 files / 35.5 MB，`_internal` 内无 ffmpeg，`hls_download.exe --help` 正常；
  - `build_portable.spec`：同时产出 `hls_download.exe` + `hls_download_gui.exe`，2048 files / 51.7 MB（共用一份 `_internal`，比两个独立包合计更小），无 ffmpeg；
  - `HLS_BUNDLE_FFMPEG=1` 且本地无 `ffmpeg*/bin` 时，spec 以 `Bundled build requested, but ffmpeg.exe/ffprobe.exe were not found.` 退出码 1 失败（不再静默打半成品包）。
- 完整版（内置 ffmpeg）产物、Windows 干净解压运行与 ZIP 体积仍由 GitHub Actions runner 验证（本地无 ffmpeg 目录，不做完整版构建）。

## 有意保留

- yt-dlp 使用完整 `collect_all("yt_dlp")`，不按猜测排除 extractor；体积裁剪需要先建立目标站点 extractor 回归集。
- UPX 保持关闭，降低杀软误报与运行时兼容风险。
- CLI / GUI 独立完整包继续保留，Portable 与 Portable Slim 作为新增发行物。
