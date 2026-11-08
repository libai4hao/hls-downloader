# build_cli.spec — hls_download 的 CLI 单文件打包
import sys
from pathlib import Path

ROOT = Path.cwd()
# vendored yt-dlp：先把它塞进 sys.path，让 collect_all 能解析 yt_dlp
YTDLP_LIB = ROOT / "ytdlp_lib"
sys.path.insert(0, str(YTDLP_LIB))

from PyInstaller.utils.hooks import collect_all

# ffmpeg.exe：优先项目目录，否则上级目录（与 hls_download._find_ffmpeg_dir 的搜索一致）
FFMPEG_BIN = next(ROOT.glob("ffmpeg*/bin/ffmpeg.exe"), None)
if FFMPEG_BIN is None:
    FFMPEG_BIN = next(ROOT.parent.glob("ffmpeg*/bin/ffmpeg.exe"), None)

# 全量收集 yt-dlp 动态 import 的 extractor 子模块（返回 datas, binaries, hiddenimports 三元组）
_yt_datas, _yt_binaries, _yt_hidden = collect_all("yt_dlp")

a = Analysis(
    ["hls_download.py"],
    pathex=[str(ROOT), str(YTDLP_LIB)],
    binaries=[(str(FFMPEG_BIN), "ffmpeg/bin")] if FFMPEG_BIN else [],
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
    a.binaries,
    a.datas,
    [],
    name="hls_download",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
