# -*- coding: utf-8 -*-
"""gui.py — hls-downloader 的 tkinter 图形界面（核心下载 + 批量 + 代理）。"""
import logging
import os
import queue
import threading

import hls_download as h

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
except ImportError:
    raise SystemExit("错误：需要 tkinter（Python 标准库自带）。")


class _QueueLogHandler(logging.Handler):
    """把 yt-dlp 的日志消息推入 queue，供主线程回显。"""

    def __init__(self, q):
        super().__init__()
        self.q = q

    def emit(self, record):
        self.q.put(record.getMessage())


def _build_logger(q):
    logger = logging.getLogger("hls_gui_ytdlp")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.addHandler(_QueueLogHandler(q))
    return logger


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("HLS 视频下载器")
        self.q = queue.Queue()
        self.stop_evt = threading.Event()
        self.worker = None

        self._build_ui()
        self.root.after(100, self._poll_queue)

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="视频链接（单条填 1 行；批量填多行，每行「URL [文件名]」）：").grid(row=0, column=0, sticky="w", **pad)
        self.url_text = scrolledtext.ScrolledText(frm, height=6, width=72)
        self.url_text.grid(row=1, column=0, columnspan=2, sticky="we", **pad)

        ttk.Label(frm, text="输出目录：").grid(row=2, column=0, sticky="w", **pad)
        self.out_var = tk.StringVar(value=os.path.join(h.DATA_DIR, "downloads"))
        ttk.Entry(frm, textvariable=self.out_var, width=56).grid(row=3, column=0, sticky="we", **pad)
        ttk.Button(frm, text="选择…", command=self._pick_out).grid(row=3, column=1, **pad)

        ttk.Label(frm, text="文件名（可选，单条时生效）：").grid(row=4, column=0, sticky="w", **pad)
        self.name_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.name_var, width=56).grid(row=5, column=0, sticky="we", **pad)

        ttk.Label(frm, text="cookies 文件（可选，Netscape 或 Cookie-Editor JSON）：").grid(row=6, column=0, sticky="w", **pad)
        self.cookie_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.cookie_var, width=56).grid(row=7, column=0, sticky="we", **pad)
        ttk.Button(frm, text="选择…", command=self._pick_cookie).grid(row=7, column=1, **pad)

        ttk.Label(frm, text="代理（可选，如 http://127.0.0.1:7890）：").grid(row=8, column=0, sticky="w", **pad)
        self.proxy_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.proxy_var, width=56).grid(row=9, column=0, sticky="we", **pad)

        btns = ttk.Frame(frm)
        btns.grid(row=10, column=0, columnspan=2, sticky="w", **pad)
        ttk.Button(btns, text="开始下载", command=self._start).pack(side="left", padx=4)
        ttk.Button(btns, text="停止", command=self._stop).pack(side="left", padx=4)

        self.status_var = tk.StringVar(value="待命")
        ttk.Label(frm, textvariable=self.status_var).grid(row=11, column=0, columnspan=2, sticky="w", **pad)

        self.log_text = scrolledtext.ScrolledText(frm, height=12, width=72, state="disabled")
        self.log_text.grid(row=12, column=0, columnspan=2, sticky="nsew", **pad)

        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(12, weight=1)

    def _pick_out(self):
        d = filedialog.askdirectory()
        if d:
            self.out_var.set(d)

    def _pick_cookie(self):
        f = filedialog.askopenfilename()
        if f:
            self.cookie_var.set(f)

    def _poll_queue(self):
        """主线程统一消费队列：str=日志，__status__=状态栏，__error__=弹框。"""
        try:
            while True:
                item = self.q.get_nowait()
                if isinstance(item, tuple):
                    kind, payload = item
                    if kind == "__status__":
                        self.status_var.set(payload)
                    elif kind == "__error__":
                        self._append_log(payload)
                        self.status_var.set("失败")
                        messagebox.showerror("错误", payload)
                else:
                    self._append_log(item)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _append_log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", str(msg) + "\n")
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    def _start(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("提示", "已有下载在进行中。")
            return
        raw = self.url_text.get("1.0", "end").strip()
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        if not lines:
            messagebox.showwarning("提示", "请填写至少一个视频链接。")
            return
        out_dir = self.out_var.get().strip() or os.path.join(h.DATA_DIR, "downloads")
        name = self.name_var.get().strip() or None
        cookies = self.cookie_var.get().strip() or None
        proxy = self.proxy_var.get().strip() or None
        is_batch = len(lines) > 1
        self.stop_evt.clear()
        self.worker = threading.Thread(
            target=self._download, args=(lines, out_dir, name, cookies, proxy, is_batch),
            daemon=True)
        self.worker.start()

    def _stop(self):
        self.stop_evt.set()
        self.q.put(("__status__", "已请求停止（当前片段结束后生效）…"))

    def _download(self, lines, out_dir, name, cookies, proxy, is_batch):
        def log(msg):
            self.q.put(msg)

        def fail(msg):
            self.q.put(("__error__", msg))

        try:
            h._setup_ytdlp()
            ffmpeg_dir = h._find_ffmpeg_dir()
            if not ffmpeg_dir:
                fail("错误：找不到 ffmpeg。请安装 ffmpeg 或设置环境变量 FFMPEG_LOCATION。")
                return

            os.makedirs(out_dir, exist_ok=True)

            ydl_opts = {
                "ffmpeg_location": ffmpeg_dir,
                "format": "best",
                "merge_output_format": "mp4",
                "noplaylist": True,
                "concurrent_fragment_downloads": 16,
                "retries": 10,
                "fragment_retries": 10,
                "logger": _build_logger(self.q),
            }

            tmp_cookie = None
            if cookies:
                if h._is_json_cookie_file(cookies):
                    tmp_cookie = h._convert_json_cookies(cookies)
                    if not tmp_cookie:
                        fail("错误：cookies 文件是 JSON 但结构不合法。")
                        return
                    log("提示：检测到 JSON cookies，已自动转 Netscape。")
                    cookies = tmp_cookie
                ydl_opts["cookiefile"] = cookies
            if proxy:
                ydl_opts["proxy"] = proxy

            config = h._load_config()
            history_enabled = bool(config.get("history", True))
            history_file = h.DEFAULT_HISTORY_FILE
            retries = 3
            try:
                retries = int(config.get("retries", 3))
            except (TypeError, ValueError):
                retries = 3

            try:
                if is_batch:
                    # 批量：复用 h._run_batch，带回重试 + 失败清单；stop_evt 支持停止后续条目
                    items = []
                    for ln in lines:
                        parts = ln.split(None, 1)
                        url = parts[0]
                        nm = parts[1].strip() if len(parts) > 1 else None
                        items.append((url, nm))
                    total = len(items)
                    self.q.put(("__status__", f"下载中 1/{total}"))
                    ok, fail_count, failed_file = h._run_batch(
                        items, ydl_opts, out_dir, history_enabled, history_file,
                        False, retries, log=log, stop_evt=self.stop_evt)
                    if self.stop_evt.is_set():
                        self.q.put(("__status__", "已停止"))
                    elif fail_count:
                        self.q.put(("__status__", f"已完成（批量）：成功 {ok}/{total}，失败 {fail_count}"))
                    else:
                        self.q.put(("__status__", f"已完成（批量）：成功 {ok}/{total}"))
                else:
                    self.q.put(("__status__", "下载中…"))
                    err = h._run_single(lines[0], name, ydl_opts, out_dir, history_enabled,
                                        history_file, False, retries, log=log,
                                        stop_evt=self.stop_evt)
                    if err is not None:
                        log(f"失败：{err}")
                        self.q.put(("__status__", "失败"))
                    else:
                        self.q.put(("__status__", "成功"))
            finally:
                if tmp_cookie and os.path.isfile(tmp_cookie):
                    try:
                        os.remove(tmp_cookie)
                    except OSError:
                        pass
        except Exception as e:
            fail(f"异常：{e}")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
