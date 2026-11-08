# -*- coding: utf-8 -*-
"""
hls_download.py — 加密 HLS 视频下载器（yt-dlp + ffmpeg 封装）
支持下载加密的 HLS 流视频，支持粘贴网页链接下载和视频直链下载。

支持解决 IDM 报「由于法律原因，IDM无法下载此受保护的数据」的问题。
原理：这类视频是 AES-128 加密的 HLS 流，IDM 不会解密；本工具用 yt-dlp + ffmpeg
自动完成「抓 m3u8 → 下载分片 → 解密 → 合并成 MP4」，并保留源标题。

用法：
    python hls_download.py "<网页链接 或 视频直链m3u8 链接>" [输出目录]

可选参数（防盗链 / 登录态 / 代理）：
    --cookies <文件>       读取 cookies.txt（浏览器过验证后导出）
    -b, --browser <名>     从浏览器读 cookie（chrome / firefox / edge）
    --ua, --user-agent <串> 覆盖 User-Agent
    -r, --referer <url>    防盗链 Referer
    --proxy <url>          代理，如 http://127.0.0.1:7890

依赖定位（按优先级）：
    yt-dlp ：优先系统已安装，否则用脚本同目录 / 上级目录下的 ytdlp_lib/
    ffmpeg ：优先环境变量 FFMPEG_LOCATION，否则用脚本同目录 / 上级目录下的 ffmpeg*/bin/
"""
import argparse
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # 上级目录


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

    return parser.parse_args()


def main():
    args = _parse_args()

    _setup_ytdlp()
    import yt_dlp  # noqa: E402

    ffmpeg_dir = _find_ffmpeg_dir()
    if not ffmpeg_dir:
        sys.exit("错误：找不到 ffmpeg。请安装 ffmpeg 或设置环境变量 FFMPEG_LOCATION。")

    out_dir = args.out_dir if args.out_dir else os.path.join(HERE, "downloads")
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
    if args.cookies:
        ydl_opts["cookiefile"] = args.cookies
    if args.browser:
        ydl_opts["cookiesfrombrowser"] = (args.browser,)

    # 防盗链 / 覆盖 UA
    headers = {}
    if args.user_agent:
        headers["User-Agent"] = args.user_agent
    if args.referer:
        headers["Referer"] = args.referer
    if headers:
        ydl_opts["http_headers"] = headers

    # 代理
    if args.proxy:
        ydl_opts["proxy"] = args.proxy

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url=args.url, download=True)
        if info and "requested_downloads" in info:
            for d in info["requested_downloads"]:
                print("已下载:", d.get("filepath") or d.get("filename"))
        else:
            print("完成，输出目录:", out_dir)


if __name__ == "__main__":
    main()
