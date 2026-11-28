# lite 版（使用环境 ffmpeg）发布打包 实现计划

> **状态：历史归档（已被取代）。** v1.12.0 起改用 `HLS_BUNDLE_FFMPEG` 开关 + `build_portable.spec` 的 Portable / Portable Slim 方案，`build_cli_lite.spec` / `build_gui_lite.spec` 已删除。本文仅保留当时的方案与决策记录，现行做法见 [../BUILDING.md](../BUILDING.md)、[发布SOP.md](发布SOP.md)、[迭代计划.md](迭代计划.md) V1.12 小节。文中 `lite` 命名、`_lite` 后缀与 4 个 zip 的产物清单均已过时。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增不含 ffmpeg 的 lite 发布包（CLI+GUI 各一），运行时自动回退探测系统 PATH 里的 ffmpeg；CI 一次发布产出 4 个 zip。

**Architecture:** `_find_ffmpeg_dir()` 在现有三级（`FFMPEG_LOCATION` > 打包内置 > 上级目录）之后追加 `shutil.which("ffmpeg")` 回退；新增两份 lite PyInstaller spec（不打包 ffmpeg）；release.yml 增加两个构建与压缩步骤。完整版行为零变化。

**Tech Stack:** Python 3.11 / pytest / PyInstaller (onedir) / GitHub Actions (windows-latest)。

**Spec:** 获批方案A（本会话 2026-11-28 确认）：命名 lite、CLI+GUI 都出、探测范围 PATH+FFMPEG_LOCATION；配套调研结论（各文件:行号）已记录在会话压缩块 b1。

## Global Constraints

- 优先级固定：`FFMPEG_LOCATION` > 打包内置 `ffmpeg*/bin` > 系统 PATH；完整版（带 ffmpeg）行为零变化。
- lite 命名统一 `_lite` 后缀：COLLECT name `hls_download_lite` / `hls_download_gui_lite`，zip 同名；**EXE 名保持 `hls_download` / `hls_download_gui` 不变**（用法文档零改动）。
- 新报错文案（逐字）：`错误：找不到 ffmpeg。请安装 ffmpeg 并加入 PATH，或设置环境变量 FFMPEG_LOCATION 指向其 bin 目录；或改用完整版（内置 ffmpeg）。`
- 不新增第三方依赖；测试用 monkeypatch，不真实依赖 PATH 里的 ffmpeg。
- 文档语言中文；提交信息沿用仓库 `feat:` / `ci:` / `docs:` 前缀风格。

## Review Focus

- 本机 PATH 没有 ffmpeg 时跑 lite 包：应得到清晰报错（新文案），不能是 Python traceback —— 由 Task 1 `test_find_ffmpeg_dir_falls_back_to_path` 与文案替换钉住。
- `FFMPEG_LOCATION` 指向不存在的目录：回退到下一级探测，PATH 兜底仍生效 —— 由 Task 1 三个优先级测试钉住。
- 本机 PATH 有 ffmpeg 但版本过旧：探测只看存在性，不校验版本 —— 与完整版一致，接受（冒烟观察项）。
- CI 无 ffmpeg 的 runner 上打完整版：ffmpeg 下载步骤失败应使任务失败（保持现状），lite 步骤不得依赖 ffmpeg 产物（Task 3 核对）。

---

### Task 1: `_find_ffmpeg_dir()` PATH 回退 + 报错文案（TDD）

**Files:**
- Modify: `hls_download.py:72-83`（函数末尾加回退分支）
- Modify: `hls_download.py:600`、`gui.py:268`（报错文案）
- Test: `tests/test_hls_download.py`（文件末尾追加）

**Interfaces:**
- Produces: `_find_ffmpeg_dir() -> str | None` 行为扩展 —— 前三级都落空且 `shutil.which("ffmpeg")` 命中时返回其所在目录；`gui.py:266-268` 调用方式不变。

- [ ] **Step 1: 写失败测试**（追加到 tests/test_hls_download.py 末尾）

```python
# --- _find_ffmpeg_dir：PATH 回退（lite 版不带 ffmpeg 打包） ---

def test_find_ffmpeg_dir_falls_back_to_path(tmp_path, monkeypatch):
    monkeypatch.delenv("FFMPEG_LOCATION", raising=False)
    monkeypatch.setattr(h, "RESOURCE_DIR", str(tmp_path))
    monkeypatch.setattr(h, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(h, "ROOT", str(tmp_path))
    monkeypatch.setattr(h.shutil, "which", lambda name: str(tmp_path / "ffmpeg.exe"))
    assert h._find_ffmpeg_dir() == str(tmp_path)


def test_find_ffmpeg_dir_prefers_bundled_over_path(tmp_path, monkeypatch):
    monkeypatch.delenv("FFMPEG_LOCATION", raising=False)
    bundled = tmp_path / "ffmpeg-9.0" / "bin"
    bundled.mkdir(parents=True)
    monkeypatch.setattr(h, "RESOURCE_DIR", str(tmp_path))
    monkeypatch.setattr(h, "DATA_DIR", str(tmp_path / "elsewhere"))
    monkeypatch.setattr(h, "ROOT", str(tmp_path / "elsewhere"))
    monkeypatch.setattr(h.shutil, "which", lambda name: str(tmp_path / "ffmpeg.exe"))
    assert h._find_ffmpeg_dir() == str(bundled)


def test_find_ffmpeg_dir_env_location_still_wins(tmp_path, monkeypatch):
    env_dir = tmp_path / "envbin"
    env_dir.mkdir()
    monkeypatch.setenv("FFMPEG_LOCATION", str(env_dir))
    monkeypatch.setattr(h.shutil, "which", lambda name: str(tmp_path / "ffmpeg.exe"))
    assert h._find_ffmpeg_dir() == str(env_dir)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_hls_download.py -k find_ffmpeg_dir -v`
Expected: 前两个 FAIL（现在不查 PATH）、第三个 PASS（现有行为）。

- [ ] **Step 3: 实现** —— 在 `_find_ffmpeg_dir()` 现有 glob 循环之后、`return None` 之前加：

```python
    # lite 版（不带 ffmpeg 打包）：回退到系统 PATH 里的 ffmpeg
    which = shutil.which("ffmpeg")
    if which:
        return os.path.dirname(which)
    return None
```

- [ ] **Step 4: 更新两处报错文案** 为 Global Constraints 里的逐字新文案（`hls_download.py:600`、`gui.py:268`）。

- [ ] **Step 5: 全量测试**

Run: `python -m pytest -q`
Expected: 全绿。

- [ ] **Step 6: Commit**

```bash
git add hls_download.py gui.py tests/test_hls_download.py
git commit -m "feat: ffmpeg 定位增加系统 PATH 回退（lite 版依赖）"
```

### Task 2: 两份 lite spec + 现有 spec 缺 ffmpeg 警告

**Files:**
- Create: `build_cli_lite.spec`、`build_gui_lite.spec`
- Modify: `build_cli.spec:14-19`、`build_gui.spec:12-17`（glob 落空时打警告）

**Interfaces:**
- Consumes: Task 1 的 PATH 回退（lite 产物运行时靠它找 ffmpeg）。
- Produces: COLLECT name `hls_download_lite` / `hls_download_gui_lite`；lite spec 不引用任何 `ffmpeg*`；EXE 名、icon、version_info.txt 与完整版一致。

- [ ] **Step 1: 复制 build_cli.spec → build_cli_lite.spec**：删掉 binaries 里 `ffmpeg*/bin` 的两行 glob；COLLECT `name="hls_download"` 改 `name="hls_download_lite"`（EXE 名不动）。build_gui_lite.spec 同法（`hls_download_gui` → `hls_download_gui_lite`）。

- [ ] **Step 2: 现有两 spec 加警告** —— glob 结果为空时：

```python
    print("警告：未找到 ffmpeg*/bin/ffmpeg.exe，将打出不含 ffmpeg 的完整版包")
```

- [ ] **Step 3: 本地打包 lite 并冒烟**（命令按 README 打包节 93-113，把 spec 换成 *_lite.spec）
Check: `dist\hls_download_lite`（与 `dist\hls_download_gui_lite`）里**没有** ffmpeg 目录；`dist\hls_download_lite\hls_download.exe --help` 正常输出；本机 PATH 有 ffmpeg 时再跑一次真实下载 URL，验证 PATH 探测生效。

- [ ] **Step 4: Commit**

```bash
git add build_cli_lite.spec build_gui_lite.spec build_cli.spec build_gui.spec
git commit -m "feat: 新增 lite（使用环境 ffmpeg）打包 spec，完整版缺 ffmpeg 时告警"
```

### Task 3: CI 出 4 个 zip

**Files:**
- Modify: `.github/workflows/release.yml`

**Interfaces:**
- Consumes: Task 2 的两份 lite spec。
- Produces: artifact `hls-downloader-windows` 与 GitHub Release 各含 4 个 zip：`hls_download.zip`、`hls_download_gui.zip`、`hls_download_lite.zip`、`hls_download_gui_lite.zip`。

- [ ] **Step 1: 追加两个 PyInstaller 步骤**（紧跟现有两个 build，命令同款换 lite spec）
- [ ] **Step 2: 追加两个 Compress-Archive**：`dist\hls_download_lite\*` → `hls_download_lite.zip`，GUI 同理。
- [ ] **Step 3: artifact 与 release 的文件清单各补两个 zip**。
- [ ] **Step 4: 核对 YAML**：缩进与现有步骤一致；lite 步骤不依赖 ffmpeg 下载步骤的产物。
- [ ] **Step 5: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: 发布产物增加 lite 版两个 zip"
```

### Task 4: 文档同步

**Files:**
- Modify: `README.md`（打包节 93-113 加 lite 命令；目录结构 132-133 加两个 spec 行）
- Modify: `doc/发布SOP.md`（产物清单改 4 zip、构建步骤）
- Modify: `doc/代码地图.md:45,72-73,218`（`_find_ffmpeg_dir` 行为加 PATH 回退）
- Modify: `doc/功能设计.md:35`（优先级行加「系统 PATH」）
- Modify: `doc/下载指南.md:33,174`（lite 版说明、排障行对齐新文案）
- 不改：`doc/GUI设计.md`、`doc/GUI实现计划.md`（历史设计记录，现有行为描述仍准确）

- [ ] **Step 1: 按上列逐文件更新**（优先级、新文案逐字一致）
- [ ] **Step 2: Commit**

```bash
git add README.md doc/
git commit -m "docs: 同步 lite 版打包与 ffmpeg PATH 探测说明"
```

### Task 5: 终验

- [x] `python -m pytest -q` 全绿（34 passed, 1 skipped，2026-11-28）
- [x] 复跑 lite 冒烟（Task 2 后代码未再动，沿用其结果）
- [x] 汇报改动清单；提醒用户触发 CI（Actions Run workflow 或推 tag）核对 4 zip

---

## 追加段：打包体积与 CI 速度优化（方案A，2026-11-29 获批）

**背景:** dist 调查发现 GUI 完整版 948.5MB，根因是 PyInstaller 清 build/ 不清 dist 同名旧目录，新旧产物叠加出 `_internal\_internal\` 完整镜像嵌套（2050 files/469.8MB ×2）；完整 CLI dist 也是 11-10 旧产物。lite 两包（36.1/43.5MB）为新打干净产物。spec/CI 属配置类改动，pytest 不覆盖，验证方式为重建实测。

### Task 6: 4 个 spec 开头加 dist 防复发清理

**Files:**
- Modify: `build_cli.spec`、`build_gui.spec`、`build_cli_lite.spec`、`build_gui_lite.spec`（清理插在 `ROOT = Path.cwd()` 之后、Analysis 之前——**不能放脚本末尾**，末尾删会把刚打好的包删掉；rmtree 目标 `ROOT/"dist"/<本 spec COLLECT 名>`，`ignore_errors=True`）

- [x] **Step 1: 四个 spec 各加**（ROOT 定义后）：

```python
# 防复发：PyInstaller 不清 dist 下同名旧目录，旧产物会与新构建叠加出嵌套镜像
shutil.rmtree(ROOT / "dist" / <COLLECT名>, ignore_errors=True)
```

- [x] **Step 2: Commit** `git commit -m "fix: 打包前清理 dist 同名旧产物，防止新旧构建叠加嵌套"`（2d34ddb）

### Task 7: 重建 4 包并验证无嵌套

- [x] **Step 1: 重建 4 包**（教训：PyInstaller CLI 一次只接受一个 specfile，多参数静默只处理第一个——必须逐条调用；本机无 ffmpeg 目录，临时复制 `D:\dev\ffmpeg` 的 ffmpeg/ffprobe 到上级 `ffmpeg-rebuild\bin\` 供完整版 glob 命中）
- [x] **Step 2: 验证**：① 4 包均无 `_internal\_internal` 嵌套 ✓；② hls_download_gui 948.5→481.3 MB（-467MB）、4101→2066 files ✓；③ 重打 CLI lite 二次验证：1136 files/36.1 MB/无嵌套，与首打一致不翻倍 ✓；④ lite 包无 ffmpeg*.exe、完整版含 ffmpeg.exe+ffprobe.exe ✓；⑤ pytest 34 passed, 1 skipped ✓
- [x] **Step 3: 台账 log 验证数据**

### Task 8: CI 拆并行 job + release 汇总

**Files:**
- Modify: `.github/workflows/release.yml`（单 job 拆为 build-full / build-lite 两个并行 job + release 汇总 job）

- [x] **Step 1: build-full job**：原 checkout/setup/pytest/ffmpeg 下载 + 两个完整版 spec + 2 个 Compress-Archive + upload-artifact（name=hls-downloader-full，2 zip）
- [x] **Step 2: build-lite job**：checkout/setup/pytest + 两个 lite spec（免 ffmpeg 下载）+ 2 个 Compress-Archive + upload-artifact（name=hls-downloader-lite，2 zip）
- [x] **Step 3: release job**：needs 两 build job，download-artifact 合并 4 zip，softprops/action-gh-release@v3 附 4 zip（仅 tag 触发；job 级 if，非 step 级）
- [x] **Step 4: PyYAML 校验**（jobs: build-full 9 步 / build-lite 8 步 / release 3 步 needs=[build-full,build-lite] if=tag）+ 核对 lite job 不依赖 ffmpeg 步骤
- [x] **Step 5: Commit** aaa61a6 `ci: 发布拆 full/lite 并行构建，release 汇总 4 zip`

### Task 9: 文档同步 + 增量审查 + 收尾

- [x] **Step 1: doc/发布SOP.md** §4 改写为并行 job 描述（build-full/build-lite/release），§5 补 lite 冒烟验证行（d32dd98）；README 无需改（未涉及 job 结构）
- [x] **Step 2: 增量审查**（reviewer2：可合并无 Critical；Important#1 dist 清空警示已补 71a4907；Minor 3 条记台账：build job permissions 收敛 / timeout+concurrency / release job 可用 ubuntu-latest）
- [ ] **Step 3: 台账 close（需用户明确说「结束掉」）**
