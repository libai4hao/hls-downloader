# -*- coding: utf-8 -*-
"""
hls_download.py — 加密 HLS 视频下载器（yt-dlp + ffmpeg 封装）
支持下载加密的 HLS 流视频，支持粘贴网页链接下载和视频直链下载。

支持解决 IDM 报「由于法律原因，IDM无法下载此受保护的数据」的问题。
原理：这类视频是 AES-128 加密的 HLS 流，IDM 不会解密；本工具用 yt-dlp + ffmpeg
自动完成「抓 m3u8 → 下载分片 → 解密 → 合并成 MP4」，并保留源标题。

用法：
    python hls_download.py "<网页链接 或 视频直链m3u8 链接>" [输出目录]

可选参数（防盗链 / 登录态 / 代理 / 历史记录）：
    --cookies <文件>       读取 cookies.txt（浏览器过验证后导出）
    -b, --browser <名>     从浏览器读 cookie（chrome / firefox / edge）
    --ua, --user-agent <串> 覆盖 User-Agent
    -r, --referer <url>    防盗链 Referer
    --proxy <url>          代理，如 http://127.0.0.1:7890
    --no-history           本次下载不写入下载历史记录
    --history-file <文件>  下载历史文件路径，默认脚本同目录 download_history.log

配置（可选）：脚本启动时读取同目录的 config.json（若存在），
    命令行参数优先于 config.json，config.json 优先于内置默认值。
    字段见 config.example.json。

依赖定位（按优先级）：
    yt-dlp ：优先系统已安装，否则用脚本同目录 / 上级目录下的 ytdlp_lib/
    ffmpeg ：优先环境变量 FFMPEG_LOCATION，否则用脚本同目录 / 上级目录下的 ffmpeg*/bin/
"""
import argparse
import glob
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # 上级目录

CONFIG_FILE = os.path.join(HERE, "config.json")
DEFAULT_HISTORY_FILE = os.path.join(HERE, "download_history.log")


def _find_ffmpeg_dir():
    env = os.environ.get("FFMPEG_LOCATION")
    if env and os.path.isdir(env):
        return env
    for base in (HERE, ROOT):
        hits = sorted(glob.glob(os.path.join(base, "ffmpeg*", "bin")))
        if hits:
            return hits[0]
    return None


def _setup_ytdlp():
    # 1) 系统已安装
    try:
        import yt_dlp  # noqa: F401
        return
    except ImportError:
        pass
    # 2) 本地 lib
    for base in (HERE, ROOT):
        lib = os.path.join(base, "ytdlp_lib")
        if os.path.isdir(lib):
            sys.path.insert(0, lib)
            return
    sys.exit("错误：找不到 yt_dlp。请安装 yt-dlp，或把 ytdlp_lib 放到脚本同目录/上级目录。")


def _load_config():
    """读取同目录 config.json（可选）。读不到或损坏时返回空字典。"""
    if not os.path.isfile(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as e:
        print(f"警告：config.json 读取失败，已忽略（{e}）")
        return {}


def _resolve_path(value, default):
    """把配置/命令行里的路径统一成绝对路径；相对路径以脚本目录为基准。"""
    if not value:
        return default
    return value if os.path.isabs(value) else os.path.join(HERE, value)


def _format_history_line(entry):
    """把一条历史记录格式化成一行可读文本（log 格式）。"""
    status = entry.get("status", "?")
    title = entry.get("title") or "-"
    vid = entry.get("id") or "-"
    url = entry.get("url", "")
    time = entry.get("time", "")
    # 成功时标文件，失败时标错误
    detail = entry.get("filepath") or entry.get("error") or entry.get("out_dir", "")
    mark = "[成功]" if status == "success" else "[失败]"
    return f"{time} {mark} {title} (id={vid}) | {url} | {detail}"


def _append_history(history_file, entry):
    try:
        os.makedirs(os.path.dirname(history_file) or ".", exist_ok=True)
        with open(history_file, "a", encoding="utf-8") as f:
            f.write(_format_history_line(entry) + "\n")
    except OSError as e:
        print(f"警告：写入下载历史失败：{e}")


def _parse_args():
    parser = argparse.ArgumentParser(
        description="加密 HLS 视频下载器（yt-dlp + ffmpeg 封装）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("url", help="网页链接 或 视频直链(m3u8)链接")
    parser.add_argument(
        "out_dir", nargs="?", default=None,
        help="输出目录，默认脚本同目录下 downloads/",
    )

    # 登录态 / 反爬（二选一）
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--cookies", metavar="文件", help="读取 cookies.txt（浏览器过验证后导出）")
    group.add_argument("-b", "--browser", metavar="名称",
                       help="从浏览器读 cookie（如 chrome / firefox / edge）")

    # 防盗链
    parser.add_argument("--ua", "--user-agent", dest="user_agent", metavar="串",
                        help="覆盖 User-Agent")
    parser.add_argument("-r", "--referer", metavar="URL", help="防盗链 Referer")
    parser.add_argument("--proxy", metavar="URL", help="代理，如 http://127.0.0.1:7890")

    # 历史记录
    parser.add_argument("--no-history", action="store_true",
                        help="本次下载不写入下载历史记录")
    parser.add_argument("--history-file", metavar="文件",
                        help="下载历史文件路径，默认脚本同目录 download_history.log")

    return parser.parse_args()


def main():
    args = _parse_args()
    config = _load_config()

    _setup_ytdlp()
    import yt_dlp  # noqa: E402

    ffmpeg_dir = _find_ffmpeg_dir()
    if not ffmpeg_dir:
        sys.exit("错误：找不到 ffmpeg。请安装 ffmpeg 或设置环境变量 FFMPEG_LOCATION。")

    # 命令行参数 > config.json > 内置默认值
    cookies = args.cookies or config.get("cookies")
    browser = args.browser or config.get("browser")
    if cookies and browser:
        sys.exit("错误：cookies 与 browser 不能同时使用（命令行与 config.json 中只能二选一）。")

    user_agent = args.user_agent or config.get("user_agent")
    referer = args.referer or config.get("referer")
    proxy = args.proxy or config.get("proxy")

    out_dir = _resolve_path(args.out_dir or config.get("out_dir"),
                            os.path.join(HERE, "downloads"))
    history_file = _resolve_path(args.history_file or config.get("history_file"),
                                 DEFAULT_HISTORY_FILE)
    # 历史记录开关：config 的 history 为 false 或命令行 --no-history 时关闭
    history_enabled = bool(config.get("history", True)) and not args.no_history

    os.makedirs(out_dir, exist_ok=True)

    # 标题保留：网页链接用源标题；m3u8 直链无标题时回退到 id
    outtmpl = os.path.join(out_dir, "%(title).180B [%(id)s].%(ext)s")

    ydl_opts = {
        "ffmpeg_location": ffmpeg_dir,
        "outtmpl": outtmpl,
        # m3u8 单流(HLS 多为音视频混合 TS)用 best 最稳
        "format": "best",
        # 下载的 TS 由 ffmpeg 转封装成 mp4
        "merge_output_format": "mp4",
        "noplaylist": True,
        "concurrent_fragment_downloads": 16,
        "retries": 10,
        "fragment_retries": 10,
    }

    # 登录态
    if cookies:
        ydl_opts["cookiefile"] = cookies
    if browser:
        ydl_opts["cookiesfrombrowser"] = (browser,)

    # 防盗链 / 覆盖 UA
    headers = {}
    if user_agent:
        headers["User-Agent"] = user_agent
    if referer:
        headers["Referer"] = referer
    if headers:
        ydl_opts["http_headers"] = headers

    # 代理
    if proxy:
        ydl_opts["proxy"] = proxy

    entry = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "url": args.url,
        "status": "success",
        "title": None,
        "id": None,
        "filepath": None,
        "out_dir": out_dir,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url=args.url, download=True)

        filepath = None
        if info and "requested_downloads" in info:
            for d in info["requested_downloads"]:
                fp = d.get("filepath") or d.get("filename")
                if fp:
                    print("已下载:", fp)
                    filepath = filepath or fp
        else:
            print("完成，输出目录:", out_dir)

        if isinstance(info, dict):
            entry["title"] = info.get("title")
            entry["id"] = info.get("id")
        entry["filepath"] = filepath
    except Exception as e:
        entry["status"] = "failed"
        entry["error"] = str(e)
        if history_enabled:
            _append_history(history_file, entry)
        raise
    else:
        if history_enabled:
            _append_history(history_file, entry)


if __name__ == "__main__":
    main()
