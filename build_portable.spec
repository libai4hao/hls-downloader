# build_portable.spec — CLI + GUI 共享一个 _internal 运行时的 onedir 组合包
# HLS_BUNDLE_FFMPEG=1（默认）内置 ffmpeg/ffprobe；=0 打 Portable Slim（运行时靠 PATH / FFMPEG_LOCATION）
import os
import shutil
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve()
YTDLP_LIB = ROOT / "ytdlp_lib"
if YTDLP_LIB.is_dir():
    sys.path.insert(0, str(YTDLP_LIB))

# 防复发：PyInstaller 不清 dist 下同名旧目录，旧产物会与新构建叠加出嵌套镜像
shutil.rmtree(Path(DISTPATH) / "hls_downloader_portable", ignore_errors=True)

BUNDLE_FFMPEG = os.environ.get("HLS_BUNDLE_FFMPEG", "1").strip().lower() not in {"0", "false", "no"}
FFMPEG_BIN = next(ROOT.glob("ffmpeg*/bin/ffmpeg.exe"), None) if BUNDLE_FFMPEG else None
if BUNDLE_FFMPEG and FFMPEG_BIN is None:
    FFMPEG_BIN = next(ROOT.parent.glob("ffmpeg*/bin/ffmpeg.exe"), None)
FFMPEG_DIR = FFMPEG_BIN.parent if FFMPEG_BIN else None
FFPROBE_BIN = FFMPEG_DIR / "ffprobe.exe" if FFMPEG_DIR else None
if BUNDLE_FFMPEG and (FFMPEG_BIN is None or FFPROBE_BIN is None or not FFPROBE_BIN.is_file()):
    raise SystemExit("Bundled build requested, but ffmpeg.exe/ffprobe.exe were not found.")

# Both analyses use the same dependency collection. COLLECT deduplicates by destination.
_yt_datas, _yt_binaries, _yt_hidden = collect_all("yt_dlp")
common_binaries = list(_yt_binaries)
if FFMPEG_BIN:
    common_binaries.append((str(FFMPEG_BIN), "ffmpeg/bin"))
if FFPROBE_BIN:
    common_binaries.append((str(FFPROBE_BIN), "ffmpeg/bin"))

def unique_entries(entries):
    seen = set()
    result = []
    for entry in entries:
        # Analysis 输出的 TOC 元组首字段是目标相对路径（dest_name）。
        key = str(entry[0]).lower().replace("\\", "/")
        if key not in seen:
            seen.add(key)
            result.append(entry)
    return result

cli = Analysis([str(ROOT / "hls_download.py")], pathex=[str(ROOT), str(YTDLP_LIB)],
               binaries=list(common_binaries), datas=list(_yt_datas), hiddenimports=list(_yt_hidden),
               hookspath=[], runtime_hooks=[], excludes=[], noarchive=False)
gui = Analysis([str(ROOT / "gui.py")], pathex=[str(ROOT), str(YTDLP_LIB)],
               binaries=list(common_binaries), datas=list(_yt_datas), hiddenimports=list(_yt_hidden),
               hookspath=[], runtime_hooks=[], excludes=[], noarchive=False)
pyz_cli = PYZ(cli.pure)
pyz_gui = PYZ(gui.pure)
exe_cli = EXE(pyz_cli, cli.scripts, [], exclude_binaries=True, name="hls_download",
              console=True, debug=False, strip=False, upx=False,
              icon=str(ROOT / "app.ico"), version=str(ROOT / "version_info.txt"))
exe_gui = EXE(pyz_gui, gui.scripts, [], exclude_binaries=True, name="hls_download_gui",
              console=False, debug=False, strip=False, upx=False,
              icon=str(ROOT / "app.ico"), version=str(ROOT / "version_info.txt"))
all_binaries = unique_entries(cli.binaries + gui.binaries)
all_datas = unique_entries(cli.datas + gui.datas)
coll = COLLECT(exe_cli, exe_gui, all_binaries, all_datas,
               strip=False, upx=False, name="hls_downloader_portable")
