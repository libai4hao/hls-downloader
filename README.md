# hls-downloader

好用的视频下载工具，支持下载加密 HLS（AES-128）视频。

## 背景

很多在线视频站的视频是 **AES-128 加密的 HLS 流**：m3u8 里带
`#EXT-X-KEY:METHOD=AES-128`，分片（`.ts`）是加密的。IDM 只会原样下载分片、不会解密，无法下载。

本工具用 **yt-dlp + ffmpeg** 自动完成「抓 m3u8 → 下载分片 → 解密 → 合并成 MP4」，并保留源标题。

## 环境依赖

| 组件 | 说明 | 定位方式 |
|------|------|----------|
| Python 3.11+ | `python` 在 PATH 即可 |
| yt-dlp | 系统已装则直接用；否则把 `ytdlp_lib/` 放到脚本同目录/上级目录 |
| ffmpeg | 解压到脚本同目录或上级目录（形如 `ffmpeg-xxx/bin/`），或设环境变量 `FFMPEG_LOCATION` 指向 `bin` |

依赖（yt-dlp、ffmpeg）体积大，**不进 git**，见 [.gitignore](.gitignore)。

## 快速开始

```bat
python hls_download.py "<网页链接 或 .m3u8 直链>" [输出目录]
```

示例：

```bat
:: 网页链接（推荐，标题最准）
python hls_download.py "https://www.example.com/video/xxx" "D:\下载"

:: m3u8 直链（URL 含 & 时必须加引号）
python hls_download.py "https://cdn.example.com/hls/xxx.m3u8&sign=xxx"

:: 指定输出文件名（自动补 .mp4）
python hls_download.py "https://www.example.com/video/xxx" -o 我的视频

:: 批量下载（urls.txt 每行 "URL [文件名]"，# 注释与空行忽略）
python hls_download.py --batch urls.txt
```

输出：`<标题> [<id>].mp4`（省略输出目录时默认落到 `downloads/`）。同名文件默认加序号 `名称 (1).mp4`，加 `--overwrite` 直接覆盖。

## 图形界面（GUI）

```bat
python gui.py
```

tkinter 图形界面（标准库自带，无需额外依赖），支持核心下载 + 批量 + 代理；链接框填多行自动按批量逐条下载，下载在后台线程跑、日志实时回显，不冻结界面。

## 可选参数（防盗链 / 登录态 / 代理 / 文件名 / 批量 / 历史记录）

| 参数 | 作用 |
|------|------|
| `--cookies <文件>` | 读 cookies 文件（Netscape cookies.txt 或 Cookie-Editor 的 JSON 导出，自动识别；登录态首选） |
| `-b, --browser <名>` | 从浏览器读 cookie（仅 firefox 等非 Chromium 可用；chrome/edge 受 ABE 限制） |
| `--ua, --user-agent <串>` | 覆盖 User-Agent |
| `-r, --referer <url>` | 防盗链 Referer |
| `--proxy <url>` | 代理，如 `http://127.0.0.1:7890` |
| `-o, --output <文件名>` | 固定输出文件名（不含扩展名自动补 `.mp4`，已含扩展名则原样） |
| `--overwrite` | 同名文件直接覆盖（默认加序号 `名称 (1).mp4`） |
| `--batch <文件>` | 批量下载，每行 `URL [文件名]`，`#` 注释与空行忽略 |
| `--retries <次数>` | 下载失败额外重试次数，默认 3（0 关闭重试） |
| `--no-history` | 本次下载不写入下载历史记录 |
| `--history-file <文件>` | 下载历史文件路径，默认脚本同目录 `download_history.log` |

> 需要登录态 / 过 Cloudflare 验证的站点（如 `jav.sb`、FC2 登录墙视频），请优先按
> [doc/cookies导出指南.md](doc/cookies导出指南.md) 导出 cookies 后用 `--cookies`。
> `--cookies` 同时支持 Netscape `cookies.txt` 和 Cookie-Editor 导出的 JSON（自动识别转换）。
> 新版 Chrome/Edge 的 cookie 库被 App-Bound Encryption 锁定，`-b chrome` / `-b edge` 官方无解。

完整映射与示例见 [doc/参数对照.md](doc/参数对照.md)。

```bat
:: 带 cookie + UA + Referer + 代理
python hls_download.py "https://cdn.example.com/hls/xxx.m3u8" ^
  --cookies cookies.txt --ua "Mozilla/5.0 ..." -r "https://www.example.com/" --proxy "http://127.0.0.1:7890"

:: 批量下载 + 覆盖 UA / 代理 + 失败重试
python hls_download.py --batch urls.txt --ua "Mozilla/5.0 ..." --proxy "http://127.0.0.1:7890" --retries 5
```

## 配置与下载历史

- **配置**：把 [config.example.json](config.example.json) 复制为 `config.json`（脚本同目录），脚本启动时自动读取。优先级：命令行参数 > config.json > 内置默认值。
- **下载历史**：默认每次下载（成功/失败/取消）追加一行可读文本到 `download_history.log`（脚本同目录，txt/log 格式）。可用 config 的 `history: false` 全局关闭，或用 `--no-history` 单次关闭；路径可用 config 的 `history_file` 或 `--history-file` 指定。
- **失败清单**：批量下载重试耗尽后仍失败的条目写入 `failed_downloads.txt`（脚本同目录，每行 `URL [文件名]`）。查询串中的签名会脱敏；含签名查询参数的条目需使用原始 URL 重新下载。
- 功能规划见 [doc/功能清单.md](doc/功能清单.md)、[doc/迭代计划.md](doc/迭代计划.md)。

## 打包（可选）

用 PyInstaller 打成**文件夹（onedir）**，双击里面的 exe 即可用（无需装 Python / yt-dlp / ffmpeg）。构建依赖锁定在 `requirements-build.txt`，三个 spec 的作用：

| spec | 产物 | 说明 |
|------|------|------|
| `build_cli.spec` | `dist\hls_download\` | CLI 独立包（控制台窗口，双击无参数进交互式引导） |
| `build_gui.spec` | `dist\hls_download_gui\` | GUI 独立包（无控制台）；CI 不再发行，仅本地构建用 |
| `build_portable.spec` | `dist\hls_downloader_portable\` | CLI + GUI **共享同一个 `_internal\` 运行时**的组合包 |

内置还是外置 ffmpeg 由环境变量 `HLS_BUNDLE_FFMPEG` 决定（默认 `1` 内置）：

```powershell
python -m pip install -r requirements-build.txt
python -m pytest -q

# 完整版：ffmpeg + ffprobe 随包
$env:HLS_BUNDLE_FFMPEG = "1"
pyinstaller --noconfirm --workpath build/pyi-cli --distpath dist build_cli.spec
pyinstaller --noconfirm --workpath build/pyi-gui --distpath dist build_gui.spec
pyinstaller --noconfirm --workpath build/pyi-portable --distpath dist build_portable.spec

# 精简版（Slim）：不内置 ffmpeg，运行机器需从 PATH 找到 ffmpeg 与 ffprobe，或用 FFMPEG_LOCATION 指定
$env:HLS_BUNDLE_FFMPEG = "0"
pyinstaller --noconfirm --workpath build/pyi-portable-slim --distpath dist/slim build_portable.spec
```

> ℹ️ **yt-dlp 版本来源**：本地构建打包你环境里已安装的 yt-dlp——可以是系统装的，也可以是脚本同目录/上级的 `ytdlp_lib/`（nightly 构建，如 `2026.09.27.232945`）；**GitHub Actions 自动发布**（打 tag `v*` 触发）固定安装 `requirements-build.txt` 里的稳定版（`yt-dlp==2026.11.23`）。这是刻意取舍：CI 用可复现的稳定版，本地可用较新的 nightly。

产物（**只认 `--distpath` 下的，别点 `build\` 里的**）：
- `dist\hls_download\hls_download.exe` — CLI 独立版
- `dist\hls_download_gui\hls_download_gui.exe` — GUI 独立版（仅本地构建保留；CI 不再单独发行，见下节）
- `dist\hls_downloader_portable\hls_download.exe` + `hls_download_gui.exe` — 共享运行时组合版（两个 exe 共用一份 `_internal\`）

> ⚠️ 运行产物目录里的 exe。打包时 GUI 窗口还开着（或上一个 exe 进程未退出）会占用输出目录导致重新打包失败，请先关闭正在运行的下载器再打包。
>
> ⚠️ **重新打包会先清空目标产物目录**（如 `dist\hls_download\`）再输出，防止新旧构建叠加出嵌套镜像。数据文件（`config.json` / `download_history.log` / 输出目录）默认落在 exe 旁，也就是这个目录里——**别把数据存在产物目录内**，重打包会静默删掉；要迁移就把数据文件复制到新包旁。
>
> 构建中间目录由 `--workpath` 指定（如 `build/pyi-cli`），spec 不再自动删除 `build\`，需要清理时自行删除、或交给 CI 的 runner 生命周期回收。
>
> **为什么用文件夹分发（onedir）而不是单个 exe？** 单文件 exe 每次启动都要先把几百 MB 的 Python + yt-dlp + ffmpeg 解压到系统临时目录，首次启动要等十几秒甚至更久。文件夹分发的 exe 直接读取旁边的 `_internal\`，**启动秒开**。代价是产物是一整个文件夹，不是单个文件。
>
> **怎么发给别人？** 把整个产物文件夹（如 `dist\hls_downloader_portable\`）压成一个 zip 发出去；对方解压后双击里面的 exe 即可。数据文件（`config.json` / `download_history.log` / 输出目录）落在 exe 旁（即 `_internal\` 同级目录）。

## 首次运行被 Windows 拦截怎么办（SmartScreen）

本工具是**未签名的免费程序**，Windows 会把它标记为「未知发布者」，首次从网络下载/解压运行时会弹蓝色提示「Windows 已保护你的电脑」。这是 Windows 对未签名程序的标准提醒，**不是病毒，也不是杀软误报**；点击过一次「仍要运行」后，Windows 记下解锁标记，之后就不再弹。

- 拦截框里点 **「更多信息」→「仍要运行」** 即可。
- 若右键菜单或文件属性里显示「此文件来自其他计算机」，可右键 exe → **属性** → 勾选「解除锁定」→ 确定，也能消除提示。
- 要**彻底根除**这个提示，只能购买代码签名证书（OV/EV，按年付费），免费无法做到。已尽量在 exe 里写入产品名/版本信息让观感更正规，但 SmartScreen 对未签名程序仍会提示。

## 目录结构

```
hls-downloader/
├── hls_download.py      # 主脚本（CLI 入口 + 下载核心函数）
├── gui.py               # tkinter 图形界面（复用 hls_download）
├── config.example.json  # 配置示例（复制为 config.json 生效）
├── app.ico              # 程序图标（打包时写入 exe）
├── version_info.txt     # exe 版本信息（公司名/产品名/版本号）
├── build_cli.spec       # PyInstaller 打包 CLI 独立包（onedir）
├── build_gui.spec       # PyInstaller 打包 GUI 独立包（onedir）
├── build_portable.spec  # PyInstaller 打包 CLI + GUI 共享运行时组合包
├── requirements-build.txt # 锁定的构建依赖（PyInstaller / yt-dlp / pytest）
├── BUILDING.md          # 本地构建与 CI 发布说明
├── SECOND_PASS_REVIEW.md # 第二轮审查与实施记录
├── doc/                 # 文档目录
│   ├── 发布SOP.md        # 发布流程（版本号 → 打 tag → 自动构建发布）
│   ├── 功能设计.md       # 功能设计文档（设计决策 / 模块划分 / 数据流）
│   ├── 代码地图.md       # 代码地图（文件导航 + 关键代码行号）
│   ├── 功能清单.md       # 功能清单（已实现 / 规划中 / 暂不做）
│   ├── 迭代计划.md       # 版本路线与优先级
│   ├── 参数对照.md       # 参数 ↔ yt-dlp 映射 + 示例
│   ├── 下载指南.md       # 详细指南 + 报错速查 + IDM 抓不到链接的兜底方案
│   ├── cookies导出指南.md # cookies.txt 导出（登录态 / 过 Cloudflare 验证站点的首选方案）
│   ├── GUI设计.md        # GUI 技术选型与设计
│   └── GUI实现计划.md    # GUI 分步实现计划
├── examples/            # 纯 Python 手动 AES-128 解密示例（教学用，不依赖 yt-dlp）
│   ├── download_video.py
│   └── refill.py
└── README.md
```

## Windows 发布包

GitHub Releases 提供以下发行物：

- `hls-downloader-portable.zip`：CLI + GUI，共享 onedir 运行时，内置 FFmpeg/FFprobe（同时覆盖独立 GUI 包的用途）。
- `hls-downloader-portable-slim.zip`：CLI + GUI，共享运行时，不内置 FFmpeg；需要系统 PATH 中同时可用 `ffmpeg` 和 `ffprobe`，或设置 `FFMPEG_LOCATION`。
- `hls-downloader-cli.zip`：内置 FFmpeg 的 CLI 独立包（适合脚本/自动化）。
- `SHA256SUMS.txt`：以上三个 ZIP 的 SHA256 校验值。

> v1.12.1 起停止单独发行 `hls-downloader-gui.zip`：`portable.zip` 已包含 GUI + CLI + ffmpeg，独立 GUI 包属于重复资产（98.8 MB）。需要单 exe GUI 的可以本地用 `build_gui.spec` 构建。

便携版解压后可直接运行。精简版适合已经安装 FFmpeg 的用户；若检测不到 FFmpeg/FFprobe，程序会提示安装或设置 `FFMPEG_LOCATION`。

构建和打包细节见 [BUILDING.md](BUILDING.md)。

## 常见问题

见 [doc/下载指南.md](doc/下载指南.md)。
