# -*- coding: utf-8 -*-
"""
hls_download.py — 加密 HLS 视频下载器（yt-dlp + ffmpeg 封装）
支持下载加密的 HLS 流视频，支持粘贴网页链接下载和视频直链下载。

支持解决 IDM 报「由于法律原因，IDM无法下载此受保护的数据」的问题。
原理：这类视频是 AES-128 加密的 HLS 流，IDM 不会解密；本工具用 yt-dlp + ffmpeg
自动完成「抓 m3u8 → 下载分片 → 解密 → 合并成 MP4」，并保留源标题。

用法：
    python hls_download.py "<网页链接 或 视频直链m3u8 链接>" [输出目录]

可选参数（防盗链 / 登录态 / 代理 / 历史记录 / 文件名 / 批量）：
    --cookies <文件>       读取 cookies 文件（Netscape cookies.txt 或 Cookie-Editor 的 JSON 导出，自动识别）
    -b, --browser <名>     从浏览器读 cookie（chrome / firefox / edge）
    --ua, --user-agent <串> 覆盖 User-Agent
    -r, --referer <url>    防盗链 Referer
    --proxy <url>          代理，如 http://127.0.0.1:7890
    -o, --output <文件名>  固定输出文件名（不含扩展名时自动补 .mp4，已含扩展名则原样）
    --overwrite            同名文件直接覆盖（默认加序号，如 名称 (1).mp4）
    --batch <文件>         批量下载，每行 "URL [文件名]"，# 注释行与空行忽略
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
import re
import shutil
import sys
import tempfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # 上级目录

CONFIG_FILE = os.path.join(HERE, "config.json")
DEFAULT_HISTORY_FILE = os.path.join(HERE, "download_history.log")

# 视为「已含扩展名」的音视频后缀，命中则文件名原样不补 .mp4
_VIDEO_EXTS = (
    ".mp4", ".mkv", ".ts", ".mov", ".flv", ".webm", ".avi",
    ".mp3", ".m4a", ".aac", ".wav", ".m3u8",
)


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


def _strip_ansi(text):
    """去掉文本里的 ANSI 颜色控制码（如 [0;31m），避免写进下载历史。"""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _is_json_cookie_file(path):
    """判断 --cookies 指向的文件是否为 Cookie-Editor 导出的 JSON 格式。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return isinstance(data, (dict, list))
    except (OSError, ValueError):
        return False


def _convert_json_cookies(src):
    """把 Cookie-Editor 的 JSON 导出转成 Netscape cookies.txt，写入临时文件并返回路径。

    转换失败（非预期结构）返回 None。
    """
    with open(src, "r", encoding="utf-8") as f:
        data = json.load(f)
    cookies = data.get("cookies") if isinstance(data, dict) else data
    if not isinstance(cookies, list):
        return None
    lines = ["# Netscape HTTP Cookie File", ""]
    for c in cookies:
        if not isinstance(c, dict):
            continue
        domain = c.get("domain", "")
        if not domain:
            continue
        host_only = bool(c.get("hostOnly", False))
        include = "FALSE" if host_only else "TRUE"
        d = domain if host_only else (domain if domain.startswith(".") else "." + domain)
        path = c.get("path") or "/"
        secure = "TRUE" if c.get("secure") else "FALSE"
        exp = c.get("expirationDate")
        expiry = "0" if (c.get("session") or exp is None) else str(int(float(exp)))
        lines.append("\t".join([d, include, path, secure, expiry,
                                c.get("name", ""), c.get("value", "")]))
    fd, tmp = tempfile.mkstemp(prefix="hls_cookies_", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return tmp


def _ensure_ext(name):
    """把用户指定的文件名补全扩展名：已含常见音视频后缀则原样，否则补 .mp4。"""
    name = (name or "").strip()
    if not name:
        return None
    if any(name.lower().endswith(e) for e in _VIDEO_EXTS):
        return name
    return name + ".mp4"


def _move_to_final(src, out_dir, overwrite):
    """把 staging 里的成品文件移到 out_dir。

    同名时默认加序号（名称 (1).mp4、(2)…）；--overwrite 时直接覆盖。
    返回最终落盘路径。
    """
    basename = os.path.basename(src)
    dst = os.path.join(out_dir, basename)
    if overwrite:
        existed = os.path.exists(dst)
        os.replace(src, dst)
        if existed:
            print(f"提示：{basename} 已存在，已覆盖")
        return dst
    if not os.path.exists(dst):
        os.replace(src, dst)
        return dst
    root, ext = os.path.splitext(basename)
    i = 1
    while True:
        cand = f"{root} ({i}){ext}"
        cand_path = os.path.join(out_dir, cand)
        if not os.path.exists(cand_path):
            os.replace(src, cand_path)
            print(f"提示：{basename} 已存在，改存为 {cand}")
            return cand_path
        i += 1


def _read_batch_file(path):
    """读批量下载文件：每行 "URL [文件名]"，# 注释行与空行忽略。

    返回 [(url, 文件名或 None), ...]。
    """
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 1)
            url = parts[0]
            name = parts[1].strip() if len(parts) > 1 else None
            items.append((url, name))
    return items


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
    return _strip_ansi(f"{time} {mark} {title} (id={vid}) | {url} | {detail}")


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
    parser.add_argument("url", nargs="?", default=None,
                        help="网页链接 或 视频直链(m3u8)链接（与 --batch 二选一）")
    parser.add_argument(
        "out_dir", nargs="?", default=None,
        help="输出目录，默认脚本同目录下 downloads/",
    )

    # 登录态 / 反爬（二选一）
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--cookies", metavar="文件",
                       help="读取 cookies 文件（支持 Netscape cookies.txt 或 Cookie-Editor 导出的 JSON）")
    group.add_argument("-b", "--browser", metavar="名称",
                       help="从浏览器读 cookie（如 chrome / firefox / edge）")

    # 防盗链
    parser.add_argument("--ua", "--user-agent", dest="user_agent", metavar="串",
                        help="覆盖 User-Agent")
    parser.add_argument("-r", "--referer", metavar="URL", help="防盗链 Referer")
    parser.add_argument("--proxy", metavar="URL", help="代理，如 http://127.0.0.1:7890")

    # 文件名 / 重复处理 / 批量
    parser.add_argument("-o", "--output", metavar="文件名",
                        help="固定输出文件名（不含扩展名时自动补 .mp4，已含扩展名则原样）")
    parser.add_argument("--overwrite", action="store_true",
                        help="同名文件直接覆盖（默认加序号，如 名称 (1).mp4）")
    parser.add_argument("--batch", metavar="文件",
                        help="批量下载，每行 \"URL [文件名]\"，# 注释行与空行忽略")

    # 历史记录
    parser.add_argument("--no-history", action="store_true",
                        help="本次下载不写入下载历史记录")
    parser.add_argument("--history-file", metavar="文件",
                        help="下载历史文件路径，默认脚本同目录 download_history.log")

    return parser.parse_args()


def _download_one(url, ydl_opts, out_dir, history_enabled, history_file, overwrite, want_name):
    """下载单个 URL，落到 out_dir（同名加序号/覆盖）。返回 (entry, error)。

    error 为 None 表示成功，否则为捕获到的异常（已写失败历史）。
    """
    entry = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "url": url,
        "status": "success",
        "title": None,
        "id": None,
        "filepath": None,
        "out_dir": out_dir,
    }

    # 下载到同盘 staging 目录，保证 move 原子、不会留下半成品
    staging_dir = tempfile.mkdtemp(dir=out_dir, prefix=".hls_staging_")
    opts = dict(ydl_opts)
    if want_name:
        final_name = _ensure_ext(want_name)
        opts["outtmpl"] = os.path.join(staging_dir, final_name)
        # 用户指定了扩展名时，让 ffmpeg 转封装成对应容器
        ext = os.path.splitext(final_name)[1].lstrip(".")
        if ext:
            opts["merge_output_format"] = ext
    else:
        opts["outtmpl"] = os.path.join(staging_dir, "%(title).180B [%(id)s].%(ext)s")

    import yt_dlp  # 已由 main() 先调用 _setup_ytdlp() 保证可导入

    error = None
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url=url, download=True)

        final_path = None
        downloaded = info.get("requested_downloads") if isinstance(info, dict) else None
        if downloaded:
            for d in downloaded:
                src = d.get("filepath") or d.get("filename")
                if src and os.path.isfile(src):
                    p = _move_to_final(src, out_dir, overwrite)
                    final_path = final_path or p
        # 回退：拿不到 requested_downloads 时，扫 staging 里的成品文件
        if final_path is None:
            for fn in sorted(os.listdir(staging_dir)):
                src = os.path.join(staging_dir, fn)
                if os.path.isfile(src):
                    p = _move_to_final(src, out_dir, overwrite)
                    final_path = final_path or p

        if isinstance(info, dict):
            entry["title"] = info.get("title")
            entry["id"] = info.get("id")
        entry["filepath"] = final_path

        if final_path:
            print("已下载:", final_path)
        else:
            print("完成，输出目录:", out_dir)
    except Exception as e:
        entry["status"] = "failed"
        entry["error"] = str(e)
        error = e
    finally:
        if history_enabled:
            _append_history(history_file, entry)
        shutil.rmtree(staging_dir, ignore_errors=True)

    return entry, error


def main():
    args = _parse_args()
    config = _load_config()

    _setup_ytdlp()

    ffmpeg_dir = _find_ffmpeg_dir()
    if not ffmpeg_dir:
        sys.exit("错误：找不到 ffmpeg。请安装 ffmpeg 或设置环境变量 FFMPEG_LOCATION。")

    # 命令行参数 > config.json > 内置默认值
    cookies = args.cookies or config.get("cookies")
    browser = args.browser or config.get("browser")
    if cookies and browser:
        sys.exit("错误：cookies 与 browser 不能同时使用（命令行与 config.json 中只能二选一）。")

    # --cookies 指向 Cookie-Editor 的 JSON 导出时，自动转成 Netscape 临时文件
    tmp_cookie = None
    if cookies and _is_json_cookie_file(cookies):
        tmp_cookie = _convert_json_cookies(cookies)
        if not tmp_cookie:
            sys.exit("错误：cookies 文件是 JSON 格式但结构不合法，无法转换（应为 Cookie-Editor 导出格式）。")
        print("提示：检测到 JSON 格式 cookies，已自动转换为 Netscape 格式。")
        cookies = tmp_cookie

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

    # 参数互斥校验
    if args.batch and args.url:
        sys.exit("错误：url 与 --batch 不能同时使用。")
    if args.batch and args.output:
        sys.exit("错误：--output 与 --batch 不能同时使用（批量时文件名写在每行链接后面）。")
    if not args.batch and not args.url:
        sys.exit("错误：请提供 url，或使用 --batch 指定批量下载文件。")

    ydl_opts = {
        "ffmpeg_location": ffmpeg_dir,
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

    try:
        if args.batch:
            items = _read_batch_file(args.batch)
            if not items:
                sys.exit("错误：批量文件为空或无可下载的 URL。")
            ok = fail = 0
            for i, (url, name) in enumerate(items, 1):
                print(f"[{i}/{len(items)}] 下载中: {url}")
                _, err = _download_one(url, ydl_opts, out_dir, history_enabled,
                                       history_file, args.overwrite, name)
                if err is None:
                    ok += 1
                else:
                    fail += 1
                    print(f"    失败：{url}（{err}）")
            print(f"批量下载完成：成功 {ok} 条，失败 {fail} 条。")
        else:
            _, err = _download_one(args.url, ydl_opts, out_dir, history_enabled,
                                   history_file, args.overwrite, args.output)
            if err is not None:
                raise err
    finally:
        if tmp_cookie and os.path.isfile(tmp_cookie):
            try:
                os.remove(tmp_cookie)
            except OSError:
                pass


if __name__ == "__main__":
    main()
