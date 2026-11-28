# -*- coding: utf-8 -*-
"""gui.py — hls-downloader 的 tkinter 图形界面（核心下载 + 批量 + 代理）。"""
import logging
import os
import queue
import re
import threading

import hls_download as h

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
except ImportError:
    raise SystemExit("错误：需要 tkinter（Python 标准库自带）。")


MAX_LOG_LINES = 5000
QUEUE_MAXSIZE = 5000


def _configured_out_dir():
    default = os.path.join(h.DATA_DIR, "downloads")
    return h._resolve_path(h._load_config().get("out_dir"), default)


class _QueueLogHandler(logging.Handler):
    """把 yt-dlp 的日志消息推入 queue，供主线程回显。"""

    def __init__(self, q):
        super().__init__()
        self.q = q

    def emit(self, record):
        try:
            self.q.put_nowait(h._redact_sensitive_text(record.getMessage()))
        except queue.Full:
            # 日志拥塞时丢弃最旧的普通日志，不能阻塞 yt-dlp 下载线程。
            try:
                self.q.get_nowait()
                self.q.put_nowait(h._redact_sensitive_text(record.getMessage()))
            except (queue.Empty, queue.Full):
                pass


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
        self.q = queue.Queue(maxsize=QUEUE_MAXSIZE)
        self.stop_evt = threading.Event()
        self.worker = None
        self._progress_title = None
        self._closing = False
        self._tmp_cookie = None

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._poll_queue)

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="视频链接（单条填 1 行；批量填多行，每行「URL [文件名]」）：").grid(row=0, column=0, sticky="w", **pad)
        self.url_text = scrolledtext.ScrolledText(frm, height=6, width=72)
        self.url_text.grid(row=1, column=0, columnspan=2, sticky="we", **pad)

        ttk.Label(frm, text="输出目录：").grid(row=2, column=0, sticky="w", **pad)
        self.out_var = tk.StringVar(value=_configured_out_dir())
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

        self.progress = ttk.Progressbar(frm, mode="determinate", maximum=100, value=0)
        self.progress.grid(row=11, column=0, columnspan=2, sticky="we", **pad)

        self.status_var = tk.StringVar(value="待命")
        self.status_label = tk.Label(
            frm, textvariable=self.status_var, anchor="w",
            font=("Microsoft YaHei", 11, "bold"), fg="#1a1a1a")
        self.status_label.grid(row=12, column=0, columnspan=2, sticky="we", **pad)

        self.log_text = scrolledtext.ScrolledText(frm, height=12, width=72, state="disabled")
        self.log_text.grid(row=13, column=0, columnspan=2, sticky="nsew", **pad)

        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(13, weight=1)

    def _pick_out(self):
        d = filedialog.askdirectory()
        if d:
            self.out_var.set(d)

    def _pick_cookie(self):
        f = filedialog.askopenfilename()
        if f:
            self.cookie_var.set(f)

    def _queue_put(self, item, critical=False):
        """跨线程投递 UI 消息；队列满时优先保留状态/错误等关键事件。"""
        try:
            self.q.put_nowait(item)
            return
        except queue.Full:
            if not critical:
                return
        try:
            self.q.get_nowait()
            self.q.put_nowait(item)
        except (queue.Empty, queue.Full):
            pass

    def _poll_queue(self):
        """主线程统一消费队列：str=日志，__status__=状态栏，__progress__=进度，__error__=弹框。"""
        try:
            # 每轮最多处理 300 条，避免高频日志长期占用 Tk 主线程。
            for _ in range(300):
                item = self.q.get_nowait()
                if isinstance(item, tuple):
                    kind, payload = item
                    if kind == "__status__":
                        self.status_var.set(payload)
                    elif kind == "__progress__":
                        self._set_progress(payload)
                    elif kind == "__error__":
                        self._append_log(payload)
                        self.status_var.set("❌ 失败")
                        messagebox.showerror("错误", payload)
                else:
                    self._append_log(item)
        except queue.Empty:
            pass
        if self._closing and self.worker:
            if not self.worker.is_alive():
                # worker 已收尾（临时 cookie 等已清理），此时再销毁窗口
                self.root.destroy()
                return
        self.root.after(100, self._poll_queue)

    def _set_progress(self, d):
        """根据 yt-dlp progress_hooks 的 dict 刷新进度条与状态栏。

        进度源优先级：
        1. HLS 分片进度 fragment_index/fragment_count —— 单调、稳定，不会因
           yt-dlp 的 total_bytes_estimate 逐片估算而回退/忽快忽慢（动画异常根因）；
        2. yt-dlp 的 _percent_str（普通 HTTP 下载，最准）；
        3. downloaded_bytes / total_bytes（或 total_bytes_estimate）字节推算；
        4. live 流（无总片数、无总字节）—— 只显示已下载字节数，不设进度百分比。
        """
        if d.get("_reset"):
            self.progress["value"] = 0
            self._progress_title = None
            return

        pct = None
        frag_index = d.get("fragment_index")
        frag_count = d.get("fragment_count")
        if frag_count:
            # HLS 分片进度：fragment_index 单调递增到 fragment_count，最稳
            pct = (frag_index or 0) / frag_count * 100
        if pct is None and d.get("_percent_str"):
            try:
                pct = float(d["_percent_str"].rstrip("%"))
            except (TypeError, ValueError):
                pct = None
        if pct is None and (d.get("total_bytes") or d.get("total_bytes_estimate")):
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total > 0:
                pct = (d.get("downloaded_bytes") or 0) / total * 100

        if pct is not None:
            self.progress["value"] = min(max(pct, 0.0), 100.0)

        title = (d.get("info_dict") or {}).get("title")
        if title:
            self._progress_title = title
        prefix = d.get("_prefix") or "下载中："
        live_done = (d.get("downloaded_bytes") or 0) / 1048576  # MB
        if self._progress_title:
            if pct is not None:
                self.status_var.set(f"{prefix}{self._progress_title}  {pct:.1f}%")
            elif not frag_count and live_done > 0:
                self.status_var.set(f"{prefix}{self._progress_title}  已下载 {live_done:.1f} MB")
            else:
                self.status_var.set(f"{prefix}{self._progress_title}")
        elif pct is not None:
            self.status_var.set(f"{prefix}{pct:.1f}%")

    def _append_log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", h._redact_sensitive_text(msg) + "\n")
        # 限制 Text 控件历史，防止长时间批量下载导致 GUI 内存持续增长。
        line_count = int(self.log_text.index("end-1c").split(".")[0])
        if line_count > MAX_LOG_LINES:
            self.log_text.delete("1.0", f"{line_count - MAX_LOG_LINES}.0")
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    def _cleanup_tmp_cookie(self):
        path = self._tmp_cookie
        self._tmp_cookie = None
        if path and os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass

    def _start(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("提示", "已有下载在进行中。")
            return
        raw = self.url_text.get("1.0", "end").strip()
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        if not lines:
            messagebox.showwarning("提示", "请填写至少一个视频链接。")
            return
        out_dir = h._resolve_path(self.out_var.get().strip(), _configured_out_dir())
        name = self.name_var.get().strip() or None
        cookies = self.cookie_var.get().strip() or None
        proxy = self.proxy_var.get().strip() or None
        is_batch = len(lines) > 1
        self.stop_evt.clear()
        self.worker = threading.Thread(
            target=self._download, args=(lines, out_dir, name, cookies, proxy, is_batch),
            daemon=False)
        self.worker.start()

    def _stop(self):
        self.stop_evt.set()
        self._queue_put(("__status__", "已请求停止（当前片段结束后生效）…"), critical=True)

    def _on_close(self):
        """关闭窗口：下载中先请求停止，等 worker 收尾并清理临时文件后再销毁窗口。"""
        if self.worker and self.worker.is_alive():
            self._closing = True
            self.stop_evt.set()
            self.status_var.set("正在停止并清理，请稍候…（下载线程结束后自动关闭）")
        else:
            self.root.destroy()

    def _progress_hook(self, d, prefix="下载中："):
        """yt-dlp progress_hooks 回调（worker 线程）：把下载进度推到主线程。

        前缀随进度 payload 一起传入，避免 worker 写主线程属性造成竞态。
        """
        if d.get("status") in ("downloading", "finished"):
            self._queue_put(("__progress__", {**d, "_prefix": prefix}))

    def _download(self, lines, out_dir, name, cookies, proxy, is_batch):
        prefix = "下载中："

        def log(msg):
            self._queue_put(msg)

        def fail(msg):
            self._queue_put(("__error__", msg), critical=True)

        try:
            h._setup_ytdlp()
            ffmpeg_dir = h._find_ffmpeg_dir()
            if not ffmpeg_dir:
                fail("错误：找不到 ffmpeg。请安装 ffmpeg 并加入 PATH，或设置环境变量 FFMPEG_LOCATION 指向其 bin 目录；或改用完整版（内置 ffmpeg）。")
                return

            ydl_opts = {
                "ffmpeg_location": ffmpeg_dir,
                "format": "best",
                "merge_output_format": "mp4",
                "noplaylist": True,
                "concurrent_fragment_downloads": 16,
                # 重试由外层 _run_single/_run_batch 控制，yt-dlp 内部不再叠加
                "retries": 0,
                "fragment_retries": 0,
                "logger": _build_logger(self.q),
                "progress_hooks": [lambda d: self._progress_hook(d, prefix)],
            }

            if cookies:
                if h._is_json_cookie_file(cookies):
                    tmp_cookie = h._convert_json_cookies(cookies)
                    if not tmp_cookie:
                        fail("错误：cookies 文件是 JSON 但结构不合法。")
                        return
                    self._tmp_cookie = tmp_cookie
                    log("提示：检测到 JSON cookies，已自动转 Netscape。")
                    cookies = tmp_cookie
                ydl_opts["cookiefile"] = cookies
            if proxy:
                ydl_opts["proxy"] = proxy

            config = h._load_config()
            history_enabled = h._as_bool(config.get("history", True))
            history_file = h._resolve_path(config.get("history_file"), h.DEFAULT_HISTORY_FILE)
            retries = 3
            try:
                retries = int(config.get("retries", 3))
            except (TypeError, ValueError):
                retries = 3
            retries = max(0, min(retries, h.MAX_RETRIES))
            os.makedirs(out_dir, exist_ok=True)

            if is_batch:
                # 批量：复用 h._run_batch；拦截「[i/M] 开始下载」更新进度前缀
                items = []
                for ln in lines:
                    parts = ln.split(None, 1)
                    url = parts[0]
                    nm = parts[1].strip() if len(parts) > 1 else None
                    items.append((url, nm))
                total = len(items)

                def batch_log(msg):
                    nonlocal prefix
                    m = re.match(r"\[(\d+)/(\d+)\] 开始下载", msg)
                    if m:
                        prefix = f"[{m.group(1)}/{total}] 正在下载："
                        self._queue_put(("__progress__", {"_reset": True}))
                    self._queue_put(msg)

                self._queue_put(("__status__", f"开始批量下载，共 {total} 条"), critical=True)
                ok, fail_count, failed_file = h._run_batch(
                    items, ydl_opts, out_dir, history_enabled, history_file,
                    False, retries, log=batch_log, stop_evt=self.stop_evt)
                if self.stop_evt.is_set():
                    self._queue_put(("__status__", "已停止"), critical=True)
                elif fail_count:
                    self._queue_put(("__status__", f"⚠️ 批量下载完成：成功 {ok}/{total}，失败 {fail_count}"), critical=True)
                else:
                    self._queue_put(("__status__", f"✅ 批量下载完成：成功 {ok}/{total}"), critical=True)
            else:
                self._queue_put(("__status__", "开始下载…"), critical=True)
                err = h._run_single(lines[0], name, ydl_opts, out_dir, history_enabled,
                                    history_file, False, retries, log=log,
                                    stop_evt=self.stop_evt)
                if self.stop_evt.is_set():
                    self._queue_put(("__status__", "已停止"), critical=True)
                elif err is not None:
                    log(f"下载失败：{err}")
                    self._queue_put(("__status__", "❌ 下载失败"), critical=True)
                else:
                    self._queue_put(("__status__", "✅ 下载成功"), critical=True)
        except h.DownloadCancelled:
            self._queue_put(("__status__", "已停止"), critical=True)
        except Exception as e:
            fail(f"异常：{e}")
        finally:
            self._cleanup_tmp_cookie()


def main():
    h._ensure_console_utf8()
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
