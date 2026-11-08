# GUI + 单文件打包 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不破坏 CLI 的前提下，新增 tkinter GUI（核心下载 + 批量 + 代理），并把 CLI 与 GUI 分别打包成单文件自包含 exe（含 ffmpeg + vendored yt-dlp）。

**Architecture:** `gui.py` 直接 `import hls_download` 复用纯函数；给 `hls_download.py` 加 frozen 资源/数据目录区分、`_download_one` 的 `log` 回调、以及把 main() 里的单条/批量循环抽成 `_run_single`/`_run_batch` 两个可复用编排函数。GUI 在后台线程跑下载，经 `queue.Queue` + `root.after` 回主线程刷新日志。

**Tech Stack:** Python 3.11、tkinter（标准库）、yt-dlp（vendored `ytdlp_lib/`）、ffmpeg、PyInstaller（构建期依赖）。

**Spec:** `doc/GUI设计.md`

## Global Constraints

- Python 3.11+，无新增运行时依赖（PyInstaller 仅构建期）。
- 现有 CLI 参数语义、默认值、历史记录格式、`config.json` 优先级（命令行 > config > 默认）**一律不变**。
- ffmpeg 查找优先级不变：环境变量 `FFMPEG_LOCATION` > 搜索目录下 `ffmpeg*/bin`。
- yt-dlp 查找优先级不变：系统已安装 > `ytdlp_lib/`。
- exe 打包**只打 `ffmpeg.exe`**，不打 ffprobe/ffplay/文档。
- 数据文件（config.json / download_history.log / failed_downloads.txt / downloads/）在 frozen 下写 exe 旁边（`os.path.dirname(sys.executable)`），资源（ytdlp_lib / ffmpeg）在 frozen 下读 `sys._MEIPASS`。
- 本仓库**无 pytest 测试套件**，历史上用临时打桩脚本 `_verify_*.py`（fake YoutubeDL）+ 真实命令回归验证，验证后删除。本计划沿用此约定，不引入 pytest。

## Review Focus

| 输入 / 场景 | 期望行为 |
|---|---|
| frozen 下 `__file__` 指向 `_MEIPASS` | config/history/downloads 仍写 exe 旁边（可写），ffmpeg/ytdlp_lib 从 `_MEIPASS` 读到 |
| `_download_one` 的 `log` 默认值 | CLI 不传时输出与改造前逐字一致（默认 `print`） |
| `_run_single`/`_run_batch` 替换 main() 循环后 | 单条重试次数、批量首轮+N 轮、失败清单内容与改造前一致 |
| GUI 跨线程改控件 | 全部经 queue + `root.after` 回主线程，不 `RuntimeError` |
| GUI 传 cookies 为 JSON | 复用 `_convert_json_cookies` 转临时文件并 finally 清理 |
| 无 Python 环境机器双击 exe | 能启动并下载（打包资源完整） |

---

### Task 1: frozen 资源/数据目录区分

**Files:**
- Modify: `hls_download.py:44-50`（HERE/ROOT/常量区）
- Modify: `hls_download.py:59-67`（`_find_ffmpeg_dir`）
- Modify: `hls_download.py:70-83`（`_setup_ytdlp`）

**Interfaces:**
- Consumes: 现有 `HERE`/`ROOT`/`CONFIG_FILE`/`DEFAULT_HISTORY_FILE`/`DEFAULT_FAILED_FILE` 的语义（源码运行 = 脚本同目录）。
- Produces: 新常量 `FROZEN`(bool)、`RESOURCE_DIR`(str)、`DATA_DIR`(str)；`CONFIG_FILE`/`DEFAULT_HISTORY_FILE`/`DEFAULT_FAILED_FILE` 改用 `DATA_DIR`；`_find_ffmpeg_dir()`/`_setup_ytdlp()` 改用 `RESOURCE_DIR`/`DATA_DIR` 搜索。

- [ ] **Step 1: 写验证脚本（打桩，模拟 frozen 路径）**

```python
# _verify_frozen.py（临时，验证后删）
import importlib, sys, os, tempfile
import hls_download as h

# 非 frozen：常量应等于 HERE
assert h.FROZEN is False
assert h.DATA_DIR == h.HERE
assert h.RESOURCE_DIR == h.HERE
assert h.CONFIG_FILE == os.path.join(h.HERE, "config.json")
assert h.DEFAULT_HISTORY_FILE == os.path.join(h.HERE, "download_history.log")

# 模拟 frozen：sys.frozen + sys._MEIPASS + sys.executable 指向临时 exe 目录
tmp = tempfile.mkdtemp()
exe = os.path.join(tmp, "hls_download.exe")
mei = os.path.join(tmp, "_MEI")
sys.frozen = True
sys._MEIPASS = mei
sys.executable = exe
# 重新载入模块以应用新常量
import importlib.util
spec = importlib.util.spec_from_file_location("h2", "hls_download.py")
h2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h2)
assert h2.FROZEN is True
assert h2.DATA_DIR == tmp
assert h2.RESOURCE_DIR == mei
assert h2.CONFIG_FILE == os.path.join(tmp, "config.json")
print("PASS")
```

- [ ] **Step 2: 运行验证脚本，确认失败**

Run: `python _verify_frozen.py`
Expected: FAIL（`h.FROZEN` 不存在 / `AttributeError`）

- [ ] **Step 3: 实现 frozen 目录区分**

在 `hls_download.py` 顶部常量区（替换第 44-50 行）：

```python
HERE = os.path.dirname(os.path.abspath(__file__))
FROZEN = getattr(sys, "frozen", False)
# 资源目录：exe 打包后从 _MEIPASS 读 ytdlp_lib / ffmpeg；源码运行 = 脚本目录
RESOURCE_DIR = getattr(sys, "_MEIPASS", HERE)
# 数据目录：exe 打包后写 exe 旁边（可写）；源码运行 = 脚本目录
DATA_DIR = os.path.dirname(sys.executable) if FROZEN else HERE
ROOT = os.path.dirname(HERE)

CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
DEFAULT_HISTORY_FILE = os.path.join(DATA_DIR, "download_history.log")
DEFAULT_FAILED_FILE = os.path.join(DATA_DIR, "failed_downloads.txt")
DEFAULT_RETRIES = 3
```

修改 `_find_ffmpeg_dir`（第 59-67 行）：

```python
def _find_ffmpeg_dir():
    env = os.environ.get("FFMPEG_LOCATION")
    if env and os.path.isdir(env):
        return env
    bases = [RESOURCE_DIR, DATA_DIR]
    if not FROZEN:
        bases.append(ROOT)
    for base in dict.fromkeys(bases):
        hits = sorted(glob.glob(os.path.join(base, "ffmpeg*", "bin")))
        if hits:
            return hits[0]
    return None
```

修改 `_setup_ytdlp` 的本地 lib 搜索（第 77-82 行）：

```python
    # 2) 本地 lib
    bases = [RESOURCE_DIR, DATA_DIR]
    if not FROZEN:
        bases.append(ROOT)
    for base in dict.fromkeys(bases):
        lib = os.path.join(base, "ytdlp_lib")
        if os.path.isdir(lib):
            sys.path.insert(0, lib)
            return
```

- [ ] **Step 4: 运行验证脚本，确认通过**

Run: `python _verify_frozen.py`
Expected: PASS

- [ ] **Step 5: 回归 CLI（确认源码模式无影响）**

Run: `python hls_download.py --help`
Expected: 参数齐全，无报错；`CONFIG_FILE`/历史文件仍在脚本同目录（用 `python -c "import hls_download as h; print(h.CONFIG_FILE)"` 核对指向脚本同目录）。

- [ ] **Step 6: 提交**

```bash
git add hls_download.py
git commit -m "feat: 支持 frozen（exe 打包）下的资源/数据目录区分"
```
删 `_verify_frozen.py`。

---

### Task 2: `_download_one` 加 `log` 回调

**Files:**
- Modify: `hls_download.py:310-379`（`_download_one` 签名与内部 `print`）

**Interfaces:**
- Consumes: `_download_one` 现有签名（`url, ydl_opts, out_dir, history_enabled, history_file, overwrite, want_name`）。
- Produces: `_download_one(url, ydl_opts, out_dir, history_enabled, history_file, overwrite, want_name, log=print) -> (entry, error)`；函数内 `print(...)` 全部改为 `log(...)`。

- [ ] **Step 1: 写验证脚本**

```python
# _verify_log_cb.py（临时）
import importlib, os, shutil, tempfile
import hls_download as h

captured = []
def my_log(msg):
    captured.append(msg)

# 用一个真实但极小的公开 mp4 直链（非 m3u8，秒下）
url = "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8"  # 大文件，改用小文件见下
```

> 说明：Mux 流 478MB 太大，改用一个小文件（如 `https://filesamples.com/samples/video/mp4/sample_640x360.mp4`）或本地构造。验证重点只测「log 回调被调用、默认 print 不抛错」，不强依赖具体 URL。

```python
h._setup_ytdlp()
ff = h._find_ffmpeg_dir()
opts = {"ffmpeg_location": ff, "format": "best", "merge_output_format": "mp4",
        "noplaylist": True, "concurrent_fragment_downloads": 4,
        "retries": 2, "fragment_retries": 2, "quiet": True}
out = tempfile.mkdtemp()
entry, err = h._download_one(url, opts, out, False, h.DEFAULT_HISTORY_FILE, False, "cb测试", log=my_log)
print("captured count:", len(captured))
print("entry status:", entry["status"], "filepath:", entry["filepath"])
assert len(captured) > 0, "log 回调应被调用"
shutil.rmtree(out, ignore_errors=True)
print("PASS")
```

- [ ] **Step 2: 运行验证脚本，确认失败**

Run: `python _verify_log_cb.py`
Expected: FAIL（`TypeError: _download_one() got an unexpected keyword argument 'log'`）

- [ ] **Step 3: 实现 `log` 回调**

修改 `_download_one` 签名（第 310 行）：

```python
def _download_one(url, ydl_opts, out_dir, history_enabled, history_file, overwrite, want_name, log=print):
```

把函数体里的三处 `print(...)` 改为 `log(...)`：
- 第 367 行 `print("已下载:", final_path)` → `log("已下载:", final_path)`
- 第 369 行 `print("完成，输出目录:", out_dir)` → `log("完成，输出目录:", out_dir)`

（`_move_to_final`/`_append_history`/`_write_failed_list` 内部的 `print` 警告**保持不变**，属 CLI 侧提示；GUI 通过 yt-dlp logger 回显下载进度，这些罕见警告不进 GUI 日志，可接受。）

- [ ] **Step 4: 运行验证脚本，确认通过**

Run: `python _verify_log_cb.py`
Expected: PASS（captured count > 0，entry status 正常）

- [ ] **Step 5: 提交**

```bash
git add hls_download.py
git commit -m "feat: _download_one 增加 log 回调，供 GUI 复用下载日志"
```
删 `_verify_log_cb.py`。

---

### Task 3: 抽 `_run_single`/`_run_batch`，main 变薄壳

**Files:**
- Modify: `hls_download.py:382-528`（`main`）
- Create: 在 `_download_one` 之后、`main` 之前插入 `_run_single`/`_run_batch`

**Interfaces:**
- Consumes: `_download_one`（Task 2 产物）、`_retry_pending`、`_write_failed_list`、`_read_batch_file`。
- Produces:
  - `_run_single(url, name, ydl_opts, out_dir, history_enabled, history_file, overwrite, retries, log=print) -> error`（None=成功）
  - `_run_batch(items, ydl_opts, out_dir, history_enabled, history_file, overwrite, retries, log=print) -> (ok, fail, failed_file)`

- [ ] **Step 1: 写验证脚本（打桩，验证编排逻辑等价）**

```python
# _verify_run.py（临时）
import importlib, os, shutil, tempfile
import hls_download as h

class FakeYDL:
    def __init__(self, opts): self.opts = opts
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def extract_info(self, url, download): return None

# 打桩 _download_one：成功/失败可控
calls = []
def fake_download_one(url, ydl_opts, out_dir, hist_en, hist_file, overwrite, want_name, log=print):
    calls.append(url)
    if "bad" in url:
        return {"status":"failed"}, RuntimeError("boom")
    return {"status":"success"}, None
h._download_one = fake_download_one

# _run_single：失败应额外重试 retries 次
calls.clear()
err = h._run_single("bad", None, {}, ".", False, h.DEFAULT_HISTORY_FILE, False, 2, log=print)
assert err is not None
assert calls == ["bad", "bad", "bad"], calls  # 首次 + 2 次重试

# _run_batch：1 成功 1 失败，retries=1
calls.clear()
ok, fail, failed_file = h._run_batch([("good", None), ("bad", None)], {}, ".", False,
                                      h.DEFAULT_HISTORY_FILE, False, 1, log=print)
assert ok == 1 and fail == 1, (ok, fail)
assert failed_file is not None and os.path.isfile(failed_file)
content = open(failed_file, encoding="utf-8").read().strip()
assert content == "bad", content
os.remove(failed_file)
print("PASS")
```

- [ ] **Step 2: 运行验证脚本，确认失败**

Run: `python _verify_run.py`
Expected: FAIL（`AttributeError: module 'hls_download' has no attribute '_run_single'`）

- [ ] **Step 3: 实现 `_run_single`/`_run_batch`**

在 `_download_one` 函数体之后、`def main()` 之前插入：

```python
def _run_single(url, name, ydl_opts, out_dir, history_enabled, history_file, overwrite, retries, log=print):
    """单条下载，失败后额外重试 retries 次。返回 error（None 表示成功）。"""
    def _dl(u, n):
        return _download_one(u, ydl_opts, out_dir, history_enabled,
                             history_file, overwrite, n, log=log)[1]
    err = _dl(url, name)
    attempt = 1
    while err is not None and attempt <= retries:
        attempt += 1
        log(f"第 {attempt - 1} 次重试: {url}")
        err = _dl(url, name)
    return err


def _run_batch(items, ydl_opts, out_dir, history_enabled, history_file, overwrite, retries, log=print):
    """批量下载：第一轮全跑 → 失败进队列重试 → 耗尽写失败清单。返回 (ok, fail, failed_file)。"""
    def _dl(u, n):
        return _download_one(u, ydl_opts, out_dir, history_enabled,
                             history_file, overwrite, n, log=log)[1]
    ok = fail = 0
    pending = []
    for i, (url, name) in enumerate(items, 1):
        log(f"[{i}/{len(items)}] 下载中: {url}")
        err = _dl(url, name)
        if err is None:
            ok += 1
        else:
            pending.append((url, name))
            log(f"    失败：{url}（{err}）")
    if pending and retries > 0:
        log(f"重试失败条目（最多 {retries} 轮）…")
        gained, pending = _retry_pending(_dl, pending, retries)
        ok += gained
    fail = len(pending)
    failed_file = None
    if pending:
        failed_file = DEFAULT_FAILED_FILE
        if not _write_failed_list(failed_file, pending):
            failed_file = None
    if fail:
        if failed_file:
            log(f"批量下载完成：成功 {ok} 条，失败 {fail} 条（详见 {failed_file}）。")
        else:
            log(f"批量下载完成：成功 {ok} 条，失败 {fail} 条（失败清单写入失败）。")
    else:
        log(f"批量下载完成：成功 {ok} 条，失败 0 条。")
    return ok, fail, failed_file
```

- [ ] **Step 4: 改 main() 调用（替换第 469-518 行下载编排）**

删除 main() 里的 `def _dl(...)` 与 `try:` 内的批量/单条循环，替换为：

```python
    try:
        if args.batch:
            items = _read_batch_file(args.batch)
            if not items:
                sys.exit("错误：批量文件为空或无可下载的 URL。")
            _run_batch(items, ydl_opts, out_dir, history_enabled,
                       history_file, args.overwrite, retries)
        else:
            err = _run_single(args.url, args.output, ydl_opts, out_dir,
                              history_enabled, history_file, args.overwrite, retries)
            if err is not None:
                raise err
    finally:
        if tmp_cookie and os.path.isfile(tmp_cookie):
            try:
                os.remove(tmp_cookie)
            except OSError:
                pass
```

（`finally` 块保留，`tmp_cookie` 清理逻辑不变。）

- [ ] **Step 5: 运行验证脚本，确认通过**

Run: `python _verify_run.py`
Expected: PASS

- [ ] **Step 6: CLI 回归（真实命令）**

Run: `python hls_download.py --help`
Expected: 参数齐全。再用一条真实下载回归（单条 Mux 流或小 mp4），确认输出与改造前一致。

- [ ] **Step 7: 提交**

```bash
git add hls_download.py
git commit -m "refactor: 抽出 _run_single/_run_batch 供 CLI 与 GUI 复用下载编排"
```
删 `_verify_run.py`。

---

### Task 4: `gui.py`（tkinter 界面）

**Files:**
- Create: `gui.py`

**Interfaces:**
- Consumes: `hls_download` 的 `_setup_ytdlp`、`_find_ffmpeg_dir`、`_load_config`、`_is_json_cookie_file`、`_convert_json_cookies`、`_read_batch_file`、`_run_single`、`_run_batch`、`DATA_DIR`、`CONFIG_FILE`、`DEFAULT_HISTORY_FILE`。
- Produces: `gui.py` 作为独立入口（`python gui.py` 或打包后双击），无导出接口（仅 `main()` 内部）。

- [ ] **Step 1: 写完整 gui.py**

```python
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

    def _log(self, msg):
        self.q.put(msg)

    def _poll_queue(self):
        try:
            while True:
                msg = self.q.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", str(msg) + "\n")
                self.log_text.configure(state="disabled")
                self.log_text.see("end")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _start(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("提示", "已有下载在进行中。")
            return
        raw = self.url_text.get("1.0", "end").strip()
        lines = [ln for ln in raw.splitlines() if ln.strip() and not ln.strip().startswith("#")]
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
        self.status_var.set("已请求停止（当前片段结束后生效）…")

    def _download(self, lines, out_dir, name, cookies, proxy, is_batch):
        def log(msg):
            self._log(msg)

        def fail(msg):
            self._log(msg)
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
                    items = [(ln.split(None, 1)[0], ln.split(None, 1)[1].strip() if len(ln.split(None, 1)) > 1 else None) for ln in lines]
                    total = len(items)
                    for i, (url, nm) in enumerate(items, 1):
                        if self.stop_evt.is_set():
                            log("已停止。")
                            break
                        self.status_var.set(f"下载中 {i}/{total}")
                        # 批量：逐条走 _run_single 以支持逐条停止
                        err = h._run_single(url, nm, ydl_opts, out_dir, history_enabled,
                                            history_file, False, retries, log=log)
                        if err is not None:
                            log(f"失败：{url}（{err}）")
                    self.status_var.set("已完成（批量）" if not self.stop_evt.is_set() else "已停止")
                else:
                    self.status_var.set("下载中…")
                    err = h._run_single(lines[0], name, ydl_opts, out_dir, history_enabled,
                                        history_file, False, retries, log=log)
                    if err is not None:
                        log(f"失败：{err}")
                        self.status_var.set("失败")
                    else:
                        self.status_var.set("成功")
            finally:
                if tmp_cookie and os.path.isfile(tmp_cookie):
                    try:
                        os.remove(tmp_cookie)
                    except OSError:
                        pass
        except Exception as e:
            fail(f"异常：{e}")

    def _handle_error(self, msg):
        messagebox.showerror("错误", msg)


def main():
    root = tk.Tk()
    app = App(root)
    # __error__ 消息在 poll 里弹出错误框
    def poll_with_error():
        app._poll_queue()
        # 额外处理错误框
        try:
            while True:
                item = app.q.get_nowait()
                if isinstance(item, tuple) and item[0] == "__error__":
                    messagebox.showerror("错误", item[1])
        except queue.Empty:
            pass
        root.after(100, poll_with_error)
    root.after(100, poll_with_error)
    root.mainloop()


if __name__ == "__main__":
    main()
```

> 注：`_handle_error` 与 `poll_with_error` 里用 `__error__` 元组触发 `messagebox`；若发现竞态，简化为错误仅写日志框 + 状态栏（不弹框），以先跑通为准。

- [ ] **Step 2: 语法检查**

Run: `python -m py_compile gui.py`
Expected: 无输出（编译通过）。

- [ ] **Step 3: 手动冒烟（GUI 需真实显示，需用户或 agent 在桌面环境）**

Run: `python gui.py`
Expected: 窗口弹出。填入公开直链（如 `https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8`），点「开始下载」，日志框实时回显、状态栏「成功」，`downloads/` 出现成品，`download_history.log` 追加一条。

> 若无桌面环境，此项标记为「待用户在桌面验证」，不阻塞后续打包任务。

- [ ] **Step 4: 提交**

```bash
git add gui.py
git commit -m "feat: 新增 tkinter GUI（核心下载 + 批量 + 代理，后台线程 + queue 回显）"
```

---

### Task 5: PyInstaller 打包（CLI + GUI 两个单文件 exe）

**Files:**
- Create: `build_cli.spec`
- Create: `build_gui.spec`
- Modify: `.gitignore`（忽略 `dist/`、`build/`、`*.spec`）

**Interfaces:**
- Consumes: `hls_download.py`、`gui.py`、`ytdlp_lib/`、`ffmpeg-*/bin/ffmpeg.exe`。
- Produces: `dist/hls_download.exe`（console）、`dist/hls_download_gui.exe`（windowed）。

- [ ] **Step 1: 写 build_cli.spec**

```python
# build_cli.spec
import os
from pathlib import Path

ROOT = Path.cwd()
FFMPEG_BIN = next(ROOT.glob("ffmpeg*/bin/ffmpeg.exe"), None)

a = Analysis(
    ["hls_download.py"],
    pathex=[str(ROOT)],
    binaries=[(str(FFMPEG_BIN), "ffmpeg/bin")] if FFMPEG_BIN else [],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
# 全量收集 yt-dlp 动态 import 的 extractor 子模块
a = collect_all("yt_dlp", analysis=a)

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
```

- [ ] **Step 2: 写 build_gui.spec**

同上，仅两处不同：`Analysis(["gui.py"], ...)`，`EXE(..., name="hls_download_gui", console=False, ...)`。

```python
# build_gui.spec
import os
from pathlib import Path

ROOT = Path.cwd()
FFMPEG_BIN = next(ROOT.glob("ffmpeg*/bin/ffmpeg.exe"), None)

a = Analysis(
    ["gui.py"],
    pathex=[str(ROOT)],
    binaries=[(str(FFMPEG_BIN), "ffmpeg/bin")] if FFMPEG_BIN else [],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
a = collect_all("yt_dlp", analysis=a)

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
```

- [ ] **Step 3: 安装 PyInstaller（构建期）**

Run: `pip install pyinstaller`
Expected: 安装成功（版本 ≥ 6）。

- [ ] **Step 4: 打包 CLI**

Run: `pyinstaller --clean --noconfirm build_cli.spec`
Expected: 生成 `dist/hls_download.exe`（体积约 200–250 MB）。

- [ ] **Step 5: 打包 GUI**

Run: `pyinstaller --clean --noconfirm build_gui.spec`
Expected: 生成 `dist/hls_download_gui.exe`。

- [ ] **Step 6: .gitignore 追加**

```gitignore
# PyInstaller 产物
dist/
build/
*.spec
```

- [ ] **Step 7: 提交**

```bash
git add .gitignore build_cli.spec build_gui.spec
git commit -m "build: 新增 PyInstaller 单文件打包（CLI + GUI，含 ffmpeg 与 ytdlp_lib）"
```

---

### Task 6: 文档同步

**Files:**
- Modify: `doc/功能设计.md`、`doc/迭代计划.md`、`doc/代码地图.md`、`doc/功能清单.md`、`doc/下载指南.md`、`README.md`

- [ ] **Step 1: 功能设计.md** — 「目标与定位」（第 7-14 行）改「轻量命令行工具 + 可选 GUI」，删「非目标：不做 GUI」，非目标改为「不做 DRM」；架构（第 20 行附近）补 `gui.py` 组件与「资源/数据目录区分」。
- [ ] **Step 2: 迭代计划.md** — V3.0「添加 GUI 模式」标 `[x] 已完成`；删第 74 行「GUI——保持命令行工具，轻量」自相矛盾行；新增 V3.0 段记录「tkinter GUI + 单文件打包」。
- [ ] **Step 3: 代码地图.md** — 新增 `gui.py` 条目；`hls_download.py` 函数清单补 `_run_single`/`_run_batch`；顶部常量区补 `FROZEN`/`RESOURCE_DIR`/`DATA_DIR`；行号按改造后实际更新。
- [ ] **Step 4: 功能清单.md** — 加「GUI 界面」「单文件打包（CLI/GUI exe）」✅。
- [ ] **Step 5: 下载指南.md / README.md** — 快速开始加「GUI 启动 `python gui.py`」「打包 `pyinstaller build_gui.spec`」；目录结构补 `gui.py`、`build_*.spec`、`doc/GUI设计.md`、`doc/GUI实现计划.md`。

- [ ] **Step 6: 提交**

```bash
git add doc README.md
git commit -m "docs: 同步 GUI 与打包说明，更新迭代计划与功能设计定位"
```

---

### Task 7: 打包验收

- [ ] **Step 1: CLI exe 冒烟**

Run: `dist/hls_download.exe --help`
Expected: 参数齐全。用一条真实直链下载，确认落盘成功（`download_history.log` 写在 exe 旁）。

- [ ] **Step 2: GUI exe 冒烟（需桌面）**

Run: `dist/hls_download_gui.exe`
Expected: 窗口弹出，可下载一条公开流。

- [ ] **Step 3: 无系统 yt_dlp 环境验证（可选）**

临时改环境变量屏蔽系统 `yt_dlp`（或在无 Python 机器双击），确认 exe 自包含可用。

- [ ] **Step 4: 最终提交（如有改动）**

```bash
git status && git log --oneline -12
```

---

## 备注

- 本仓库无 pytest，全部验证用「临时打桩脚本 + 真实命令」，验证后删脚本，沿用历史约定。
- `gui.py` 的「停止」为尽力语义（yt-dlp 不支持中断当前片段），与 spec 第 5.3 节一致。
- 打包体积 200–250 MB 是「单文件自包含」的必然代价，spec 已确认接受。
