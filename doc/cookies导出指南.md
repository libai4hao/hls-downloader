# cookies.txt 导出指南

需要「登录态 / 过 Cloudflare 人机验证」才能下载的站点（如 `jav.sb`、FC2 登录墙视频），
用本工具时**最稳的做法是导出 `cookies.txt`**，再用 `--cookies` 喂给脚本。

> **为什么不直接用 `-b chrome` 从浏览器自动读？**
> 新版 Chrome / Edge（128+，开启 App-Bound Encryption 后）的 cookie 数据库被锁且用
> v20 加密，yt-dlp **官方没有解决方案**（见 [yt-dlp#15401](https://github.com/yt-dlp/yt-dlp/issues/15401)：
> 维护者明确「没有计划」，甚至提议移除 Windows 上 Chromium 系浏览器的 `--cookies-from-browser` 支持）。
> 所以在你当前机器（Chrome 156 + Edge，均开 ABE）上，`-b chrome` / `-b edge` 必然失败，报
> `Could not copy Chrome cookie database`。
> 手动导出 `cookies.txt` 不依赖解密、不受 ABE 限制，是唯一稳妥路径。

---

## 一、用浏览器扩展导出（推荐）

### Chrome / Edge

1. 打开浏览器扩展商店，搜索并安装 **「Get cookies.txt LOCALLY」**（作者：kairi003 / 社区维护，
   Chromium 系通用，Edge 也可装 Chrome 商店扩展）。
   - Chrome Web Store：<https://chromewebstore.google.com/>
   - Edge 加载项：<https://microsoftedge.microsoft.com/addons/>
2. 打开目标站点（如 `xx.com`），先**手动完成人机验证 / 登录**，确保页面能正常看到视频。
3. 点击浏览器右上角的「Get cookies.txt LOCALLY」扩展图标。
4. 选择导出范围：**当前站点**（Current site）即可，格式选 **Netscape**。
5. 点 **Export**，把下载到的 `cookies.txt` 放到脚本同目录（或记住其路径）。

### Firefox

Firefox 不需要扩展，自带导出：

1. 打开目标站点并登录 / 过验证。
2. `F12` → 存储 / Storage → Cookies → 右键 `https://…` → 导出，或
3. 用扩展「cookies.txt」（作者 kairi003）导出 Netscape 格式。

---

## 二、格式要求

yt-dlp 的 `cookiefile` 只认 **Netscape cookies.txt** 格式，首行应为：

```
# Netscape HTTP Cookie File
```

每行形如：

```
.example.com	TRUE	/	TRUE	1735689600	cf_clearance	xxxxx
```

> ⚠️ 若导出的是 JSON（如 Cookie-Editor 默认导出），**本工具会自动识别并转成 Netscape 格式**，
> 直接喂给 `--cookies` 即可，无需手动转换。也可以手动用扩展导出 Netscape 格式。

---

## 三、喂给脚本

```bat
python hls_download.py "https://jav.sb/jav/xxx.html" --cookies cookies.txt
```

### 关键：`cf_clearance` 必须绑 UA + IP

Cloudflare 的 `cf_clearance` cookie 与「User-Agent + 出口 IP」绑定。用 `--cookies` 时：

1. **同时带 `--ua`**，且填的值必须与导出 cookie 的那台浏览器一致：

   ```bat
   python hls_download.py "https://jav.sb/jav/xxx.html" ^
     --cookies cookies.txt ^
     --ua "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"
   ```

2. **出口 IP 一致**：过验证时若走代理（如 7890），下载时也要 `--proxy "http://127.0.0.1:7890"`；
   过验证时没走代理，下载时就别加 `--proxy`。UA + IP 任一不一致都会被服务器判定不匹配而 403。

---

## 四、常见问题

| 现象 | 原因 | 处理 |
|------|------|------|
| `Could not copy Chrome cookie database` | `-b chrome/edge` 撞上 App-Bound Encryption（ABE），官方无解 | 改用本指南的 `--cookies` 导出方案 |
| 带 `--cookies` 仍 403 | UA / 出口 IP 与过验证时不一致 | 按第三节同时带 `--ua` + 一致 `--proxy` |
| cookies 失效 | `cf_clearance` 有时效（通常几小时~一天） | 重新过验证、重新导出 cookies.txt |
| 导出的是 JSON | 用了 Cookie-Editor 等默认 JSON 导出 | 直接喂给 `--cookies`，脚本会自动转成 Netscape 格式 |

---

相关文档：[下载指南](下载指南.md) · [参数对照](参数对照.md) · 主脚本 [hls_download.py](../hls_download.py)
