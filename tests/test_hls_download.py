# -*- coding: utf-8 -*-
"""hls_download 核心行为回归测试（TDD：先失败，再实现）。"""
import argparse
import builtins
import json
import os
import queue
import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import hls_download as h


def _cookie_file(tmp_path, cookies):
    p = tmp_path / "cookies.json"
    p.write_text(json.dumps({"cookies": cookies}), encoding="utf-8")
    return str(p)


def _read_tmp_cookie(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    finally:
        os.remove(path)


def _load_gui():
    pytest.importorskip("tkinter")
    import gui
    return gui


# --- _as_bool：配置里的字符串布尔值 ---

def test_as_bool_treats_string_false_as_false():
    assert h._as_bool("false") is False


def test_as_bool_treats_string_true_as_true():
    assert h._as_bool("true") is True


def test_as_bool_uses_default_when_value_is_none():
    assert h._as_bool(None, default=False) is False
    assert h._as_bool(None) is True


# --- _convert_json_cookies：坏 expirationDate / 换行值 ---

def test_convert_json_cookies_non_numeric_expiry_does_not_crash(tmp_path):
    src = _cookie_file(tmp_path, [{
        "domain": "example.com", "name": "a", "value": "b",
        "expirationDate": "never",
    }])
    tmp = h._convert_json_cookies(src)
    assert tmp is not None
    fields = _read_tmp_cookie(tmp).splitlines()[-1].split("\t")
    assert fields[4] == "0"


def test_convert_json_cookies_sanitizes_newline_in_value(tmp_path):
    src = _cookie_file(tmp_path, [{
        "domain": "example.com", "name": "a", "value": "x\ny\tz",
    }])
    tmp = h._convert_json_cookies(src)
    assert tmp is not None
    content = _read_tmp_cookie(tmp)
    lines = [ln for ln in content.splitlines() if ln and not ln.startswith("#")]
    assert len(lines) == 1
    assert "\n" not in lines[0] and "\t" not in lines[0].split("\t", 6)[-1]


def test_convert_json_cookies_removes_temp_file_on_write_failure(tmp_path, monkeypatch):
    src = _cookie_file(tmp_path, [{
        "domain": "example.com", "name": "a", "value": "b",
    }])
    created = []
    real_mkstemp = h.tempfile.mkstemp

    def track_mkstemp(*args, **kwargs):
        fd, path = real_mkstemp(*args, **kwargs)
        created.append(path)
        return fd, path

    def fail_fdopen(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(h.tempfile, "mkstemp", track_mkstemp)
    monkeypatch.setattr(h.os, "fdopen", fail_fdopen)
    with pytest.raises(OSError, match="disk full"):
        h._convert_json_cookies(src)
    assert len(created) == 1
    assert not os.path.exists(created[0])


def test_setup_ytdlp_missing_raises_runtime_error(tmp_path, monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "yt_dlp":
            raise ImportError
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(h, "FROZEN", True)
    monkeypatch.setattr(h, "RESOURCE_DIR", str(tmp_path))
    monkeypatch.setattr(h, "DATA_DIR", str(tmp_path))
    with pytest.raises(RuntimeError, match="找不到 yt_dlp"):
        h._setup_ytdlp()


# --- _format_history_line：签名 URL 脱敏 / 错误截断 ---

def test_format_history_line_redacts_signed_query():
    line = h._format_history_line({
        "status": "failed", "title": "t", "id": "i",
        "url": "https://example.com/hls/secret?token=ABC123&expires=9",
        "error": "HTTP 403 https://example.com/hls/secret?token=ABC123",
    })
    assert "token=ABC123" not in line
    assert "expires=9" not in line
    assert "<redacted>" in line


def test_format_history_line_truncates_long_error():
    line = h._format_history_line({
        "status": "failed", "error": "E" * 500,
    })
    assert len(line) <= 260


def test_format_history_line_marks_cancelled():
    line = h._format_history_line({"status": "cancelled", "error": "下载已停止"})
    assert "[取消]" in line
    assert "[失败]" not in line


def test_write_failed_list_redacts_signed_query(tmp_path):
    path = tmp_path / "failed_downloads.txt"
    assert h._write_failed_list(str(path), [
        ("https://example.com/video?token=SECRET", "clip"),
    ])
    content = path.read_text(encoding="utf-8")
    assert "SECRET" not in content
    assert "?<redacted> clip" in content


# --- _retry_pending：停止时丢弃未尝试条目 ---

def test_retry_pending_drops_unattempted_on_stop():
    stop = types.SimpleNamespace(is_set=lambda: True)
    calls = []

    def dl(url, name):
        calls.append(url)
        return "err"

    ok, pending = h._retry_pending(dl, [("u1", None), ("u2", None)], 3, stop)
    assert calls == []
    assert pending == []


def test_run_batch_pre_stop_skips_download(monkeypatch):
    stop = threading.Event()
    stop.set()
    monkeypatch.setattr(
        h, "_download_one",
        lambda *args, **kwargs: pytest.fail("download must not start"),
    )
    assert h._run_batch(
        [("http://example.com", None)], {}, "out", False, "history",
        False, 3, stop_evt=stop,
    ) == (0, 0, None)


def test_run_batch_keeps_successes_when_cancelled_during_retry(monkeypatch):
    stop = threading.Event()
    attempts = []

    def fake_download(url, *args, **kwargs):
        attempts.append(url)
        if len(attempts) <= 2:
            return {}, "err"
        if len(attempts) == 3:
            return {}, None
        stop.set()
        raise h.DownloadCancelled("下载已停止")

    monkeypatch.setattr(h, "_download_one", fake_download)
    assert h._run_batch(
        [("u1", None), ("u2", None)], {}, "out", False, "history",
        False, 1, stop_evt=stop,
    ) == (1, 0, None)


# --- _move_to_final：覆盖与改名 ---

def test_move_to_final_overwrites_when_requested(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    src = staging / "a.mp4"
    src.write_bytes(b"new")
    (tmp_path / "a.mp4").write_bytes(b"old")
    result = h._move_to_final(str(src), str(tmp_path), True)
    assert os.path.basename(result) == "a.mp4"
    assert open(result, "rb").read() == b"new"


def test_move_to_final_adds_suffix_on_collision(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    src = staging / "a.mp4"
    src.write_bytes(b"new")
    (tmp_path / "a.mp4").write_bytes(b"old")
    result = h._move_to_final(str(src), str(tmp_path), False)
    assert os.path.basename(result) == "a (1).mp4"


def test_move_no_replace_is_exclusive(tmp_path):
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    target = tmp_path / "a.mp4"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    assert h._move_no_replace(str(first), str(target)) is True
    assert h._move_no_replace(str(second), str(target)) is False
    assert target.read_bytes() == b"first"
    assert second.exists()


def test_move_no_replace_publishes_complete_file_atomically(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    target = tmp_path / "a.mp4"
    source.write_bytes(b"complete")
    observed = []
    publish_name = "rename" if os.name == "nt" else "link"
    real_publish = getattr(os, publish_name)

    def publish_and_observe(src, dst):
        real_publish(src, dst)
        with open(dst, "rb") as f:
            observed.append(f.read())

    monkeypatch.setattr(h.os, publish_name, publish_and_observe)
    assert h._move_no_replace(str(source), str(target)) is True
    assert observed == [b"complete"]
    assert target.read_bytes() == b"complete"
    assert not source.exists()


@pytest.mark.skipif(os.name == "nt", reason="Windows 使用 rename 直接移动")
def test_move_no_replace_keeps_complete_target_when_unlink_fails(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    target = tmp_path / "a.mp4"
    source.write_bytes(b"complete")

    def fail_unlink(path):
        raise PermissionError("source is busy")

    monkeypatch.setattr(h.os, "unlink", fail_unlink)
    assert h._move_no_replace(str(source), str(target)) is True
    assert target.read_bytes() == b"complete"
    assert source.read_bytes() == b"complete"


def test_move_to_final_concurrent_collision_keeps_both(tmp_path):
    sources = []
    for value in (b"first", b"second"):
        staging = tmp_path / f"source-{len(sources)}"
        staging.mkdir()
        path = staging / "a.mp4"
        path.write_bytes(value)
        sources.append(path)
    barrier = threading.Barrier(2)

    def move(source):
        barrier.wait()
        return h._move_to_final(str(source), str(tmp_path), False)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(move, sources))
    assert {os.path.basename(path) for path in results} == {"a.mp4", "a (1).mp4"}
    assert {Path(path).read_bytes() for path in results} == {b"first", b"second"}


# --- main：批量失败必须以非零码退出 ---

def test_main_batch_failure_exits_nonzero(tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    args = argparse.Namespace(
        url=None, out_dir=str(out_dir), cookies=None, browser=None,
        user_agent=None, referer=None, proxy=None, output=None,
        overwrite=False, batch="fake.txt", retries=0, no_history=True,
        history_file=None,
    )
    monkeypatch.setattr(h, "_parse_args", lambda: args)
    monkeypatch.setattr(h, "_load_config", lambda: {})
    monkeypatch.setattr(h, "_setup_ytdlp", lambda: None)
    monkeypatch.setattr(h, "_find_ffmpeg_dir", lambda: "/fake/ffmpeg/bin")
    monkeypatch.setattr(h, "_read_batch_file", lambda p: [("http://x", None)])
    monkeypatch.setattr(h, "_run_batch", lambda *a, **k: (0, 1, None))
    with pytest.raises(SystemExit) as exc:
        h.main()
    assert exc.value.code == 1


def test_main_removes_temp_cookie_when_initialization_fails(tmp_path, monkeypatch):
    temp_cookie = tmp_path / "cookies.tmp"
    temp_cookie.write_text("secret", encoding="utf-8")
    args = argparse.Namespace(
        url="http://example.com", out_dir=None, cookies="cookies.json", browser=None,
        user_agent=None, referer=None, proxy=None, output=None,
        overwrite=False, batch=None, retries=0, no_history=True,
        history_file=None,
    )

    def bad_path(*args, **kwargs):
        raise RuntimeError("bad path")

    monkeypatch.setattr(h, "_parse_args", lambda: args)
    monkeypatch.setattr(h, "_load_config", lambda: {})
    monkeypatch.setattr(h, "_setup_ytdlp", lambda: None)
    monkeypatch.setattr(h, "_find_ffmpeg_dir", lambda: "/fake/ffmpeg/bin")
    monkeypatch.setattr(h, "_is_json_cookie_file", lambda path: True)
    monkeypatch.setattr(h, "_convert_json_cookies", lambda path: str(temp_cookie))
    monkeypatch.setattr(h, "_resolve_path", bad_path)
    with pytest.raises(RuntimeError, match="bad path"):
        h.main()
    assert not temp_cookie.exists()


# --- _download_one：输出名不得逃出 staging ---

def test_download_one_basename_keeps_file_in_staging(tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    captured = {}

    class FakeYDL:
        def __init__(self, opts):
            captured["outtmpl"] = opts["outtmpl"]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download):
            path = captured["outtmpl"]
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"x")
            return {"requested_downloads": [{"filepath": path}]}

    fake = types.ModuleType("yt_dlp")
    fake.YoutubeDL = FakeYDL
    monkeypatch.setitem(sys.modules, "yt_dlp", fake)

    absolute_escape = str(tmp_path / "escape.mp4")
    entry, err = h._download_one(
        "http://example.com", {}, str(out_dir), False,
        str(tmp_path / "history.log"), False, absolute_escape,
    )
    assert err is None
    assert os.path.basename(captured["outtmpl"]) == "escape.mp4"
    staging_dir = os.path.dirname(captured["outtmpl"])
    assert os.path.basename(staging_dir).startswith(".hls_staging_")
    assert os.path.dirname(staging_dir) == str(out_dir)


def test_download_one_cancels_from_progress_hook(tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    stop = threading.Event()

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download):
            stop.set()
            self.opts["progress_hooks"][0]({"status": "downloading"})
            raise AssertionError("download should have been cancelled")

    fake = types.ModuleType("yt_dlp")
    fake.YoutubeDL = FakeYDL
    monkeypatch.setitem(sys.modules, "yt_dlp", fake)
    with pytest.raises(h.DownloadCancelled):
        h._download_one(
            "http://example.com", {}, str(out_dir), False,
            str(tmp_path / "history.log"), False, None, stop_evt=stop,
        )
    assert list(out_dir.iterdir()) == []


def test_download_one_stops_after_extract_before_promotion(tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    stop = threading.Event()

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download):
            path = self.opts["outtmpl"]
            with open(path, "wb") as f:
                f.write(b"complete")
            stop.set()
            return {"requested_downloads": [{"filepath": path}]}

    fake = types.ModuleType("yt_dlp")
    fake.YoutubeDL = FakeYDL
    monkeypatch.setitem(sys.modules, "yt_dlp", fake)
    with pytest.raises(h.DownloadCancelled):
        h._download_one(
            "http://example.com", {}, str(out_dir), False,
            str(tmp_path / "history.log"), False, "clip.mp4", stop_evt=stop,
        )
    assert list(out_dir.iterdir()) == []


@pytest.mark.parametrize("report_downloads", [True, False])
def test_download_one_stops_between_file_promotions(tmp_path, monkeypatch, report_downloads):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    stop = threading.Event()
    downloaded = []

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download):
            staging = os.path.dirname(self.opts["outtmpl"])
            for name in ("first.mp4", "second.mp4"):
                path = os.path.join(staging, name)
                with open(path, "wb") as f:
                    f.write(name.encode("ascii"))
                downloaded.append({"filepath": path})
            return {"requested_downloads": downloaded} if report_downloads else {}

    fake = types.ModuleType("yt_dlp")
    fake.YoutubeDL = FakeYDL
    monkeypatch.setitem(sys.modules, "yt_dlp", fake)
    real_move = h._move_to_final
    promoted = []

    def move_then_stop(src, destination, overwrite):
        result = real_move(src, destination, overwrite)
        promoted.append(result)
        stop.set()
        return result

    monkeypatch.setattr(h, "_move_to_final", move_then_stop)
    with pytest.raises(h.DownloadCancelled):
        h._download_one(
            "http://example.com", {}, str(out_dir), False,
            str(tmp_path / "history.log"), False, "clip.mp4", stop_evt=stop,
        )
    assert [os.path.basename(path) for path in promoted] == ["first.mp4"]
    assert [path.name for path in out_dir.iterdir()] == ["first.mp4"]


def test_run_single_stops_before_first_attempt(monkeypatch):
    stop = threading.Event()
    stop.set()
    monkeypatch.setattr(
        h, "_download_one",
        lambda *args, **kwargs: pytest.fail("download must not start"),
    )
    with pytest.raises(h.DownloadCancelled):
        h._run_single(
            "http://example.com", None, {}, "out", False, "history",
            False, 3, stop_evt=stop,
        )


# --- GUI：配置目录、取消状态和关闭超时 ---

def test_gui_uses_configured_out_dir(tmp_path, monkeypatch):
    gui = _load_gui()
    monkeypatch.setattr(gui.h, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(gui.h, "_load_config", lambda: {"out_dir": "configured"})
    assert gui._configured_out_dir() == str(tmp_path / "configured")


def test_gui_reports_cancelled_download(tmp_path, monkeypatch):
    gui = _load_gui()
    app = gui.App.__new__(gui.App)
    app.q = queue.Queue()
    app.stop_evt = threading.Event()
    app._tmp_cookie = None
    monkeypatch.setattr(gui, "_build_logger", lambda q: None)
    monkeypatch.setattr(gui.h, "_setup_ytdlp", lambda: None)
    monkeypatch.setattr(gui.h, "_find_ffmpeg_dir", lambda: "/fake/ffmpeg/bin")
    monkeypatch.setattr(gui.h, "_load_config", lambda: {})

    def cancel(*args, **kwargs):
        raise gui.h.DownloadCancelled("stopped")

    monkeypatch.setattr(gui.h, "_run_single", cancel)
    app._download(["http://example.com"], str(tmp_path), None, None, None, False)
    items = []
    while not app.q.empty():
        items.append(app.q.get_nowait())
    statuses = [payload for kind, payload in items if kind == "__status__"]
    assert statuses[-1] == "已停止"


def test_gui_removes_temp_cookie_when_initialization_fails(tmp_path, monkeypatch):
    gui = _load_gui()
    app = gui.App.__new__(gui.App)
    app.q = queue.Queue()
    app.stop_evt = threading.Event()
    app._tmp_cookie = None
    temp_cookie = tmp_path / "cookies.tmp"
    temp_cookie.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(gui, "_build_logger", lambda q: None)
    monkeypatch.setattr(gui.h, "_setup_ytdlp", lambda: None)
    monkeypatch.setattr(gui.h, "_find_ffmpeg_dir", lambda: "/fake/ffmpeg/bin")
    monkeypatch.setattr(gui.h, "_is_json_cookie_file", lambda path: True)
    monkeypatch.setattr(gui.h, "_convert_json_cookies", lambda path: str(temp_cookie))
    monkeypatch.setattr(gui.h, "_load_config", lambda: {})

    def bad_path(*args, **kwargs):
        raise RuntimeError("bad path")

    monkeypatch.setattr(gui.h, "_resolve_path", bad_path)
    app._download(["http://example.com"], str(tmp_path), None, "cookies.json", None, False)
    assert not temp_cookie.exists()


def test_gui_close_forces_exit_after_timeout(monkeypatch):
    gui = _load_gui()
    app = gui.App.__new__(gui.App)
    app.q = queue.Queue()
    app._closing = True
    app._close_deadline = 0
    app._tmp_cookie = None
    app.worker = types.SimpleNamespace(is_alive=lambda: True)

    class FakeRoot:
        destroyed = False

        def destroy(self):
            self.destroyed = True

        def after(self, *args):
            raise AssertionError("polling should stop after forced close")

    app.root = FakeRoot()
    app._poll_queue()
    assert app.root.destroyed is True
