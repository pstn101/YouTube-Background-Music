# -*- coding: utf-8 -*-

"""
YouTube Background Music V4.8.0

V4.8.0 改动：

- 新增多语言（中文 / English）：语言由 config.json 的 "language" 决定
  （在 Config Editor 里切换），没有该字段时按 Windows 界面语言。
  托盘菜单、捐赠窗口、音量窗口、启动错误提示全部随语言切换。
- 删除 ybm_debug.log 及所有 debug_log 调用，不再写任何日志文件。

V4.7.3 修复：

- 托盘"播放 / 暂停"按钮文字不同步：pystray 的菜单文字回调只在
  update_menu() 时重新求值，而 music_paused 的所有变更点都没有
  刷新托盘，导致自动暂停 / 自动恢复一个循环之后按钮文字停在旧
  快照上（开机自启时最明显：音乐在放，按钮却显示"播放 / 继续"，
  点一下反而把音乐暂停了）。
- 新增 set_music_paused()，统一修改 music_paused 并在状态真的
  变化时刷新托盘；mpv_pause() / mpv_resume() 改为走这个入口。
- 绕过 mpv_resume() 直接改标志的路径（watchdog 反向自愈、
  reset_runtime_playback_state、launch_mpv_if_needed、
  stop_current_mpv）各自补上 refresh_tray_menu()。

V4.7.2 改动：

- 全屏自动暂停改为与其他声音自动暂停相同的淡出 / 淡入，
  两者在"交接"时不再出现"闪一下恢复播放"。
- 音量窗口打开时安装全局鼠标滚轮钩子（WH_MOUSE_LL），
  鼠标不必悬停在窗口上也能调音量。

V4.7.1 修复：

- 音乐模式期间手动点"播放"，不再污染 audio_pause_enabled 的持久化。
- 进入 / 退出音乐模式时无条件清 manual_override_audio，避免音频暂停永久失效。
- cancel_audio_fade 增加 join，避免音量被淡出线程写回 0。
- start_audio_fade_in 先恢复播放、再压 0 音量，避免 MPV 恢复失败时卡暂停。
- tray_toggle_fullscreen_pause 关闭且之前是自动暂停时，恢复播放。
- 删除死代码：song_title_monitor / SONG_TITLE_POLL_SECONDS / get_current_youtube_url。
"""

import json
import subprocess
import time
import threading
import queue
import os
import tempfile
import sys
import winreg
import ctypes
import tkinter as tk

from tkinter import ttk
import tkinter.font as tkfont

import win32api
import win32con
import win32file
import win32gui
import win32process
import win32pipe
import win32event
import pywintypes

import pystray
from PIL import Image, ImageDraw

from pycaw.pycaw import AudioUtilities


# ============================================================
# Donate 地址（提示文字在 STRINGS 里，随语言切换）
# ============================================================

DONATE_ADDRESSES = [
    {
        "name": "Binance UID",
        "address": "951608743",
    },
    {
        "name": "Bybit UID",
        "address": "424360102",
    },
    {
        "name": "USDT/USDC – TRC20",
        "address": "TQS9H5TFic7bZ3P6mbqq9tm2ecB95zAqgj",
    },
    {
        "name": "USDT/USDC – ERC20",
        "address": "0x6Fe9E2a0E9884bd11Fb575732c4E6B08b20D94C9",
    },
]


# ============================================================
# 路径
# ============================================================

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _get_resource_path(relative_path):
    """获取打包后资源的路径（兼容 onefile 和开发模式）。"""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = BASE_DIR
    return os.path.join(base, relative_path)

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
SETTINGS_FILE = os.path.join(
    BASE_DIR,
    "youtube_background_music_settings.json"
)

CONFIG_EDITOR_EXE = os.path.join(BASE_DIR, "Config Editor.exe")
CONFIG_EDITOR_PY = os.path.join(BASE_DIR, "Config Editor.py")


# ============================================================
# 多语言
# ============================================================

SUPPORTED_LANGUAGES = ("zh", "en")

_current_lang = "en"


def detect_system_language():

    """按 Windows 界面语言决定默认语言：中文系统用中文，其余用英文。"""

    try:
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        if (lang_id & 0xFF) == 0x04:
            return "zh"
    except Exception:
        pass

    return "en"


def set_language(lang):

    global _current_lang

    _current_lang = lang if lang in SUPPORTED_LANGUAGES else "en"


STRINGS = {
    "zh": {
        "fetching": "正在获取...",

        # 托盘菜单
        "menu_startup_on": "🚀 开机自启动：已开启（点击关闭）",
        "menu_startup_off": "🚀 开机自启动：已关闭",
        "menu_pause": "⏸ 暂停",
        "menu_play": "▶ 播放 / 继续",
        "menu_previous": "⏮ 上一首",
        "menu_next": "⏭ 下一首",
        "menu_loop_on": "🔂 单曲循环：已开启（点击关闭）",
        "menu_loop_off": "🔂 单曲循环：已关闭",
        "menu_volume": "🔊 音量：{volume}%",
        "menu_music_mode_on": "🎧 音乐模式：已开启（点击关闭音乐模式）",
        "menu_music_mode_off": "🎧 音乐模式：已关闭（点击开始无限播放）",
        "menu_fullscreen_prefix": "🖥 全屏自动暂停：",
        "menu_audio_prefix": "🔊 有其他声音自动暂停：",
        "menu_resume_delay": "⏱ 恢复播放延迟",
        "menu_fs_delay": "🖥 退出全屏后：{n}",
        "menu_audio_delay": "🔊 其他声音停止后：{n}",
        "delay_seconds": "{n} 秒",
        "delay_instant": "立即",
        "state_on": "已开启",
        "state_off": "已关闭",
        "state_disabled_music_mode": "已禁用（音乐模式中）",
        "menu_source_prefix": "🎵 播放来源：",
        "source_local": "本地音乐",
        "source_local_short": "本地",
        "source_unknown": "未知",
        "menu_no_playlists": "没有配置 YouTube Playlist",
        "menu_no_folders": "没有配置本地音乐文件夹",
        "menu_settings": "⚙ 设置",
        "menu_donate": "💝 捐赠",
        "menu_exit": "❌ 退出",

        # 音量窗口
        "volume_label": "音量",

        # 捐赠窗口
        "donate_window_title": "捐赠 - YouTube Background Music",
        "donate_heading": "💝 捐赠",
        "donate_message": (
            "感谢你支持 YouTube Background Music！\n\n"
            "如果这个小工具帮到了你，欢迎请我喝杯咖啡 ☕️"
        ),
        "donate_thanks": "谢谢！",
        "donate_copy": "复制",
        "donate_copied": "{name} 地址已复制！",
        "donate_hint": "点击“复制”按钮复制地址。",
        "donate_copy_failed": "复制失败",
        "donate_no_addresses": "没有配置捐赠地址。",
        "donate_close": "关闭",

        # 错误提示
        "err_startup_toggle": "无法修改 Windows 开机自启动设置。",
        "err_no_config_editor": "找不到 Config Editor。\n\n{exe}\n{py}",
        "err_no_mpv_path": "config.json 中没有设置 mpv_path。",
        "err_mpv_not_found": "找不到 MPV：\n\n{path}",
        "err_no_playlists": (
            "config.json 没有配置 YouTube Playlist。\n\n"
            "请至少配置一个 youtube_playlists。"
        ),
        "err_no_sources": (
            "config.json 没有配置 local_music_folders，"
            "也没有配置 YouTube Playlist。"
        ),
        "err_no_ytdlp_path": "当前播放来源是 YouTube，但 config.json 没有设置 yt_dlp_path。",
        "err_ytdlp_not_found": "找不到 yt-dlp：\n\n{path}",
        "err_no_local_files": (
            "当前本地音乐文件夹中没有找到支持的音乐文件。\n\n"
            "请检查 config.json 中的 folder 路径。"
        ),
        "err_mpv_start": (
            "MPV 启动失败。\n\n"
            "请检查：\n"
            "1. MPV 路径是否正确\n"
            "2. 当前播放来源是否正确\n"
            "3. YouTube 是否配置正确\n"
            "4. yt-dlp 是否存在\n"
            "5. 本地音乐文件夹是否存在"
        ),
        "err_tray_create": "托盘图标创建失败。\n\n{error}",
        "err_tray_run": "托盘运行失败。\n\n{error}",
    },

    "en": {
        "fetching": "Loading...",

        # Tray menu
        "menu_startup_on": "🚀 Start with Windows: On",
        "menu_startup_off": "🚀 Start with Windows: Off",
        "menu_pause": "⏸ Pause",
        "menu_play": "▶ Play / Resume",
        "menu_previous": "⏮ Previous",
        "menu_next": "⏭ Next",
        "menu_loop_on": "🔂 Loop: On",
        "menu_loop_off": "🔂 Loop: Off",
        "menu_volume": "🔊 Volume: {volume}%",
        "menu_music_mode_on": "🎧 Music mode: On (click to turn off)",
        "menu_music_mode_off": "🎧 Music mode: Off (click to turn on)",
        "menu_fullscreen_prefix": "🖥 Pause on fullscreen: ",
        "menu_audio_prefix": "🔊 Pause on other audio: ",
        "menu_resume_delay": "⏱ Resume delay",
        "menu_fs_delay": "🖥 After leaving fullscreen: {n}",
        "menu_audio_delay": "🔊 After other audio stops: {n}",
        "delay_seconds": "{n}s",
        "delay_instant": "Instant",
        "state_on": "On",
        "state_off": "Off",
        "state_disabled_music_mode": "Disabled (music mode)",
        "menu_source_prefix": "🎵 Source: ",
        "source_local": "Local Music",
        "source_local_short": "Local",
        "source_unknown": "Unknown",
        "menu_no_playlists": "No YouTube playlists configured",
        "menu_no_folders": "No local music folders configured",
        "menu_settings": "⚙ Settings",
        "menu_donate": "💝 Donate",
        "menu_exit": "❌ Exit",

        # Volume window
        "volume_label": "Volume",

        # Donate window
        "donate_window_title": "Donate - YouTube Background Music",
        "donate_heading": "💝 Donate",
        "donate_message": (
            "Thank you for supporting YouTube Background Music!\n\n"
            "If this little tool has helped you, feel free to buy me a coffee ☕️"
        ),
        "donate_thanks": "Thank you!",
        "donate_copy": "Copy",
        "donate_copied": "{name} address copied!",
        "donate_hint": "Use the Copy button to copy an address.",
        "donate_copy_failed": "Copy failed",
        "donate_no_addresses": "No donation addresses configured.",
        "donate_close": "Close",

        # Error messages
        "err_startup_toggle": "Could not change the Windows startup setting.",
        "err_no_config_editor": "Config Editor was not found.\n\n{exe}\n{py}",
        "err_no_mpv_path": "mpv_path is not set in config.json.",
        "err_mpv_not_found": "MPV was not found:\n\n{path}",
        "err_no_playlists": (
            "No YouTube playlist is configured in config.json.\n\n"
            "Please configure at least one entry in youtube_playlists."
        ),
        "err_no_sources": (
            "Neither local_music_folders nor youtube_playlists "
            "is configured in config.json."
        ),
        "err_no_ytdlp_path": "The current source is YouTube, but yt_dlp_path is not set in config.json.",
        "err_ytdlp_not_found": "yt-dlp was not found:\n\n{path}",
        "err_no_local_files": (
            "No supported music files were found in the current local music folder.\n\n"
            "Please check the folder path in config.json."
        ),
        "err_mpv_start": (
            "MPV failed to start.\n\n"
            "Please check:\n"
            "1. The MPV path is correct\n"
            "2. The current source is correct\n"
            "3. YouTube is configured correctly\n"
            "4. yt-dlp exists\n"
            "5. The local music folder exists"
        ),
        "err_tray_create": "Failed to create the tray icon.\n\n{error}",
        "err_tray_run": "The tray icon failed to run.\n\n{error}",
    },
}


def t(key, **kwargs):

    text = STRINGS.get(_current_lang, {}).get(key)

    if text is None:
        text = STRINGS["en"].get(key, key)

    if kwargs:
        try:
            text = text.format(**kwargs)
        except Exception:
            pass

    return text


# ============================================================
# 本地音乐格式
# ============================================================

LOCAL_AUDIO_EXTENSIONS = {
    ".mp3",
    ".flac",
    ".wav",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
    ".wma",
    ".alac",
    ".aiff",
    ".ape",
}


# ============================================================
# 配置
# ============================================================

config = {}
MPV_PATH = ""
YTDLP_PATH = ""
YOUTUBE_PLAYLISTS = []
LOCAL_MUSIC_FOLDERS = []


# ============================================================
# 播放来源
# ============================================================

SOURCE_YOUTUBE = "youtube"
SOURCE_LOCAL = "local"

source_type = SOURCE_YOUTUBE
youtube_playlist_index = 0
local_folder_index = 0

local_playlist_file = os.path.join(
    tempfile.gettempdir(),
    "YBM_local_music_playlist.m3u8"
)


# ============================================================
# 音量
# ============================================================

DEFAULT_VOLUME = 100.0
DEFAULT_WINDOW_X = 1537
DEFAULT_WINDOW_Y = 891
MIN_VOLUME = 0.0
MAX_VOLUME = 100.0
current_volume = DEFAULT_VOLUME


# ============================================================
# 当前歌曲名称
# ============================================================

current_song_title = ""
TITLE_PROPERTY_TIMEOUT = 0.25


# ============================================================
# GUI
# ============================================================

gui_command_queue = queue.Queue()
gui_thread = None
gui_ready = threading.Event()
gui_root = None

donate_window = None
volume_window = None

volume_save_after_id = None
volume_refresh_after_id = None


# ============================================================
# 可调参数
# ============================================================

THRESHOLD_MINUTES = 10
POLL_SECONDS = 0.5
AUDIO_POLL_SECONDS = 0.5
AUDIO_THRESHOLD = 0.001

DEFAULT_AUDIO_RESUME_BUFFER = 10.0

AUDIO_FADE_OUT_SECONDS = 1.0
AUDIO_FADE_IN_SECONDS = 1.0
AUDIO_FADE_STEP_SECONDS = 0.05

# 退出全屏后等待多久才恢复播放（秒）——默认值；用户可在托盘菜单里改，
# 保存在 settings.json 的 fullscreen_resume_delay。
FULLSCREEN_RESUME_DELAY = 10.0

# 可选的恢复延迟（秒），托盘菜单里显示这些选项
RESUME_DELAY_OPTIONS = (0, 3, 5, 8, 10, 15, 20, 30, 60)

fullscreen_resume_delay = FULLSCREEN_RESUME_DELAY
audio_resume_delay = DEFAULT_AUDIO_RESUME_BUFFER


# ============================================================
# MPV IPC
# ============================================================

PIPE_NAME = r"\\.\pipe\mpv-wallpaper-music"

mpv_ipc_lock = threading.Lock()

mpv_request_id_lock = threading.Lock()
mpv_request_id_counter = 0

volume_request_lock = threading.Lock()
pending_volume_request = None
volume_request_event = threading.Event()


title_event_stop = threading.Event()
title_event_handle_lock = threading.Lock()
title_event_handle = None


# ============================================================
# 浏览器排除
# ============================================================

BROWSER_PROCESSES = {
    "firefox.exe",
    "chrome.exe",
    "msedge.exe",
    "brave.exe",
    "vivaldi.exe",
    "opera.exe",
    "opera_gx.exe",
    "arc.exe",
    "librewolf.exe",
    "waterfox.exe",
}


# ============================================================
# Windows 特殊窗口
# ============================================================

IGNORED_CLASSES = {
    "Progman",
    "WorkerW",
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
}


# ============================================================
# 全局状态
# ============================================================

started_proc = None
tray_icon = None
running = True
music_paused = False
source_switching = False
source_switch_lock = threading.Lock()
single_loop_enabled = False

fullscreen_pause_enabled = True
auto_fullscreen_paused = False
fullscreen_paused_at = None
fullscreen_exited_at = None

audio_pause_enabled = True
auto_audio_paused = False
manual_override_audio = False
last_audio_stop_time = None
last_other_audio_state = None

# 音乐模式
music_mode_enabled = False
saved_fullscreen_pause_enabled = True
saved_audio_pause_enabled = True

STARTUP_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_REG_NAME = "YouTubeBackgroundMusic"
startup_enabled = True


# ============================================================
# MPV Watchdog
# ============================================================

MPV_WATCHDOG_SECONDS = 2.0
MPV_INTERNAL_PAUSE_RECOVERY_SECONDS = 4.0
MPV_IDLE_RECOVERY_SECONDS = 8.0
MPV_RESTART_COOLDOWN_SECONDS = 10.0
MPV_HEALTH_FAIL_LIMIT = 3
MPV_PROPERTY_TIMEOUT = 0.8

# music_paused=True 但 mpv 实际 pause 属性不是 True（按钮显示"暂停"，
# 但音乐其实还在播放）的反向自愈参数。
MPV_PAUSE_VERIFY_SETTLE_SECONDS = 0.15
MPV_FLAG_DESYNC_RECOVERY_SECONDS = 4.0

mpv_started_at = None
mpv_last_recovery_time = 0.0
mpv_unexpected_pause_since = None
mpv_unexpected_playing_since = None
mpv_idle_since = None
mpv_health_fail_count = 0


# ============================================================
# 淡出 / 淡入
# ============================================================

audio_fade_lock = threading.Lock()
audio_fade_thread = None
audio_fade_cancel_event = None


# ============================================================
# 全局鼠标滚轮钩子
# ============================================================

volume_wheel_hook = None
volume_wheel_hook_proc = None
volume_wheel_delta_queue = queue.Queue()


# ============================================================
# 状态锁
# ============================================================

state_lock = threading.Lock()


# ============================================================
# 脱离当前 CMD
# ============================================================

def detach_from_console():

    if os.name != "nt":
        return

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_console_window = kernel32.GetConsoleWindow
        get_console_window.restype = ctypes.c_void_p
        console_window = get_console_window()

        if not console_window:
            return

        free_console = kernel32.FreeConsole
        free_console.restype = ctypes.c_bool
        free_console()

    except Exception:
        pass


# ============================================================
# 配置
# ============================================================

def load_config():

    global config
    global MPV_PATH
    global YTDLP_PATH
    global YOUTUBE_PLAYLISTS
    global LOCAL_MUSIC_FOLDERS

    data = {}

    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

        if not isinstance(data, dict):
            data = {}

    except Exception:
        data = {}

    config = data

    lang = data.get("language")
    set_language(
        lang if lang in SUPPORTED_LANGUAGES
        else detect_system_language()
    )

    MPV_PATH = os.path.expandvars(os.path.expanduser(str(
        data.get("mpv_path", "")
    ).strip()))

    YTDLP_PATH = os.path.expandvars(os.path.expanduser(str(
        data.get("yt_dlp_path", "")
    ).strip()))

    YOUTUBE_PLAYLISTS = []

    playlists = data.get("youtube_playlists", [])

    if isinstance(playlists, list):
        for item in playlists:
            if not isinstance(item, dict):
                continue

            name = str(item.get("name", "")).strip()
            url = str(item.get("url", "")).strip()

            if name and url:
                YOUTUBE_PLAYLISTS.append({
                    "name": name,
                    "url": url,
                })

    LOCAL_MUSIC_FOLDERS = []

    folders = data.get("local_music_folders", [])

    if isinstance(folders, list):
        for item in folders:
            if not isinstance(item, dict):
                continue

            name = str(item.get("name", "")).strip()
            folder = os.path.expandvars(os.path.expanduser(str(
                item.get("folder", "")
            ).strip()))

            if name and folder:
                LOCAL_MUSIC_FOLDERS.append({
                    "name": name,
                    "folder": folder,
                })


# ============================================================
# JSON
# ============================================================

def _read_json_file(path):

    try:
        if not os.path.exists(path):
            return {}

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data if isinstance(data, dict) else {}

    except Exception:
        return {}


def _write_settings_file(data):

    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return True
    except Exception:
        return False


def load_settings():
    return _read_json_file(SETTINGS_FILE)


def save_settings(**updates):

    try:
        data = load_settings()
        data.update(updates)
        return _write_settings_file(data)
    except Exception:
        return False


# ============================================================
# 音量设置
# ============================================================

def load_volume():

    global current_volume

    try:
        data = load_settings()
        volume = float(data.get("volume", DEFAULT_VOLUME))
        current_volume = max(MIN_VOLUME, min(MAX_VOLUME, volume))
    except Exception:
        current_volume = DEFAULT_VOLUME


def save_volume():

    with state_lock:
        volume = current_volume

    return save_settings(volume=round(volume, 1))


def load_volume_window_position():

    data = load_settings()

    try:
        if "x" not in data or "y" not in data:
            return None

        return int(data["x"]), int(data["y"])
    except Exception:
        return None


def save_volume_window_position(root):

    try:
        return save_settings(
            x=int(root.winfo_x()),
            y=int(root.winfo_y())
        )
    except Exception:
        return False


def position_volume_window(root):

    saved = load_volume_window_position()

    if saved is None:
        x, y = DEFAULT_WINDOW_X, DEFAULT_WINDOW_Y
    else:
        x, y = saved

    root.geometry(f"+{x}+{y}")


# ============================================================
# 播放来源设置
# ============================================================

def load_source_settings():

    global source_type
    global youtube_playlist_index
    global local_folder_index

    data = load_settings()

    saved_source = data.get("source_type", SOURCE_YOUTUBE)
    if saved_source not in {SOURCE_YOUTUBE, SOURCE_LOCAL}:
        saved_source = SOURCE_YOUTUBE

    try:
        saved_youtube_index = int(data.get("youtube_playlist_index", 0))
    except Exception:
        saved_youtube_index = 0

    try:
        saved_local_index = int(data.get("local_folder_index", 0))
    except Exception:
        saved_local_index = 0

    if YOUTUBE_PLAYLISTS:
        saved_youtube_index = max(
            0,
            min(len(YOUTUBE_PLAYLISTS) - 1, saved_youtube_index)
        )
    else:
        saved_youtube_index = 0

    if LOCAL_MUSIC_FOLDERS:
        saved_local_index = max(
            0,
            min(len(LOCAL_MUSIC_FOLDERS) - 1, saved_local_index)
        )
    else:
        saved_local_index = 0

    with state_lock:
        source_type = saved_source
        youtube_playlist_index = saved_youtube_index
        local_folder_index = saved_local_index


def save_source_settings():

    with state_lock:
        return save_settings(
            source_type=source_type,
            youtube_playlist_index=youtube_playlist_index,
            local_folder_index=local_folder_index
        )


def load_pause_settings():

    global fullscreen_pause_enabled
    global audio_pause_enabled
    global fullscreen_resume_delay
    global audio_resume_delay

    data = load_settings()

    fullscreen_value = data.get("fullscreen_pause_enabled", True)
    audio_value = data.get("audio_pause_enabled", True)

    if not isinstance(fullscreen_value, bool):
        fullscreen_value = True
    if not isinstance(audio_value, bool):
        audio_value = True

    def _delay(key, default):
        try:
            v = float(data.get(key, default))
            return max(0.0, min(600.0, v))
        except Exception:
            return float(default)

    with state_lock:
        fullscreen_pause_enabled = fullscreen_value
        audio_pause_enabled = audio_value
        fullscreen_resume_delay = _delay(
            "fullscreen_resume_delay", FULLSCREEN_RESUME_DELAY
        )
        audio_resume_delay = _delay(
            "audio_resume_delay", DEFAULT_AUDIO_RESUME_BUFFER
        )


# ============================================================
# 开机自启动
# ============================================================

def get_pythonw_path():

    try:
        current = os.path.abspath(sys.executable)
        if os.path.basename(current).lower() == "pythonw.exe":
            return current

        candidate = os.path.join(os.path.dirname(current), "pythonw.exe")
        if os.path.isfile(candidate):
            return candidate
    except Exception:
        pass

    return sys.executable


def get_startup_command():

    if getattr(sys, "frozen", False):
        return '"' + os.path.abspath(sys.executable) + '"'

    pythonw = get_pythonw_path()
    script = os.path.abspath(__file__)

    return '"' + pythonw + '" "' + script + '"'


def set_windows_startup(enabled):

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            STARTUP_REG_PATH,
            0,
            winreg.KEY_SET_VALUE
        )

        try:
            if enabled:
                winreg.SetValueEx(
                    key,
                    STARTUP_REG_NAME,
                    0,
                    winreg.REG_SZ,
                    get_startup_command()
                )
            else:
                try:
                    winreg.DeleteValue(key, STARTUP_REG_NAME)
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)

        return True

    except Exception:
        return False


def load_startup_settings():

    global startup_enabled

    data = load_settings()

    if "startup_enabled" not in data:
        startup_enabled = True
        save_settings(startup_enabled=True)
        set_windows_startup(True)
        return

    value = data.get("startup_enabled")
    startup_enabled = value if isinstance(value, bool) else True

    set_windows_startup(startup_enabled)


def toggle_startup():

    global startup_enabled

    with state_lock:
        new_value = not startup_enabled

    if not set_windows_startup(new_value):
        try:
            win32gui.MessageBox(
                0,
                t("err_startup_toggle"),
                "YouTube Background Music",
                win32con.MB_ICONERROR | win32con.MB_OK
            )
        except Exception:
            pass
        return

    with state_lock:
        startup_enabled = new_value

    save_settings(startup_enabled=new_value)
    refresh_tray_menu()


# ============================================================
# Config Editor
# ============================================================

def _launch_detached(target_args):
    """
    通过 cmd /c start 中转启动，让新进程的父进程是已退出的 cmd，
    而不是 YBM。这样 taskkill /T 杀 YBM 进程树时不会连带杀掉它。
    """
    subprocess.Popen(
        ["cmd.exe", "/c", "start", ""] + target_args,
        cwd=BASE_DIR,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        close_fds=True,
    )


def open_config_editor():

    if os.path.isfile(CONFIG_EDITOR_EXE):
        try:
            _launch_detached([CONFIG_EDITOR_EXE])
            return True
        except Exception as e:
            pass

    if os.path.isfile(CONFIG_EDITOR_PY):
        try:
            _launch_detached([get_pythonw_path(), CONFIG_EDITOR_PY])
            return True
        except Exception as e:
            pass

    try:
        win32gui.MessageBox(
            0,
            t(
                "err_no_config_editor",
                exe=CONFIG_EDITOR_EXE,
                py=CONFIG_EDITOR_PY
            ),
            "YouTube Background Music",
            win32con.MB_ICONERROR | win32con.MB_OK
        )
    except Exception:
        pass

    return False


# ============================================================
# 本地音乐
# ============================================================

def scan_local_music():

    files = []
    seen = set()

    with state_lock:
        index = local_folder_index

    if index < 0 or index >= len(LOCAL_MUSIC_FOLDERS):
        return files

    folder = LOCAL_MUSIC_FOLDERS[index].get("folder", "")

    if not folder or not os.path.isdir(folder):
        return files

    try:
        for root, dirs, filenames in os.walk(folder):
            for filename in filenames:
                ext = os.path.splitext(filename)[1].lower()
                if ext not in LOCAL_AUDIO_EXTENSIONS:
                    continue

                full_path = os.path.abspath(os.path.join(root, filename))
                normalized = os.path.normcase(full_path)

                if normalized in seen:
                    continue

                seen.add(normalized)
                files.append(full_path)
    except Exception:
        return files

    files.sort(key=lambda p: p.lower())
    return files


def create_local_playlist():

    files = scan_local_music()

    if not files:
        return 0

    try:
        with open(local_playlist_file, "w", encoding="utf-8", newline="\n") as f:
            f.write("#EXTM3U\n")
            for path in files:
                f.write(path + "\n")
        return len(files)
    except Exception:
        return 0


# ============================================================
# 来源名称
# ============================================================

def get_current_source_name():

    with state_lock:
        current_source = source_type
        yt_index = youtube_playlist_index
        local_index = local_folder_index

    if current_source == SOURCE_LOCAL:
        if 0 <= local_index < len(LOCAL_MUSIC_FOLDERS):
            return t("source_local") + " / " + LOCAL_MUSIC_FOLDERS[local_index]["name"]
        return t("source_local")

    if current_source == SOURCE_YOUTUBE:
        if 0 <= yt_index < len(YOUTUBE_PLAYLISTS):
            return "YouTube / " + YOUTUBE_PLAYLISTS[yt_index]["name"]
        return "YouTube"

    return t("source_unknown")


# ============================================================
# 托盘刷新
# ============================================================

def refresh_tray_menu():

    try:
        if tray_icon is not None:
            tray_icon.update_menu()
    except Exception:
        pass


def set_music_paused(value):
    """
    统一修改 music_paused，并在状态真的发生变化时刷新托盘菜单。

    托盘菜单的文字（play_pause_text 等）是回调，pystray 只在
    update_menu() 时重新求值，不会在每次右键弹出时自动刷新。
    因此每一次 music_paused 变化都必须主动刷新，否则按钮文字
    会停留在旧快照上（例如开机时误判全屏暂停、随后自愈恢复播放，
    菜单却一直显示"播放 / 继续"）。

    注意：state_lock 是不可重入的 threading.Lock()，而菜单文字
    回调内部会获取 state_lock，所以 refresh_tray_menu() 必须在
    释放锁之后调用，绝不能放进 with state_lock 块里。
    """

    global music_paused

    with state_lock:
        if music_paused == value:
            return False
        music_paused = value

    refresh_tray_menu()
    return True


# ============================================================
# MPV IPC 基础
# ============================================================

def _mpv_pipe_open():

    try:
        return win32file.CreateFile(
            PIPE_NAME,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0,
            None,
            win32file.OPEN_EXISTING,
            0,
            None,
        )
    except Exception:
        return None


def mpv_is_running():

    with mpv_ipc_lock:
        handle = _mpv_pipe_open()
        if handle is None:
            return False

        try:
            win32file.CloseHandle(handle)
        except Exception:
            pass

        return True


def send_mpv_command(command_list):

    with mpv_ipc_lock:
        handle = _mpv_pipe_open()
        if handle is None:
            return False

        try:
            payload = (
                json.dumps({"command": command_list}) + "\n"
            ).encode("utf-8")

            win32file.WriteFile(handle, payload)
            return True

        except Exception:
            return False

        finally:
            try:
                win32file.CloseHandle(handle)
            except Exception:
                pass


def _get_next_mpv_request_id():

    global mpv_request_id_counter

    with mpv_request_id_lock:
        mpv_request_id_counter += 1
        if mpv_request_id_counter >= 0x7FFFFFFF:
            mpv_request_id_counter = 1
        return mpv_request_id_counter


def mpv_get_property(property_name, default=None, timeout=MPV_PROPERTY_TIMEOUT):

    with mpv_ipc_lock:
        handle = _mpv_pipe_open()
        if handle is None:
            return default

        request_id = _get_next_mpv_request_id()

        payload = (
            json.dumps({
                "command": ["get_property", property_name],
                "request_id": request_id,
            }) + "\n"
        ).encode("utf-8")

        try:
            win32file.WriteFile(handle, payload)
            deadline = time.monotonic() + timeout
            received = b""

            while time.monotonic() < deadline:
                try:
                    peek = win32pipe.PeekNamedPipe(handle, 0)
                    available = int(peek[1]) if peek else 0
                except Exception:
                    return default

                if available > 0:
                    try:
                        _, data = win32file.ReadFile(
                            handle,
                            min(available, 65536)
                        )
                    except Exception:
                        return default

                    if data:
                        received += data

                        while b"\n" in received:
                            line, received = received.split(b"\n", 1)
                            if not line.strip():
                                continue

                            try:
                                response = json.loads(
                                    line.decode("utf-8")
                                )
                            except Exception:
                                continue

                            if response.get("request_id") != request_id:
                                continue

                            if response.get("error") == "success":
                                return response.get("data", default)

                            return default

                time.sleep(0.01)

        except Exception:
            return default

        finally:
            try:
                win32file.CloseHandle(handle)
            except Exception:
                pass

    return default


# ============================================================
# 音量异步 worker
# ============================================================

def request_async_volume(volume):

    global pending_volume_request

    try:
        volume = float(volume)
    except Exception:
        return

    volume = max(MIN_VOLUME, min(MAX_VOLUME, volume))

    with volume_request_lock:
        pending_volume_request = volume

    volume_request_event.set()


def volume_command_worker():

    global pending_volume_request

    while running:
        volume_request_event.wait(0.5)
        volume_request_event.clear()

        while running:
            with volume_request_lock:
                volume = pending_volume_request
                pending_volume_request = None

            if volume is None:
                break

            send_mpv_command([
                "set_property",
                "volume",
                volume
            ])

            with volume_request_lock:
                newer_value_exists = pending_volume_request is not None

            if not newer_value_exists:
                break


# ============================================================
# 音量状态
# ============================================================

def update_volume_state_from_gui(volume):

    global current_volume

    try:
        volume = float(volume)
    except Exception:
        return

    volume = max(MIN_VOLUME, min(MAX_VOLUME, volume))

    with state_lock:
        current_volume = volume

    request_async_volume(volume)


# ============================================================
# 当前歌曲名称
# ============================================================

def normalize_song_title(title):

    if title is None:
        return ""

    try:
        title = str(title).strip()
    except Exception:
        return ""

    if not title:
        return ""

    if title.startswith("file://"):
        title = title[7:]

    with state_lock:
        current_source = source_type

    if current_source == SOURCE_LOCAL:
        path_value = title.replace("\\", "/")
        filename = os.path.basename(path_value)
        stem, _ = os.path.splitext(filename)
        return stem or filename

    lower = title.lower()

    # 过滤各种形式的链接，避免歌名还没解析出来时把 URL 显示到托盘上。
    if lower.startswith(("http://", "https://", "ytdl://", "www.")):
        return ""
    if "youtube.com/" in lower or "youtu.be/" in lower:
        return ""
    if lower.endswith((".m3u", ".m3u8")):
        return ""

    return title


def get_current_song_title():

    title = normalize_song_title(
        mpv_get_property(
            "media-title",
            None,
            TITLE_PROPERTY_TIMEOUT
        )
    )

    return title


def update_current_song_title():

    global current_song_title

    title = get_current_song_title()

    # 拿不到有效标题（包括被过滤掉的链接）时，统一显示"正在获取..."，
    # 不再保留旧标题，避免托盘里出现 URL 或上一首过期的歌名。
    new_title = title if title else t("fetching")

    with state_lock:
        if current_song_title == new_title:
            return False
        current_song_title = new_title

    refresh_tray_menu()
    return True


# ============================================================
# 淡出 / 淡入
# ============================================================

def _close_title_event_handle():

    global title_event_handle

    with title_event_handle_lock:
        handle = title_event_handle
        title_event_handle = None

    if handle is not None:
        try:
            win32file.CancelIoEx(handle)
        except Exception:
            pass
        try:
            win32file.CloseHandle(handle)
        except Exception:
            pass


def _open_title_event_pipe():

    global title_event_handle

    try:
        handle = win32file.CreateFile(
            PIPE_NAME,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0,
            None,
            win32file.OPEN_EXISTING,
            win32con.FILE_FLAG_OVERLAPPED,
            None,
        )
    except Exception:
        return None

    try:
        payload = (json.dumps({
            "command": ["observe_property", 1, "playlist-playing-pos"]
        }) + "\n").encode("utf-8")

        write_overlapped = pywintypes.OVERLAPPED()
        write_overlapped.hEvent = win32event.CreateEvent(None, True, False, None)
        try:
            win32file.WriteFile(handle, payload, write_overlapped)
            win32event.WaitForSingleObject(write_overlapped.hEvent, 2000)
        finally:
            win32api.CloseHandle(write_overlapped.hEvent)
    except Exception:
        try:
            win32file.CloseHandle(handle)
        except Exception:
            pass
        return None

    with title_event_handle_lock:
        title_event_handle = handle

    return handle


def _playlist_position_changed(old_position, new_position):

    if old_position is None:
        return False
    if new_position is None:
        return True

    try:
        return float(old_position) != float(new_position)
    except Exception:
        return old_position != new_position


def _title_event_source_is_switching():

    with state_lock:
        return source_switching


def song_title_event_monitor():

    global title_event_handle

    reconnect_delay = 0.5
    READ_WAIT_POLL_MS = 300

    while running and not title_event_stop.is_set():
        if _title_event_source_is_switching():
            title_event_stop.wait(0.1)
            continue

        handle = _open_title_event_pipe()
        if handle is None:
            title_event_stop.wait(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 1.5, 3.0)
            continue

        reconnect_delay = 0.5
        received = b""
        first_position_event = True
        last_position = None

        read_event = win32event.CreateEvent(None, True, False, None)
        overlapped = pywintypes.OVERLAPPED()
        overlapped.hEvent = read_event
        read_pending = False
        buf = None

        try:
            while running and not title_event_stop.is_set():

                if not read_pending:
                    buf = win32file.AllocateReadBuffer(65536)
                    win32event.ResetEvent(read_event)
                    win32file.ReadFile(handle, buf, overlapped)
                    read_pending = True

                wait_result = win32event.WaitForSingleObject(
                    read_event, READ_WAIT_POLL_MS
                )

                if wait_result == win32event.WAIT_TIMEOUT:
                    continue

                read_pending = False
                nbytes = win32file.GetOverlappedResult(handle, overlapped, False)

                if not nbytes:
                    break

                data = bytes(buf[:nbytes])
                received += data
                while b"\n" in received:
                    line, received = received.split(b"\n", 1)
                    if not line.strip():
                        continue

                    try:
                        message = json.loads(line.decode("utf-8"))
                    except Exception:
                        continue

                    if (
                        message.get("event") != "property-change"
                        or message.get("name") != "playlist-playing-pos"
                    ):
                        continue

                    position = message.get("data")
                    if first_position_event:
                        first_position_event = False
                        last_position = position

                        with state_lock:
                            title_needed = (
                                current_song_title in {
                                    "",
                                    t("fetching")
                                }
                            )

                        if (
                            title_needed
                            and not _title_event_source_is_switching()
                        ):
                            update_current_song_title()

                        continue

                    if not _playlist_position_changed(last_position, position):
                        continue

                    last_position = position
                    if not _title_event_source_is_switching():
                        update_current_song_title()

        except Exception:
            pass

        finally:
            with title_event_handle_lock:
                if title_event_handle is handle:
                    title_event_handle = None

            if read_pending:
                try:
                    win32file.CancelIoEx(handle)
                    win32event.WaitForSingleObject(read_event, 1000)
                except Exception:
                    pass

            try:
                win32file.CloseHandle(handle)
            except Exception:
                pass

            try:
                win32api.CloseHandle(read_event)
            except Exception:
                pass

        if running and not title_event_stop.is_set():
            title_event_stop.wait(reconnect_delay)


def cancel_audio_fade(restore_volume=False):

    global audio_fade_cancel_event

    with audio_fade_lock:
        event = audio_fade_cancel_event
        if event is not None:
            event.set()

    # 等淡出/淡入线程真正退出，避免它把音量又写回 0。
    # 最多等 0.5 秒，避免在极少数异常场景里卡住主线程。
    with audio_fade_lock:
        thread = audio_fade_thread

    if thread is not None and thread.is_alive():
        thread.join(timeout=0.5)

    if restore_volume:
        with state_lock:
            target_volume = current_volume
        request_async_volume(target_volume)


def _start_audio_fade_worker(fade_out, target_volume):

    global audio_fade_thread
    global audio_fade_cancel_event

    with audio_fade_lock:
        if audio_fade_thread is not None and audio_fade_thread.is_alive():
            return False

        cancel_event = threading.Event()
        audio_fade_cancel_event = cancel_event

        def worker():

            global audio_fade_thread
            global audio_fade_cancel_event

            try:
                if fade_out:
                    start_volume = target_volume
                    end_volume = 0.0
                    duration = AUDIO_FADE_OUT_SECONDS
                else:
                    start_volume = 0.0
                    end_volume = target_volume
                    duration = AUDIO_FADE_IN_SECONDS

                request_async_volume(start_volume)
                start_time = time.monotonic()

                while True:
                    if cancel_event.is_set():
                        return

                    elapsed = time.monotonic() - start_time
                    progress = 1.0 if duration <= 0 else min(1.0, elapsed / duration)

                    volume = (
                        start_volume
                        + (end_volume - start_volume) * progress
                    )

                    if cancel_event.is_set():
                        return

                    request_async_volume(volume)

                    if progress >= 1.0:
                        break

                    time.sleep(AUDIO_FADE_STEP_SECONDS)

                request_async_volume(end_volume)

                if fade_out:
                    mpv_pause()
                else:
                    with state_lock:
                        final_volume = current_volume
                    request_async_volume(final_volume)

            finally:
                with audio_fade_lock:
                    if audio_fade_cancel_event is cancel_event:
                        audio_fade_cancel_event = None
                    audio_fade_thread = None

        thread = threading.Thread(
            target=worker,
            daemon=True,
            name="YBM-AudioFade"
        )
        audio_fade_thread = thread
        thread.start()
        return True


def start_audio_fade_out():

    with state_lock:
        target_volume = current_volume

    return _start_audio_fade_worker(True, target_volume)


def start_audio_fade_in():

    with state_lock:
        target_volume = current_volume

    # 先尝试恢复播放。只有真正恢复成功后才把音量压到 0 做淡入，
    # 否则若 mpv_resume() 失败，音乐会卡在"暂停 + 音量 0"的状态。
    if not mpv_resume():
        request_async_volume(target_volume)
        return False

    request_async_volume(0.0)

    return _start_audio_fade_worker(False, target_volume)


# ============================================================
# MPV 状态
# ============================================================

def restore_mpv_runtime_state():

    global music_paused

    with state_lock:
        volume = current_volume
        loop_enabled = single_loop_enabled

    pipe_ok = False
    for attempt in range(6):
        if mpv_is_running():
            pipe_ok = True
            break
        time.sleep(0.2)

    if not pipe_ok:
        return False

    send_mpv_command(["set_property", "volume", volume])
    send_mpv_command([
        "set_property",
        "loop-file",
        "inf" if loop_enabled else "no"
    ])

    set_music_paused(False)

    return True


def reset_runtime_playback_state():

    global auto_audio_paused
    global auto_fullscreen_paused
    global fullscreen_paused_at
    global fullscreen_exited_at
    global manual_override_audio
    global last_audio_stop_time
    global last_other_audio_state
    global music_paused
    global current_song_title

    cancel_audio_fade(False)

    with state_lock:
        auto_audio_paused = False
        auto_fullscreen_paused = False
        fullscreen_paused_at = None
        fullscreen_exited_at = None
        manual_override_audio = False
        last_audio_stop_time = None
        last_other_audio_state = None
        music_paused = False
        current_song_title = t("fetching")

    # music_paused / current_song_title 都变了，必须在锁外刷新菜单文字。
    refresh_tray_menu()


def synchronize_after_source_switch():

    global auto_audio_paused
    global auto_fullscreen_paused
    global fullscreen_paused_at
    global last_other_audio_state

    if not restore_mpv_runtime_state():
        return False

    with state_lock:
        fullscreen_enabled = fullscreen_pause_enabled
        audio_enabled = audio_pause_enabled
        music_mode = music_mode_enabled

    if music_mode:
        return True

    now_fullscreen = is_foreground_fullscreen() if fullscreen_enabled else False

    if now_fullscreen:
        if mpv_pause():
            with state_lock:
                auto_fullscreen_paused = True
                fullscreen_paused_at = time.time()

    other_audio = other_app_is_playing_audio() if audio_enabled else False

    with state_lock:
        last_other_audio_state = other_audio

    if audio_enabled and other_audio and not now_fullscreen:
        with state_lock:
            auto_audio_paused = True
        start_audio_fade_out()

    return True


# ============================================================
# MPV 播放控制
# ============================================================

def _confirm_mpv_pause_property(expected, attempts=3, interval=MPV_PAUSE_VERIFY_SETTLE_SECONDS):
    """
    在 set_property pause 写入成功后，读回真实属性确认是否真的生效。
    重试几次是为了不让单次 IPC 读取的偶然抖动（管道繁忙、瞬时超时）
    被误判成"真的没生效"；如果连续几次都读不到期望值，才认为不生效。
    """
    actual = None
    for _ in range(attempts):
        time.sleep(interval)
        actual = mpv_get_property("pause", None)
        if actual is expected:
            return True, actual
    return False, actual


def mpv_pause():

    global music_paused

    if not send_mpv_command(["set_property", "pause", True]):
        return False

    # send_mpv_command() 只代表 IPC 管道写入成功，不代表 mpv 真的
    # 应用了这个属性（例如 mpv 刚启动、yt-dlp 还在解析/缓冲第一首歌时，
    # 这个 pause 请求可能在真正开始播放那一刻被悄悄覆盖）。
    # 读回真实属性确认后再更新本地状态，这样按钮显示的"暂停"
    # 永远对应 mpv 实际暂停了的情况。
    confirmed, actual = _confirm_mpv_pause_property(True)

    if not confirmed:
        return False

    set_music_paused(True)
    return True


def mpv_resume():

    global music_paused

    if not send_mpv_command(["set_property", "pause", False]):
        return False

    confirmed, actual = _confirm_mpv_pause_property(False)

    if not confirmed:
        return False

    set_music_paused(False)
    return True


def mpv_next():
    return send_mpv_command(["playlist-next"])


def mpv_previous():
    return send_mpv_command(["playlist-prev"])


def mpv_set_single_loop(enabled):

    global single_loop_enabled

    result = send_mpv_command([
        "set_property",
        "loop-file",
        "inf" if enabled else "no"
    ])

    if result:
        with state_lock:
            single_loop_enabled = enabled

    return result


def mpv_toggle_single_loop():

    with state_lock:
        enabled = single_loop_enabled

    return mpv_set_single_loop(not enabled)


def mpv_stop():
    return send_mpv_command(["quit"])


# ============================================================
# 全屏检测
# ============================================================

def get_foreground_process_name():

    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None

    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if not pid:
            return None

        handle = win32api.OpenProcess(
            win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ,
            False,
            pid
        )

        try:
            filename = win32process.GetModuleFileNameEx(handle, 0)
        finally:
            win32api.CloseHandle(handle)

        return os.path.basename(filename).lower()

    except Exception:
        return None


def is_foreground_fullscreen():

    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return False

    try:
        class_name = win32gui.GetClassName(hwnd)
    except Exception:
        return False

    if class_name in IGNORED_CLASSES:
        return False

    if get_foreground_process_name() in BROWSER_PROCESSES:
        return False

    try:
        if win32gui.IsIconic(hwnd):
            return False

        win_rect = win32gui.GetWindowRect(hwnd)
        monitor = win32api.MonitorFromWindow(
            hwnd,
            win32con.MONITOR_DEFAULTTONEAREST
        )
        monitor_info = win32api.GetMonitorInfo(monitor)
        monitor_rect = monitor_info["Monitor"]

    except Exception:
        return False

    win_left, win_top, win_right, win_bottom = win_rect
    mon_left, mon_top, mon_right, mon_bottom = monitor_rect
    tolerance = 10

    return (
        abs(win_left - mon_left) <= tolerance
        and abs(win_top - mon_top) <= tolerance
        and abs(win_right - mon_right) <= tolerance
        and abs(win_bottom - mon_bottom) <= tolerance
    )


# ============================================================
# 其他应用声音（跳过被静音 / 音量归零的会话）
# ============================================================

def other_app_is_playing_audio():

    try:
        sessions = AudioUtilities.GetAllSessions()
    except Exception as e:
        return False

    current_pid = None
    try:
        if started_proc is not None:
            current_pid = started_proc.pid
    except Exception:
        pass

    try:
        from pycaw.pycaw import IAudioMeterInformation
    except Exception as e:
        return False

    session_count = 0
    peak_hits = 0
    errors = 0

    for session in sessions:
        session_count += 1
        try:
            process = session.Process
            if process is None:
                continue

            pid = process.pid
            if current_pid is not None and pid == current_pid:
                continue

            process_name = ""
            try:
                process_name = process.name().lower()
            except Exception:
                pass

            if not process_name:
                continue

            try:
                simple_volume = session.SimpleAudioVolume
                if simple_volume is not None:
                    if simple_volume.GetMute():
                        continue
                    if simple_volume.GetMasterVolume() <= 0.0001:
                        continue
            except Exception:
                pass

            meter = session._ctl.QueryInterface(IAudioMeterInformation)
            peak = meter.GetPeakValue()
            if peak >= AUDIO_THRESHOLD:
                peak_hits += 1
                return True

        except Exception as e:
            errors += 1
            # 只记录前几次异常，避免日志被刷爆
            if errors <= 3:
                pass
            continue

    return False


# ============================================================
# MPV 启动
# ============================================================

def build_mpv_args():

    with state_lock:
        current_source = source_type
        playlist_index = youtube_playlist_index
        startup_volume = current_volume

    args = [
        MPV_PATH,
        "--no-video",
        "--force-window=no",
        "--audio-display=no",
        "--idle=yes",
        f"--input-ipc-server={PIPE_NAME}",
        "--loop-playlist=inf",
        "--shuffle",
        "--really-quiet",
        f"--volume={startup_volume}",
    ]

    if current_source == SOURCE_YOUTUBE:
        if not YTDLP_PATH:
            return None

        if not (0 <= playlist_index < len(YOUTUBE_PLAYLISTS)):
            return None

        playlist_url = YOUTUBE_PLAYLISTS[playlist_index]["url"]
        if not playlist_url:
            return None


        args.extend([
            "--ytdl-format=bestaudio/best",
            "--script-opts=ytdl_hook-ytdl_path=" + YTDLP_PATH,
            playlist_url,
        ])

    elif current_source == SOURCE_LOCAL:
        if create_local_playlist() <= 0:
            return None
        args.append(f"--playlist={local_playlist_file}")

    else:
        return None

    return args


def launch_mpv_if_needed():

    global started_proc
    global music_paused
    global mpv_started_at
    global current_song_title

    if (
        started_proc is not None
        and started_proc.poll() is None
        and mpv_is_running()
    ):
        return started_proc

    if started_proc is not None:
        try:
            if started_proc.poll() is not None:
                started_proc = None
        except Exception:
            started_proc = None

    args = build_mpv_args()
    if not args:
        return None

    try:
        started_proc = subprocess.Popen(
            args,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    except Exception as e:
        started_proc = None
        return None

    mpv_started_at = time.time()

    for _ in range(40):
        try:
            if started_proc is None or started_proc.poll() is not None:
                started_proc = None
                return None
        except Exception:
            started_proc = None
            return None

        if mpv_is_running():
            with state_lock:
                music_paused = False
                current_song_title = t("fetching")
                volume = current_volume
                loop_enabled = single_loop_enabled

            refresh_tray_menu()

            send_mpv_command(["set_property", "volume", volume])
            send_mpv_command([
                "set_property",
                "loop-file",
                "inf" if loop_enabled else "no"
            ])
            return started_proc

        time.sleep(0.25)


    try:
        if started_proc is not None and started_proc.poll() is None:
            started_proc.terminate()
    except Exception:
        pass

    started_proc = None
    return None


def stop_current_mpv():

    global started_proc
    global music_paused
    global mpv_started_at
    global current_song_title

    proc = started_proc

    if mpv_is_running():
        send_mpv_command(["quit"])

        for _ in range(30):
            if not mpv_is_running():
                break
            time.sleep(0.1)

    if proc is not None:
        try:
            if proc.poll() is None:
                proc.wait(timeout=2)
        except Exception:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=2)
                except Exception:
                    pass

        try:
            exit_code = proc.poll()
        except Exception:
            exit_code = None

        if exit_code is None:
            pass

    started_proc = None
    mpv_started_at = None

    with state_lock:
        music_paused = False
        current_song_title = t("fetching")

    refresh_tray_menu()


def restart_current_source():

    cancel_audio_fade(False)
    reset_runtime_playback_state()
    stop_current_mpv()

    proc = launch_mpv_if_needed()
    if proc is None:
        return False

    synchronize_after_source_switch()
    update_current_song_title()
    return mpv_is_running()


# ============================================================
# 来源切换
# ============================================================

def switch_to_source(new_source, new_playlist_index=None, new_local_index=None):

    global source_type
    global youtube_playlist_index
    global local_folder_index
    global source_switching

    if new_source not in {SOURCE_YOUTUBE, SOURCE_LOCAL}:
        return False

    if new_source == SOURCE_YOUTUBE:
        if not YOUTUBE_PLAYLISTS:
            return False

        if new_playlist_index is None:
            new_playlist_index = 0

        try:
            new_playlist_index = int(new_playlist_index)
        except Exception:
            new_playlist_index = 0

        new_playlist_index = max(
            0,
            min(len(YOUTUBE_PLAYLISTS) - 1, new_playlist_index)
        )

    else:
        if not LOCAL_MUSIC_FOLDERS:
            return False

        if new_local_index is None:
            new_local_index = 0

        try:
            new_local_index = int(new_local_index)
        except Exception:
            new_local_index = 0

        new_local_index = max(
            0,
            min(len(LOCAL_MUSIC_FOLDERS) - 1, new_local_index)
        )

    with state_lock:
        old_source = source_type
        old_youtube_index = youtube_playlist_index
        old_local_index = local_folder_index
        source_switching = True


    try:
        _close_title_event_handle()
        reset_runtime_playback_state()

        with state_lock:
            source_type = new_source
            if new_source == SOURCE_YOUTUBE:
                youtube_playlist_index = new_playlist_index
            else:
                local_folder_index = new_local_index

        stop_current_mpv()

        proc = launch_mpv_if_needed()
        if proc is None:

            with state_lock:
                source_type = old_source
                youtube_playlist_index = old_youtube_index
                local_folder_index = old_local_index

            reset_runtime_playback_state()
            old_proc = launch_mpv_if_needed()
            if old_proc is not None:
                synchronize_after_source_switch()
                update_current_song_title()

            save_source_settings()
            refresh_tray_menu()
            return False

        if not synchronize_after_source_switch():
            stop_current_mpv()

            with state_lock:
                source_type = old_source
                youtube_playlist_index = old_youtube_index
                local_folder_index = old_local_index

            reset_runtime_playback_state()
            old_proc = launch_mpv_if_needed()
            if old_proc is not None:
                synchronize_after_source_switch()
                update_current_song_title()

            save_source_settings()
            refresh_tray_menu()
            return False

        update_current_song_title()
        save_source_settings()
        refresh_tray_menu()
        return mpv_is_running()

    finally:
        with state_lock:
            source_switching = False
        refresh_tray_menu()


# ============================================================
# GUI：Donate / Volume
# ============================================================

def request_source_switch(new_source, new_playlist_index=None, new_local_index=None):

    if not source_switch_lock.acquire(blocking=False):
        return False

    def worker():
        try:
            switch_to_source(
                new_source,
                new_playlist_index=new_playlist_index,
                new_local_index=new_local_index,
            )
        finally:
            source_switch_lock.release()

    threading.Thread(
        target=worker,
        daemon=True,
        name="YBM-SourceSwitch"
    ).start()

    return True


def copy_donate_address(window, address, label_name, status_label):

    try:
        address = str(address)
        if not address:
            return

        window.clipboard_clear()
        window.clipboard_append(address)
        window.update()

        status_label.config(text=t("donate_copied", name=label_name))
        window.after(
            1500,
            lambda: (
                status_label.config(
                    text=t("donate_hint")
                )
                if window.winfo_exists()
                else None
            )
        )
    except Exception:
        try:
            status_label.config(text=t("donate_copy_failed"))
        except Exception:
            pass


def create_donate_window(root):

    global donate_window

    if donate_window is not None:
        try:
            if donate_window.winfo_exists():
                donate_window.deiconify()
                donate_window.lift()
                donate_window.focus_force()
                return
        except Exception:
            pass
        donate_window = None

    window = tk.Toplevel(root)
    donate_window = window

    window.title(t("donate_window_title"))
    window.resizable(False, False)
    window.attributes("-topmost", True)

    outer = ttk.Frame(window, padding=15)
    outer.pack(fill="both", expand=True)

    ttk.Label(
        outer,
        text=t("donate_heading")
    ).pack(pady=(0, 12))

    ttk.Label(
        outer,
        text=t("donate_message"),
        justify="left"
    ).pack(anchor="w", fill="x")

    address_frame = ttk.Frame(outer)
    address_frame.pack(fill="x", pady=(15, 0))
    address_frame.columnconfigure(1, weight=1)

    valid_addresses = []
    for item in DONATE_ADDRESSES:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        address = str(item.get("address", ""))
        if name:
            valid_addresses.append((name, address))

    for row, (name, address) in enumerate(valid_addresses):
        ttk.Label(
            address_frame,
            text=f"{name}:"
        ).grid(
            row=row,
            column=0,
            sticky="w",
            padx=(0, 8),
            pady=(0, 8)
        )

        variable = tk.StringVar(master=window, value=address)
        entry = ttk.Entry(
            address_frame,
            textvariable=variable,
            width=45,
            state="readonly"
        )
        # 必须保留 StringVar 的引用：循环下一轮会覆盖 variable，
        # 旧对象被回收后 Tk 变量会被销毁，对应输入框就显示为空。
        entry._ybm_var = variable
        entry.grid(
            row=row,
            column=1,
            sticky="ew",
            pady=(0, 8)
        )

        ttk.Button(
            address_frame,
            text=t("donate_copy"),
            command=lambda
                addr=address,
                label_name=name:
                copy_donate_address(
                    window,
                    addr,
                    label_name,
                    status_label
                )
        ).grid(
            row=row,
            column=2,
            padx=(8, 0),
            pady=(0, 8)
        )

    if not valid_addresses:
        ttk.Label(
            address_frame,
            text=t("donate_no_addresses")
        ).grid(row=0, column=0, columnspan=3, sticky="w")

    ttk.Label(
        outer,
        text=t("donate_thanks")
    ).pack(anchor="w", pady=(7, 0))

    button_frame = ttk.Frame(outer)
    button_frame.pack(fill="x", pady=(15, 0))

    status_label = ttk.Label(
        button_frame,
        text=t("donate_hint")
    )
    status_label.pack(side="left")

    def close_donate():
        global donate_window
        try:
            window.destroy()
        except Exception:
            pass
        donate_window = None

    ttk.Button(
        button_frame,
        text=t("donate_close"),
        command=close_donate
    ).pack(side="right")

    window.protocol("WM_DELETE_WINDOW", close_donate)

    window.update_idletasks()
    window.geometry(
        f"+{max(0, window.winfo_screenwidth() // 2 - window.winfo_width() // 2)}"
        f"+{max(0, window.winfo_screenheight() // 2 - window.winfo_height() // 2)}"
    )

    window.deiconify()
    window.lift()
    window.focus_force()


def schedule_volume_save(root, delay=500):

    global volume_save_after_id

    if volume_save_after_id is not None:
        try:
            root.after_cancel(volume_save_after_id)
        except Exception:
            pass

    volume_save_after_id = root.after(delay, save_volume)


def schedule_volume_menu_refresh(root):

    global volume_refresh_after_id

    if volume_refresh_after_id is not None:
        try:
            root.after_cancel(volume_refresh_after_id)
        except Exception:
            pass

    volume_refresh_after_id = root.after(150, refresh_tray_menu)


_wheel_user32 = None
_wheel_HOOKPROC = None
_wheel_MSLLHOOKSTRUCT = None
_wheel_types_ready = False


def _init_wheel_types():

    global _wheel_user32
    global _wheel_HOOKPROC
    global _wheel_MSLLHOOKSTRUCT
    global _wheel_types_ready

    if _wheel_types_ready:
        return True

    try:
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)

        class MSLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("pt", wintypes.POINT),
                ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t),
            ]

        HOOKPROC = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            ctypes.c_int,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        )

        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int,
            HOOKPROC,
            ctypes.c_void_p,
            ctypes.c_uint,
        ]
        user32.UnhookWindowsHookEx.restype = ctypes.c_bool
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.CallNextHookEx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        ]

        _wheel_user32 = user32
        _wheel_HOOKPROC = HOOKPROC
        _wheel_MSLLHOOKSTRUCT = MSLLHOOKSTRUCT
        _wheel_types_ready = True
        return True

    except Exception:
        return False


def _install_volume_wheel_hook():

    global volume_wheel_hook
    global volume_wheel_hook_proc

    if volume_wheel_hook is not None:
        return True

    if not _init_wheel_types():
        return False

    user32 = _wheel_user32
    HOOKPROC = _wheel_HOOKPROC
    MSLLHOOKSTRUCT = _wheel_MSLLHOOKSTRUCT

    WH_MOUSE_LL = 14
    WM_MOUSEWHEEL = 0x020A

    def _proc(nCode, wParam, lParam):
        if nCode >= 0 and wParam == WM_MOUSEWHEEL:
            try:
                info = ctypes.cast(
                    ctypes.c_void_p(lParam),
                    ctypes.POINTER(MSLLHOOKSTRUCT)
                ).contents
                raw = (info.mouseData >> 16) & 0xFFFF
                delta = ctypes.c_short(raw).value
                if delta:
                    try:
                        # 钩子回调里只做一件事：入队。
                        # 真正的 Tk 操作放到 Tk 事件循环里的轮询处理。
                        volume_wheel_delta_queue.put_nowait(delta)
                    except Exception:
                        pass
            except Exception:
                pass
            return 1

        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    cb = HOOKPROC(_proc)
    handle = user32.SetWindowsHookExW(WH_MOUSE_LL, cb, None, 0)

    if not handle:
        return False

    volume_wheel_hook = handle
    volume_wheel_hook_proc = cb
    return True


def _uninstall_volume_wheel_hook():

    global volume_wheel_hook
    global volume_wheel_hook_proc

    handle = volume_wheel_hook
    if handle is None:
        return

    # 先卸载钩子，再释放回调引用。
    # 顺序反了的话，如果此时系统还在调用 proc，就会崩。
    try:
        _wheel_user32.UnhookWindowsHookEx(handle)
    except Exception:
        pass

    volume_wheel_hook = None
    volume_wheel_hook_proc = None


def create_volume_window(root):

    global volume_window

    if volume_window is not None:
        try:
            if volume_window.winfo_exists():
                volume_window.deiconify()
                volume_window.lift()
                volume_window.focus_force()
                return
        except Exception:
            pass
        volume_window = None

    window = tk.Toplevel(root)
    volume_window = window

    window.overrideredirect(True)
    window.attributes("-topmost", True)

    with state_lock:
        initial_volume = current_volume

    frame = tk.Frame(
        window,
        padx=18,
        pady=15,
        relief=tk.RAISED,
        borderwidth=1
    )
    frame.pack()

    tk.Label(frame, text=t("volume_label")).pack(pady=(0, 5))

    value_label = tk.Label(
        frame,
        text=f"{initial_volume:.0f}%"
    )
    value_label.pack(pady=(0, 5))

    drag_data = {
        "mouse_x": 0,
        "mouse_y": 0,
        "window_x": 0,
        "window_y": 0,
    }

    def start_drag(event):
        drag_data["mouse_x"] = event.x_root
        drag_data["mouse_y"] = event.y_root
        drag_data["window_x"] = window.winfo_x()
        drag_data["window_y"] = window.winfo_y()

    def drag_window(event):
        dx = event.x_root - drag_data["mouse_x"]
        dy = event.y_root - drag_data["mouse_y"]
        window.geometry(
            f"+{drag_data['window_x'] + dx}+{drag_data['window_y'] + dy}"
        )

    def on_volume_change(value):
        try:
            volume = float(value)
        except Exception:
            return

        volume = max(MIN_VOLUME, min(MAX_VOLUME, volume))
        try:
            value_label.config(text=f"{volume:.0f}%")
        except Exception:
            pass
        update_volume_state_from_gui(volume)
        schedule_volume_save(root)
        schedule_volume_menu_refresh(root)

    scale = tk.Scale(
        frame,
        from_=MAX_VOLUME,
        to=MIN_VOLUME,
        orient=tk.VERTICAL,
        length=220,
        resolution=1,
        showvalue=False,
        command=on_volume_change
    )
    scale.set(initial_volume)
    scale.pack(pady=(0, 5))

    position_volume_window(window)

    for widget in (frame, value_label):
        widget.bind("<Button-1>", start_drag)
        widget.bind("<B1-Motion>", drag_window)

    closing = False

    def close_volume(event=None):
        nonlocal closing
        global volume_window

        if closing:
            return

        closing = True

        save_volume_window_position(window)
        save_volume()

        _uninstall_volume_wheel_hook()

        # 清空队列里还没被消费的滚轮事件，避免残留到下一次打开。
        try:
            while True:
                volume_wheel_delta_queue.get_nowait()
        except queue.Empty:
            pass
        except Exception:
            pass

        try:
            window.destroy()
        except Exception:
            pass

        volume_window = None

    def on_focus_out(event):
        close_volume()

    # 轮询：在纯 Tk 上下文里消费滚轮队列，避免钩子回调里直接操作 Tk。
    def poll_wheel():
        try:
            if not window.winfo_exists():
                return

            total = 0
            got = False
            while True:
                try:
                    total += volume_wheel_delta_queue.get_nowait()
                    got = True
                except queue.Empty:
                    break

            if got and total != 0:
                steps = int(total / 120.0)
                if steps == 0:
                    steps = 1 if total > 0 else -1

                try:
                    current = float(scale.get())
                except Exception:
                    current = None

                if current is not None:
                    current += 2 * steps
                    current = max(MIN_VOLUME, min(MAX_VOLUME, current))
                    try:
                        scale.set(current)
                        # set() 只在值变化时触发 command，保险起见显式再调一次。
                        on_volume_change(current)
                    except Exception:
                        pass

        except Exception:
            pass

        # 窗口还活着就继续轮询
        try:
            if volume_window is window and window.winfo_exists():
                window.after(40, poll_wheel)
        except Exception:
            pass

    window.bind("<FocusOut>", on_focus_out)
    window.protocol("WM_DELETE_WINDOW", close_volume)

    window.update_idletasks()
    window.deiconify()
    window.lift()
    window.focus_force()

    # 安装全局滚轮钩子，然后开始 Tk 侧的轮询消费。
    _install_volume_wheel_hook()
    window.after(40, poll_wheel)


def process_gui_commands(root):

    global donate_window
    global volume_window

    try:
        while True:
            command = gui_command_queue.get_nowait()

            if command == "donate":
                create_donate_window(root)

            elif command == "volume":
                create_volume_window(root)

            elif command == "shutdown":
                if donate_window is not None:
                    try:
                        donate_window.destroy()
                    except Exception:
                        pass
                    donate_window = None

                if volume_window is not None:
                    try:
                        volume_window.destroy()
                    except Exception:
                        pass
                    volume_window = None

                _uninstall_volume_wheel_hook()

                try:
                    while True:
                        volume_wheel_delta_queue.get_nowait()
                except queue.Empty:
                    pass
                except Exception:
                    pass

                try:
                    root.destroy()
                except Exception:
                    pass
                return

    except queue.Empty:
        pass

    if not running:
        try:
            root.destroy()
        except Exception:
            pass
        return

    try:
        root.after(20, lambda: process_gui_commands(root))
    except Exception:
        pass


def apply_gui_fonts():

    """
    Tk 默认字体（Segoe UI）没有中文字形，中文会回退到很丑的宋体。
    中文界面统一换成微软雅黑 UI（其拉丁字母与 Segoe UI 风格一致），
    这样中英文看起来一样；英文界面保持 Segoe UI。
    """

    family = "Microsoft YaHei UI" if _current_lang == "zh" else "Segoe UI"

    try:
        available = set(tkfont.families())
        if family not in available:
            family = "Microsoft YaHei" if "Microsoft YaHei" in available else family
    except Exception:
        pass

    for name in (
        "TkDefaultFont",
        "TkTextFont",
        "TkMenuFont",
        "TkHeadingFont",
        "TkCaptionFont",
        "TkSmallCaptionFont",
        "TkIconFont",
        "TkTooltipFont",
    ):
        try:
            tkfont.nametofont(name).configure(family=family, size=10)
        except Exception:
            pass


def gui_worker():

    global gui_root

    try:
        root = tk.Tk()
        gui_root = root
        root.withdraw()
        root.title("YouTube Background Music")
        apply_gui_fonts()

        gui_ready.set()

        root.after(20, lambda: process_gui_commands(root))
        root.mainloop()

    except Exception:
        gui_ready.set()

    finally:
        gui_root = None


def start_gui_thread():

    global gui_thread

    if gui_thread is not None and gui_thread.is_alive():
        return

    gui_ready.clear()

    gui_thread = threading.Thread(
        target=gui_worker,
        daemon=True,
        name="YBM-TkGUI"
    )
    gui_thread.start()


def open_donate_window():
    try:
        gui_command_queue.put("donate")
    except Exception:
        pass


def open_volume_window():
    try:
        gui_command_queue.put("volume")
    except Exception:
        pass


# ============================================================
# 托盘图标图片
# ============================================================

def create_tray_image():

    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    draw.ellipse((4, 4, 60, 60), fill=(40, 40, 40, 255))
    draw.line((35, 16, 35, 43), fill=(255, 255, 255, 255), width=6)
    draw.line((35, 16, 49, 12), fill=(255, 255, 255, 255), width=6)
    draw.ellipse((21, 37, 36, 51), fill=(255, 255, 255, 255))
    draw.ellipse((36, 31, 51, 45), fill=(255, 255, 255, 255))

    return image


def load_tray_icon():
    """从 icon.ico 加载托盘图标，失败时回退到默认图案。"""
    try:
        path = _get_resource_path("icon.ico")
        if os.path.isfile(path):
            return Image.open(path)
    except Exception:
        pass
    # 回退
    return create_tray_image()


# ============================================================
# 托盘回调：基本播放控制
# ============================================================

def tray_toggle_play(icon, item):

    global manual_override_audio
    global audio_pause_enabled

    with state_lock:
        paused = music_paused
        mm = music_mode_enabled

    if paused:
        cancel_audio_fade(True)

        # 音乐模式期间不要动 audio_pause_enabled，也不要写盘，
        # 避免把音乐模式强制的 False 持久化到 settings.json。
        if not mm and other_app_is_playing_audio():
            with state_lock:
                audio_pause_enabled = False
                manual_override_audio = True

            save_settings(audio_pause_enabled=False)
            refresh_tray_menu()
        else:
            with state_lock:
                manual_override_audio = False

        mpv_resume()

        with state_lock:
            volume = current_volume
        request_async_volume(volume)

    else:
        cancel_audio_fade(False)
        mpv_pause()


def tray_previous(icon, item):
    cancel_audio_fade(True)
    mpv_previous()


def tray_next(icon, item):
    cancel_audio_fade(True)
    mpv_next()


def tray_toggle_single_loop(icon, item):
    mpv_toggle_single_loop()


def tray_open_volume(icon, item):
    open_volume_window()


# ============================================================
# 托盘回调：音乐模式
# ============================================================

def tray_toggle_music_mode(icon, item):

    global music_mode_enabled
    global saved_fullscreen_pause_enabled
    global saved_audio_pause_enabled
    global fullscreen_pause_enabled
    global audio_pause_enabled
    global auto_fullscreen_paused
    global auto_audio_paused
    global fullscreen_paused_at
    global fullscreen_exited_at
    global last_other_audio_state
    global manual_override_audio

    with state_lock:
        new_value = not music_mode_enabled
        music_mode_enabled = new_value

        if new_value:
            # 进入音乐模式：保存当前开关状态并强制关闭
            saved_fullscreen_pause_enabled = fullscreen_pause_enabled
            saved_audio_pause_enabled = audio_pause_enabled

            fullscreen_pause_enabled = False
            audio_pause_enabled = False

            auto_fullscreen_paused = False
            auto_audio_paused = False
            fullscreen_paused_at = None
            fullscreen_exited_at = None
            last_other_audio_state = None
            manual_override_audio = False

            paused_snapshot = music_paused
            volume_snapshot = current_volume
        else:
            # 退出音乐模式：恢复原开关
            fullscreen_pause_enabled = saved_fullscreen_pause_enabled
            audio_pause_enabled = saved_audio_pause_enabled
            manual_override_audio = False

            paused_snapshot = False
            volume_snapshot = 0.0

    if new_value:
        cancel_audio_fade(True)
        request_async_volume(volume_snapshot)

        if paused_snapshot:
            mpv_resume()

    refresh_tray_menu()


# ============================================================
# 托盘回调：全屏暂停 / 其他声音暂停
# ============================================================

def tray_toggle_fullscreen_pause(icon, item):

    global fullscreen_pause_enabled
    global auto_fullscreen_paused
    global fullscreen_paused_at
    global fullscreen_exited_at
    global auto_audio_paused
    global last_other_audio_state
    global last_audio_stop_time

    with state_lock:
        if music_mode_enabled:
            return

        fullscreen_pause_enabled = not fullscreen_pause_enabled
        enabled = fullscreen_pause_enabled

        was_auto_paused = auto_fullscreen_paused

        auto_fullscreen_paused = False
        fullscreen_paused_at = None
        fullscreen_exited_at = None

        audio_enabled = audio_pause_enabled

    if not enabled and was_auto_paused:

        take_over = False
        if audio_enabled:
            try:
                take_over = other_app_is_playing_audio()
            except Exception:
                take_over = False

        if take_over:
            # 交接给音频自动暂停：保持暂停，音量保持 0。
            with state_lock:
                auto_audio_paused = True
                last_other_audio_state = True
                last_audio_stop_time = None
            request_async_volume(0.0)
        else:
            # 使用淡入恢复
            cancel_audio_fade(False)
            if not start_audio_fade_in():
                with state_lock:
                    volume = current_volume
                request_async_volume(volume)

    save_settings(fullscreen_pause_enabled=enabled)
    refresh_tray_menu()


def tray_toggle_audio_pause(icon, item):

    global audio_pause_enabled
    global manual_override_audio
    global auto_audio_paused
    global auto_fullscreen_paused
    global fullscreen_paused_at
    global fullscreen_exited_at

    with state_lock:
        if music_mode_enabled:
            return

        audio_pause_enabled = not audio_pause_enabled
        enabled = audio_pause_enabled

        if enabled:
            manual_override_audio = False

        # 记录是否真的是它在自动暂停
        was_auto_paused = auto_audio_paused

        # 无条件清掉自动暂停标志
        auto_audio_paused = False

        fs_enabled = fullscreen_pause_enabled

    # 关掉它 + 之前确实是它触发的暂停 → 决定交给谁
    if not enabled and was_auto_paused:
        if fs_enabled and is_foreground_fullscreen():
            # 交接给全屏自动暂停：保持暂停，音量保持 0。
            with state_lock:
                auto_fullscreen_paused = True
                fullscreen_paused_at = time.time()
                fullscreen_exited_at = None
            request_async_volume(0.0)
        else:
            # 使用淡入恢复
            cancel_audio_fade(False)
            if not start_audio_fade_in():
                with state_lock:
                    volume = current_volume
                request_async_volume(volume)

    save_settings(audio_pause_enabled=enabled)
    refresh_tray_menu()


# ============================================================
# 托盘回调：开机自启 / 设置 / Donate / 退出
# ============================================================

def tray_toggle_startup(icon, item):
    toggle_startup()


def tray_open_settings(icon, item):
    open_config_editor()


def tray_open_donate(icon, item):
    open_donate_window()


def tray_exit(icon, item):

    global running

    running = False

    title_event_stop.set()
    _close_title_event_handle()

    cancel_audio_fade(False)
    save_volume()
    save_source_settings()

    try:
        volume_request_event.set()
        gui_command_queue.put("shutdown")
    except Exception:
        pass

    if mpv_is_running():
        mpv_stop()

    try:
        icon.stop()
    except Exception:
        pass


# ============================================================
# 托盘菜单文本
# ============================================================

def startup_menu_text(item):
    with state_lock:
        enabled = startup_enabled
    return t("menu_startup_on") if enabled else t("menu_startup_off")


def song_title_menu_text(item):
    with state_lock:
        title = current_song_title or t("fetching")
    return "🎵 " + title


def play_pause_text(item):
    with state_lock:
        paused = music_paused
    return t("menu_play") if paused else t("menu_pause")


def previous_text(item):
    return t("menu_previous")


def next_text(item):
    return t("menu_next")


def single_loop_menu_text(item):
    with state_lock:
        enabled = single_loop_enabled
    return t("menu_loop_on") if enabled else t("menu_loop_off")


def volume_menu_text(item):
    with state_lock:
        volume = current_volume
    return t("menu_volume", volume=f"{volume:.0f}")


def music_mode_menu_text(item):
    with state_lock:
        enabled = music_mode_enabled
    if enabled:
        return t("menu_music_mode_on")
    return t("menu_music_mode_off")


def fullscreen_menu_text(item):
    with state_lock:
        enabled = fullscreen_pause_enabled
        mm = music_mode_enabled

    prefix = t("menu_fullscreen_prefix")
    if mm:
        return prefix + t("state_disabled_music_mode")
    return prefix + (t("state_on") if enabled else t("state_off"))


def audio_menu_text(item):
    with state_lock:
        enabled = audio_pause_enabled
        mm = music_mode_enabled

    prefix = t("menu_audio_prefix")
    if mm:
        return prefix + t("state_disabled_music_mode")
    return prefix + (t("state_on") if enabled else t("state_off"))


def source_menu_text(item):
    return t("menu_source_prefix") + get_current_source_name()


# ============================================================
# 恢复延迟子菜单
# ============================================================

def _delay_label(seconds):

    seconds = float(seconds)
    if seconds <= 0:
        return t("delay_instant")
    n = int(seconds) if seconds == int(seconds) else seconds
    return t("delay_seconds", n=n)


def fullscreen_delay_menu_text(item):
    with state_lock:
        value = fullscreen_resume_delay
    return t("menu_fs_delay", n=_delay_label(value))


def audio_delay_menu_text(item):
    with state_lock:
        value = audio_resume_delay
    return t("menu_audio_delay", n=_delay_label(value))


def _make_delay_text(kind, seconds):

    def text(item):
        with state_lock:
            current = (
                fullscreen_resume_delay if kind == "fullscreen"
                else audio_resume_delay
            )
        label = _delay_label(seconds)
        return ("✓ " + label) if abs(current - seconds) < 0.001 else label

    return text


def _make_delay_callback(kind, seconds):

    def callback(icon, item):
        global fullscreen_resume_delay
        global audio_resume_delay

        with state_lock:
            if kind == "fullscreen":
                fullscreen_resume_delay = float(seconds)
            else:
                audio_resume_delay = float(seconds)

        if kind == "fullscreen":
            save_settings(fullscreen_resume_delay=float(seconds))
        else:
            save_settings(audio_resume_delay=float(seconds))

        refresh_tray_menu()

    return callback


def _build_delay_menu(kind):

    return pystray.Menu(*[
        pystray.MenuItem(
            _make_delay_text(kind, s),
            _make_delay_callback(kind, s)
        )
        for s in RESUME_DELAY_OPTIONS
    ])


def build_resume_delay_menu():

    return pystray.Menu(
        pystray.MenuItem(
            fullscreen_delay_menu_text,
            _build_delay_menu("fullscreen")
        ),
        pystray.MenuItem(
            audio_delay_menu_text,
            _build_delay_menu("audio")
        ),
    )


def _music_mode_off(item):
    with state_lock:
        return not music_mode_enabled


# ============================================================
# 来源子菜单
# ============================================================

def make_youtube_playlist_callback(index):

    def callback(icon, item):
        request_source_switch(
            SOURCE_YOUTUBE,
            new_playlist_index=index
        )

    return callback


def youtube_playlist_text(index):

    with state_lock:
        current_source = source_type
        current_index = youtube_playlist_index

    name = YOUTUBE_PLAYLISTS[index]["name"]
    return f"✓ {name}" if current_source == SOURCE_YOUTUBE and current_index == index else name


def build_youtube_menu():

    items = []

    for index in range(len(YOUTUBE_PLAYLISTS)):
        items.append(
            pystray.MenuItem(
                lambda item, i=index: youtube_playlist_text(i),
                make_youtube_playlist_callback(index)
            )
        )

    if not items:
        items.append(
            pystray.MenuItem(
                t("menu_no_playlists"),
                lambda icon, item: None,
                enabled=False
            )
        )

    return pystray.Menu(*items)


def make_local_folder_callback(index):

    def callback(icon, item):
        request_source_switch(
            SOURCE_LOCAL,
            new_local_index=index
        )

    return callback


def local_folder_text(index):

    with state_lock:
        current_source = source_type
        current_index = local_folder_index

    name = LOCAL_MUSIC_FOLDERS[index]["name"]
    return f"✓ {name}" if current_source == SOURCE_LOCAL and current_index == index else name


def build_local_menu():

    items = []

    for index in range(len(LOCAL_MUSIC_FOLDERS)):
        items.append(
            pystray.MenuItem(
                lambda item, i=index: local_folder_text(i),
                make_local_folder_callback(index)
            )
        )

    if not items:
        items.append(
            pystray.MenuItem(
                t("menu_no_folders"),
                lambda icon, item: None,
                enabled=False
            )
        )

    return pystray.Menu(*items)


def youtube_source_text(item):
    with state_lock:
        current_source = source_type
    return "✓ YouTube" if current_source == SOURCE_YOUTUBE else "YouTube"


def local_source_text(item):
    with state_lock:
        current_source = source_type
    local_name = t("source_local_short")
    return "✓ " + local_name if current_source == SOURCE_LOCAL else local_name


def build_source_menu():
    return pystray.Menu(
        pystray.MenuItem(youtube_source_text, build_youtube_menu()),
        pystray.MenuItem(local_source_text, build_local_menu()),
    )


# ============================================================
# 托盘构建
# ============================================================

def create_tray():

    global tray_icon

    menu = pystray.Menu(
        pystray.MenuItem(
            song_title_menu_text,
            lambda icon, item: None,
            enabled=False
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(play_pause_text, tray_toggle_play),
        pystray.MenuItem(previous_text, tray_previous),
        pystray.MenuItem(next_text, tray_next),
        pystray.MenuItem(single_loop_menu_text, tray_toggle_single_loop),
        pystray.MenuItem(volume_menu_text, tray_open_volume),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(source_menu_text, build_source_menu()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            music_mode_menu_text,
            tray_toggle_music_mode
        ),
        pystray.MenuItem(
            fullscreen_menu_text,
            tray_toggle_fullscreen_pause,
            enabled=_music_mode_off
        ),
        pystray.MenuItem(
            audio_menu_text,
            tray_toggle_audio_pause,
            enabled=_music_mode_off
        ),
        pystray.MenuItem(
            t("menu_resume_delay"),
            build_resume_delay_menu()
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(startup_menu_text, tray_toggle_startup),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(t("menu_settings"), tray_open_settings),
        pystray.MenuItem(t("menu_donate"), tray_open_donate),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(t("menu_exit"), tray_exit),
    )

    tray_icon = pystray.Icon(
        "YouTube Background Music",
        load_tray_icon(),
        "YouTube Background Music",
        menu
    )

    return tray_icon


# ============================================================
# 全屏监视（退出全屏后延迟 5 秒才恢复）
# ============================================================

def fullscreen_monitor():

    global auto_fullscreen_paused
    global fullscreen_paused_at
    global fullscreen_exited_at
    global auto_audio_paused
    global last_other_audio_state
    global last_audio_stop_time

    while running:
        try:
            with state_lock:
                enabled = fullscreen_pause_enabled
                switching = source_switching
                auto_paused = auto_fullscreen_paused
                music_mode = music_mode_enabled
                audio_auto_paused = auto_audio_paused

            # 音乐模式 / 切换来源 / 功能关闭 → 不干预
            if switching or music_mode or not enabled:
                fullscreen_exited_at = None
                time.sleep(POLL_SECONDS)
                continue

            # 有其他声音自动暂停已经接管 → 本功能完全离线
            if audio_auto_paused:
                fullscreen_exited_at = None
                time.sleep(POLL_SECONDS)
                continue

            now_fullscreen = is_foreground_fullscreen()

            if now_fullscreen:
                # 回到全屏 → 重置"退出全屏"计时器
                fullscreen_exited_at = None

                if not auto_paused:
                    # 与 audio_monitor 一样：锁内重读，避免两者互设标志。
                    should_trigger_pause = False
                    with state_lock:
                        if (
                            not music_paused
                            and not auto_fullscreen_paused
                            and not auto_audio_paused
                        ):
                            fullscreen_paused_at = time.time()
                            auto_fullscreen_paused = True
                            should_trigger_pause = True

                    if should_trigger_pause:
                        start_audio_fade_out()

            else:
                if auto_paused:
                    if fullscreen_exited_at is None:
                        fullscreen_exited_at = time.time()

                    # 退出全屏后必须等待用户设定的秒数
                    with state_lock:
                        resume_delay = fullscreen_resume_delay
                    if time.time() - fullscreen_exited_at >= resume_delay:
                        paused_duration = (
                            time.time() - (fullscreen_paused_at or time.time())
                        )

                        # 关键：在恢复前检查"有其他声音自动暂停"是否应该接管。
                        with state_lock:
                            audio_enabled = audio_pause_enabled
                            mm = music_mode_enabled

                        take_over_by_audio = False
                        if audio_enabled and not mm:
                            try:
                                take_over_by_audio = other_app_is_playing_audio()
                            except Exception:
                                take_over_by_audio = False

                        if take_over_by_audio:
                            # 交接给"有其他声音自动暂停"：保持暂停，音量保持 0。
                            with state_lock:
                                auto_fullscreen_paused = False
                                auto_audio_paused = True
                                last_other_audio_state = True
                                last_audio_stop_time = None

                            fullscreen_paused_at = None
                            fullscreen_exited_at = None
                            request_async_volume(0.0)

                        else:
                            with state_lock:
                                auto_fullscreen_paused = False
                                volume = current_volume

                            fullscreen_paused_at = None
                            fullscreen_exited_at = None

                            if paused_duration >= THRESHOLD_MINUTES * 60:
                                mpv_next()

                            # 使用淡入（与有其他声音自动暂停一致）
                            with audio_fade_lock:
                                fade_running = (
                                    audio_fade_thread is not None
                                    and audio_fade_thread.is_alive()
                                )

                            if not fade_running:
                                if not start_audio_fade_in():
                                    request_async_volume(volume)

        except Exception:
            pass

        time.sleep(POLL_SECONDS)


# ============================================================
# 其他声音监视（修复反复暂停后失效）
# ============================================================

def audio_monitor():

    global auto_audio_paused
    global manual_override_audio
    global last_audio_stop_time
    global last_other_audio_state
    global auto_fullscreen_paused
    global fullscreen_paused_at
    global fullscreen_exited_at

    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pythoncom = None

    # 诊断用：记录上一次日志时的状态，用于节流
    last_log_state = None
    last_log_time = 0.0

    # 自检用
    desync_audio_paused_since = None     # auto_audio_paused=True 而 music_paused=False 的起始时间
    orphan_paused_since = None           # music_paused=True 而两个 auto_* 都 False 的起始时间

    DESYNC_RESET_SECONDS = 2.0
    ORPHAN_RESET_SECONDS = 5.0

    try:
        # ---- 启动时的第一次检查 ----
        try:
            with state_lock:
                enabled = audio_pause_enabled
                override = manual_override_audio
                currently_paused = music_paused
                switching = source_switching
                music_mode = music_mode_enabled
                fullscreen_auto_paused = auto_fullscreen_paused

            if (
                enabled and not override and not switching
                and not music_mode and not fullscreen_auto_paused
            ):
                other_audio = other_app_is_playing_audio()
                with state_lock:
                    last_other_audio_state = other_audio

                if other_audio and not currently_paused:
                    with state_lock:
                        auto_audio_paused = True
                    start_audio_fade_out()
        except Exception:
            pass

        # ---- 主循环 ----
        while running:
            try:
                with state_lock:
                    enabled = audio_pause_enabled
                    override = manual_override_audio
                    music_paused_snapshot = music_paused
                    previous_audio = last_other_audio_state
                    currently_auto_paused = auto_audio_paused
                    switching = source_switching
                    music_mode = music_mode_enabled
                    fullscreen_auto_paused = auto_fullscreen_paused

                # 节流日志：状态变化时才写
                now_log = time.time()
                state_tuple = (
                    enabled, override, music_paused_snapshot,
                    previous_audio, currently_auto_paused,
                    switching, music_mode, fullscreen_auto_paused,
                )
                if state_tuple != last_log_state or now_log - last_log_time > 30.0:
                    last_log_state = state_tuple
                    last_log_time = now_log

                # ---- 自检 1：auto_audio_paused=True 但音乐没有暂停 ----
                if currently_auto_paused and not music_paused_snapshot:
                    if desync_audio_paused_since is None:
                        desync_audio_paused_since = now_log
                    elif now_log - desync_audio_paused_since >= DESYNC_RESET_SECONDS:
                        with state_lock:
                            auto_audio_paused = False
                        desync_audio_paused_since = None
                else:
                    desync_audio_paused_since = None

                # ---- 自检 2：music_paused=True 但没有任何 auto_* 负责 ----
                if (
                    music_paused_snapshot
                    and not currently_auto_paused
                    and not fullscreen_auto_paused
                    and not switching
                    and not music_mode
                ):
                    if orphan_paused_since is None:
                        orphan_paused_since = now_log
                    elif now_log - orphan_paused_since >= ORPHAN_RESET_SECONDS:
                        cancel_audio_fade(True)
                        mpv_resume()
                        orphan_paused_since = None
                else:
                    orphan_paused_since = None

                # 音乐模式 / 切换来源 / 功能关闭 / 手动覆盖 → 不干预
                if switching or music_mode or not enabled or override:
                    time.sleep(AUDIO_POLL_SECONDS)
                    continue

                # 全屏自动暂停已经接管 → 本功能完全离线
                if fullscreen_auto_paused:
                    with state_lock:
                        auto_audio_paused = False
                        last_other_audio_state = None
                        last_audio_stop_time = None
                    time.sleep(AUDIO_POLL_SECONDS)
                    continue

                other_audio = other_app_is_playing_audio()
                now = time.time()

                # ---- 状态跟踪 ----
                if previous_audio is None:
                    with state_lock:
                        last_other_audio_state = other_audio

                elif previous_audio and not other_audio:
                    with state_lock:
                        last_audio_stop_time = now
                        last_other_audio_state = False

                elif not previous_audio and other_audio:
                    with state_lock:
                        last_audio_stop_time = None
                        last_other_audio_state = True

                else:
                    with state_lock:
                        last_other_audio_state = other_audio

                # ---- 触发暂停 ----
                if other_audio:
                    should_trigger_pause = False
                    with state_lock:
                        if (
                            not music_paused
                            and not auto_audio_paused
                            and not auto_fullscreen_paused
                        ):
                            auto_audio_paused = True
                            should_trigger_pause = True

                    if should_trigger_pause:
                        start_audio_fade_out()

                # ---- 触发恢复 ----
                else:
                    with state_lock:
                        was_auto_paused = auto_audio_paused
                        quiet_start = last_audio_stop_time

                    if was_auto_paused:
                        with state_lock:
                            fullscreen_paused = auto_fullscreen_paused

                        if fullscreen_paused:
                            with state_lock:
                                auto_audio_paused = False

                        else:
                            if quiet_start is None:
                                with state_lock:
                                    last_audio_stop_time = now
                                quiet_start = now

                            quiet_duration = now - quiet_start

                            with state_lock:
                                resume_buffer = audio_resume_delay

                            if quiet_duration >= resume_buffer:
                                with state_lock:
                                    fs_enabled = fullscreen_pause_enabled
                                    mm = music_mode_enabled

                                take_over_by_fullscreen = False
                                if fs_enabled and not mm:
                                    try:
                                        take_over_by_fullscreen = (
                                            is_foreground_fullscreen()
                                        )
                                    except Exception:
                                        take_over_by_fullscreen = False

                                if take_over_by_fullscreen:
                                    with state_lock:
                                        auto_audio_paused = False
                                        auto_fullscreen_paused = True
                                        fullscreen_paused_at = time.time()
                                        fullscreen_exited_at = None
                                    request_async_volume(0.0)

                                else:
                                    with state_lock:
                                        auto_audio_paused = False

                                    with audio_fade_lock:
                                        fade_running = (
                                            audio_fade_thread is not None
                                            and audio_fade_thread.is_alive()
                                        )

                                    if not fade_running:
                                        if not start_audio_fade_in():
                                            with state_lock:
                                                target = current_volume
                                            request_async_volume(target)
                                    else:
                                        pass

            except Exception as e:
                pass

            time.sleep(AUDIO_POLL_SECONDS)

    finally:
        try:
            if pythoncom is not None:
                pythoncom.CoUninitialize()
        except Exception:
            pass


# ============================================================
# MPV Watchdog
# ============================================================

def recover_mpv():

    global mpv_last_recovery_time
    global mpv_unexpected_pause_since
    global mpv_idle_since

    now = time.time()

    if now - mpv_last_recovery_time < MPV_RESTART_COOLDOWN_SECONDS:
        return False

    with state_lock:
        if source_switching or not running:
            return False

    mpv_last_recovery_time = now
    mpv_unexpected_pause_since = None
    mpv_idle_since = None

    with state_lock:
        current_source = source_type
        yt_index = youtube_playlist_index
        local_index = local_folder_index


    cancel_audio_fade(False)
    reset_runtime_playback_state()
    stop_current_mpv()

    proc = launch_mpv_if_needed()
    if proc is None:
        return False

    if not synchronize_after_source_switch():
        return False

    update_current_song_title()
    return mpv_is_running()


def mpv_watchdog():

    global mpv_unexpected_pause_since
    global mpv_unexpected_playing_since
    global mpv_idle_since
    global mpv_health_fail_count
    global music_paused
    global auto_fullscreen_paused
    global auto_audio_paused
    global fullscreen_paused_at
    global fullscreen_exited_at

    while running:
        try:
            with state_lock:
                switching = source_switching
                manually_paused = music_paused
                fullscreen_paused = auto_fullscreen_paused
                audio_paused = auto_audio_paused
                started_at = mpv_started_at

            if switching:
                mpv_health_fail_count = 0
                mpv_unexpected_pause_since = None
                mpv_idle_since = None
                time.sleep(MPV_WATCHDOG_SECONDS)
                continue

            process_dead = False
            if started_proc is not None:
                try:
                    process_dead = started_proc.poll() is not None
                except Exception:
                    process_dead = False

            if process_dead:
                mpv_health_fail_count = 0
                recover_mpv()
                time.sleep(MPV_WATCHDOG_SECONDS)
                continue

            # 启动后的前 10 秒不因为 IPC 尚未稳定而重启
            if started_at is not None and time.time() - started_at < 10.0:
                mpv_health_fail_count = 0
                time.sleep(MPV_WATCHDOG_SECONDS)
                continue

            pipe_alive = mpv_is_running()

            if not pipe_alive:
                mpv_health_fail_count += 1

                if mpv_health_fail_count >= MPV_HEALTH_FAIL_LIMIT:
                    mpv_health_fail_count = 0
                    recover_mpv()

                time.sleep(MPV_WATCHDOG_SECONDS)
                continue

            mpv_health_fail_count = 0

            idle_active = mpv_get_property("idle-active", None)

            if idle_active is True:
                if mpv_idle_since is None:
                    mpv_idle_since = time.time()
                elif time.time() - mpv_idle_since >= MPV_IDLE_RECOVERY_SECONDS:
                    recover_mpv()
            else:
                mpv_idle_since = None

            if not manually_paused and not fullscreen_paused and not audio_paused:
                pause_state = mpv_get_property("pause", None)

                if pause_state is True:
                    if mpv_unexpected_pause_since is None:
                        mpv_unexpected_pause_since = time.time()
                    elif time.time() - mpv_unexpected_pause_since >= MPV_INTERNAL_PAUSE_RECOVERY_SECONDS:
                        cancel_audio_fade(True)
                        mpv_resume()
                        mpv_unexpected_pause_since = None
                else:
                    mpv_unexpected_pause_since = None
            else:
                mpv_unexpected_pause_since = None

            # 反向自愈：music_paused=True（按钮显示"播放/继续"），
            # 但 mpv 读回的真实 pause 属性其实是 False，
            # 说明本地状态和 mpv 实际播放情况脱钩了（例如开机自启时
            # 全屏误判触发的 mpv_pause() 没有真正生效）。
            # 无论是哪个 auto_* 功能"认领"了这次暂停，只要 mpv 明确
            # 说自己没暂停，就该以 mpv 为准，把状态纠正回来。
            if manually_paused:
                real_pause_state = mpv_get_property("pause", None)

                if real_pause_state is False:
                    if mpv_unexpected_playing_since is None:
                        mpv_unexpected_playing_since = time.time()
                    elif (
                        time.time() - mpv_unexpected_playing_since
                        >= MPV_FLAG_DESYNC_RECOVERY_SECONDS
                    ):
                        cancel_audio_fade(True)
                        with state_lock:
                            music_paused = False
                            auto_fullscreen_paused = False
                            auto_audio_paused = False
                            fullscreen_paused_at = None
                            fullscreen_exited_at = None

                        # 这条路径绕过了 mpv_resume()，直接改标志，
                        # 所以必须自己刷新托盘，否则按钮文字会一直
                        # 停在"播放 / 继续"。
                        refresh_tray_menu()

                        mpv_unexpected_playing_since = None
                else:
                    mpv_unexpected_playing_since = None
            else:
                mpv_unexpected_playing_since = None

        except Exception:
            pass

        time.sleep(MPV_WATCHDOG_SECONDS)


# ============================================================
# 错误
# ============================================================

def show_startup_error(message):

    try:
        win32gui.MessageBox(
            0,
            message,
            "YouTube Background Music",
            win32con.MB_ICONERROR | win32con.MB_OK
        )
    except Exception:
        print(message)


# ============================================================
# Main
# ============================================================

def main():

    global running
    global started_proc
    global source_type
    global local_folder_index
    global tray_icon

    detach_from_console()
    running = True

    load_config()

    # 只初始化一次 Tkinter。
    start_gui_thread()

    if not MPV_PATH:
        show_startup_error(t("err_no_mpv_path"))
        return

    if not os.path.isfile(MPV_PATH):
        show_startup_error(t("err_mpv_not_found", path=MPV_PATH))
        return

    load_volume()
    load_pause_settings()
    load_source_settings()
    load_startup_settings()

    with state_lock:
        current_source = source_type

    if current_source == SOURCE_YOUTUBE and not YOUTUBE_PLAYLISTS:
        if LOCAL_MUSIC_FOLDERS:
            with state_lock:
                source_type = SOURCE_LOCAL
                local_folder_index = 0
            save_source_settings()
        else:
            show_startup_error(t("err_no_playlists"))
            return

    elif current_source == SOURCE_LOCAL and not LOCAL_MUSIC_FOLDERS:
        if YOUTUBE_PLAYLISTS:
            with state_lock:
                source_type = SOURCE_YOUTUBE
            save_source_settings()
        else:
            show_startup_error(t("err_no_sources"))
            return

    with state_lock:
        current_source = source_type

    if current_source == SOURCE_YOUTUBE and not YTDLP_PATH:
        show_startup_error(t("err_no_ytdlp_path"))
        return

    if current_source == SOURCE_YOUTUBE and not os.path.isfile(YTDLP_PATH):
        show_startup_error(t("err_ytdlp_not_found", path=YTDLP_PATH))
        return

    if current_source == SOURCE_LOCAL and create_local_playlist() <= 0:
        show_startup_error(t("err_no_local_files"))
        return

    # 音量异步 worker
    volume_thread = threading.Thread(
        target=volume_command_worker,
        daemon=True,
        name="YBM-VolumeWorker"
    )
    volume_thread.start()

    started_proc = launch_mpv_if_needed()

    if started_proc is None:
        show_startup_error(t("err_mpv_start"))
        return

    synchronize_after_source_switch()
    update_current_song_title()

    try:
        icon = create_tray()
        if icon is None:
            raise RuntimeError("create_tray() returned no tray object.")
        tray_icon = icon
    except Exception as e:
        show_startup_error(t("err_tray_create", error=repr(e)))
        running = False
        try:
            if mpv_is_running():
                mpv_stop()
            gui_command_queue.put("shutdown")
        except Exception:
            pass
        return

    threading.Thread(
        target=song_title_event_monitor,
        daemon=True,
        name="YBM-SongTitleEvent"
    ).start()

    threading.Thread(
        target=fullscreen_monitor,
        daemon=True,
        name="YBM-FullscreenMonitor"
    ).start()

    threading.Thread(
        target=audio_monitor,
        daemon=True,
        name="YBM-AudioMonitor"
    ).start()

    threading.Thread(
        target=mpv_watchdog,
        daemon=True,
        name="YBM-MPVWatchdog"
    ).start()

    try:
        icon.run()
    except Exception as e:
        show_startup_error(t("err_tray_run", error=repr(e)))
    finally:
        running = False
        title_event_stop.set()
        _close_title_event_handle()
        cancel_audio_fade(False)
        save_volume()
        save_source_settings()

        try:
            volume_request_event.set()
            gui_command_queue.put("shutdown")
        except Exception:
            pass

        if started_proc is not None:
            try:
                if mpv_is_running():
                    mpv_stop()
                started_proc.wait(timeout=3)
            except Exception:
                try:
                    started_proc.terminate()
                except Exception:
                    pass

        tray_icon = None


if __name__ == "__main__":
    main()