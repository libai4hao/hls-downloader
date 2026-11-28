# build_cli.spec — CLI 独立 onedir 包
# HLS_BUNDLE_FFMPEG=1（默认）内置 ffmpeg/ffprobe；=0 打精简变体，运行时靠 PATH / FFMPEG_LOCATION
import os
import shutil
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve()
YTDLP_LIB = ROOT / "ytdlp_lib"
if YTDLP_LIB.is_dir():
    sys.path.insert(0, str(YTDLP_LIB))

BUNDLE_FFMPEG = os.environ.get("HLS_BUNDLE_FFMPEG", "1").strip().lower() not in {"0", "false", "no"}

# 防复发：PyInstaller 不清 dist 下同名旧目录，旧产物会与新构建叠加出嵌套镜像
shutil.rmtree(Path(DISTPATH) / "hls_download", ignore_errors=True)

# ffmpeg.exe + ffprobe.exe：优先项目目录，否则上级目录（与 hls_download._find_ffmpeg_dir 的搜索一致）
FFMPEG_BIN = next(ROOT.glob("ffmpeg*/bin/ffmpeg.exe"), None) if BUNDLE_FFMPEG else None
if BUNDLE_FFMPEG and FFMPEG_BIN is None:
    FFMPEG_BIN = next(ROOT.parent.glob("ffmpeg*/bin/ffmpeg.exe"), None)
FFMPEG_DIR = FFMPEG_BIN.parent if FFMPEG_BIN else None
FFPROBE_BIN = FFMPEG_DIR / "ffprobe.exe" if FFMPEG_DIR else None
if BUNDLE_FFMPEG and (FFMPEG_BIN is None or FFPROBE_BIN is None or not FFPROBE_BIN.is_file()):
    raise SystemExit("Bundled build requested, but ffmpeg.exe/ffprobe.exe were not found.")

# 保留 yt-dlp 完整动态 extractor 集合，避免站点支持因激进裁剪而回归。
_yt_datas, _yt_binaries, _yt_hidden = collect_all("yt_dlp")
binaries = list(_yt_binaries)
if FFMPEG_BIN:
    binaries.append((str(FFMPEG_BIN), "ffmpeg/bin"))
if FFPROBE_BIN:
    binaries.append((str(FFPROBE_BIN), "ffmpeg/bin"))

a = Analysis(
    [str(ROOT / "hls_download.py")],
    pathex=[str(ROOT), str(YTDLP_LIB)],
    binaries=binaries,
    datas=_yt_datas,
    hiddenimports=_yt_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

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
    icon=str(ROOT / "app.ico"),
    version=str(ROOT / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="hls_download",
)
