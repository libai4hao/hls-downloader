# build_cli_lite.spec — hls_download 的 CLI lite 打包（不内置 ffmpeg，运行时靠 PATH / FFMPEG_LOCATION 探测）
import shutil
import sys
from pathlib import Path

ROOT = Path.cwd()
# vendored yt-dlp：先把它塞进 sys.path，让 collect_all 能解析 yt_dlp
YTDLP_LIB = ROOT / "ytdlp_lib"
sys.path.insert(0, str(YTDLP_LIB))

from PyInstaller.utils.hooks import collect_all

# lite 版：不打包 ffmpeg（与完整版 build_cli.spec 的唯一区别）

# 全量收集 yt-dlp 动态 import 的 extractor 子模块（返回 datas, binaries, hiddenimports 三元组）
_yt_datas, _yt_binaries, _yt_hidden = collect_all("yt_dlp")

a = Analysis(
    ["hls_download.py"],
    pathex=[str(ROOT), str(YTDLP_LIB)],
    binaries=[],
    datas=_yt_datas,
    hiddenimports=_yt_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
# yt-dlp 的动态库（含 extractor 依赖的二进制）
a.binaries += _yt_binaries

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="hls_download",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    icon="app.ico",
    version="version_info.txt",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="hls_download_lite",
)

# 打包完成后清理 PyInstaller 中间产物目录 build/（只留 dist/ 成品）
shutil.rmtree(ROOT / "build", ignore_errors=True)
