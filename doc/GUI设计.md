# GUI 设计文档

> 日期：2026-11-08
> 状态：待评审
> 关联：`doc/功能设计.md`（总体架构）、`doc/迭代计划.md`（V3.0 添加 GUI 模式）

## 1. 目标

在**不破坏现有命令行能力**的前提下，为 hls-downloader 增加一个 tkinter 图形界面，让不懂命令行的用户也能「粘贴链接 / 选 cookies / 点下载」，并支持把 CLI 与 GUI 分别打包成**单文件自包含 exe**（含 ffmpeg 与 vendored yt-dlp）。

**这次明确推翻** `doc/功能设计.md:14`「非目标：不做 GUI」与 `doc/迭代计划.md:74`「GUI——保持命令行工具，轻量」的旧定位。新定位：**CLI 与 GUI 并存的工具**，GUI 面向普通用户，CLI 面向脚本/进阶用户。

## 2. 非目标（本次不做）

- 不做 DRM（Widevine/PlayReady）解密。
- 不做 curl_cffi / TLS 指纹伪装（已评估对 Cloudflare Turnstile 无效）。
- 不做 GUI 自动化测试（tkinter 不适合 headless 单测）。
- 不改动现有 CLI 参数语义、默认值、历史记录格式。
- 不把 ffprobe / ffplay / ffmpeg 文档打进 exe（只打 `ffmpeg.exe`）。

## 3. 用户已确认的决策

| 决策项 | 结论 |
|---|---|
| 技术栈 | tkinter（标准库，零额外运行时依赖） |
| 功能范围 | 核心下载 + 批量 + 代理（UA/Referer/cookies/browser/retries/overwrite 等高级参数保留在 CLI） |
| 复用方式 | 方案 A：`gui.py` 直接 `import hls_download` 复用纯函数 + `log` 回调改造 |
| 分发方式 | PyInstaller 打包成**单文件自包含 exe**（含 ffmpeg + ytdlp_lib），提供 **CLI exe** 与 **GUI exe** 两种 |

## 4. 架构

### 4.1 组件划分

```
hls_download.py      现有，改造约 +60 行：
                     - 顶部加 frozen 资源/数据目录区分
                     - _find_ffmpeg_dir / _setup_ytdlp 改走资源目录
                     - _download_one 加 log 回调 + logger 透传
                     - 抽 _run_single / _run_batch（下载编排下放到可复用函数）
                     - main() 变薄壳，调用 _run_single / _run_batch
gui.py               新增，tkinter 单文件（约 250 行）：
                     主窗口 + 下载线程 + queue 日志回显 + 停止
build_cli.spec       新增，PyInstaller 打包 CLI exe
build_gui.spec       新增，PyInstaller 打包 GUI exe
doc/ 7 份文档        同步（含本文档、迭代计划 V3.0 标记完成）
```

### 4.2 关键改造：frozen 资源/数据目录区分

打包成 exe 后 `sys.frozen=True`、`__file__` 指向 PyInstaller 临时解压目录 `sys._MEIPASS`，现有 `HERE = os.path.dirname(os.path.abspath(__file__))` 会指错。需要区分「资源目录」与「数据目录」：

| 用途 | 非 frozen（源码运行） | frozen（exe 运行） |
|---|---|---|
| 资源目录（ytdlp_lib、ffmpeg） | `HERE` / `ROOT` | `sys._MEIPASS` |
| 数据目录（config.json、download_history.log、failed_downloads.txt、downloads/） | `HERE` | `os.path.dirname(sys.executable)`（exe 旁，用户可写） |

实现：模块级新增 `FROZEN = getattr(sys, "frozen", False)`、`RESOURCE_DIR = getattr(sys, "_MEIPASS", HERE)`、`DATA_DIR = os.path.dirname(sys.executable) if FROZEN else HERE`。`CONFIG_FILE` / `DEFAULT_HISTORY_FILE` / `DEFAULT_FAILED_FILE` 改用 `DATA_DIR`；`_find_ffmpeg_dir` / `_setup_ytdlp` 的搜索路径改用 `(RESOURCE_DIR, DATA_DIR)`，兼容两种运行方式。

### 4.3 关键改造：`log` 回调与 logger 透传

- `_download_one(..., log=print)`：函数内 `print(...)` 改为 `log(...)`，默认 `print` → CLI 零变化。
- `ydl_opts` 增加可选 `logger`：GUI 传入自定义 `logging.Logger`（`handler` 把消息推入 `queue.Queue`），实现 yt-dlp 分片进度/日志的实时回显；CLI 不传则维持 yt-dlp 默认 logger。

### 4.4 关键改造：下载编排下放

将 `main()` 里的下载编排抽为两个可复用函数（消除 CLI/GUI 双重循环）：

- `_run_single(url, name, ydl_opts, out_dir, history_enabled, history_file, overwrite, retries, log) -> error`：单条下载 + 失败额外重试 `retries` 次（逻辑同现 main() 单条分支）。
- `_run_batch(items, ydl_opts, out_dir, history_enabled, history_file, overwrite, retries, log) -> (ok, fail, failed_file)`：第一轮全跑 → 失败进 `_retry_pending` → 耗尽写 `failed_downloads.txt`（逻辑同现 main() 批量分支）。

`main()` 保留参数解析 / config 合并 / 互斥校验 / `ydl_opts` 组装，最后调 `_run_single` 或 `_run_batch`；`sys.exit` 类错误只在 main() 层处理。`gui.py` 调同一组函数，传 `log=queue_logger`。

## 5. GUI 界面与数据流

### 5.1 界面（tkinter 单窗口）

- **输入区**：多行 URL 文本框（单条填 1 行，批量填多行，每行 `URL [文件名]`）、输出目录（`filedialog.askdirectory` 选择 + 文本框）、文件名（可选，单条时生效，等价 `-o`）、cookies 文件（可选，`filedialog.askopenfilename`）、代理框（可选，等价 `--proxy`）。
- **操作区**：「开始下载」「停止」按钮。
- **回显区**：只读日志文本框（滚动），实时显示下载进度与结果。
- **状态栏**：显示「待命 / 下载中 i/N / 成功 / 失败 / 已停止」。

### 5.2 数据流

```
用户填 URL/目录/文件名/cookies/代理 → 点「开始」
  → 主线程读控件值 → 后台 Thread：
      _setup_ytdlp() + _find_ffmpeg_dir()（找不到则经 queue 通知主线程弹 messagebox）
      → 组 ydl_opts（proxy/cookies/UA/logger）
      → 单条走 _run_single、批量走 _run_batch（want_name = 文件名或批量行内文件名）
      → 日志经 queue.Queue → 主线程 root.after(100, poll) 轮询刷新文本框
  → 结束回写状态栏「成功/失败」，批量失败提示「详见 failed_downloads.txt」
```

### 5.3 线程模型（tkinter 非线程安全）

- 下载在后台 `threading.Thread` 执行，tkinter 主线程只负责渲染与轮询 queue。
- 所有对控件的写操作都通过 `root.after` 回到主线程。
- 「停止」设置一个 `threading.Event`，在日志轮询处检查；yt-dlp 片段下载不支持优雅中断，停止语义为「停止后续重试/后续条目 + 清理当前 staging」（下载中的当前片段会在其内部循环结束后退出）。

## 6. 错误处理

| 场景 | 处理 |
|---|---|
| ffmpeg 找不到 | 经 queue 通知主线程 `messagebox.showerror`，不退出 GUI |
| cookies 是 JSON | 复用 `_is_json_cookie_file` + `_convert_json_cookies`，下载完 `finally` 清理临时文件 |
| 下载异常 | `_download_one` 已捕获并写失败历史；GUI 显示 error 到日志框 + 状态栏，不崩溃 |
| 批量失败 | 复用 `_retry_pending` + `_write_failed_list`，GUI 提示「失败 N 条，详见 failed_downloads.txt」 |
| config.json 损坏 | 复用 `_load_config`（返回空 + 警告），GUI 继续运行 |

## 7. 打包（PyInstaller）

- 构建环境需安装 PyInstaller（`pip install pyinstaller`，构建期依赖，不进运行时）。
- 两个 spec，均 `--onefile`：
  - `build_cli.spec`：入口 `hls_download.py`，`console=True`（保留命令行交互）。
  - `build_gui.spec`：入口 `gui.py`，`console=False`（`--windowed`，无黑框）。
- 资源收集：
  - `ytdlp_lib/` → 打进 exe（`--collect-all yt_dlp` 收集动态 import 的 extractor 子模块）。
  - `ffmpeg-*/bin/ffmpeg.exe` → 打进 exe（映射为 `ffmpeg/bin/ffmpeg.exe`，供 `_find_ffmpeg_dir` 在 `sys._MEIPASS` 下找到）。**只打 ffmpeg.exe，不打 ffprobe/ffplay/文档**。
  - `hls_download.py` 的 datas：无（config.example.json 仅作参考，不打进 exe）。
- 体积预估：ffmpeg.exe 217.9 MB + ytdlp_lib 13.6 MB + Python 运行时 ≈ **200–250 MB** 单文件。
- 已知代价：单文件 exe 每次启动解压到临时目录，启动比源码运行慢数秒；这是「单文件自包含」的必然权衡，用户已确认接受。
- 打包产物输出到 `dist/`（`hls_download.exe`、`hls_download_gui.exe`），`.gitignore` 忽略 `dist/`、`build/`、`*.spec`。

## 8. 测试与验收

1. **CLI 回归**（改造后）：`python hls_download.py --help` 参数齐全；单条下载公开 Mux 流成功，`log` 回调改造零影响；批量 + 重试 + 失败清单行为不变。
2. **GUI 手动冒烟**：启动窗口 → 用公开 Mux 流下载一次 → 验证落盘 + 历史记录 + 日志回显 + 状态栏「成功」；批量 2 条（1 成功 1 失败）验证失败提示。
3. **frozen 路径回归**：源码模式下 `HERE` 逻辑与改造前一致（config/history/downloads 仍在脚本同目录）。
4. **打包验收**：分别产出 `hls_download.exe` 与 `hls_download_gui.exe`，在无 Python 环境的机器上（或临时改名屏蔽系统 yt_dlp）双击启动，验证 CLI 能下载、GUI 能打开并下载。

## 9. 风险与回滚

| 风险 | 缓解 | 回滚 |
|---|---|---|
| PyInstaller 未收集 yt-dlp 动态 extractor | `--collect-all yt_dlp` 全量收集 | 回退 commit |
| exe 体积 200MB+ | 只打 ffmpeg.exe，剔除 ffprobe/ffplay/文档 | 用户已确认接受 |
| frozen 下 HERE 指错导致找不到 config/ffmpeg | 第 4.2 节资源/数据目录区分 | 回退 commit |
| `log` 回调改造影响 CLI 输出 | 默认 `print`，回归测试覆盖 | 回退 commit |
| tkinter 跨线程改控件崩溃 | 严格经 `queue` + `root.after` 回主线程 | 回退 commit |

## 10. 文档同步清单

- `doc/功能设计.md`：更新「目标与定位」与「非目标」（去掉「不做 GUI」），架构加 GUI 组件。
- `doc/迭代计划.md`：V3.0「添加 GUI 模式」标记完成；删末段「暂不做 GUI」自相矛盾行。
- `doc/代码地图.md`：新增 gui.py 与 hls_download.py 新函数（`_run_single`/`_run_batch`/frozen 常量）行号。
- `doc/功能清单.md`：加「GUI 界面」「单文件打包」✅。
- `README.md`：快速开始加「GUI 启动」「打包 exe」小节。
- `doc/下载指南.md`：加 GUI 操作说明。
