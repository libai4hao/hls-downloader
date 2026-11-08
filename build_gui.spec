# build_gui.spec — hls_download 的 GUI 单文件打包（windowed，无控制台）
import sys
from pathlib import Path

ROOT = Path.cwd()
YTDLP_LIB = ROOT / "ytdlp_lib"
sys.path.insert(0, str(YTDLP_LIB))

from PyInstaller.utils.hooks import collect_all

FFMPEG_BIN = next(ROOT.glob("ffmpeg*/bin/ffmpeg.exe"), None)
if FFMPEG_BIN is None:
    FFMPEG_BIN = next(ROOT.parent.glob("ffmpeg*/bin/ffmpeg.exe"), None)

_yt_datas, _yt_binaries, _yt_hidden = collect_all("yt_dlp")

a = Analysis(
    ["gui.py"],
    pathex=[str(ROOT), str(YTDLP_LIB)],
    binaries=[(str(FFMPEG_BIN), "ffmpeg/bin")] if FFMPEG_BIN else [],
    datas=_yt_datas,
    hiddenimports=_yt_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
a.binaries += _yt_binaries

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="hls_download_gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
