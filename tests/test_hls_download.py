# -*- coding: utf-8 -*-
"""hls_download 核心行为回归测试（TDD：先失败，再实现）。"""
import argparse
import json
import os
import sys
import types

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
    assert os.path.dirname(captured["outtmpl"]).startswith(str(out_dir))
