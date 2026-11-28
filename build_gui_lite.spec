# build_gui_lite.spec — hls_download 的 GUI lite 打包（不内置 ffmpeg，运行时靠 PATH / FFMPEG_LOCATION 探测）
import shutil
import sys
from pathlib import Path

ROOT = Path.cwd()

# 防复发：PyInstaller 不清 dist 下同名旧目录，旧产物会与新构建叠加出嵌套镜像
shutil.rmtree(ROOT / "dist" / "hls_download_gui_lite", ignore_errors=True)
YTDLP_LIB = ROOT / "ytdlp_lib"
sys.path.insert(0, str(YTDLP_LIB))

from PyInstaller.utils.hooks import collect_all

# lite 版：不打包 ffmpeg（与完整版 build_gui.spec 的唯一区别）

_yt_datas, _yt_binaries, _yt_hidden = collect_all("yt_dlp")

a = Analysis(
    ["gui.py"],
    pathex=[str(ROOT), str(YTDLP_LIB)],
    binaries=[],
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
    [],
    exclude_binaries=True,
    name="hls_download_gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
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
    name="hls_download_gui_lite",
)

# 打包完成后清理 PyInstaller 中间产物目录 build/（只留 dist/ 成品）
shutil.rmtree(ROOT / "build", ignore_errors=True)
