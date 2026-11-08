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

:: 批量下载 + 覆盖 UA / 代理
python hls_download.py --batch urls.txt --ua "Mozilla/5.0 ..." --proxy "http://127.0.0.1:7890"
```

## 配置与下载历史

- **配置**：把 [config.example.json](config.example.json) 复制为 `config.json`（脚本同目录），脚本启动时自动读取。优先级：命令行参数 > config.json > 内置默认值。
- **下载历史**：默认每次下载（成功/失败）追加一行可读文本到 `download_history.log`（脚本同目录，txt/log 格式）。可用 config 的 `history: false` 全局关闭，或用 `--no-history` 单次关闭；路径可用 config 的 `history_file` 或 `--history-file` 指定。
- 功能规划见 [doc/功能清单.md](doc/功能清单.md)、[doc/迭代计划.md](doc/迭代计划.md)。

## 目录结构

```
hls-downloader/
├── hls_download.py      # 主脚本（yt-dlp 封装）
├── config.example.json  # 配置示例（复制为 config.json 生效）
├── doc/                 # 文档目录
│   ├── 功能设计.md       # 功能设计文档（设计决策 / 模块划分 / 数据流）
│   ├── 代码地图.md       # 代码地图（文件导航 + 关键代码行号）
│   ├── 功能清单.md       # 功能清单（已实现 / 规划中 / 暂不做）
│   ├── 迭代计划.md       # 版本路线与优先级
│   ├── 参数对照.md       # 参数 ↔ yt-dlp 映射 + 示例
│   ├── 下载指南.md       # 详细指南 + 报错速查 + IDM 抓不到链接的兜底方案
│   └── cookies导出指南.md # cookies.txt 导出（登录态 / 过 Cloudflare 验证站点的首选方案）
├── examples/            # 纯 Python 手动 AES-128 解密示例（教学用，不依赖 yt-dlp）
│   ├── download_video.py
│   └── refill.py
└── README.md
```

## 常见问题

见 [doc/下载指南.md](doc/下载指南.md)。
