# -*- coding: utf-8 -*-

"""
YouTube Background Music - Config Editor V2.8

V2.8：
- 更新 yt-dlp 改为后台线程，界面不再冻结
- 状态栏逐步显示：读取本地版本 → 本地版本: xxx → 查询最新版本 → 最新版本: xxx
- 版本查询改为拦截 GitHub 第一跳重定向（国内可访问）
- 本地已是最新版时不再重复下载
"""

import os
import sys
import json
import time
import glob
import shutil
import subprocess
import tempfile
import tkinter as tk
from urllib.parse import urlparse
from tkinter import ttk, filedialog, messagebox
import tkinter.font as tkfont
import threading


# ============================================================
# 高 DPI 感知
# ============================================================

try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass


# ============================================================
# 基本路径
# ============================================================

def _get_base_dir():

    if getattr(sys, "frozen", False):
        return os.path.dirname(
            os.path.abspath(sys.executable)
        )

    return os.path.dirname(
        os.path.abspath(__file__)
    )


BASE_DIR = _get_base_dir()

def _get_resource_path(relative_path):
    """获取打包后资源的路径（兼容 onefile 和开发模式）。"""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = BASE_DIR
    return os.path.join(base, relative_path)

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
CONFIG_BAK = os.path.join(BASE_DIR, "config.json.bak")

YBM_EXE = os.path.join(
    BASE_DIR,
    "YouTube Background Music.exe"
)

YBM_PY = os.path.join(
    BASE_DIR,
    "youtube_background_music.py"
)


# ============================================================
# 跨平台进程常量
# ============================================================

CREATE_NO_WINDOW = getattr(
    subprocess,
    "CREATE_NO_WINDOW",
    0
)

CREATE_NEW_PROCESS_GROUP = getattr(
    subprocess,
    "CREATE_NEW_PROCESS_GROUP",
    0
)

YBM_CREATIONFLAGS = (
    CREATE_NO_WINDOW
    | CREATE_NEW_PROCESS_GROUP
)


# ============================================================
# 多语言
# ============================================================

LANG_NAMES = {
    "zh": "中文",
    "en": "English",
}

_current_lang = "en"


def detect_system_language():

    try:
        import ctypes
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        if (lang_id & 0xFF) == 0x04:
            return "zh"
    except Exception:
        pass

    return "en"


def set_language(lang):

    global _current_lang

    _current_lang = lang if lang in LANG_NAMES else "en"


def get_language():
    return _current_lang


STRINGS = {
    "zh": {
        # 通用
        "ok": "确定",
        "cancel": "取消",
        "hint_title": "提示",
        "err_title": "错误",
        "unnamed": "未命名",
        "list_sep": "；",

        # 配置文件
        "cfg_err_title": "配置文件错误",
        "cfg_json_broken": (
            "config.json 无法读取，因为 JSON 格式损坏。\n\n"
            "错误位置：第 {line} 行，第 {col} 列\n\n"
            "原来的 config.json 不会被覆盖。"
        ),
        "cfg_not_object": "config.json 的最外层必须是 JSON 对象。",
        "err_create_config": "无法创建 config.json：\n\n{error}",
        "err_read_config": "无法读取 config.json：\n\n{error}",
        "save_failed_title": "保存失败",
        "err_save_config": "无法保存 config.json：\n\n{error}",

        # 启动 YBM
        "launch_failed_title": "启动失败",
        "ybm_not_found": (
            "找不到 YBM：\n\n"
            "YouTube Background Music.exe\n"
            "或\n"
            "youtube_background_music.py\n\n"
            "请确认它们位于 Config Editor.exe 同一个文件夹。"
        ),
        "err_launch_ybm": "无法启动 YBM：\n\n{error}",

        # 对话框
        "dlg_add_playlist": "添加 YouTube 播放列表",
        "dlg_edit_playlist": "编辑 YouTube 播放列表",
        "dlg_add_folder": "添加本地音乐文件夹",
        "dlg_edit_folder": "编辑本地音乐文件夹",
        "label_name": "名称：",
        "label_folder_colon": "文件夹：",
        "browse_dots": "浏览...",
        "select_music_folder_title": "选择音乐文件夹",
        "enter_playlist_name": "请输入播放列表名称。",
        "enter_url": "请输入 YouTube URL。",
        "invalid_url": (
            "请输入有效的 YouTube URL。\n\n"
            "支持：youtube.com / youtu.be /\n"
            "m.youtube.com / music.youtube.com"
        ),
        "enter_folder_name": "请输入文件夹名称。",
        "choose_folder": "请选择本地音乐文件夹。",
        "folder_missing_title": "文件夹不存在",
        "folder_missing_save": (
            "这个文件夹目前不存在。\n\n"
            "仍然保存这个路径吗？"
        ),

        # 主窗口
        "label_mpv": "MPV 路径：",
        "label_ytdlp": "yt-dlp 路径：",
        "btn_browse": "浏览",
        "frame_youtube": "YouTube 播放列表",
        "frame_local": "本地音乐文件夹",
        "col_name": "名称",
        "col_folder": "文件夹",
        "btn_add": "添加",
        "btn_edit": "编辑",
        "btn_delete": "删除",
        "btn_autodetect": "自动检测工具",
        "btn_apply": "保存并应用",
        "label_language": "语言：",
        "pick_mpv_title": "选择 mpv.exe",
        "pick_ytdlp_title": "选择 yt-dlp.exe",

        # 状态栏
        "status_ready": "就绪",
        "status_autodetected": "已自动检测：{items}",
        "status_nothing_found": "未找到可自动填充的工具",
        "status_stopping": "正在停止旧 YBM...",
        "status_starting": "正在启动 YBM...",
        "status_start_failed": "启动 YBM 失败",
        "status_started": "YBM 已启动",

        # 列表操作
        "select_item_first": "请先选择一个项目。",
        "select_playlist_first": "请先选择一个播放列表。",
        "select_folder_first": "请先选择一个本地音乐文件夹。",
        "confirm_delete_title": "确认删除",
        "confirm_delete_playlist": "确定要删除播放列表：\n\n{name}\n\n吗？",
        "confirm_delete_folder": "确定要删除本地音乐文件夹：\n\n{name}\n\n吗？",

        # 配置检查
        "err_mpv_unset": "• 尚未设置 MPV 路径",
        "err_mpv_missing": "• MPV 路径不存在：\n  {path}",
        "err_ytdlp_unset": "• 尚未设置 yt-dlp 路径",
        "err_ytdlp_missing": "• yt-dlp 路径不存在：\n  {path}",
        "err_no_source": "• 至少需要设置一个 YouTube 播放列表或一个本地音乐文件夹",
        "incomplete_title": "配置不完整",
        "incomplete_body": (
            "无法运行 YBM。\n\n"
            "请先完成以下配置：\n\n"
            "{errors}"
        ),
        "invalid_folders_body": (
            "以下本地音乐文件夹不存在：\n\n"
            "{folders}\n\n"
            "仍然继续吗？"
        ),

        # 关闭
        "unsaved_title": "未保存的修改",
        "unsaved_body": (
            "你有尚未保存的修改。\n\n"
            "确定要放弃这些修改并退出吗？"
        ),

        # 更新 yt-dlp
        "btn_update_ytdlp": "更新 yt-dlp",
        "ytdlp_update_title": "更新 yt-dlp",
        "updating_ytdlp": "正在下载最新版 yt-dlp...",
        "ytdlp_update_success": "yt-dlp 已更新到最新版：\n\n{path}",
        "ytdlp_update_failed": "更新 yt-dlp 失败：\n\n{error}",
        "ytdlp_no_path": (
            "尚未设置 yt-dlp 路径。\n\n"
            "请先设置路径，或点击“自动检测工具”。"
        ),
        "ytdlp_confirm_update": (
            "将从 GitHub 下载最新版 yt-dlp 并替换：\n\n{path}\n\n"
            "继续吗？"
        ),
        "ytdlp_already_updating": "yt-dlp 正在更新中，请稍候。",
        "ytdlp_in_use_detail": (
            "无法替换 yt-dlp：文件正在被使用。\n\n"
            "请先停止 YouTube Background Music，然后重试。"
        ),
        "ytdlp_already_latest": (
            "yt-dlp 已经是最新版（{version}）。\n\n无需更新。"
        ),
        "ytdlp_confirm_install": (
            "未检测到 yt-dlp。\n\n"
            "将自动下载最新版到：\n{path}\n\n"
            "继续吗？"
        ),
        "ytdlp_install_success": "yt-dlp 已安装并配置：\n\n{path}",
        "ytdlp_preparing": "准备中...",
        "ytdlp_reading_local": "读取本地版本...",
        "ytdlp_local_version": "本地版本: {version}",
        "ytdlp_querying_latest": "查询最新版本...",
        "ytdlp_latest_version": "最新版本: {version}",
        "ytdlp_unknown_version": "(未知)",
    },

    "en": {
        # General
        "ok": "OK",
        "cancel": "Cancel",
        "hint_title": "Notice",
        "err_title": "Error",
        "unnamed": "Unnamed",
        "list_sep": "; ",

        # Config file
        "cfg_err_title": "Config file error",
        "cfg_json_broken": (
            "config.json could not be read because its JSON is malformed.\n\n"
            "Error at line {line}, column {col}.\n\n"
            "The original config.json will not be overwritten."
        ),
        "cfg_not_object": "The top level of config.json must be a JSON object.",
        "err_create_config": "Could not create config.json:\n\n{error}",
        "err_read_config": "Could not read config.json:\n\n{error}",
        "save_failed_title": "Save failed",
        "err_save_config": "Could not save config.json:\n\n{error}",

        # Launching YBM
        "launch_failed_title": "Launch failed",
        "ybm_not_found": (
            "YBM was not found:\n\n"
            "YouTube Background Music.exe\n"
            "or\n"
            "youtube_background_music.py\n\n"
            "Make sure it is in the same folder as Config Editor.exe."
        ),
        "err_launch_ybm": "Could not launch YBM:\n\n{error}",

        # Dialogs
        "dlg_add_playlist": "Add YouTube Playlist",
        "dlg_edit_playlist": "Edit YouTube Playlist",
        "dlg_add_folder": "Add Local Music Folder",
        "dlg_edit_folder": "Edit Local Music Folder",
        "label_name": "Name:",
        "label_folder_colon": "Folder:",
        "browse_dots": "Browse...",
        "select_music_folder_title": "Select music folder",
        "enter_playlist_name": "Please enter a playlist name.",
        "enter_url": "Please enter a YouTube URL.",
        "invalid_url": (
            "Please enter a valid YouTube URL.\n\n"
            "Supported: youtube.com / youtu.be /\n"
            "m.youtube.com / music.youtube.com"
        ),
        "enter_folder_name": "Please enter a folder name.",
        "choose_folder": "Please choose a local music folder.",
        "folder_missing_title": "Folder not found",
        "folder_missing_save": (
            "This folder does not exist.\n\n"
            "Save this path anyway?"
        ),

        # Main window
        "label_mpv": "MPV path:",
        "label_ytdlp": "yt-dlp path:",
        "btn_browse": "Browse",
        "frame_youtube": "YouTube Playlists",
        "frame_local": "Local Music Folders",
        "col_name": "Name",
        "col_folder": "Folder",
        "btn_add": "Add",
        "btn_edit": "Edit",
        "btn_delete": "Delete",
        "btn_autodetect": "Auto-detect tools",
        "btn_apply": "Save & Apply",
        "label_language": "Language:",
        "pick_mpv_title": "Select mpv.exe",
        "pick_ytdlp_title": "Select yt-dlp.exe",

        # Status bar
        "status_ready": "Ready",
        "status_autodetected": "Auto-detected: {items}",
        "status_nothing_found": "No tools found to fill in automatically",
        "status_stopping": "Stopping the old YBM...",
        "status_starting": "Starting YBM...",
        "status_start_failed": "Failed to start YBM",
        "status_started": "YBM started",

        # List actions
        "select_item_first": "Please select an item first.",
        "select_playlist_first": "Please select a playlist first.",
        "select_folder_first": "Please select a local music folder first.",
        "confirm_delete_title": "Confirm delete",
        "confirm_delete_playlist": "Delete this playlist?\n\n{name}",
        "confirm_delete_folder": "Delete this local music folder?\n\n{name}",

        # Validation
        "err_mpv_unset": "• MPV path is not set",
        "err_mpv_missing": "• MPV path does not exist:\n  {path}",
        "err_ytdlp_unset": "• yt-dlp path is not set",
        "err_ytdlp_missing": "• yt-dlp path does not exist:\n  {path}",
        "err_no_source": "• At least one YouTube playlist or local music folder is required",
        "incomplete_title": "Incomplete configuration",
        "incomplete_body": (
            "YBM cannot run yet.\n\n"
            "Please complete the following:\n\n"
            "{errors}"
        ),
        "invalid_folders_body": (
            "These local music folders do not exist:\n\n"
            "{folders}\n\n"
            "Continue anyway?"
        ),

        # Closing
        "unsaved_title": "Unsaved changes",
        "unsaved_body": (
            "You have unsaved changes.\n\n"
            "Discard them and exit?"
        ),

        # Update yt-dlp
        "btn_update_ytdlp": "Update yt-dlp",
        "ytdlp_update_title": "Update yt-dlp",
        "updating_ytdlp": "Downloading the latest yt-dlp...",
        "ytdlp_update_success": "yt-dlp updated to the latest version:\n\n{path}",
        "ytdlp_update_failed": "Failed to update yt-dlp:\n\n{error}",
        "ytdlp_no_path": (
            "yt-dlp path is not set.\n\n"
            "Set it first, or click \"Auto-detect tools\"."
        ),
        "ytdlp_confirm_update": (
            "This will download the latest yt-dlp from GitHub and replace:\n\n{path}\n\n"
            "Continue?"
        ),
        "ytdlp_already_updating": "yt-dlp is already being updated. Please wait.",
        "ytdlp_in_use_detail": (
            "Failed to replace yt-dlp: the file is in use.\n\n"
            "Please stop YouTube Background Music first, then try again."
        ),
        "ytdlp_already_latest": (
            "yt-dlp is already the latest version ({version}).\n\n"
            "No update needed."
        ),
        "ytdlp_confirm_install": (
            "yt-dlp was not found.\n\n"
            "The latest version will be downloaded to:\n{path}\n\n"
            "Continue?"
        ),
        "ytdlp_install_success": "yt-dlp installed and configured:\n\n{path}",
        "ytdlp_preparing": "Preparing...",
        "ytdlp_reading_local": "Reading local version...",
        "ytdlp_local_version": "Local version: {version}",
        "ytdlp_querying_latest": "Querying latest version...",
        "ytdlp_latest_version": "Latest version: {version}",
        "ytdlp_unknown_version": "(unknown)",
    },
}


def apply_gui_fonts():

    family = "Microsoft YaHei UI" if _current_lang == "zh" else "Segoe UI"

    try:
        available = set(tkfont.families())
        if family not in available and "Microsoft YaHei" in available:
            family = "Microsoft YaHei"
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

    try:
        ttk.Style().configure("Treeview", rowheight=26)
    except Exception:
        pass


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
# 默认配置
# ============================================================

DEFAULT_CONFIG = {
    "mpv_path": "",
    "yt_dlp_path": "",
    "youtube_playlists": [],
    "local_music_folders": []
}


# ============================================================
# 工具函数
# ============================================================

def clean_path(path):

    if not isinstance(path, str):
        return ""

    path = path.strip().strip('"').strip("'")
    path = os.path.expandvars(path)
    path = os.path.expanduser(path)

    return path


def normalize_config(config):

    if not isinstance(config, dict):
        config = {}

    if not isinstance(config.get("mpv_path"), str):
        config["mpv_path"] = ""

    if not isinstance(config.get("yt_dlp_path"), str):
        config["yt_dlp_path"] = ""

    if not isinstance(config.get("youtube_playlists"), list):
        config["youtube_playlists"] = []

    if not isinstance(config.get("local_music_folders"), list):
        config["local_music_folders"] = []

    config["youtube_playlists"] = [
        {
            "name": str(item.get("name", "")).strip(),
            "url": str(item.get("url", "")).strip()
        }
        for item in config["youtube_playlists"]
        if isinstance(item, dict)
    ]

    config["local_music_folders"] = [
        {
            "name": str(item.get("name", "")).strip(),
            "folder": str(item.get("folder", "")).strip()
        }
        for item in config["local_music_folders"]
        if isinstance(item, dict)
    ]

    if config.get("language") not in LANG_NAMES:
        config["language"] = detect_system_language()

    return config


def create_default_config():

    try:

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:

            json.dump(
                dict(DEFAULT_CONFIG, language=detect_system_language()),
                f,
                ensure_ascii=False,
                indent=4
            )

            f.write("\n")

        return True

    except Exception as e:

        messagebox.showerror(
            t("err_title"),
            t("err_create_config", error=e)
        )

        return False


def load_config():

    if not os.path.exists(CONFIG_FILE):

        if not create_default_config():
            return None

        return normalize_config(
            json.loads(
                json.dumps(DEFAULT_CONFIG)
            )
        )

    try:

        with open(CONFIG_FILE, "r", encoding="utf-8") as f:

            config = json.load(f)

    except json.JSONDecodeError as e:

        messagebox.showerror(
            t("cfg_err_title"),
            t("cfg_json_broken", line=e.lineno, col=e.colno)
        )

        return None

    except Exception as e:

        messagebox.showerror(
            t("err_title"),
            t("err_read_config", error=e)
        )

        return None

    if not isinstance(config, dict):

        messagebox.showerror(
            t("cfg_err_title"),
            t("cfg_not_object")
        )

        return None

    return normalize_config(config)


def save_config_file(config):

    temp_path = None

    try:

        if os.path.exists(CONFIG_FILE):

            try:

                shutil.copy2(
                    CONFIG_FILE,
                    CONFIG_BAK
                )

            except Exception:

                pass

        fd, temp_path = tempfile.mkstemp(
            prefix="config_",
            suffix=".json",
            dir=BASE_DIR
        )

        with os.fdopen(fd, "w", encoding="utf-8") as f:

            json.dump(
                config,
                f,
                ensure_ascii=False,
                indent=4
            )

            f.write("\n")

        os.replace(temp_path, CONFIG_FILE)

        return True

    except Exception as e:

        if temp_path and os.path.exists(temp_path):

            try:
                os.remove(temp_path)
            except Exception:
                pass

        messagebox.showerror(
            t("save_failed_title"),
            t("err_save_config", error=e)
        )

        return False


def is_valid_youtube_url(url):

    if not url:
        return False

    try:

        parsed = urlparse(url.strip())

    except Exception:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    host = parsed.netloc.lower().split(":")[0]

    return (
        host == "youtu.be"
        or host == "youtube.com"
        or host == "www.youtube.com"
        or host == "m.youtube.com"
        or host == "music.youtube.com"
        or host.endswith(".youtube.com")
    )


# ============================================================
# YBM 进程管理
# ============================================================

def _get_pids_by_commandline(keyword):

    pids = []

    try:

        ps_script = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { "
            "$_.Name -eq 'python.exe' -or "
            "$_.Name -eq 'pythonw.exe' "
            "} | "
            "ForEach-Object { "
            "if ($_.CommandLine -and "
            f"$_.CommandLine -like '*{keyword}*') "
            "{ $_.ProcessId }"
            "}"
        )

        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps_script
            ],
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW
        )

        if result.returncode != 0:
            return []

        for line in result.stdout.splitlines():

            line = line.strip()

            if line.isdigit():

                pid = int(line)

                if pid > 0:
                    pids.append(pid)

    except Exception:

        pass

    return list(dict.fromkeys(pids))


def _get_pids_by_imagename(imagename):

    pids = []

    try:

        ps_script = (
            "Get-CimInstance Win32_Process | "
            f"Where-Object {{ $_.Name -eq '{imagename}' }} | "
            "ForEach-Object { $_.ProcessId }"
        )

        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps_script
            ],
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW
        )

        if result.returncode != 0:
            return []

        for line in result.stdout.splitlines():

            line = line.strip()

            if line.isdigit():

                pid = int(line)

                if pid > 0:
                    pids.append(pid)

    except Exception:

        pass

    return list(dict.fromkeys(pids))


def _kill_pids(pids):

    for pid in pids:

        try:

            subprocess.run(
                [
                    "taskkill",
                    "/F",
                    "/T",
                    "/PID",
                    str(pid)
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW
            )

        except Exception:

            pass


def get_running_ybm_python_pids():

    return _get_pids_by_commandline(
        "youtube_background_music.py"
    )


def get_running_ybm_exe_pids():

    return _get_pids_by_imagename(
        "YouTube Background Music.exe"
    )


def stop_ybm_python():

    pids = get_running_ybm_python_pids()

    if pids:
        _kill_pids(pids)


def stop_ybm_exe():

    pids = get_running_ybm_exe_pids()

    if pids:
        _kill_pids(pids)


def is_ybm_exe_running():

    return bool(get_running_ybm_exe_pids())


def is_ybm_running():

    if os.path.exists(YBM_EXE):

        if is_ybm_exe_running():
            return True

    if os.path.exists(YBM_PY):

        if get_running_ybm_python_pids():
            return True

    return False


def stop_ybm():

    if os.path.exists(YBM_EXE):

        if is_ybm_exe_running():
            stop_ybm_exe()

    if os.path.exists(YBM_PY):

        if get_running_ybm_python_pids():
            stop_ybm_python()

    for _ in range(10):

        if not is_ybm_running():
            return

        time.sleep(0.2)


def start_ybm():

    try:

        if os.path.exists(YBM_EXE):

            subprocess.Popen(
                [YBM_EXE],
                cwd=BASE_DIR,
                creationflags=YBM_CREATIONFLAGS
            )

            return True

        if os.path.exists(YBM_PY):

            python_exe = sys.executable

            subprocess.Popen(
                [
                    python_exe,
                    YBM_PY
                ],
                cwd=BASE_DIR,
                creationflags=YBM_CREATIONFLAGS
            )

            return True

        messagebox.showerror(
            t("launch_failed_title"),
            t("ybm_not_found")
        )

        return False

    except Exception as e:

        messagebox.showerror(
            t("launch_failed_title"),
            t("err_launch_ybm", error=e)
        )

        return False


# ============================================================
# YouTube 播放列表编辑窗口
# ============================================================

class PlaylistDialog:

    def __init__(self, parent, title=None, name="", url=""):

        self.result = None

        if title is None:
            title = t("dlg_add_playlist")

        self.window = tk.Toplevel(parent)

        self.window.title(title)
        self.window.geometry("520x210")
        self.window.resizable(False, False)

        self.window.transient(parent)
        self.window.grab_set()

        frame = ttk.Frame(self.window, padding=15)

        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text=t("label_name")).grid(
            row=0, column=0, sticky="w", pady=(0, 10)
        )

        self.name_var = tk.StringVar(value=name)

        name_entry = ttk.Entry(
            frame, textvariable=self.name_var, width=55
        )

        name_entry.grid(row=0, column=1, sticky="ew", pady=(0, 10))

        ttk.Label(frame, text="URL:").grid(
            row=1, column=0, sticky="w", pady=(0, 10)
        )

        self.url_var = tk.StringVar(value=url)

        url_entry = ttk.Entry(
            frame, textvariable=self.url_var, width=55
        )

        url_entry.grid(row=1, column=1, sticky="ew", pady=(0, 10))

        frame.columnconfigure(1, weight=1)

        button_frame = ttk.Frame(frame)

        button_frame.grid(
            row=2, column=0, columnspan=2, pady=(15, 0)
        )

        ttk.Button(
            button_frame, text=t("ok"), command=self.on_ok
        ).pack(side="left", padx=5)

        ttk.Button(
            button_frame, text=t("cancel"), command=self.on_cancel
        ).pack(side="left", padx=5)

        name_entry.focus_set()

        self.window.bind("<Return>", lambda event: self.on_ok())
        self.window.bind("<Escape>", lambda event: self.on_cancel())
        self.window.protocol("WM_DELETE_WINDOW", self.on_cancel)

    def on_ok(self):

        name = self.name_var.get().strip()
        url = self.url_var.get().strip()

        if not name:

            messagebox.showwarning(
                t("hint_title"),
                t("enter_playlist_name"),
                parent=self.window
            )

            return

        if not url:

            messagebox.showwarning(
                t("hint_title"),
                t("enter_url"),
                parent=self.window
            )

            return

        if not is_valid_youtube_url(url):

            messagebox.showwarning(
                t("hint_title"),
                t("invalid_url"),
                parent=self.window
            )

            return

        self.result = {"name": name, "url": url}

        self.window.destroy()

    def on_cancel(self):

        self.result = None

        self.window.destroy()


# ============================================================
# 本地文件夹编辑窗口
# ============================================================

class FolderDialog:

    def __init__(self, parent, title=None, name="", folder=""):

        self.result = None

        if title is None:
            title = t("dlg_add_folder")

        self.window = tk.Toplevel(parent)

        self.window.title(title)
        self.window.geometry("560x210")
        self.window.resizable(False, False)

        self.window.transient(parent)
        self.window.grab_set()

        frame = ttk.Frame(self.window, padding=15)

        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text=t("label_name")).grid(
            row=0, column=0, sticky="w", pady=(0, 10)
        )

        self.name_var = tk.StringVar(value=name)

        name_entry = ttk.Entry(
            frame, textvariable=self.name_var, width=60
        )

        name_entry.grid(
            row=0, column=1, columnspan=2, sticky="ew", pady=(0, 10)
        )

        ttk.Label(frame, text=t("label_folder_colon")).grid(
            row=1, column=0, sticky="w", pady=(0, 10)
        )

        self.folder_var = tk.StringVar(value=folder)

        folder_entry = ttk.Entry(
            frame, textvariable=self.folder_var, width=48
        )

        folder_entry.grid(row=1, column=1, sticky="ew", pady=(0, 10))

        ttk.Button(
            frame, text=t("browse_dots"), command=self.browse_folder
        ).grid(row=1, column=2, padx=(8, 0), pady=(0, 10))

        frame.columnconfigure(1, weight=1)

        button_frame = ttk.Frame(frame)

        button_frame.grid(
            row=2, column=0, columnspan=3, pady=(15, 0)
        )

        ttk.Button(
            button_frame, text=t("ok"), command=self.on_ok
        ).pack(side="left", padx=5)

        ttk.Button(
            button_frame, text=t("cancel"), command=self.on_cancel
        ).pack(side="left", padx=5)

        name_entry.focus_set()

        self.window.bind("<Return>", lambda event: self.on_ok())
        self.window.bind("<Escape>", lambda event: self.on_cancel())
        self.window.protocol("WM_DELETE_WINDOW", self.on_cancel)

    def browse_folder(self):

        folder = filedialog.askdirectory(
            parent=self.window,
            title=t("select_music_folder_title")
        )

        if folder:
            self.folder_var.set(folder)

    def on_ok(self):

        name = self.name_var.get().strip()
        folder = clean_path(self.folder_var.get())

        if not name:

            messagebox.showwarning(
                t("hint_title"),
                t("enter_folder_name"),
                parent=self.window
            )

            return

        if not folder:

            messagebox.showwarning(
                t("hint_title"),
                t("choose_folder"),
                parent=self.window
            )

            return

        if not os.path.isdir(folder):

            result = messagebox.askyesno(
                t("folder_missing_title"),
                t("folder_missing_save"),
                parent=self.window
            )

            if not result:
                return

        self.result = {"name": name, "folder": folder}

        self.window.destroy()

    def on_cancel(self):

        self.result = None

        self.window.destroy()


# ============================================================
# 主窗口
# ============================================================

class ConfigEditor:

    def __init__(self, root):

        self.root = root

        self.root.title(
            "YouTube Background Music - Config Editor V2.8"
        )

        try:
            icon_path = _get_resource_path("icon.ico")
            if os.path.isfile(icon_path):
                self.root.iconbitmap(icon_path)
                self.root.iconbitmap(default=icon_path)
        except Exception:
            pass

        self.root.geometry("800x760")

        self.root.minsize(720, 660)

        self._loading = True
        self.is_modified = False
        self.saved_config = None
        self._ytdlp_updating = False

        self.config = load_config()

        if self.config is None:
            return

        set_language(self.config.get("language"))
        apply_gui_fonts()

        self.saved_config = self.copy_config(self.config)

        self.build_ui()
        self.load_data_to_ui()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    @staticmethod
    def copy_config(config):

        return json.loads(
            json.dumps(config, ensure_ascii=False)
        )

    def check_modified(self, *args):

        if self._loading:
            return

        self.update_config_from_ui()

        self.is_modified = (self.saved_config != self.config)

    def mark_saved(self):

        self.update_config_from_ui()

        self.saved_config = self.copy_config(self.config)

        self.is_modified = False

    # ========================================================
    # UI
    # ========================================================

    def build_ui(self):

        main = ttk.Frame(self.root, padding=12)

        main.pack(fill="both", expand=True)

        self.main_frame = main

        # ---------------- MPV ----------------

        ttk.Label(main, text=t("label_mpv")).grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )

        self.mpv_var = tk.StringVar()

        self.mpv_var.trace_add("write", self.check_modified)

        self.mpv_entry = ttk.Entry(main, textvariable=self.mpv_var)

        self.mpv_entry.grid(row=0, column=1, sticky="ew", pady=(0, 8))

        ttk.Button(
            main, text=t("btn_browse"), command=self.browse_mpv
        ).grid(row=0, column=2, padx=(8, 0), pady=(0, 8))

        # ---------------- yt-dlp ----------------

        ttk.Label(main, text=t("label_ytdlp")).grid(
            row=1, column=0, sticky="w", pady=(0, 12)
        )

        self.ytdlp_var = tk.StringVar()

        self.ytdlp_var.trace_add("write", self.check_modified)

        self.ytdlp_entry = ttk.Entry(main, textvariable=self.ytdlp_var)

        self.ytdlp_entry.grid(row=1, column=1, sticky="ew", pady=(0, 12))

        ttk.Button(
            main, text=t("btn_browse"), command=self.browse_ytdlp
        ).grid(row=1, column=2, padx=(8, 0), pady=(0, 12))

        # ---------------- YouTube ----------------

        youtube_frame = ttk.LabelFrame(
            main, text=t("frame_youtube"), padding=8
        )

        youtube_frame.grid(
            row=2, column=0, columnspan=3, sticky="nsew", pady=(0, 10)
        )

        youtube_frame.rowconfigure(0, weight=1)
        youtube_frame.columnconfigure(0, weight=1)

        self.youtube_tree = ttk.Treeview(
            youtube_frame,
            columns=("name", "url"),
            show="headings",
            selectmode="browse"
        )

        self.youtube_tree.heading("name", text=t("col_name"))
        self.youtube_tree.heading("url", text="URL")

        self.youtube_tree.column(
            "name", width=180, minwidth=120, stretch=False
        )
        self.youtube_tree.column(
            "url", width=480, minwidth=250, stretch=True
        )

        youtube_scrollbar = ttk.Scrollbar(
            youtube_frame, orient="vertical",
            command=self.youtube_tree.yview
        )

        self.youtube_tree.configure(
            yscrollcommand=youtube_scrollbar.set
        )

        self.youtube_tree.grid(row=0, column=0, sticky="nsew")
        youtube_scrollbar.grid(row=0, column=1, sticky="ns")

        youtube_buttons = ttk.Frame(youtube_frame)

        youtube_buttons.grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )

        ttk.Button(
            youtube_buttons, text=t("btn_add"),
            command=self.add_playlist
        ).pack(side="left", padx=(0, 5))

        ttk.Button(
            youtube_buttons, text=t("btn_edit"),
            command=self.edit_playlist
        ).pack(side="left", padx=5)

        ttk.Button(
            youtube_buttons, text=t("btn_delete"),
            command=self.delete_playlist
        ).pack(side="left", padx=5)

        ttk.Button(
            youtube_buttons, text="↑", width=3,
            command=lambda: self.move_item("youtube", -1)
        ).pack(side="left", padx=(15, 2))

        ttk.Button(
            youtube_buttons, text="↓", width=3,
            command=lambda: self.move_item("youtube", 1)
        ).pack(side="left", padx=2)

        self.youtube_tree.bind(
            "<Double-1>",
            lambda event: self.on_tree_double_click(
                event, self.edit_playlist
            )
        )

        # ---------------- Local ----------------

        local_frame = ttk.LabelFrame(
            main, text=t("frame_local"), padding=8
        )

        local_frame.grid(
            row=3, column=0, columnspan=3, sticky="nsew", pady=(0, 10)
        )

        local_frame.rowconfigure(0, weight=1)
        local_frame.columnconfigure(0, weight=1)

        self.local_tree = ttk.Treeview(
            local_frame,
            columns=("name", "folder"),
            show="headings",
            selectmode="browse"
        )

        self.local_tree.heading("name", text=t("col_name"))
        self.local_tree.heading("folder", text=t("col_folder"))

        self.local_tree.column(
            "name", width=180, minwidth=120, stretch=False
        )
        self.local_tree.column(
            "folder", width=480, minwidth=250, stretch=True
        )

        local_scrollbar = ttk.Scrollbar(
            local_frame, orient="vertical",
            command=self.local_tree.yview
        )

        self.local_tree.configure(
            yscrollcommand=local_scrollbar.set
        )

        self.local_tree.grid(row=0, column=0, sticky="nsew")
        local_scrollbar.grid(row=0, column=1, sticky="ns")

        local_buttons = ttk.Frame(local_frame)

        local_buttons.grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )

        ttk.Button(
            local_buttons, text=t("btn_add"),
            command=self.add_local_folder
        ).pack(side="left", padx=(0, 5))

        ttk.Button(
            local_buttons, text=t("btn_edit"),
            command=self.edit_local_folder
        ).pack(side="left", padx=5)

        ttk.Button(
            local_buttons, text=t("btn_delete"),
            command=self.delete_local_folder
        ).pack(side="left", padx=5)

        ttk.Button(
            local_buttons, text="↑", width=3,
            command=lambda: self.move_item("local", -1)
        ).pack(side="left", padx=(15, 2))

        ttk.Button(
            local_buttons, text="↓", width=3,
            command=lambda: self.move_item("local", 1)
        ).pack(side="left", padx=2)

        self.local_tree.bind(
            "<Double-1>",
            lambda event: self.on_tree_double_click(
                event, self.edit_local_folder
            )
        )

        main.columnconfigure(1, weight=1)
        main.rowconfigure(2, weight=1)
        main.rowconfigure(3, weight=1)

        # ---------------- Bottom buttons ----------------

        bottom_frame = ttk.Frame(main)

        bottom_frame.grid(
            row=4, column=0, columnspan=3, sticky="ew", pady=(4, 0)
        )

        ttk.Button(
            bottom_frame, text=t("btn_autodetect"),
            command=self.auto_detect_tools
        ).pack(side="left", padx=5)

        ttk.Button(
            bottom_frame, text=t("btn_update_ytdlp"),
            command=self.update_ytdlp
        ).pack(side="left", padx=5)

        ttk.Label(
            bottom_frame, text=t("label_language")
        ).pack(side="left", padx=(16, 4))

        self.language_var = tk.StringVar()

        language_combo = ttk.Combobox(
            bottom_frame,
            textvariable=self.language_var,
            values=list(LANG_NAMES.values()),
            state="readonly",
            width=10
        )

        language_combo.pack(side="left")

        language_combo.bind(
            "<<ComboboxSelected>>", self.on_language_changed
        )

        ttk.Button(
            bottom_frame, text=t("btn_apply"),
            command=self.save_and_run
        ).pack(side="right", padx=5)

        # ---------------- Status ----------------

        self.status_var = tk.StringVar(value=t("status_ready"))

        status_bar = ttk.Label(
            main,
            textvariable=self.status_var,
            relief="sunken",
            anchor="w",
            padding=(6, 3)
        )

        status_bar.grid(
            row=5, column=0, columnspan=3, sticky="ew", pady=(8, 0)
        )

    def load_data_to_ui(self):

        self._loading = True

        try:
            self.fill_ui_from_config()
        finally:
            self._loading = False

        self.is_modified = False

    def fill_ui_from_config(self):

        self.mpv_var.set(self.config.get("mpv_path", ""))
        self.ytdlp_var.set(self.config.get("yt_dlp_path", ""))

        self.language_var.set(
            LANG_NAMES.get(
                get_language(),
                LANG_NAMES["en"]
            )
        )

        self.refresh_youtube_tree()
        self.refresh_local_tree()

        self.status_var.set(t("status_ready"))

    def on_language_changed(self, event=None):

        chosen = self.language_var.get()

        code = next(
            (
                c for c, name in LANG_NAMES.items()
                if name == chosen
            ),
            None
        )

        if code is None or code == get_language():
            return

        self.update_config_from_ui()

        self.config["language"] = code

        set_language(code)
        apply_gui_fonts()

        self.root.after(10, self.rebuild_ui)

    def rebuild_ui(self):

        self._loading = True

        try:
            self.main_frame.destroy()
            self.build_ui()
            self.fill_ui_from_config()
        finally:
            self._loading = False

        self.check_modified()

    # ========================================================
    # 浏览
    # ========================================================

    def browse_mpv(self):

        path = filedialog.askopenfilename(
            parent=self.root,
            title=t("pick_mpv_title"),
            filetypes=[
                ("MPV executable", "mpv.exe"),
                ("EXE files", "*.exe"),
                ("All files", "*.*")
            ]
        )

        if path:
            self.mpv_var.set(path)

    def browse_ytdlp(self):

        path = filedialog.askopenfilename(
            parent=self.root,
            title=t("pick_ytdlp_title"),
            filetypes=[
                ("yt-dlp executable", "yt-dlp.exe"),
                ("EXE files", "*.exe"),
                ("All files", "*.*")
            ]
        )

        if path:
            self.ytdlp_var.set(path)

    # ========================================================
    # 候选路径收集
    # ========================================================

    @staticmethod
    def _dedup_paths(paths):

        seen = set()
        result = []

        for p in paths:

            if not p:
                continue

            try:
                p = os.path.normpath(p)
            except Exception:
                continue

            if p in seen:
                continue

            seen.add(p)
            result.append(p)

        return result

    def _find_mpv_candidates(self):

        candidates = []

        candidates.append(os.path.join(BASE_DIR, "mpv.exe"))
        candidates.append(os.path.join(BASE_DIR, "mpv", "mpv.exe"))
        candidates.append(os.path.join(BASE_DIR, "tools", "mpv.exe"))
        candidates.append(os.path.join(BASE_DIR, "bin", "mpv.exe"))

        candidates.append(r"C:\Program Files\mpv\mpv.exe")
        candidates.append(r"C:\Program Files (x86)\mpv\mpv.exe")
        candidates.append(r"C:\Program Files\mpv.net\mpv.exe")

        local_appdata = os.environ.get("LOCALAPPDATA", "")
        userprofile = os.environ.get("USERPROFILE", "")

        if local_appdata:

            try:

                candidates.extend(
                    glob.glob(
                        os.path.join(
                            local_appdata,
                            "Microsoft", "WinGet", "Packages",
                            "*mpv*", "**", "mpv.exe"
                        ),
                        recursive=True
                    )
                )

            except Exception:
                pass

            candidates.extend(
                glob.glob(
                    os.path.join(
                        local_appdata, "Programs", "mpv", "mpv.exe"
                    )
                )
            )

            candidates.extend(
                glob.glob(
                    os.path.join(
                        local_appdata, "Programs", "mpv*", "mpv.exe"
                    )
                )
            )

        if userprofile:

            candidates.append(
                os.path.join(userprofile, "scoop", "shims", "mpv.exe")
            )

            candidates.extend(
                glob.glob(
                    os.path.join(
                        userprofile, "scoop", "apps", "mpv",
                        "current", "mpv.exe"
                    )
                )
            )

        which = (shutil.which("mpv.exe") or shutil.which("mpv"))

        if which:
            candidates.append(which)

        return self._dedup_paths(candidates)

    def _find_ytdlp_candidates(self):

        candidates = []

        candidates.append(os.path.join(BASE_DIR, "yt-dlp.exe"))
        candidates.append(os.path.join(BASE_DIR, "tools", "yt-dlp.exe"))
        candidates.append(os.path.join(BASE_DIR, "bin", "yt-dlp.exe"))

        candidates.append(r"C:\Program Files\yt-dlp\yt-dlp.exe")
        candidates.append(r"C:\Program Files (x86)\yt-dlp\yt-dlp.exe")

        local_appdata = os.environ.get("LOCALAPPDATA", "")
        appdata = os.environ.get("APPDATA", "")
        userprofile = os.environ.get("USERPROFILE", "")

        if local_appdata:

            candidates.extend(
                glob.glob(
                    os.path.join(
                        local_appdata, "Python", "pythoncore-*",
                        "Scripts", "yt-dlp.exe"
                    )
                )
            )

            candidates.extend(
                glob.glob(
                    os.path.join(
                        local_appdata, "Programs", "Python",
                        "Python*", "Scripts", "yt-dlp.exe"
                    )
                )
            )

            candidates.extend(
                glob.glob(
                    os.path.join(
                        local_appdata, "Microsoft", "WindowsApps",
                        "yt-dlp.exe"
                    )
                )
            )

        if appdata:

            candidates.extend(
                glob.glob(
                    os.path.join(
                        appdata, "Python", "Python*",
                        "Scripts", "yt-dlp.exe"
                    )
                )
            )

        if userprofile:

            candidates.extend(
                glob.glob(
                    os.path.join(
                        userprofile, "AppData", "Local",
                        "Programs", "Python", "Python*",
                        "Scripts", "yt-dlp.exe"
                    )
                )
            )

            candidates.append(
                os.path.join(userprofile, "scoop", "shims", "yt-dlp.exe")
            )

        if sys.executable:

            python_dir = os.path.dirname(sys.executable)

            candidates.append(
                os.path.join(python_dir, "yt-dlp.exe")
            )

            candidates.append(
                os.path.join(python_dir, "..", "Scripts", "yt-dlp.exe")
            )

            candidates.append(
                os.path.join(python_dir, "Scripts", "yt-dlp.exe")
            )

        which = (shutil.which("yt-dlp.exe") or shutil.which("yt-dlp"))

        if which:
            candidates.append(which)

        return self._dedup_paths(candidates)

    # ========================================================
    # 自动检测
    # ========================================================

    def auto_detect_tools(self):

        found_mpv = ""

        for p in self._find_mpv_candidates():

            if p and os.path.isfile(p):

                found_mpv = p
                break

        found_ytdlp = ""

        for p in self._find_ytdlp_candidates():

            if p and os.path.isfile(p):

                found_ytdlp = p
                break

        messages = []

        if found_mpv and not self.mpv_var.get().strip():

            self.mpv_var.set(found_mpv)
            messages.append(f"MPV: {found_mpv}")

        if found_ytdlp and not self.ytdlp_var.get().strip():

            self.ytdlp_var.set(found_ytdlp)
            messages.append(f"yt-dlp: {found_ytdlp}")

        if messages:

            self.status_var.set(
                t(
                    "status_autodetected",
                    items=t("list_sep").join(messages)
                )
            )

        else:

            self.status_var.set(t("status_nothing_found"))

    # ========================================================
    # 更新 yt-dlp
    # ========================================================

    def update_ytdlp(self):

        if self._ytdlp_updating:

            messagebox.showinfo(
                t("ytdlp_update_title"),
                t("ytdlp_already_updating"),
                parent=self.root
            )

            return

        current = clean_path(self.ytdlp_var.get())
        is_new_install = False

        # ---- 1. 没路径：尝试自动查找 ----
        if not current:

            for p in self._find_ytdlp_candidates():

                if p and os.path.isfile(p):

                    current = p
                    break

        # ---- 2. 还找不到：自动安装到程序目录 ----
        if not current:

            current = os.path.join(BASE_DIR, "yt-dlp.exe")
            is_new_install = True

        # ---- 3. 确认提示 ----
        if is_new_install:

            confirm_text = t("ytdlp_confirm_install", path=current)

        else:

            confirm_text = t("ytdlp_confirm_update", path=current)

        if not messagebox.askyesno(
            t("ytdlp_update_title"),
            confirm_text,
            parent=self.root
        ):
            return

        # ---- 4. 后台执行 ----
        self._ytdlp_updating = True
        self._set_status(t("ytdlp_preparing"))

        def worker():

            try:

                # 4.1 读取本地版本
                local_ver = None

                if not is_new_install and os.path.isfile(current):

                    self._set_status(t("ytdlp_reading_local"))

                    local_ver = self._get_ytdlp_local_version(current)

                self._set_status(
                    t("ytdlp_local_version", version=local_ver or t("ytdlp_unknown_version"))
                )

                # 4.2 查询最新版本
                self._set_status(t("ytdlp_querying_latest"))

                latest_ver = self._get_ytdlp_latest_version()

                self._set_status(
                    t("ytdlp_latest_version", version=latest_ver or t("ytdlp_unknown_version"))
                )

                # 4.3 判断已是最新
                if (
                    local_ver
                    and latest_ver
                    and local_ver.strip() == latest_ver.strip()
                ):

                    self.root.after(
                        0,
                        lambda: self._on_ytdlp_already_latest(
                            current, local_ver
                        )
                    )

                    return

                # 4.4 下载并替换
                self._set_status(t("updating_ytdlp"))

                self._download_and_replace_ytdlp(current)

                self.root.after(
                    0,
                    lambda: self._on_ytdlp_update_done(
                        current, None, is_new_install
                    )
                )

            except PermissionError:

                self.root.after(
                    0,
                    lambda: self._on_ytdlp_update_done(
                        current, "file_in_use", is_new_install
                    )
                )

            except Exception as e:

                err = str(e)

                self.root.after(
                    0,
                    lambda err=err: self._on_ytdlp_update_done(
                        current, err, is_new_install
                    )
                )

        threading.Thread(
            target=worker,
            daemon=True,
            name="YBM-YtdlpUpdater"
        ).start()

    def _set_status(self, text):

        try:
            self.root.after(0, lambda: self.status_var.set(text))
        except Exception:
            pass

    def _get_ytdlp_local_version(self, path):

        try:

            result = subprocess.run(
                [path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=CREATE_NO_WINDOW
            )

            if result.returncode == 0:

                return (result.stdout or "").strip() or None

        except Exception:

            pass

        return None

    def _get_ytdlp_latest_version(self):

        import urllib.request
        import urllib.error
        import re

        captured_url = []

        class _CaptureRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                captured_url.append(newurl)
                return None

        try:

            opener = urllib.request.build_opener(_CaptureRedirect)

            url = (
                "https://github.com/yt-dlp/yt-dlp/releases/"
                "latest/download/yt-dlp.exe"
            )

            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 YBM-Config-Editor"}
            )

            try:
                opener.open(req, timeout=10)
            except urllib.error.HTTPError:
                pass

            if captured_url:

                m = re.search(
                    r"/releases/download/([^/]+)/",
                    captured_url[0]
                )

                if m:
                    return m.group(1).strip() or None

        except Exception:

            pass

        return None

    def _download_and_replace_ytdlp(self, target_path):

        import urllib.request

        url = (
            "https://github.com/yt-dlp/yt-dlp/releases/latest/"
            "download/yt-dlp.exe"
        )

        target_dir = os.path.dirname(target_path) or BASE_DIR

        fd, tmp_path = tempfile.mkstemp(
            prefix="yt-dlp-new-",
            suffix=".exe",
            dir=target_dir
        )

        os.close(fd)

        try:

            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 YBM-Config-Editor"}
            )

            with urllib.request.urlopen(req, timeout=60) as resp:

                with open(tmp_path, "wb") as f:

                    shutil.copyfileobj(resp, f)

            size = os.path.getsize(tmp_path)

            if size < 1024 * 1024:

                raise RuntimeError(
                    "Downloaded file is too small "
                    "({size} bytes), the download may have failed."
                    .format(size=size)
                )

            try:

                os.replace(tmp_path, target_path)

            except PermissionError:

                raise PermissionError("file_in_use")

        finally:

            if os.path.exists(tmp_path):

                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    def _on_ytdlp_already_latest(self, path, version):

        self._ytdlp_updating = False
        self.status_var.set(t("status_ready"))

        if self.ytdlp_var.get().strip() != path:

            self.ytdlp_var.set(path)
            self.check_modified()

        messagebox.showinfo(
            t("ytdlp_update_title"),
            t("ytdlp_already_latest", version=version),
            parent=self.root
        )

    def _on_ytdlp_update_done(self, target_path, error, is_new_install=False):

        self._ytdlp_updating = False
        self.status_var.set(t("status_ready"))

        if error is None:

            if is_new_install or not self.ytdlp_var.get().strip():

                self.ytdlp_var.set(target_path)
                self.check_modified()

            if is_new_install:

                messagebox.showinfo(
                    t("ytdlp_update_title"),
                    t("ytdlp_install_success", path=target_path),
                    parent=self.root
                )

            else:

                messagebox.showinfo(
                    t("ytdlp_update_title"),
                    t("ytdlp_update_success", path=target_path),
                    parent=self.root
                )

            return

        if error == "file_in_use":

            messagebox.showwarning(
                t("ytdlp_update_title"),
                t("ytdlp_in_use_detail"),
                parent=self.root
            )

        else:

            messagebox.showerror(
                t("ytdlp_update_title"),
                t("ytdlp_update_failed", error=error),
                parent=self.root
            )

    # ========================================================
    # Treeview 双击
    # ========================================================

    def on_tree_double_click(self, event, handler):

        tree = event.widget

        region = tree.identify_region(event.x, event.y)

        if region != "cell":
            return

        if not tree.selection():
            return

        handler()

    # ========================================================
    # 移动列表项
    # ========================================================

    def move_item(self, which, direction):

        if which == "youtube":

            tree = self.youtube_tree
            key = "youtube_playlists"

        else:

            tree = self.local_tree
            key = "local_music_folders"

        selected = tree.selection()

        if not selected:

            messagebox.showinfo(
                t("hint_title"),
                t("select_item_first"),
                parent=self.root
            )

            return

        item_id = selected[0]

        index = tree.index(item_id)

        new_index = index + direction

        items = self.config[key]

        if new_index < 0 or new_index >= len(items):
            return

        items[index], items[new_index] = items[new_index], items[index]

        if which == "youtube":
            self.refresh_youtube_tree()
        else:
            self.refresh_local_tree()

        children = tree.get_children()

        if new_index < len(children):

            tree.selection_set(children[new_index])
            tree.see(children[new_index])

        self.check_modified()

    # ========================================================
    # YouTube 列表
    # ========================================================

    def refresh_youtube_tree(self):

        for item in self.youtube_tree.get_children():

            self.youtube_tree.delete(item)

        for playlist in self.config.get("youtube_playlists", []):

            self.youtube_tree.insert(
                "",
                "end",
                values=(playlist.get("name", ""), playlist.get("url", ""))
            )

    def add_playlist(self):

        dialog = PlaylistDialog(self.root, title=t("dlg_add_playlist"))

        self.root.wait_window(dialog.window)

        if dialog.result is None:
            return

        self.config["youtube_playlists"].append(dialog.result)

        self.refresh_youtube_tree()
        self.check_modified()

    def edit_playlist(self):

        selected = self.youtube_tree.selection()

        if not selected:

            messagebox.showinfo(
                t("hint_title"),
                t("select_playlist_first"),
                parent=self.root
            )

            return

        item_id = selected[0]

        index = self.youtube_tree.index(item_id)

        playlists = self.config["youtube_playlists"]

        if index < 0 or index >= len(playlists):
            return

        playlist = playlists[index]

        dialog = PlaylistDialog(
            self.root,
            title=t("dlg_edit_playlist"),
            name=playlist.get("name", ""),
            url=playlist.get("url", "")
        )

        self.root.wait_window(dialog.window)

        if dialog.result is None:
            return

        playlists[index] = dialog.result

        self.refresh_youtube_tree()

        children = self.youtube_tree.get_children()

        if index < len(children):

            self.youtube_tree.selection_set(children[index])

        self.check_modified()

    def delete_playlist(self):

        selected = self.youtube_tree.selection()

        if not selected:

            messagebox.showinfo(
                t("hint_title"),
                t("select_playlist_first"),
                parent=self.root
            )

            return

        item_id = selected[0]

        index = self.youtube_tree.index(item_id)

        playlists = self.config["youtube_playlists"]

        if index < 0 or index >= len(playlists):
            return

        playlist = playlists[index]

        name = playlist.get("name", t("unnamed"))

        if not messagebox.askyesno(
            t("confirm_delete_title"),
            t("confirm_delete_playlist", name=name),
            parent=self.root
        ):
            return

        del playlists[index]

        self.refresh_youtube_tree()
        self.check_modified()

    # ========================================================
    # 本地音乐文件夹
    # ========================================================

    def refresh_local_tree(self):

        for item in self.local_tree.get_children():

            self.local_tree.delete(item)

        for folder in self.config.get("local_music_folders", []):

            self.local_tree.insert(
                "",
                "end",
                values=(folder.get("name", ""), folder.get("folder", ""))
            )

    def add_local_folder(self):

        dialog = FolderDialog(self.root, title=t("dlg_add_folder"))

        self.root.wait_window(dialog.window)

        if dialog.result is None:
            return

        self.config["local_music_folders"].append(dialog.result)

        self.refresh_local_tree()
        self.check_modified()

    def edit_local_folder(self):

        selected = self.local_tree.selection()

        if not selected:

            messagebox.showinfo(
                t("hint_title"),
                t("select_folder_first"),
                parent=self.root
            )

            return

        item_id = selected[0]

        index = self.local_tree.index(item_id)

        folders = self.config["local_music_folders"]

        if index < 0 or index >= len(folders):
            return

        folder = folders[index]

        dialog = FolderDialog(
            self.root,
            title=t("dlg_edit_folder"),
            name=folder.get("name", ""),
            folder=folder.get("folder", "")
        )

        self.root.wait_window(dialog.window)

        if dialog.result is None:
            return

        folders[index] = dialog.result

        self.refresh_local_tree()

        children = self.local_tree.get_children()

        if index < len(children):

            self.local_tree.selection_set(children[index])

        self.check_modified()

    def delete_local_folder(self):

        selected = self.local_tree.selection()

        if not selected:

            messagebox.showinfo(
                t("hint_title"),
                t("select_folder_first"),
                parent=self.root
            )

            return

        item_id = selected[0]

        index = self.local_tree.index(item_id)

        folders = self.config["local_music_folders"]

        if index < 0 or index >= len(folders):
            return

        folder = folders[index]

        name = folder.get("name", t("unnamed"))

        if not messagebox.askyesno(
            t("confirm_delete_title"),
            t("confirm_delete_folder", name=name),
            parent=self.root
        ):
            return

        del folders[index]

        self.refresh_local_tree()
        self.check_modified()

    # ========================================================
    # 从 UI 同步到 config
    # ========================================================

    def update_config_from_ui(self):

        self.config["mpv_path"] = self.mpv_var.get().strip()
        self.config["yt_dlp_path"] = self.ytdlp_var.get().strip()

    # ========================================================
    # 校验
    # ========================================================

    def validate_for_run(self):

        self.update_config_from_ui()

        mpv_path = clean_path(self.config.get("mpv_path", ""))
        ytdlp_path = clean_path(self.config.get("yt_dlp_path", ""))

        playlists = self.config.get("youtube_playlists", [])
        folders = self.config.get("local_music_folders", [])

        errors = []

        if not mpv_path:

            errors.append(t("err_mpv_unset"))

        elif not os.path.isfile(mpv_path):

            errors.append(t("err_mpv_missing", path=mpv_path))

        if not ytdlp_path:

            errors.append(t("err_ytdlp_unset"))

        elif not os.path.isfile(ytdlp_path):

            errors.append(t("err_ytdlp_missing", path=ytdlp_path))

        valid_playlist_count = 0

        for playlist in playlists:

            if not isinstance(playlist, dict):
                continue

            name = str(playlist.get("name", "")).strip()
            url = str(playlist.get("url", "")).strip()

            if name and is_valid_youtube_url(url):

                valid_playlist_count += 1

        valid_folder_count = 0
        invalid_folders = []

        for folder in folders:

            if not isinstance(folder, dict):
                continue

            name = str(folder.get("name", "")).strip()
            path = clean_path(folder.get("folder", ""))

            if not (name and path):
                continue

            if os.path.isdir(path):

                valid_folder_count += 1

            else:

                invalid_folders.append(path)

        if valid_playlist_count == 0 and valid_folder_count == 0:

            errors.append(t("err_no_source"))

        if errors:

            messagebox.showwarning(
                t("incomplete_title"),
                t("incomplete_body", errors="\n\n".join(errors)),
                parent=self.root
            )

            return False

        if invalid_folders:

            if not messagebox.askyesno(
                t("folder_missing_title"),
                t(
                    "invalid_folders_body",
                    folders="\n".join(invalid_folders)
                ),
                parent=self.root
            ):
                return False

        return True

    # ========================================================
    # 保存并应用
    # ========================================================

    def save_and_run(self):

        if not self.validate_for_run():
            return

        if not save_config_file(self.config):
            return

        self.mark_saved()

        self.status_var.set(t("status_stopping"))
        self.root.update_idletasks()

        stop_ybm()

        self.status_var.set(t("status_starting"))
        self.root.update_idletasks()

        if not start_ybm():

            self.status_var.set(t("status_start_failed"))
            return

        self.status_var.set(t("status_started"))

        self.root.after(500, self.root.destroy)

    def on_close(self):

        if not self.is_modified:

            self.root.destroy()
            return

        if messagebox.askyesno(
            t("unsaved_title"),
            t("unsaved_body"),
            parent=self.root
        ):

            self.root.destroy()


# ============================================================
# 主程序
# ============================================================

def main():

    root = tk.Tk()

    try:

        style = ttk.Style()

        if "vista" in style.theme_names():

            style.theme_use("vista")

    except Exception:
        pass

    editor = ConfigEditor(root)

    if editor.config is None:

        try:
            root.destroy()
        except Exception:
            pass

        return

    root.mainloop()


if __name__ == "__main__":
    main()