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

:: m3u8 直链
python hls_download.py "https://cdn.example.com/hls/xxx.m3u8"
```

输出：`<标题> [<id>].mp4`（省略输出目录时默认落到 `downloads/`）。

## 目录结构

```
hls-downloader/
├── hls_download.py     # 主脚本（yt-dlp 封装）
├── 下载指南.md          # 详细指南 + 报错速查 + IDM 抓不到链接的兜底方案
├── examples/           # 纯 Python 手动 AES-128 解密示例（教学用，不依赖 yt-dlp）
│   ├── download_video.py
│   └── refill.py
└── README.md
```

## 常见问题

见 [下载指南.md](下载指南.md)。
