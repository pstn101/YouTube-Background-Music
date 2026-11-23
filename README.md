# YouTube Background Music

Windows 系统托盘背景音乐播放器。可播放 YouTube 播放列表或本地音乐，并会在你全屏或其他程序发声时自动暂停，结束后自动淡入恢复。

A Windows system tray background music player. It plays YouTube playlists or local music, and automatically pauses (with fade-out) when you go fullscreen or when another app makes sound, then resumes (with fade-in) afterwards.

## 功能 / Features

- **🖥 全屏自动暂停**：前台窗口全屏时（如游戏、视频播放器）自动暂停，退出全屏后等待设定秒数再恢复。浏览器全屏不会触发。
- **🔊 有其他声音自动暂停**：其他程序正在发声时自动暂停，对方停止发声后等待设定秒数再恢复。已静音或音量为 0 的程序不会触发。
- **淡出 / 淡入**：暂停和恢复时音量平滑过渡，不会突然中断。
- **恢复播放延迟可调**：托盘菜单中可选 立即 / 3 / 5 / 8 / 10 / 15 / 20 / 30 / 60 秒（默认 10 秒），全屏和其他声音可分别设置。
- **长时间暂停后自动切歌**：暂停超过 10 分钟，恢复时自动播放下一首。
- **🎧 音乐模式**：临时关闭上面两种自动暂停，一直播放。退出音乐模式后恢复原来的开关状态。
- **两种播放来源**：YouTube 播放列表（需要 yt-dlp）或本地音乐文件夹，可在托盘菜单切换。
- 托盘菜单还包括：暂停 / 播放、上一首 / 下一首、单曲循环、音量调节、开机自启动
- 中文 / English 界面（在 Config Editor 中切换；未设置时跟随 Windows 语言）

---

- **🖥 Fullscreen auto-pause**: Pauses when the foreground window is fullscreen (games, video players, etc.) and resumes after a configurable delay once you leave fullscreen. Fullscreen in web browsers does not trigger it.
- **🔊 Other-sound auto-pause**: Pauses when another app is playing sound, and resumes after a configurable delay once it stops. Muted apps and apps with volume at 0 are ignored.
- **Fade out / fade in** when pausing and resuming.
- **Adjustable resume delay** from the tray menu: instant / 3 / 5 / 8 / 10 / 15 / 20 / 30 / 60 seconds (default 10), set separately for fullscreen and other sound.
- **Skips to the next track** if the pause lasted more than 10 minutes.
- **🎧 Music mode**: temporarily disables both auto-pause features. Your previous settings are restored when you turn it off.
- **Two sources**: YouTube playlists (requires yt-dlp) or local music folders, switchable from the tray menu.
- The tray menu also has: play/pause, previous/next, single-track loop, volume, start with Windows.
- Chinese / English UI (set in Config Editor; follows the Windows language by default).

## 使用前需要准备 / Requirements

- **mpv**（必需）：本程序不包含 mpv，请自行下载：https://mpv.io/installation/
  下载解压后，可以放在本程序同一文件夹，或让 Config Editor 的"自动检测工具"去找，也可以手动指定 `mpv.exe` 的路径。
- **yt-dlp**（只在播放 YouTube 时需要）：**不用手动下载**。在 Config Editor 中点击"更新 yt-dlp"按钮，程序会自动从 GitHub 下载最新版到程序所在文件夹，并自动填好路径。之后 YouTube 播放出问题时，再点一次该按钮即可更新。
  只播放本地音乐则完全不需要 yt-dlp。

仅支持 Windows。

---

- **mpv** (required): Not included. Download it from https://mpv.io/installation/
  Extract it next to this program, or let Config Editor's "Auto-detect tools" find it, or set the path to `mpv.exe` manually.
- **yt-dlp** (only needed for YouTube): **no manual download needed.** Click "Update yt-dlp" in Config Editor and it will download the latest version from GitHub into the program folder and fill in the path automatically. If YouTube playback breaks later, click the button again to update.
  Not needed at all if you only play local music.

Windows only.

## 使用方法 / How to use

1. 在 Releases 页面下载 zip 并解压。两个 exe 必须放在同一个文件夹。
2. 下载 mpv（见上）。
3. 运行 `Config Editor.exe`：点"自动检测工具"找 mpv（找不到就手动选择 `mpv.exe`）；要播放 YouTube 就点"更新 yt-dlp"自动安装；添加 YouTube 播放列表或本地音乐文件夹；保存。
4. 运行 `YouTube Background Music.exe`，托盘区会出现图标，右键打开菜单。

---

1. Download the zip from Releases and extract it. Keep both exe files in the same folder.
2. Download mpv (see above).
3. Run `Config Editor.exe`: click "Auto-detect tools" to find mpv (or pick `mpv.exe` manually); for YouTube, click "Update yt-dlp" to install it automatically; add a YouTube playlist or local music folder; save.
4. Run `YouTube Background Music.exe`. A tray icon will appear; right-click it for the menu.

## 关于杀毒软件误报 / Antivirus note

用 PyInstaller 打包的程序可能被杀毒软件误报。源码全部公开在本仓库，可自行检查或自己打包。

Programs packaged with PyInstaller may be flagged by antivirus software. The full source code is in this repository, so you can review it or build it yourself.

## 声明 / Disclaimer

仅供个人学习使用。请自行遵守 YouTube 服务条款及当地法律。

For personal use only. Please follow YouTube's Terms of Service and your local laws.
