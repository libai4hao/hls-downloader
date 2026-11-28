# Windows 构建与发布

## 构建依赖

使用 Python 3.11，并安装锁定的构建依赖：

```powershell
python -m pip install -r requirements-build.txt
python -m pytest -q
```

## 本地构建

先准备 yt-dlp（由 requirements-build.txt 安装）和 FFmpeg essentials，确保目录结构为 `ffmpeg-*/bin/ffmpeg.exe` 与 `ffmpeg-*/bin/ffprobe.exe`。

```powershell
$env:HLS_BUNDLE_FFMPEG = "1"
pyinstaller --noconfirm --workpath build/pyi-cli --distpath dist build_cli.spec
pyinstaller --noconfirm --workpath build/pyi-gui --distpath dist build_gui.spec
pyinstaller --noconfirm --workpath build/pyi-portable --distpath dist build_portable.spec
```

生成的目录分别为 `dist/hls_download`、`dist/hls_download_gui`、`dist/hls_downloader_portable`。

精简版不包含 FFmpeg：

```powershell
$env:HLS_BUNDLE_FFMPEG = "0"
pyinstaller --noconfirm --workpath build/pyi-portable-slim --distpath dist/slim build_portable.spec
```

精简版运行时必须能从 `PATH` 找到 `ffmpeg` 和 `ffprobe`，或通过 `FFMPEG_LOCATION` 指定包含二者的目录。

## 构建设计

- `build_cli.spec`、`build_gui.spec` 仍可单独构建：前者是 CI 的 CLI 发行包，后者自 v1.12.1 起只服务本地调试（CI 不再发行独立 GUI 包，`build_portable.spec` 已包含 GUI）。
- `build_portable.spec` 生成两个 EXE，并将依赖文件按目标路径去重后放入同一个 onedir 目录；两个 EXE 内嵌各自的 PYZ 归档（约 8.8 / 8.9 MB），这部分无法共享，所以组合包 ≈ 单个 GUI 包 + 一个 CLI exe。
- `HLS_BUNDLE_FFMPEG=1` 为完整包；`0` 为外置 FFmpeg 精简包。
- 各构建使用独立 `--workpath`，避免并行构建互相清理中间目录。
- spec 不再自行删除 `build/`，清理工作交给 CI 生命周期管理。
- 每个 spec 在评估阶段先清空 `--distpath` 下的**同名产物目录**，防止新旧构建叠加出嵌套镜像（数据文件不要放在产物目录内）。
- yt-dlp extractor 暂不做激进裁剪，避免动态加载的网站支持回归。

### 本地重复构建的缓存边界（实测）

`--noconfirm` 且**不加 `--clean`** 时，PyInstaller 会复用同 `--workpath` 下同 spec 的 TOC 缓存（实测：CLI 冷构建 25.8 s，同 spec 二次构建 5.2 s）。但**换 spec 不会复用**：同一 `--workpath` 下紧接构建 `build_gui.spec` 仍需 36.2 s，与冷启动的约 40 s 只差文件缓存那几秒。所以：

- 本地反复调同一份 spec：保留 `--workpath`，别加 `--clean`；
- 想靠"同 Runner 连打 CLI 和 GUI"省时间：不成立，跨 spec 无 TOC 复用；合并 job 只省一次 checkout + 装依赖，却损失并行；
- Python 版本、PyInstaller 版本或源码大改后应加 `--clean`，避免命中过期缓存。

## GitHub Actions

Release workflow 的关键路径：`test` 与 `prepare-ffmpeg` **并行** → `build-cli` / `build-portable-full` / `build-portable-slim` 三路并行 → `release`。

- FFmpeg 下载后先校验 SHA256，再通过短期 artifact `verified-ffmpeg` 供两个完整包构建复用；`build-portable-slim` 只依赖 `test`，不等 FFmpeg。
- 发布前检查 CLI `--help`、GUI 启动、Slim 包不含 `_internal/ffmpeg`，并校验恰好 3 个 zip 非空、生成 `SHA256SUMS.txt`。
- `workflow_dispatch` 只构建不发布，可用于采集耗时样本（含 runner 排队波动，建议取 5 次中位数与 P90）。

本地非 Windows 环境不能替代 Windows runner 对 PyInstaller 产物的最终验证；每次修改 spec 后应以 GitHub Actions 产物做干净 Windows 解压运行测试。
