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

- CLI、GUI 独立 spec 仍然可单独构建，保持兼容旧分发方式。
- `build_portable.spec` 生成两个 EXE，并将依赖文件按目标路径去重后放入同一个 onedir 目录。
- `HLS_BUNDLE_FFMPEG=1` 为完整包；`0` 为外置 FFmpeg 精简包。
- 各构建使用独立 `--workpath`，避免并行构建互相清理中间目录。
- spec 不再自行删除 `build/`，清理工作交给 CI 生命周期管理。
- 每个 spec 在评估阶段先清空 `--distpath` 下的**同名产物目录**，防止新旧构建叠加出嵌套镜像（数据文件不要放在产物目录内）。
- yt-dlp extractor 暂不做激进裁剪，避免动态加载的网站支持回归。

## GitHub Actions

Release workflow 分为测试、FFmpeg 准备、CLI/GUI/Portable 并行构建和最终发布。FFmpeg 下载后先校验 SHA256，再通过短期 artifact 供完整包构建复用。精简包不打包 FFmpeg。发布前检查 CLI `--help`、GUI 启动，并生成 `SHA256SUMS.txt`。

本地非 Windows 环境不能替代 Windows runner 对 PyInstaller 产物的最终验证；每次修改 spec 后应以 GitHub Actions 产物做干净 Windows 解压运行测试。
