#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import json
import uuid
import argparse
import subprocess
import threading
import re
import urllib.request
import urllib.error
import webbrowser
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import register_menu

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False

# ─────────────────────────────────────────────
# タスクバー進捗表示用 (Windows API)
# ─────────────────────────────────────────────
import ctypes
from ctypes import wintypes

TBPF_NOPROGRESS = 0
TBPF_INDETERMINATE = 1  # 準備 (緑のアニメーション)
TBPF_NORMAL = 2         # 通常 (システム設定色, デフォルトで緑または青)
TBPF_ERROR = 4          # エラー (赤)
TBPF_PAUSED = 8         # 一時停止 (黄)

try:
    import comtypes.client
    from comtypes import GUID, IUnknown, COMMETHOD, HRESULT
    from ctypes.wintypes import HWND, DWORD
    
    class ITaskbarList3(IUnknown):
        _iid_ = GUID('{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}')
        _methods_ = [
            COMMETHOD([], HRESULT, 'HrInit'),
            COMMETHOD([], HRESULT, 'AddTab', (['in'], HWND, 'hwnd')),
            COMMETHOD([], HRESULT, 'DeleteTab', (['in'], HWND, 'hwnd')),
            COMMETHOD([], HRESULT, 'ActivateTab', (['in'], HWND, 'hwnd')),
            COMMETHOD([], HRESULT, 'SetActiveAlt', (['in'], HWND, 'hwnd')),
            COMMETHOD([], HRESULT, 'MarkFullscreenWindow', (['in'], HWND, 'hwnd'), (['in'], ctypes.c_int, 'fFullscreen')),
            COMMETHOD([], HRESULT, 'SetProgressValue', (['in'], HWND, 'hwnd'), (['in'], ctypes.c_uint64, 'ullCompleted'), (['in'], ctypes.c_uint64, 'ullTotal')),
            COMMETHOD([], HRESULT, 'SetProgressState', (['in'], HWND, 'hwnd'), (['in'], DWORD, 'tbpFlags')),
        ]
    CLSID_TaskbarList = GUID('{56FDF344-FD6D-11D0-958A-006097C9A090}')
    
    has_taskbar_api = True
except ImportError:
    has_taskbar_api = False

class TaskbarProgress:
    def __init__(self, tk_root):
        self.root = tk_root
        self.hwnd = None
        self.taskbar = None
        if has_taskbar_api:
            try:
                tk_root.update_idletasks()
                self.hwnd = int(tk_root.wm_frame(), 16)
                self.taskbar = comtypes.client.CreateObject(CLSID_TaskbarList, interface=ITaskbarList3)
                self.taskbar.HrInit()
            except Exception as e:
                print(f"Taskbar API init error: {e}")
                self.taskbar = None

    def set_state(self, state):
        def _do():
            if self.taskbar and self.hwnd:
                try:
                    self.taskbar.SetProgressState(self.hwnd, state)
                except Exception:
                    pass
        if hasattr(self, 'root') and self.root:
            self.root.after(0, _do)

    def set_value(self, current, total):
        def _do():
            if self.taskbar and self.hwnd:
                try:
                    self.taskbar.SetProgressValue(self.hwnd, int(current), int(total))
                except Exception:
                    pass
        if hasattr(self, 'root') and self.root:
            self.root.after(0, _do)

# ─────────────────────────────────────────────
# バージョン情報とリポジトリ設定
# ─────────────────────────────────────────────
# バージョン情報（アプリのタイトルやアップデートチェックに使用）
CURRENT_VERSION = "2.0.1"
GITHUB_REPO = "LunaFleuret/Quick-Compressor"

# ─────────────────────────────────────────────
# 定数とパス解決
# ─────────────────────────────────────────────
def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

APP_DIR = get_app_dir()

def load_custom_font():
    font_path = os.path.join(APP_DIR, "りぃポップ角riipopkr", "RiiPopkkR.otf")
    if os.path.exists(font_path) and sys.platform == "win32":
        try:
            FR_PRIVATE = 0x10
            ctypes.windll.gdi32.AddFontResourceExW(font_path, FR_PRIVATE, 0)
        except Exception as e:
            print(f"Font load error: {e}")

load_custom_font()

_bundled_ffmpeg = os.path.join(APP_DIR, "bin", "ffmpeg.exe")
_bundled_ffprobe = os.path.join(APP_DIR, "bin", "ffprobe.exe")

FFMPEG_PATH = _bundled_ffmpeg if os.path.exists(_bundled_ffmpeg) else "ffmpeg"
FFPROBE_PATH = _bundled_ffprobe if os.path.exists(_bundled_ffprobe) else "ffprobe"

# カラーパレット
COLORS = {
    "bg_dark":      "#f0f2f5",
    "bg_card":      "#ffffff",
    "bg_input":     "#ffffff",
    "accent":       "#005fb8",
    "accent_hover": "#0078d4",
    "accent_press": "#004a90",
    "text":         "#212529",
    "text_dim":     "#6c757d",
    "text_bright":  "#ffffff",
    "success":      "#198754",
    "warning":      "#e58f00",
    "error":        "#dc3545",
    "border":       "#dee2e6",
    "slider_track": "#e9ecef",
    "progress_trough": "#e9ecef",
}

# フォント設定
APP_FONT = "RiiPopkaku-R"


# コーデック定義
CODECS = {
    "自動 (推奨: 環境に合わせて自動選択)": {"encoder": "auto", "ext": "mp4"},
    "H.264 (NVIDIA NVENC)": {"encoder": "h264_nvenc", "ext": "mp4"},
    "HEVC / H.265 (NVIDIA NVENC)": {"encoder": "hevc_nvenc", "ext": "mp4"},
    "AV1 (NVIDIA NVENC)": {"encoder": "av1_nvenc", "ext": "mp4"},
    "H.264 (AMD AMF)": {"encoder": "h264_amf", "ext": "mp4"},
    "HEVC / H.265 (AMD AMF)": {"encoder": "hevc_amf", "ext": "mp4"},
    "AV1 (AMD AMF)": {"encoder": "av1_amf", "ext": "mp4"},
}

FRAME_RATES = ["元のまま", "24", "30", "60"]
RESOLUTIONS = ["元のまま", "1440p", "1080p", "720p", "480p"]

# CUVIDデコーダーマッピング（GPU読み込み最適化用）
CUVID_DECODERS = {
    "h264": "h264_cuvid",
    "hevc": "hevc_cuvid",
    "vp9": "vp9_cuvid",
    "mpeg4": "mpeg4_cuvid",
    "mpeg2video": "mpeg2_cuvid",
    "mpeg1video": "mpeg1_cuvid",
    "vp8": "vp8_cuvid",
}

# NVENCプリセット定義
NVENC_PRESETS = [
    ("p1", "最速（ファイルサイズ大）"),
    ("p2", "高速"),
    ("p3", "やや速い"),
    ("p4", "標準（バランス）"),
    ("p5", "やや遅い"),
    ("p6", "低速"),
    ("p7", "最遅（ファイルサイズ小）"),
]


# ─────────────────────────────────────────────
# ユーティリティ関数
# ─────────────────────────────────────────────
def detect_gpu_and_default_codec() -> str:
    """初期選択のデフォルトコーデックを返す"""
    return "自動 (推奨: 環境に合わせて自動選択)"

def get_video_info(filepath: str) -> dict:
    """FFprobeで動画の情報を取得する"""
    cmd = [
        FFPROBE_PATH,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        filepath,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
            encoding="utf-8", errors="replace"
        )
        data = json.loads(result.stdout)
    except Exception as e:
        return {"error": str(e)}

    # ビデオストリームを探す
    video_stream = None
    audio_stream = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and video_stream is None:
            video_stream = stream
        elif stream.get("codec_type") == "audio" and audio_stream is None:
            audio_stream = stream

    if not video_stream:
        return {"error": "動画ストリームが見つかりません"}

    # フレームレート解析
    fps_str = video_stream.get("r_frame_rate", "0/1")
    try:
        num, den = fps_str.split("/")
        fps = round(int(num) / int(den), 2)
    except (ValueError, ZeroDivisionError):
        fps = 0

    # ビットレート
    bitrate = int(video_stream.get("bit_rate", 0) or data.get("format", {}).get("bit_rate", 0) or 0)
    duration = float(data.get("format", {}).get("duration", 0) or 0)
    filesize = int(data.get("format", {}).get("size", 0) or 0)

    width = int(video_stream.get("width", 0))
    height = int(video_stream.get("height", 0))

    # 回転情報の取得
    rotation = 0
    tags = video_stream.get("tags", {})
    if "rotate" in tags:
        try:
            rotation = int(float(tags["rotate"]))
        except ValueError:
            pass
    for side_data in video_stream.get("side_data_list", []):
        if "rotation" in side_data:
            try:
                rotation = int(float(side_data["rotation"]))
            except ValueError:
                pass
                
    if abs(rotation) in (90, 270):
        width, height = height, width

    info = {
        "width": width,
        "height": height,
        "fps": fps,
        "bitrate": bitrate,
        "duration": duration,
        "filesize": filesize,
        "codec": video_stream.get("codec_name", "不明"),
        "has_audio": audio_stream is not None,
        "rotation": rotation,
    }
    return info


def format_filesize(size_bytes: int) -> str:
    """ファイルサイズを人間が読みやすい形式にフォーマット"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    else:
        return f"{size_bytes / (1024 ** 3):.2f} GB"


def format_duration(seconds: float) -> str:
    """秒数を hh:mm:ss 形式にフォーマット"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_bitrate(bps: int) -> str:
    """ビットレートを見やすくフォーマット"""
    if bps <= 0:
        return "不明"
    kbps = bps / 1000
    if kbps < 1000:
        return f"{kbps:.0f} kbps"
    return f"{kbps / 1000:.1f} Mbps"


# ─────────────────────────────────────────────
# メインアプリケーションクラス
# ─────────────────────────────────────────────
class QuickCompressorApp:
    def __init__(self, root: tk.Tk, input_path: str,
                 auto_start: bool = False,
                 preset: str = "p4",
                 fps: str = "元のまま",
                 resolution: str = "元のまま",
                 cq: int = 25,
                 audio_mode: str = "copy",
                 no_audio: bool = False,
                 target_size_mb: float = None,
                 codec: str = None,
                 auto_close: bool = False):
        self.preset_mode = False
        self.root = root
        self.input_paths = [input_path] if input_path else []
        self.input_path = input_path
        self.current_file_index = 0
        self.batch_saved_bytes = 0
        self.is_converting = False
        self.process = None

        if codec is None:
            codec = detect_gpu_and_default_codec()

        # ウィンドウ設定
        self.root.title(f"Quick Compressor v{CURRENT_VERSION}")
        self.root.configure(bg=COLORS["bg_dark"])
        self.root.resizable(False, False)

        # DPI対応
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        # 動画情報を取得
        if self.input_path:
            self.video_info = get_video_info(self.input_path)
            if "error" in self.video_info:
                messagebox.showerror("エラー", f"動画の読み込みに失敗しました:\n{self.video_info['error']}")
                sys.exit(1)
        else:
            self.video_info = {
                "width": 1920, "height": 1080, "fps": 60, "bitrate": 0, "duration": 0, "filesize": 0, "codec": "-", "has_audio": True
            }

        # 設定ファイルから設定を読み込む
        config_path = os.path.join(register_menu.DATA_DIR, "config.json")
        saved_auto_close = False
        saved_hide_no_audio = False
        saved_keep_metadata = True
        saved_force_auto_close_on_right_click = False
        saved_minimize_on_right_click = False
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    if "auto_close" in config:
                        saved_auto_close = bool(config["auto_close"])
                    if "preset" in config:
                        preset = config["preset"]
                    if "hide_no_audio_presets" in config:
                        saved_hide_no_audio = bool(config["hide_no_audio_presets"])
                    if "keep_metadata" in config:
                        saved_keep_metadata = bool(config["keep_metadata"])
                    if "force_auto_close_on_right_click" in config:
                        saved_force_auto_close_on_right_click = bool(config["force_auto_close_on_right_click"])
                    if "minimize_on_right_click" in config:
                        saved_minimize_on_right_click = bool(config["minimize_on_right_click"])
            except Exception:
                pass

        # コマンドライン引数(--auto-close)が指定されていれば、そちらを優先する
        if auto_close:
            saved_auto_close = True

        # 詳細設定変数
        self.preset_var = tk.StringVar(value=preset)
        self.audio_mode_var = tk.StringVar(value=audio_mode)
        self.auto_close_var = tk.BooleanVar(value=saved_auto_close)
        self.hide_no_audio_presets_var = tk.BooleanVar(value=saved_hide_no_audio)
        self.keep_metadata_var = tk.BooleanVar(value=saved_keep_metadata)
        self.force_auto_close_on_right_click_var = tk.BooleanVar(value=saved_force_auto_close_on_right_click)
        self.minimize_on_right_click_var = tk.BooleanVar(value=saved_minimize_on_right_click)

        # UI用初期値保持
        self._init_fps = fps
        self._init_resolution = resolution
        self._init_cq = cq
        self._init_no_audio = no_audio
        self._auto_start = auto_start
        self._target_size_mb = target_size_mb
        self._init_codec = codec

        # UI用ttkスタイルの設定（完全ダークモード専用）
        style = ttk.Style()
        style.theme_use("default")
        style.configure(".", background=COLORS["bg_dark"], foreground=COLORS["text"], 
                        fieldbackground=COLORS["bg_input"], selectbackground=COLORS["accent"], 
                        selectforeground=COLORS["text_bright"], bordercolor=COLORS["border"], 
                        darkcolor=COLORS["border"], lightcolor=COLORS["border"])
        style.map("TCombobox", fieldbackground=[("readonly", COLORS["bg_input"])], selectbackground=[("readonly", COLORS["bg_input"])], selectforeground=[("readonly", COLORS["text"])])
        style.configure("Horizontal.TScale", background=COLORS["accent"], troughcolor=COLORS["progress_trough"])
        style.map("Horizontal.TScale", background=[("active", COLORS["accent"])])
        style.configure("Custom.Horizontal.TProgressbar", troughcolor=COLORS["progress_trough"], background=COLORS["accent"], thickness=8)

        # UI構築
        self._build_ui()
        
        # タスクバー進捗用オブジェクトの初期化
        self.taskbar_progress = TaskbarProgress(self.root)

        # 自動開始処理
        if self._auto_start:
            self.root.after(100, self._start_conversion)
            if self.minimize_on_right_click_var.get():
                self.root.iconify()

        # ウィンドウをマウスポインターがある位置（画面）に配置（マルチディスプレイ対応）
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        pointer_x, pointer_y = self.root.winfo_pointerxy()
        x = pointer_x - (w // 2)
        y = pointer_y - (h // 2)

        # 画面外にはみ出ないように補正 (Windows用)
        try:
            import ctypes
            from ctypes import wintypes
            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)
                ]
            MONITOR_DEFAULTTONEAREST = 2
            pt = wintypes.POINT(pointer_x, pointer_y)
            h_monitor = ctypes.windll.user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
            if h_monitor:
                monitor_info = MONITORINFO()
                monitor_info.cbSize = ctypes.sizeof(MONITORINFO)
                if ctypes.windll.user32.GetMonitorInfoW(h_monitor, ctypes.byref(monitor_info)):
                    work_rect = monitor_info.rcWork
                    min_x, min_y = work_rect.left, work_rect.top
                    max_x, max_y = work_rect.right - w, work_rect.bottom - h
                    x = max(min_x, min(x, max_x))
                    y = max(min_y, min(y, max_y))
        except Exception:
            pass

        # 横幅を固定し、縦幅のみ自動調整を許可（プリセットメニュー展開時にボタンが見えなくなるのを防ぐため）
        self.root.minsize(w, h)
        self.root.maxsize(w, 9999)
        self.root.geometry(f"+{x}+{y}")
        
        # 警告ラベルなどのテキストが横幅を押し広げないように、現在の横幅に合わせて自動改行（wraplength）を設定
        if hasattr(self, 'resolution_warning_label'):
            self.resolution_warning_label.configure(wraplength=w - 60)

        # ウィンドウのどこでもドラッグ移動できるように設定
        self._enable_window_drag()

    def _enable_window_drag(self):
        def start_drag(event):
            ignore_classes = ("Button", "TButton", "TCombobox", "TScale", "Radiobutton", "TRadiobutton", "Checkbutton", "TCheckbutton")
            if event.widget.winfo_class() in ignore_classes or getattr(event.widget, '_is_file_card', False):
                self.root._drag_start_x = None
                return
            self.root._drag_start_x = event.x_root - self.root.winfo_x()
            self.root._drag_start_y = event.y_root - self.root.winfo_y()

        def dragging(event):
            if getattr(self.root, '_drag_start_x', None) is None:
                return
            x = event.x_root - self.root._drag_start_x
            y = event.y_root - self.root._drag_start_y
            self.root.geometry(f"+{x}+{y}")

        self.root.bind("<ButtonPress-1>", start_drag)
        self.root.bind("<B1-Motion>", dragging)

        if HAS_DND:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind('<<Drop>>', self._on_drop)
            self.root.dnd_bind('<<DropEnter>>', self._on_drop_enter)
            self.root.dnd_bind('<<DropPosition>>', self._on_drop_enter)

        # アップデートチェック（非同期）
        threading.Thread(target=self._check_for_updates, daemon=True).start()

    # ─────────────────────────────────────────
    # UI構築
    # ─────────────────────────────────────────
    def _build_ui(self):
        # メインコンテナ (枠線用に highlightthickness を設定)
        self.main_frame = tk.Frame(self.root, bg=COLORS["bg_dark"], padx=24, pady=20,
                                   highlightbackground=COLORS["bg_dark"], highlightthickness=8)
        self.main_frame.pack(fill="both", expand=True)
        main_frame = self.main_frame

        # --- プリセット作成モード バナー (初期は非表示) ---
        self.preset_banner = tk.Frame(main_frame, bg=COLORS["success"], pady=12)
        self.preset_banner_label = tk.Label(
            self.preset_banner, text="プリセット作成モード：現在の設定をプリセットとして保存できます",
            font=(APP_FONT, 13), fg=COLORS["text_bright"], bg=COLORS["success"]
        )
        self.preset_banner_label.pack()

        # --- タイトル ---
        self.title_frame = tk.Frame(main_frame, bg=COLORS["bg_dark"])
        self.title_frame.pack(fill="x", pady=(0, 8))

        tk.Label(
            self.title_frame, text="⚡ Quick Compressor",
            font=(APP_FONT, 19), fg=COLORS["accent"], bg=COLORS["bg_dark"]
        ).pack(side="left")

        # --- サブアクションバー (2段目) ---
        self.action_frame = tk.Frame(main_frame, bg=COLORS["bg_dark"])
        self.action_frame.pack(fill="x", pady=(0, 16))

        # ピン留めボタン (Always on top)
        self.is_topmost = False
        self.pin_btn = tk.Button(
            self.action_frame, text="📌 最前面",
            font=(APP_FONT, 11), fg=COLORS["text_dim"],
            bg=COLORS["bg_card"], activebackground=COLORS["bg_input"],
            activeforeground=COLORS["accent"],
            relief="flat", cursor="hand2", padx=8, pady=2,
            highlightbackground=COLORS["border"], highlightthickness=1,
            command=self._toggle_topmost,
        )
        self.pin_btn.pack(side="right")
        
        # デフォルトで最前面に固定
        self._toggle_topmost()

        # 設定ボタン
        settings_btn = tk.Button(
            self.action_frame, text="⚙ 設定",
            font=(APP_FONT, 11), fg=COLORS["text_dim"],
            bg=COLORS["bg_card"], activebackground=COLORS["bg_input"],
            activeforeground=COLORS["accent"],
            relief="flat", cursor="hand2", padx=8, pady=2,
            highlightbackground=COLORS["border"], highlightthickness=1,
            command=self._open_settings,
        )
        settings_btn.pack(side="right", padx=(0, 8))

        # プリセット作成ボタン
        self.preset_btn = tk.Button(
            self.action_frame, text="プリセット作成",
            font=(APP_FONT, 11), fg=COLORS["success"],
            bg=COLORS["bg_card"], activebackground=COLORS["bg_input"],
            activeforeground=COLORS["success"],
            relief="flat", cursor="hand2", padx=8, pady=2,
            highlightbackground=COLORS["border"], highlightthickness=1,
            command=self._toggle_preset_mode,
        )
        self.preset_btn.pack(side="right", padx=(0, 8))

        preset_manage_btn = tk.Button(
            self.action_frame, text="プリセット管理",
            font=(APP_FONT, 11), fg=COLORS["accent"],
            bg=COLORS["bg_card"], activebackground=COLORS["bg_input"],
            activeforeground=COLORS["accent"],
            relief="flat", cursor="hand2", padx=8, pady=2,
            highlightbackground=COLORS["border"], highlightthickness=1,
            command=self._open_preset_manager,
        )
        preset_manage_btn.pack(side="right", padx=(0, 8))

        # --- ファイル情報カード ---
        self._build_file_info_card(main_frame)

        # --- セパレーター ---
        tk.Frame(main_frame, bg=COLORS["border"], height=1).pack(fill="x", pady=12)

        # --- 設定エリア ---
        self._build_settings(main_frame)

        # --- セパレーター ---
        tk.Frame(main_frame, bg=COLORS["border"], height=1).pack(fill="x", pady=12)

        # --- 進捗 + 変換ボタン ---
        self._build_progress_area(main_frame)

    def _build_file_info_card(self, parent):
        """ファイル情報カードの構築"""
        self.card_frame = tk.Frame(parent, bg=COLORS["bg_card"], padx=16, pady=12,
                        highlightbackground=COLORS["border"], highlightthickness=1)
        self.card_frame.pack(fill="x", pady=(0, 4))

        if not self.input_path:
            self._build_empty_file_info()
        else:
            self._build_populated_file_info()

    def _build_empty_file_info(self):
        for widget in self.card_frame.winfo_children():
            widget.destroy()
        btn = tk.Button(
            self.card_frame, text="動画ファイルを選択 または ドロップ",
            font=(APP_FONT, 12), fg=COLORS["accent"], bg=COLORS["bg_card"],
            activebackground=COLORS["bg_input"], activeforeground=COLORS["accent_hover"],
            relief="flat", cursor="hand2", pady=8,
            command=self._select_file
        )
        btn.pack(fill="x")

    def _build_populated_file_info(self):
        for widget in self.card_frame.winfo_children():
            widget.destroy()

        def bind_click(widget):
            widget.bind("<ButtonRelease-1>", lambda e: self._select_file())
            widget.configure(cursor="hand2")
            widget._is_file_card = True
            for child in widget.winfo_children():
                bind_click(child)

        header_frame = tk.Frame(self.card_frame, bg=COLORS["bg_card"])
        header_frame.pack(fill="x")
            
        tk.Label(
            header_frame, text="※クリック または ドロップで変更",
            font=(APP_FONT, 10), fg=COLORS["accent"], bg=COLORS["bg_card"],
        ).pack(side="right")
        
        if hasattr(self, 'input_paths') and len(self.input_paths) > 1:
            # 複数ファイルの場合の表示
            tk.Label(
                header_frame, text=f"📁 {len(self.input_paths)} 個のファイルが選択されています",
                font=(APP_FONT, 12), fg=COLORS["text"], bg=COLORS["bg_card"],
                anchor="w"
            ).pack(side="left", fill="x", expand=True)
            
            detail_frame = tk.Frame(self.card_frame, bg=COLORS["bg_card"])
            detail_frame.pack(fill="x", pady=(6, 0))
            tk.Label(detail_frame, text="先頭のファイルに基づいて容量制限などを予測・計算します", fg=COLORS["text_dim"],
                     bg=COLORS["bg_card"], font=(APP_FONT, 9)).pack(side="left")
        else:
            # 1つの場合のファイル名
            file_path = Path(self.input_path)
            filename = file_path.name
            MAX_LEN = 22
            if len(filename) > MAX_LEN:
                ext = file_path.suffix
                stem_len = MAX_LEN - len(ext) - 3
                if stem_len > 0:
                    filename = file_path.stem[:stem_len] + "..." + ext
                else:
                    filename = filename[:MAX_LEN-3] + "..."
            
            tk.Label(
                header_frame, text=f"📁 {filename}",
                font=(APP_FONT, 12), fg=COLORS["text"], bg=COLORS["bg_card"],
                anchor="w"
            ).pack(side="left", fill="x", expand=True)

            # 詳細情報行
            info = self.video_info
            detail_frame = tk.Frame(self.card_frame, bg=COLORS["bg_card"])
            detail_frame.pack(fill="x", pady=(6, 0))

            details = [
                f"{info['width']}×{info['height']}",
                f"{info['fps']} fps",
                f"{info['codec'].upper()}",
                format_bitrate(info['bitrate']),
                format_duration(info['duration']),
                format_filesize(info['filesize']),
            ]

            for i, detail in enumerate(details):
                if i > 0:
                    tk.Label(detail_frame, text="  •  ", fg=COLORS["text_dim"],
                             bg=COLORS["bg_card"], font=(APP_FONT, 9)).pack(side="left")
                tk.Label(detail_frame, text=detail, fg=COLORS["text_dim"],
                         bg=COLORS["bg_card"], font=(APP_FONT, 9)).pack(side="left")

        # クリックイベントを全体に適用
        bind_click(self.card_frame)

    def _toggle_topmost(self):
        self.is_topmost = not self.is_topmost
        self.root.attributes("-topmost", self.is_topmost)
        if self.is_topmost:
            self.pin_btn.configure(fg=COLORS["accent"], bg=COLORS["bg_input"], text="📍 固定中")
        else:
            self.pin_btn.configure(fg=COLORS["text_dim"], bg=COLORS["bg_card"], text="📌 最前面")

    def _on_drop_enter(self, event):
        if getattr(self, 'is_converting', False):
            return
        if getattr(self, '_drop_overlay', None) is not None and self._drop_overlay.winfo_exists():
            return event.action
            
        print(f"[DEBUG] _on_drop_enter: {getattr(event, 'action', 'none')}")
        
        # ToplevelではなくFrameを親の上に配置（OSのウィンドウ制御による不具合を回避）
        self._drop_overlay = tk.Frame(self.root, bg=COLORS["bg_dark"], highlightbackground=COLORS["accent"], highlightthickness=4)
        self._drop_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        
        inner_frame = tk.Frame(self._drop_overlay, bg=COLORS["bg_dark"])
        inner_frame.pack(expand=True)
        
        tk.Label(inner_frame, text="📥", font=(APP_FONT, 48), fg=COLORS["accent"], bg=COLORS["bg_dark"]).pack()
        tk.Label(inner_frame, text="ここにドロップして変更", font=(APP_FONT, 25), fg=COLORS["accent"], bg=COLORS["bg_dark"]).pack(pady=10)
        
        if HAS_DND:
            self._drop_overlay.drop_target_register(DND_FILES)
            self._drop_overlay.dnd_bind('<<Drop>>', self._on_drop_from_overlay)
            self._drop_overlay.dnd_bind('<<DropLeave>>', self._on_overlay_drop_leave)
            
        return event.action

    def _on_overlay_drop_leave(self, event):
        print("[DEBUG] _on_overlay_drop_leave")
        if getattr(self, '_drop_overlay', None) is not None and self._drop_overlay.winfo_exists():
            self._drop_overlay.destroy()
            self._drop_overlay = None

    def _on_drop_from_overlay(self, event):
        print("[DEBUG] _on_drop_from_overlay")
        self._on_overlay_drop_leave(None)
        self._on_drop(event)

    def _on_drop(self, event):
        self._on_overlay_drop_leave(None)
        files = self.root.tk.splitlist(event.data)
        if not files:
            return
            
        self.input_paths = list(files)
        self.input_path = self.input_paths[0]
        self.video_info = get_video_info(self.input_path)
        if "error" in self.video_info:
            messagebox.showerror("エラー", f"動画の読み込みに失敗しました:\n{self.video_info['error']}")
            self.input_path = None
            self.input_paths = []
            self._build_empty_file_info()
            self._update_ui_state()
            return
            
        self._build_populated_file_info()
        self._update_ui_state()

    def _select_file(self):
        filepaths = filedialog.askopenfilenames(
            title="変換する動画ファイルを選択（複数選択可）",
            filetypes=[
                ("動画ファイル", "*.mp4 *.mkv *.mov *.avi *.webm *.wmv *.flv *.ts *.m2ts"),
                ("すべてのファイル", "*.*"),
            ],
        )
        if filepaths:
            self.input_paths = list(filepaths)
            self.input_path = self.input_paths[0]
            # 動画情報を再取得
            self.video_info = get_video_info(self.input_path)
            if "error" in self.video_info:
                messagebox.showerror("エラー", f"動画の読み込みに失敗しました:\n{self.video_info['error']}")
                self.input_path = None
                self.input_paths = []
                self._build_empty_file_info()
                self._update_ui_state()
                return
                
            self._build_populated_file_info()
            self._update_ui_state()

    def _build_settings(self, parent):
        """設定エリアの構築"""
        settings_frame = tk.Frame(parent, bg=COLORS["bg_dark"])
        settings_frame.pack(fill="x")

        # --- プリセット適用 ---
        preset_apply_frame = tk.Frame(settings_frame, bg=COLORS["bg_dark"])
        preset_apply_frame.pack(fill="x", pady=(0, 12))

        preset_apply_label_frame = tk.Frame(preset_apply_frame, bg=COLORS["bg_dark"])
        preset_apply_label_frame.pack(fill="x")

        tk.Label(preset_apply_label_frame, text="保存済みのプリセットを適用",
                 font=(APP_FONT, 13), fg=COLORS["text"], bg=COLORS["bg_dark"]
                 ).pack(side="left")

        self.apply_preset_var = tk.StringVar(value="選択してください...")
        self.preset_apply_combo = ttk.Combobox(
            preset_apply_frame, textvariable=self.apply_preset_var,
            state="readonly", font=(APP_FONT, 11)
        )
        self.preset_apply_combo.pack(fill="x", pady=(4, 0))
        self.preset_apply_combo.bind("<<ComboboxSelected>>", self._on_preset_apply_select)
        
        # 初期リストを読み込み
        self.root.after(100, self._update_apply_preset_list)

        # --- 上段: コーデック + フレームレート（横並び）---
        top_row = tk.Frame(settings_frame, bg=COLORS["bg_dark"])
        top_row.pack(fill="x", pady=(0, 12))

        # 出力コーデック
        codec_frame = tk.Frame(top_row, bg=COLORS["bg_dark"])
        codec_frame.pack(side="left", fill="x", expand=True, padx=(0, 8))

        tk.Label(codec_frame, text="出力コーデック",
                 font=(APP_FONT, 13), fg=COLORS["text"], bg=COLORS["bg_dark"]
                 ).pack(anchor="w")

        self.codec_var = tk.StringVar(value=self._init_codec)
        codec_combo = ttk.Combobox(codec_frame, textvariable=self.codec_var,
                                   values=list(CODECS.keys()), state="readonly",
                                   font=(APP_FONT, 11), width=22)
        codec_combo.pack(fill="x", pady=(4, 0))

        # フレームレート
        fps_frame = tk.Frame(top_row, bg=COLORS["bg_dark"])
        fps_frame.pack(side="left", fill="x", expand=True, padx=(8, 0))

        tk.Label(fps_frame, text="フレームレート",
                 font=(APP_FONT, 13), fg=COLORS["text"], bg=COLORS["bg_dark"]
                 ).pack(anchor="w")

        self.fps_var = tk.StringVar(value=self._init_fps)
        fps_btn_frame = tk.Frame(fps_frame, bg=COLORS["bg_dark"])
        fps_btn_frame.pack(fill="x", pady=(4, 0))

        for fps_option in FRAME_RATES:
            btn = tk.Radiobutton(
                fps_btn_frame, text=fps_option, variable=self.fps_var, value=fps_option,
                font=(APP_FONT, 11), fg=COLORS["text"], bg=COLORS["bg_dark"],
                selectcolor=COLORS["bg_input"], activebackground=COLORS["bg_dark"],
                activeforeground=COLORS["accent"], indicatoron=0,
                padx=10, pady=4, relief="flat",
                highlightbackground=COLORS["border"], highlightthickness=1,
            )
            btn.pack(side="left", padx=(0, 4))

        # --- 解像度 ---
        resolution_frame = tk.Frame(settings_frame, bg=COLORS["bg_dark"])
        resolution_frame.pack(fill="x", pady=(0, 12))

        tk.Label(resolution_frame, text="解像度",
                 font=(APP_FONT, 13), fg=COLORS["text"], bg=COLORS["bg_dark"]
                 ).pack(anchor="w")

        self.resolution_var = tk.StringVar(value=self._init_resolution)
        resolution_btn_frame = tk.Frame(resolution_frame, bg=COLORS["bg_dark"])
        resolution_btn_frame.pack(fill="x", pady=(4, 0))

        for res_option in RESOLUTIONS:
            btn = tk.Radiobutton(
                resolution_btn_frame, text=res_option, variable=self.resolution_var, value=res_option,
                font=(APP_FONT, 11), fg=COLORS["text"], bg=COLORS["bg_dark"],
                selectcolor=COLORS["bg_input"], activebackground=COLORS["bg_dark"],
                activeforeground=COLORS["accent"], indicatoron=0,
                padx=10, pady=4, relief="flat",
                highlightbackground=COLORS["border"], highlightthickness=1,
                command=self._on_resolution_change
            )
            btn.pack(side="left", padx=(0, 4))

        # 解像度変換のプレビュー表示
        self.resolution_preview_label = tk.Label(
            resolution_frame,
            text=f"{self.video_info['width']}×{self.video_info['height']} → {self.video_info['width']}×{self.video_info['height']}",
            font=(APP_FONT, 10), fg=COLORS["text_dim"], bg=COLORS["bg_dark"]
        )
        self.resolution_preview_label.pack(anchor="w")

        self.resolution_warning_label = tk.Label(
            resolution_frame,
            text="",
            font=(APP_FONT, 13), fg=COLORS["error"], bg=COLORS["bg_dark"],
            justify="left"
        )
        self.resolution_warning_label.pack(anchor="w", pady=(2, 0))

        # --- 画質 (CQP) / 容量指定 ---
        quality_frame = tk.Frame(settings_frame, bg=COLORS["bg_dark"])
        quality_frame.pack(fill="x", pady=(0, 12))

        # モード選択ラジオボタン
        mode_frame = tk.Frame(quality_frame, bg=COLORS["bg_dark"])
        mode_frame.pack(fill="x", pady=(0, 8))

        tk.Label(mode_frame, text="設定モード",
                 font=(APP_FONT, 13), fg=COLORS["text"], bg=COLORS["bg_dark"]
                 ).pack(side="left", padx=(0, 12))

        self.mode_var = tk.StringVar(value="cq" if not self._target_size_mb else "size")
        
        tk.Radiobutton(
            mode_frame, text="品質優先 (CQ)", variable=self.mode_var, value="cq",
            font=(APP_FONT, 11), fg=COLORS["text"], bg=COLORS["bg_dark"],
            selectcolor=COLORS["bg_input"], activebackground=COLORS["bg_dark"],
            activeforeground=COLORS["accent"], indicatoron=0,
            padx=10, pady=4, relief="flat",
            highlightbackground=COLORS["border"], highlightthickness=1,
            command=self._on_mode_change
        ).pack(side="left", padx=(0, 4))

        tk.Radiobutton(
            mode_frame, text="容量優先 (MB指定)", variable=self.mode_var, value="size",
            font=(APP_FONT, 11), fg=COLORS["text"], bg=COLORS["bg_dark"],
            selectcolor=COLORS["bg_input"], activebackground=COLORS["bg_dark"],
            activeforeground=COLORS["accent"], indicatoron=0,
            padx=10, pady=4, relief="flat",
            highlightbackground=COLORS["border"], highlightthickness=1,
            command=self._on_mode_change
        ).pack(side="left", padx=(0, 4))

        tk.Radiobutton(
            mode_frame, text="割合指定 (%)", variable=self.mode_var, value="percent",
            font=(APP_FONT, 11), fg=COLORS["text"], bg=COLORS["bg_dark"],
            selectcolor=COLORS["bg_input"], activebackground=COLORS["bg_dark"],
            activeforeground=COLORS["accent"], indicatoron=0,
            padx=10, pady=4, relief="flat",
            highlightbackground=COLORS["border"], highlightthickness=1,
            command=self._on_mode_change
        ).pack(side="left", padx=(0, 4))

        # --- 品質優先(CQ)用UI ---
        self.cq_frame = tk.Frame(quality_frame, bg=COLORS["bg_dark"])
        
        quality_label_frame = tk.Frame(self.cq_frame, bg=COLORS["bg_dark"])
        quality_label_frame.pack(fill="x")

        tk.Label(quality_label_frame, text="画質 (品質優先 ← → ファイルサイズ優先)",
                 font=(APP_FONT, 13), fg=COLORS["text"], bg=COLORS["bg_dark"]
                 ).pack(side="left")

        self.quality_value_label = tk.Label(
            quality_label_frame, text="CQ 25 (高画質)",
            font=(APP_FONT, 13), fg=COLORS["success"], bg=COLORS["bg_dark"]
        )
        self.quality_value_label.pack(side="right")

        self.quality_var = tk.IntVar(value=self._init_cq)
        self.quality_slider = ttk.Scale(
            self.cq_frame, from_=15, to=40, orient="horizontal",
            variable=self.quality_var, length=400,
            command=self._on_quality_change
        )
        self.quality_slider.pack(fill="x", pady=(4, 0))

        self.quality_desc_label = tk.Label(
            self.cq_frame,
            text="CQ値が低い ← 高画質・大ファイル ｜ 低画質・小ファイル → CQ値が高い",
            font=(APP_FONT, 10), fg=COLORS["text_dim"], bg=COLORS["bg_dark"]
        )
        self.quality_desc_label.pack(anchor="w")

        # --- 容量優先(MB)用UI ---
        self.size_frame = tk.Frame(quality_frame, bg=COLORS["bg_dark"])

        size_label_frame = tk.Frame(self.size_frame, bg=COLORS["bg_dark"])
        size_label_frame.pack(fill="x")
        
        tk.Label(size_label_frame, text="目標ファイルサイズ (MB)",
                 font=(APP_FONT, 13), fg=COLORS["text"], bg=COLORS["bg_dark"]
                 ).pack(side="left")

        size_input_frame = tk.Frame(self.size_frame, bg=COLORS["bg_dark"])
        size_input_frame.pack(anchor="w", pady=(4, 0))
        
        self.target_size_var = tk.StringVar(value=str(self._target_size_mb) if self._target_size_mb else "10")
        self.target_size_var.trace_add("write", lambda *a: self._check_resolution_warning())
        self.size_combo = ttk.Combobox(
            size_input_frame, textvariable=self.target_size_var,
            values=["8", "10", "25", "30", "50", "100"],
            font=(APP_FONT, 11), width=8
        )
        self.size_combo.pack(side="left")
        
        tk.Label(size_input_frame, text=" MB のサイズまで圧縮",
                 font=(APP_FONT, 13), fg=COLORS["text"], bg=COLORS["bg_dark"]
                 ).pack(side="left", padx=(8, 0))

        tk.Label(
            self.size_frame,
            text="指定した容量に収まるようにビットレートを自動調整します",
            font=(APP_FONT, 10), fg=COLORS["text_dim"], bg=COLORS["bg_dark"]
        ).pack(anchor="w", pady=(4, 0))

        # --- 割合指定(%)用UI ---
        self.percent_frame = tk.Frame(quality_frame, bg=COLORS["bg_dark"])

        percent_label_frame = tk.Frame(self.percent_frame, bg=COLORS["bg_dark"])
        percent_label_frame.pack(fill="x")
        
        tk.Label(percent_label_frame, text="目標ファイルサイズ割合 (%)",
                 font=(APP_FONT, 13), fg=COLORS["text"], bg=COLORS["bg_dark"]
                 ).pack(side="left")

        percent_input_frame = tk.Frame(self.percent_frame, bg=COLORS["bg_dark"])
        percent_input_frame.pack(anchor="w", pady=(4, 0))
        
        self.target_percent_var = tk.StringVar(value="50")
        self.target_percent_var.trace_add("write", lambda *a: self._check_resolution_warning())
        self.percent_combo = ttk.Combobox(
            percent_input_frame, textvariable=self.target_percent_var,
            values=["25", "30", "50", "75", "80"],
            font=(APP_FONT, 11), width=8
        )
        self.percent_combo.pack(side="left")
        
        tk.Label(percent_input_frame, text=" % のサイズまで圧縮",
                 font=(APP_FONT, 13), fg=COLORS["text"], bg=COLORS["bg_dark"]
                 ).pack(side="left", padx=(8, 0))

        tk.Label(
            self.percent_frame,
            text="元のファイルサイズから計算し、指定した割合に収まるように自動調整します",
            font=(APP_FONT, 10), fg=COLORS["text_dim"], bg=COLORS["bg_dark"]
        ).pack(anchor="w", pady=(4, 0))

        # 初期表示の切り替え
        self._on_mode_change()

        # --- 音声 ---
        audio_frame = tk.Frame(settings_frame, bg=COLORS["bg_dark"])
        audio_frame.pack(fill="x", pady=(0, 4))

        self.audio_var = tk.BooleanVar(value=not self._init_no_audio)
        self.audio_check_btn = tk.Checkbutton(
            audio_frame, text="音声を含める",
            variable=self.audio_var,
            font=(APP_FONT, 11), fg=COLORS["text"], bg=COLORS["bg_dark"],
            selectcolor=COLORS["bg_dark"], activebackground=COLORS["bg_dark"],
            activeforeground=COLORS["accent"],
        )
        self.audio_check_btn.pack(anchor="w")

        if not self.video_info.get("has_audio"):
            self.audio_check_btn.configure(state="disabled")
            self.audio_var.set(False)
            self.audio_check_btn.configure(text="音声を含める (元の動画に音声なし)")

        # 初期状態のプレビュー反映
        self._on_resolution_change()
        self._on_quality_change(self._init_cq)

    def _build_progress_area(self, parent):
        """進捗と変換ボタンの構築"""
        progress_frame = tk.Frame(parent, bg=COLORS["bg_dark"])
        progress_frame.pack(fill="x", pady=(4, 0))

        # 進捗バー
        self.progress_var = tk.DoubleVar(value=0)

        # ttkスタイルは__init__で設定

        self.progress_bar = ttk.Progressbar(
            progress_frame, variable=self.progress_var,
            maximum=100, style="Custom.Horizontal.TProgressbar"
        )
        self.progress_bar.pack(fill="x", pady=(0, 6))

        # ステータスラベル
        self.status_label = tk.Label(
            progress_frame, text="準備完了",
            font=(APP_FONT, 9), fg=COLORS["text_dim"], bg=COLORS["bg_dark"],
            anchor="w"
        )
        self.status_label.pack(fill="x")

        # ボタン行
        btn_frame = tk.Frame(progress_frame, bg=COLORS["bg_dark"])
        btn_frame.pack(fill="x", pady=(10, 0))

        # 変換ボタン
        self.convert_btn = tk.Button(
            btn_frame, text="⚡ 圧縮開始",
            font=(APP_FONT, 14), fg=COLORS["text_bright"],
            bg=COLORS["accent"], activebackground=COLORS["accent_hover"],
            activeforeground=COLORS["text_bright"],
            disabledforeground=COLORS["text_bright"],
            relief="flat", padx=32, pady=10, cursor="hand2",
            command=self._start_conversion,
        )
        self.convert_btn.pack(side="right")

        # 中止ボタン（初期状態では非表示）
        self.cancel_btn = tk.Button(
            btn_frame, text="✖ 中止",
            font=(APP_FONT, 12), fg=COLORS["error"],
            bg=COLORS["bg_card"], activebackground=COLORS["bg_input"],
            activeforeground=COLORS["error"],
            relief="flat", padx=16, pady=10, cursor="hand2",
            command=self._cancel_conversion,
            highlightbackground=COLORS["error"], highlightthickness=1
        )

        # ファイルを開くボタン（変換後に表示）
        self.open_btn = tk.Button(
            btn_frame, text="📂 出力先を開く",
            font=(APP_FONT, 10), fg=COLORS["text"],
            bg=COLORS["bg_card"], activebackground=COLORS["bg_input"],
            activeforeground=COLORS["text_bright"],
            relief="flat", padx=16, pady=8, cursor="hand2",
            command=self._open_output_folder,
        )
        # 初期状態では非表示

        self._update_ui_state()

    def _update_ui_state(self):
        if not self.input_path:
            self.convert_btn.configure(state="disabled", bg=COLORS["text_dim"])
            self.resolution_preview_label.configure(text="-")
        else:
            self.convert_btn.configure(state="normal", bg=COLORS["accent"])
            self._on_resolution_change()
            if hasattr(self, 'audio_check_btn'):
                if not self.video_info.get("has_audio"):
                    self.audio_check_btn.configure(state="disabled", text="音声を含める (元の動画に音声なし)")
                    self.audio_var.set(False)
                else:
                    self.audio_check_btn.configure(state="normal", text="音声を含める")

    # ─────────────────────────────────────────
    # 設定ダイアログ
    # ─────────────────────────────────────────
    def _open_settings(self):
        """詳細設定ダイアログを開く"""
        if hasattr(self, '_settings_window') and self._settings_window.winfo_exists():
            self._settings_window.lift()
            self._settings_window.focus_force()
            return

        win = tk.Toplevel(self.root)
        self._settings_window = win
        win.title("⚙ 詳細設定")
        win.configure(bg=COLORS["bg_dark"])
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        # ウィンドウのどこでもドラッグ移動できるように設定
        def start_win_drag(event):
            ignore_classes = ("Button", "TButton", "TCombobox", "TScale", "Radiobutton", "TRadiobutton", "Checkbutton", "TCheckbutton", "Entry", "TEntry")
            if event.widget.winfo_class() in ignore_classes or getattr(event.widget, '_is_file_card', False):
                win._drag_start_x = None
                return
            win._drag_start_x = event.x_root - win.winfo_x()
            win._drag_start_y = event.y_root - win.winfo_y()

        def win_dragging(event):
            if getattr(win, '_drag_start_x', None) is None:
                return
            x = event.x_root - win._drag_start_x
            y = event.y_root - win._drag_start_y
            win.geometry(f"+{x}+{y}")

        win.bind("<ButtonPress-1>", start_win_drag)
        win.bind("<B1-Motion>", win_dragging)

        pad = tk.Frame(win, bg=COLORS["bg_dark"], padx=20, pady=16)
        pad.pack(fill="both", expand=True)

        tk.Label(
            pad, text="⚙ 詳細設定",
            font=(APP_FONT, 15), fg=COLORS["accent"], bg=COLORS["bg_dark"]
        ).pack(anchor="w", pady=(0, 12))

        # --- 統計情報 ---
        config_path = os.path.join(register_menu.DATA_DIR, "config.json")
        total_saved = 0
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
                    total_saved = config_data.get("total_saved_bytes", 0)
            except Exception:
                pass
                
        if total_saved >= 0:
            stats_card = tk.Frame(pad, bg=COLORS["bg_card"], padx=12, pady=10,
                                   highlightbackground=COLORS["success"], highlightthickness=1)
            stats_card.pack(fill="x", pady=(0, 10))
            
            tk.Label(
                stats_card, text="📊 統計情報",
                font=(APP_FONT, 11), fg=COLORS["success"], bg=COLORS["bg_card"]
            ).pack(anchor="w")
            
            tk.Label(
                stats_card, text=f"これまでの累計節約容量： {format_filesize(total_saved)}",
                font=(APP_FONT, 12), fg=COLORS["text"], bg=COLORS["bg_card"]
            ).pack(anchor="w", pady=(4, 0))

            total_files = config_data.get("total_converted_files", 0) if 'config_data' in locals() else 0
            tk.Label(
                stats_card, text=f"これまでの累計変換数： {total_files} 個",
                font=(APP_FONT, 12), fg=COLORS["text"], bg=COLORS["bg_card"]
            ).pack(anchor="w", pady=(2, 0))

        # --- エンコードプリセット ---
        preset_card = tk.Frame(pad, bg=COLORS["bg_card"], padx=12, pady=10,
                               highlightbackground=COLORS["border"], highlightthickness=1)
        preset_card.pack(fill="x", pady=(0, 10))

        tk.Label(
            preset_card, text="エンコードプリセット",
            font=(APP_FONT, 11), fg=COLORS["text"], bg=COLORS["bg_card"]
        ).pack(anchor="w")

        self.preset_desc_label = tk.Label(
            preset_card,
            text="速い → ファイルサイズ大  /  遅い → ファイルサイズ小",
            font=(APP_FONT, 9), fg=COLORS["text_dim"], bg=COLORS["bg_card"]
        )
        self.preset_desc_label.pack(anchor="w", pady=(0, 6))

        amd_note_label = tk.Label(
            preset_card,
            text="※注意点：AMDの場合、P1からP3までがSpeed、\nP4がbalance、P5からP7までがQuality設定となっています。",
            font=(APP_FONT, 9), fg=COLORS["text_dim"], bg=COLORS["bg_card"],
            justify="left", anchor="w"
        )
        amd_note_label.pack(anchor="w", pady=(0, 6))

        AMF_PRESETS = [
            ("Speed", "高速（ファイルサイズ大）"),
            ("Balanced", "標準（バランス）"),
            ("Quality", "画質（ファイルサイズ小）")
        ]

        self.preset_display_var = tk.StringVar()
        preset_combo = ttk.Combobox(
            preset_card, textvariable=self.preset_display_var,
            state="readonly", font=(APP_FONT, 11), width=26
        )
        preset_combo.pack(anchor="w", pady=(2, 6))
        
        def _update_preset_display(*args):
            is_amf = "amf" in self.codec_var.get().lower()
            current_presets = AMF_PRESETS if is_amf else NVENC_PRESETS
            preset_display_values = [f"{v}  {n}" for v, n in current_presets]
            preset_combo['values'] = preset_display_values
            
            current_val = self.preset_var.get()
            
            # AMFの場合でP1~P7が選ばれている場合、表示用に丸める
            display_val = current_val
            if is_amf and current_val.lower() in [f"p{i}" for i in range(1, 8)]:
                if current_val.lower() in ("p1", "p2", "p3"): display_val = "Speed"
                elif current_val.lower() in ("p5", "p6", "p7"): display_val = "Quality"
                else: display_val = "Balanced"
            # NVENCの場合でAMFのプリセットが選ばれている場合、表示用に丸める
            elif not is_amf and current_val.lower() in ("speed", "balanced", "quality"):
                if current_val.lower() == "speed": display_val = "p2"
                elif current_val.lower() == "quality": display_val = "p6"
                else: display_val = "p4"

            if hasattr(self, 'preset_desc_label'):
                if is_amf:
                    self.preset_desc_label.config(text="Speed → ファイルサイズ大  /  Quality → ファイルサイズ小")
                else:
                    self.preset_desc_label.config(text="速い → ファイルサイズ大  /  遅い → ファイルサイズ小")
                
            current_display = next((f"{v}  {n}" for v, n in current_presets if v.lower() == display_val.lower()), preset_display_values[len(preset_display_values)//2])
            self.preset_display_var.set(current_display)
            
        _update_preset_display()
        trace_preset_id = self.preset_var.trace_add("write", _update_preset_display)
        trace_codec_id = self.codec_var.trace_add("write", _update_preset_display)
        
        def _on_destroy(event):
            if event.widget == win:
                try:
                    self.preset_var.trace_remove("write", trace_preset_id)
                    self.codec_var.trace_remove("write", trace_codec_id)
                except Exception:
                    pass
        win.bind("<Destroy>", _on_destroy, add="+")
        
        def _on_combo_select(event):
            selected = self.preset_display_var.get()
            val = selected.split("  ")[0]
            self.preset_var.set(val)
            self._save_app_config()
            preset_combo.selection_clear()
            win.focus_set()
            
        preset_combo.bind("<<ComboboxSelected>>", _on_combo_select)

        # --- 音声処理モード ---
        audio_card = tk.Frame(pad, bg=COLORS["bg_card"], padx=12, pady=10,
                              highlightbackground=COLORS["border"], highlightthickness=1)
        audio_card.pack(fill="x", pady=(0, 10))

        tk.Label(
            audio_card, text="音声処理モード",
            font=(APP_FONT, 11), fg=COLORS["text"], bg=COLORS["bg_card"]
        ).pack(anchor="w", pady=(0, 6))

        self.audio_copy_var = tk.BooleanVar(value=self.audio_mode_var.get() == "copy")
        self.audio_reencode_var = tk.BooleanVar(value=self.audio_mode_var.get() == "reencode")
        
        def _sync_audio_cbs(*args):
            val = self.audio_mode_var.get()
            self.audio_copy_var.set(val == "copy")
            self.audio_reencode_var.set(val == "reencode")
            
        trace_id_audio = self.audio_mode_var.trace_add("write", _sync_audio_cbs)
        
        def _on_destroy_audio(event):
            if event.widget == win:
                try:
                    self.audio_mode_var.trace_remove("write", trace_id_audio)
                except Exception:
                    pass
        win.bind("<Destroy>", _on_destroy_audio, add="+")

        def _on_audio_cb_click(mode_val):
            self.audio_mode_var.set(mode_val)
            _sync_audio_cbs()
            self._save_app_config()

        tk.Checkbutton(
            audio_card, text="コピー（そのまま）— 音質劣化なし",
            variable=self.audio_copy_var,
            font=(APP_FONT, 11), fg=COLORS["text"], bg=COLORS["bg_card"],
            selectcolor=COLORS["bg_card"], activebackground=COLORS["bg_card"],
            activeforeground=COLORS["accent"],
            command=lambda: _on_audio_cb_click("copy")
        ).pack(anchor="w", pady=2)

        tk.Checkbutton(
            audio_card, text="再エンコード（AAC 128kbps）— 容量を抑えた標準形式",
            variable=self.audio_reencode_var,
            font=(APP_FONT, 11), fg=COLORS["text"], bg=COLORS["bg_card"],
            selectcolor=COLORS["bg_card"], activebackground=COLORS["bg_card"],
            activeforeground=COLORS["accent"],
            command=lambda: _on_audio_cb_click("reencode")
        ).pack(anchor="w", pady=2)

        # --- 自動終了オプション / メタデータ引き継ぎ ---
        close_option_card = tk.Frame(pad, bg=COLORS["bg_card"], padx=12, pady=10,
                                     highlightbackground=COLORS["border"], highlightthickness=1)
        close_option_card.pack(fill="x", pady=(0, 10))

        tk.Checkbutton(
            close_option_card, text="変換完了後に自動で閉じる",
            variable=self.auto_close_var,
            font=(APP_FONT, 11), fg=COLORS["text"], bg=COLORS["bg_card"],
            selectcolor=COLORS["bg_card"], activebackground=COLORS["bg_card"],
            activeforeground=COLORS["accent"],
            command=self._save_app_config
        ).pack(anchor="w", pady=2)

        tk.Checkbutton(
            close_option_card, text="右クリックから起動時は強制的に自動で閉じる",
            variable=self.force_auto_close_on_right_click_var,
            font=(APP_FONT, 11), fg=COLORS["text"], bg=COLORS["bg_card"],
            selectcolor=COLORS["bg_card"], activebackground=COLORS["bg_card"],
            activeforeground=COLORS["accent"],
            command=self._save_app_config
        ).pack(anchor="w", pady=2)

        tk.Checkbutton(
            close_option_card, text="元のメタデータ（撮影日時など）を引き継ぐ",
            variable=self.keep_metadata_var,
            font=(APP_FONT, 11), fg=COLORS["text"], bg=COLORS["bg_card"],
            selectcolor=COLORS["bg_card"], activebackground=COLORS["bg_card"],
            activeforeground=COLORS["accent"],
            command=self._save_app_config
        ).pack(anchor="w", pady=2)

        tk.Checkbutton(
            close_option_card, text="右クリックから起動時はGUIを最小化した状態で開始する",
            variable=self.minimize_on_right_click_var,
            font=(APP_FONT, 11), fg=COLORS["text"], bg=COLORS["bg_card"],
            selectcolor=COLORS["bg_card"], activebackground=COLORS["bg_card"],
            activeforeground=COLORS["accent"],
            command=self._save_app_config
        ).pack(anchor="w", pady=2)

        tk.Label(
            close_option_card,
            text="（進捗は画面を表示するか、タスクバーの進捗バーで確認できます）",
            font=(APP_FONT, 9), fg=COLORS["text_dim"], bg=COLORS["bg_card"]
        ).pack(anchor="w", padx=24, pady=(0, 6))

        # 閉じるボタン
        close_btn = tk.Button(
            pad, text="閉じる",
            font=(APP_FONT, 10), fg=COLORS["text"],
            bg=COLORS["bg_card"], activebackground=COLORS["bg_input"],
            activeforeground=COLORS["text_bright"],
            relief="flat", padx=20, pady=6, cursor="hand2",
            command=win.destroy,
        )
        close_btn.pack(pady=(4, 0))

        # ウィンドウを親の近くに配置
        win.update_idletasks()
        x = self.root.winfo_x() + 50
        y = self.root.winfo_y() + 50
        win.geometry(f"+{x}+{y}")

    def _save_app_config(self, *args):
        config_path = os.path.join(register_menu.DATA_DIR, "config.json")
        config = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception:
                pass
        config["auto_close"] = self.auto_close_var.get()
        config["preset"] = self.preset_var.get()
        config["keep_metadata"] = self.keep_metadata_var.get()
        if hasattr(self, 'hide_no_audio_presets_var'):
            config["hide_no_audio_presets"] = self.hide_no_audio_presets_var.get()
        if hasattr(self, 'force_auto_close_on_right_click_var'):
            config["force_auto_close_on_right_click"] = self.force_auto_close_on_right_click_var.get()
        if hasattr(self, 'minimize_on_right_click_var'):
            config["minimize_on_right_click"] = self.minimize_on_right_click_var.get()
        
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
        except Exception:
            pass

    # ─────────────────────────────────────────
    # イベントハンドラ
    # ─────────────────────────────────────────
    def _on_resolution_change(self, *args):
        if not hasattr(self, 'video_info') or not self.input_path:
            return
        res_val = self.resolution_var.get()
        orig_w = self.video_info["width"]
        orig_h = self.video_info["height"]
        
        if res_val == "元のまま":
            new_w = orig_w
            new_h = orig_h
        else:
            target_h = int(res_val.replace("p", ""))
            if target_h != orig_h:
                new_w = int(orig_w * (target_h / orig_h))
                new_h = target_h
                # 偶数丸め
                new_w = new_w - (new_w % 2)
                new_h = new_h - (new_h % 2)
            else:
                new_w = orig_w
                new_h = orig_h

        self.resolution_preview_label.configure(
            text=f"{orig_w}×{orig_h} → {new_w}×{new_h}"
        )
        self._check_resolution_warning(new_h)

    def _check_resolution_warning(self, new_h=None):
        if not hasattr(self, 'resolution_warning_label') or not hasattr(self, 'video_info'):
            return
            
        if new_h is None:
            res_val = self.resolution_var.get()
            if res_val == "元のまま":
                new_h = self.video_info.get("height", 1080)
            else:
                new_h = int(res_val.replace("p", ""))

        warning_text = ""
        mode = self.mode_var.get()
        if mode in ("size", "percent"):
            target_size_mb = None
            if mode == "size":
                try:
                    target_size_mb = float(self.target_size_var.get())
                except ValueError:
                    pass
            elif mode == "percent":
                try:
                    percent = float(self.target_percent_var.get())
                    orig_bytes = self.video_info.get("filesize", 0)
                    if orig_bytes > 0:
                        target_size_mb = (orig_bytes / 1048576.0) * (percent / 100.0)
                except ValueError:
                    pass
                    
            if target_size_mb is not None and target_size_mb > 0:
                duration = self.video_info.get("duration", 0)
                if duration > 0:
                    target_total_kbps = (target_size_mb * 0.90 * 8192) / duration
                    has_audio_var = hasattr(self, 'audio_var') and self.audio_var.get()
                    audio_kbps = 64 if (has_audio_var and self.video_info.get("has_audio")) else 0
                    video_kbps = target_total_kbps - audio_kbps
                    
                    if new_h >= 2160:
                        required_kbps = 6000
                        rec_res = "1080pまたは720p"
                    elif new_h >= 1440:
                        required_kbps = 3000
                        rec_res = "1080pまたは720p"
                    elif new_h >= 1080:
                        required_kbps = 1500
                        rec_res = "720p以下"
                    else:
                        required_kbps = 0
                        rec_res = ""
                    
                    if required_kbps > 0 and video_kbps < required_kbps:
                        warning_text = f"⚠️ 目標容量が小さいため、現在の解像度では容量オーバーになる可能性が高いです。\n    {rec_res}への変更を推奨します。"
                        
        self.resolution_warning_label.configure(text=warning_text)

    def _on_mode_change(self, *args):
        mode = self.mode_var.get()
        if mode == "cq":
            self.size_frame.pack_forget()
            if hasattr(self, 'percent_frame'):
                self.percent_frame.pack_forget()
            self.cq_frame.pack(fill="x")
        elif mode == "size":
            self.cq_frame.pack_forget()
            if hasattr(self, 'percent_frame'):
                self.percent_frame.pack_forget()
            self.size_frame.pack(fill="x")
        elif mode == "percent":
            self.cq_frame.pack_forget()
            self.size_frame.pack_forget()
            self.percent_frame.pack(fill="x")
            
        self._check_resolution_warning()

    def _on_quality_change(self, value):
        cq = int(float(value))
        if cq <= 20:
            desc = "最高画質"
            color = COLORS["accent"]
        elif cq <= 25:
            desc = "高画質"
            color = COLORS["success"]
        elif cq <= 30:
            desc = "標準"
            color = COLORS["warning"]
        elif cq <= 35:
            desc = "低画質"
            color = COLORS["error"]
        else:
            desc = "最低画質"
            color = COLORS["error"]
        self.quality_value_label.configure(text=f"CQ {cq} ({desc})", fg=color)

    def _open_output_folder(self):
        if hasattr(self, "output_path") and os.path.exists(self.output_path):
            subprocess.Popen(
                ["explorer", "/select,", os.path.normpath(self.output_path)],
                creationflags=subprocess.CREATE_NO_WINDOW
            )

    # ─────────────────────────────────────────
    # FFmpegコマンド生成
    # ─────────────────────────────────────────
    def _build_ffmpeg_command(self, fallback_encoder=None) -> list:
        codec_name = self.codec_var.get()
        codec_info = CODECS[codec_name]
        encoder = fallback_encoder if fallback_encoder else codec_info["encoder"]
        ext = codec_info["ext"]

        if encoder == "auto":
            try:
                cmd = ["wmic", "path", "win32_VideoController", "get", "name"]
                result = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=3)
                output = result.stdout.lower()
                if "amd" in output or "radeon" in output:
                    encoder = "hevc_amf"
                else:
                    encoder = "hevc_nvenc"
            except Exception:
                encoder = "hevc_nvenc"

        self.current_encoder = encoder

        # 出力ファイルパスの生成
        input_p = Path(self.input_path)
        suffix = f"_converted.{ext}"
        self.output_path = str(input_p.parent / f"{input_p.stem}{suffix}")

        # 既にファイルが存在する場合は連番をつける
        counter = 1
        while os.path.exists(self.output_path):
            self.output_path = str(input_p.parent / f"{input_p.stem}_converted_{counter}.{ext}")
            counter += 1

        # GPU最適化: 入力コーデックに対応するCUVIDデコーダーで読み込み高速化
        is_nvenc = "nvenc" in encoder
        is_amf = "amf" in encoder

        cmd = [FFMPEG_PATH, "-y"]
        use_gpu_decode = False

        if is_nvenc:
            input_codec = self.video_info.get("codec", "")
            cuvid_decoder = CUVID_DECODERS.get(input_codec)
            use_gpu_decode = cuvid_decoder is not None
            has_rotation = self.video_info.get("rotation", 0) != 0
            if use_gpu_decode:
                if has_rotation:
                    cmd.extend(["-hwaccel", "cuda", "-c:v", cuvid_decoder])
                    use_gpu_decode = False  # 回転がある場合、自動回転を効かせるためCPUメモリに落とす
                else:
                    cmd.extend(["-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
                               "-c:v", cuvid_decoder])
            else:
                cmd.extend(["-hwaccel", "auto"])
        
            
        cmd.extend(["-i", self.input_path])

        # ビデオ設定
        cmd.extend(["-c:v", encoder])
        if not use_gpu_decode:
            cmd.extend(["-pix_fmt", "yuv420p"])  # 高い再生互換性のためのピクセルフォーマット指定 (GPUデコード時はエンコーダに任せる)
        
        if "hevc" in encoder:
            cmd.extend(["-tag:v", "hvc1"])   # iPhone/Appleデバイス互換性のためのタグ

        # CQP (品質) または VBR (容量指定)
        cq = self.quality_var.get()
        is_target_size_mode = False
        video_kbps = 0
        
        target_size_mb = None
        if self.mode_var.get() == "size":
            try:
                target_size_mb = float(self.target_size_var.get())
            except ValueError:
                target_size_mb = None
        elif self.mode_var.get() == "percent":
            try:
                percent = float(self.target_percent_var.get())
                orig_bytes = self.video_info.get("filesize", 0)
                if orig_bytes > 0:
                    target_size_mb = (orig_bytes / 1048576.0) * (percent / 100.0)
            except ValueError:
                target_size_mb = None

        if target_size_mb is not None and target_size_mb > 0:
            duration = self.video_info.get("duration", 0)
            if duration > 0:
                is_target_size_mode = True
                audio_kbps = 64 if (self.audio_var.get() and self.video_info.get("has_audio")) else 0
                # A案の対策: 50MB以下の目標サイズなど、シビアな場合はマージンを多めに取る
                if target_size_mb <= 55.0:
                    margin = 0.85 if is_amf else 0.90
                else:
                    margin = 0.90 if is_amf else 0.95
                
                target_total_kbps = (target_size_mb * margin * 8192) / duration
                video_kbps = max(100, int(target_total_kbps - audio_kbps))
                
                # B案の対策: バッファサイズを等倍(1倍)にして、瞬間的なビットレート超過を許容しない
                buf_multiplier = 1 if target_size_mb <= 55.0 else 2
                
                if is_amf:
                    # AMFエンコーダーはvbr_peakを使用
                    cmd.extend([
                        "-rc", "vbr_peak",
                        "-b:v", f"{video_kbps}k",
                        "-maxrate", f"{video_kbps}k",
                        "-bufsize", f"{video_kbps * buf_multiplier}k"
                    ])
                else:
                    cmd.extend([
                        "-rc", "vbr",
                        "-b:v", f"{video_kbps}k",
                        "-maxrate", f"{video_kbps}k",
                        "-bufsize", f"{video_kbps * buf_multiplier}k"
                    ])
                
        if not is_target_size_mode:
            orig_total_bitrate = self.video_info.get("bitrate", 0)
            orig_video_kbps = 0
            if orig_total_bitrate > 0:
                audio_kbps = 128 if (self.audio_var.get() and self.video_info.get("has_audio")) else 0
                orig_video_kbps = max(100, int(orig_total_bitrate / 1000) - audio_kbps)
            
            if orig_video_kbps > 0:
                # スマートCQモード: 元のビットレートを上限としてロック
                if encoder in ("h264_nvenc", "hevc_nvenc", "av1_nvenc"):
                    cmd.extend([
                        "-rc", "vbr",
                        "-cq", str(cq),
                        "-maxrate", f"{orig_video_kbps}k",
                        "-bufsize", f"{orig_video_kbps * 2}k"
                    ])
                elif is_amf:
                    # AMD AMF のVBR上限ロック付き画質設定
                    cmd.extend([
                        "-rc", "vbr_peak",
                        "-qp_p", str(cq),
                        "-qp_i", str(cq),
                        "-maxrate", f"{orig_video_kbps}k",
                        "-bufsize", f"{orig_video_kbps * 2}k"
                    ])
            else:
                # 元のビットレートが取得できない場合の従来のフォールバック
                if encoder in ("h264_nvenc", "hevc_nvenc"):
                    cmd.extend(["-rc", "constqp", "-qp", str(cq)])
                elif encoder == "av1_nvenc":
                    cmd.extend(["-cq", str(cq)])
                elif is_amf:
                    # AMD AMF の固定画質設定 (CQモード)
                    cmd.extend(["-rc", "cqp", "-qp_p", str(cq), "-qp_i", str(cq)])

        # NVENC プリセット（設定ダイアログから取得）
        preset_val = self.preset_var.get()
        if is_amf:
            amf_preset = "balanced"
            if preset_val.lower() in ("p1", "p2", "p3", "speed"):
                amf_preset = "speed"
            elif preset_val.lower() in ("p5", "p6", "p7", "quality"):
                amf_preset = "quality"
            elif preset_val.lower() in ("p4", "balanced"):
                amf_preset = "balanced"
            cmd.extend(["-preset", amf_preset])
        else:
            cmd.extend(["-preset", preset_val.lower()])

        # ビデオフィルター
        filters = []

        # 解像度スケーリング
        res_val = self.resolution_var.get()
        
        # 容量指定モードで「元のまま」かつビットレートが低すぎる場合は自動ダウンスケール
        if is_target_size_mode and res_val == "元のまま":
            orig_h = self.video_info.get("height", 1080)
            if video_kbps < 500:
                res_val = "480p" if orig_h > 480 else res_val
            elif video_kbps < 1500:
                res_val = "720p" if orig_h > 720 else res_val
        
        if res_val != "元のまま":
            target_h = int(res_val.replace("p", ""))
            orig_w = self.video_info["width"]
            orig_h = self.video_info["height"]
            
            if target_h != orig_h:
                new_w = int(orig_w * (target_h / orig_h))
                new_h = target_h
                new_w = new_w - (new_w % 2)
                new_h = new_h - (new_h % 2)
                if use_gpu_decode:
                    filters.append(f"scale_cuda={new_w}:{new_h}")
                else:
                    filters.append(f"scale={new_w}:{new_h}")

        if filters:
            cmd.extend(["-vf", ",".join(filters)])

        # フレームレート
        fps_val = self.fps_var.get()
        if fps_val != "元のまま":
            cmd.extend(["-r", fps_val])

        # 音声（設定ダイアログの音声モードに従う）
        if self.audio_var.get() and self.video_info.get("has_audio"):
            if is_target_size_mode:
                # 目標サイズモード時は強制的に AAC 64kbps にして容量節約
                cmd.extend(["-c:a", "aac", "-b:a", "64k"])
            elif self.audio_mode_var.get() == "copy":
                cmd.extend(["-c:a", "copy"])
            else:
                cmd.extend(["-c:a", "aac", "-b:a", "128k"])
        else:
            cmd.append("-an")

        # オリジナルのメタデータ（内部撮影日時・GPS等）をすべて引き継ぐ
        if self.keep_metadata_var.get():
            cmd.extend(["-map_metadata", "0"])

        cmd.extend(["-movflags", "+faststart"])  # プレビュー/ストリーミング最適化

        cmd.append(self.output_path)
        return cmd

    # ─────────────────────────────────────────
    # 変換処理
    # ─────────────────────────────────────────
    def _toggle_preset_mode(self):
        self.preset_mode = not self.preset_mode
        if self.preset_mode:
            self.preset_banner.pack(fill="x", pady=(0, 16), before=self.title_frame)
            self.main_frame.configure(highlightbackground=COLORS["success"])
            self.convert_btn.configure(
                text="💾 現在の設定をプリセットとして保存",
                bg=COLORS["success"],
                activebackground="#157347",
                state="normal"
            )
            self.preset_btn.configure(
                text="✖ キャンセル",
                fg=COLORS["error"],
                activeforeground=COLORS["error"]
            )
        else:
            self.preset_banner.pack_forget()
            self.main_frame.configure(highlightbackground=COLORS["bg_dark"])
            bg_color = COLORS["accent"] if self.input_path else COLORS["text_dim"]
            btn_state = "normal" if self.input_path else "disabled"
            self.convert_btn.configure(
                text="⚡ 圧縮開始",
                bg=bg_color,
                activebackground=COLORS["accent_hover"],
                state=btn_state
            )
            self.preset_btn.configure(
                text="プリセット作成",
                fg=COLORS["success"],
                activeforeground=COLORS["success"]
            )

    # ─────────────────────────────────────────
    # プリセット管理ダイアログ
    # ─────────────────────────────────────────
    def _open_preset_manager(self):
        if hasattr(self, '_manager_window') and self._manager_window.winfo_exists():
            self._manager_window.lift()
            self._manager_window.focus_force()
            return

        win = tk.Toplevel(self.root)
        self._manager_window = win
        win.title("プリセット管理")
        win.configure(bg=COLORS["bg_dark"])
        win.geometry("400x480")
        win.transient(self.root)
        win.grab_set()

        pad = tk.Frame(win, bg=COLORS["bg_dark"], padx=20, pady=16)
        pad.pack(fill="both", expand=True)

        tk.Label(
            pad, text="プリセット一覧",
            font=(APP_FONT, 13), fg=COLORS["accent"], bg=COLORS["bg_dark"]
        ).pack(anchor="w", pady=(0, 8))

        list_frame = tk.Frame(pad, bg=COLORS["bg_card"], highlightbackground=COLORS["border"], highlightthickness=1)
        list_frame.pack(fill="both", expand=True, pady=(0, 12))

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")

        self.preset_listbox = tk.Listbox(
            list_frame, font=(APP_FONT, 10), bg=COLORS["bg_input"], fg=COLORS["text"],
            selectbackground=COLORS["accent"], selectforeground=COLORS["text_bright"],
            relief="flat", borderwidth=0, highlightthickness=0,
            yscrollcommand=scrollbar.set
        )
        self.preset_listbox.pack(side="left", fill="both", expand=True, padx=2, pady=2)
        scrollbar.config(command=self.preset_listbox.yview)

        def _on_hide_cb_click():
            self._save_app_config()
            self._refresh_preset_list()
            self._update_apply_preset_list()
            try:
                import register_menu
                register_menu.register_context_menu()
            except Exception:
                pass

        tk.Checkbutton(
            pad, text="デフォルトのノーオーディオプリセットを非表示",
            variable=self.hide_no_audio_presets_var,
            font=(APP_FONT, 10), fg=COLORS["text"], bg=COLORS["bg_dark"],
            selectcolor=COLORS["bg_dark"], activebackground=COLORS["bg_dark"],
            activeforeground=COLORS["accent"],
            command=_on_hide_cb_click
        ).pack(anchor="w", pady=(4, 12))

        edit_frame = tk.Frame(pad, bg=COLORS["bg_dark"])
        edit_frame.pack(fill="x")

        tk.Label(edit_frame, text="選択中の名前を変更:", font=(APP_FONT, 9), fg=COLORS["text"], bg=COLORS["bg_dark"]).pack(anchor="w")
        
        rename_frame = tk.Frame(edit_frame, bg=COLORS["bg_dark"])
        rename_frame.pack(fill="x", pady=(4, 12))
        
        self.preset_name_var = tk.StringVar()
        name_entry = tk.Entry(
            rename_frame, textvariable=self.preset_name_var,
            font=(APP_FONT, 10), bg=COLORS["bg_input"], fg=COLORS["text"],
            relief="flat", highlightbackground=COLORS["border"], highlightthickness=1,
            insertbackground=COLORS["text"]
        )
        name_entry.pack(side="left", fill="x", expand=True, ipady=4)

        rename_btn = tk.Button(
            rename_frame, text="変更",
            font=(APP_FONT, 9), fg=COLORS["text_bright"], bg=COLORS["accent"],
            activebackground=COLORS["accent_hover"], activeforeground=COLORS["text_bright"],
            relief="flat", cursor="hand2", padx=12,
            command=self._rename_preset
        )
        rename_btn.pack(side="left", padx=(8, 0))

        action_frame = tk.Frame(pad, bg=COLORS["bg_dark"])
        action_frame.pack(fill="x")

        delete_btn = tk.Button(
            action_frame, text="🗑 削除",
            font=(APP_FONT, 9), fg=COLORS["error"], bg=COLORS["bg_card"],
            activebackground=COLORS["bg_input"], activeforeground=COLORS["error"],
            relief="flat", cursor="hand2", padx=12, pady=6,
            highlightbackground=COLORS["border"], highlightthickness=1,
            command=self._delete_preset
        )
        delete_btn.pack(side="left")

        close_btn = tk.Button(
            action_frame, text="閉じる",
            font=(APP_FONT, 9), fg=COLORS["text"], bg=COLORS["bg_card"],
            activebackground=COLORS["bg_input"], activeforeground=COLORS["text_bright"],
            relief="flat", cursor="hand2", padx=16, pady=6,
            command=win.destroy
        )
        close_btn.pack(side="right")

        self.preset_listbox.bind("<<ListboxSelect>>", self._on_preset_select)
        
        win.update_idletasks()
        x = self.root.winfo_x() + 50
        y = self.root.winfo_y() + 50
        win.geometry(f"+{x}+{y}")

        self._refresh_preset_list()

    def _update_apply_preset_list(self):
        if not hasattr(self, 'preset_apply_combo'):
            return
        _, presets = self._get_filtered_presets_data()
        preset_names = ["選択してください..."] + sorted([p.get("name", "") for p in presets.values()])
        self.preset_apply_combo.configure(values=preset_names)
        
        # もし現在選択中の名前が消去された場合はリセット
        if self.apply_preset_var.get() not in preset_names:
            self.apply_preset_var.set("選択してください...")

    def _on_preset_apply_select(self, event):
        self.preset_apply_combo.selection_clear()
        self.root.focus_set()
        
        name = self.apply_preset_var.get()
        if name == "選択してください...":
            # デフォルト状態に戻す
            config_preset = "p4"
            config_path = os.path.join(register_menu.DATA_DIR, "config.json")
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                        if "preset" in config:
                            config_preset = config["preset"]
                except Exception:
                    pass
                    
            if hasattr(self, '_init_codec'):
                self.codec_var.set(self._init_codec)
            self.preset_var.set(config_preset)
            if hasattr(self, '_init_fps'):
                self.fps_var.set(self._init_fps)
            if hasattr(self, '_init_resolution'):
                self.resolution_var.set(self._init_resolution)
            
            self.audio_mode_var.set("copy")
            if hasattr(self, '_init_no_audio'):
                self.audio_var.set(not self._init_no_audio)
            
            if hasattr(self, '_target_size_mb') and self._target_size_mb:
                self.mode_var.set("size")
                self.target_size_var.set(str(self._target_size_mb))
            else:
                self.mode_var.set("cq")
                if hasattr(self, '_init_cq'):
                    self.quality_var.set(self._init_cq)
                    self._on_quality_change(self._init_cq)
                
            self._on_mode_change()
            self._on_resolution_change()
            if hasattr(self, '_update_ui_state'):
                self._update_ui_state()
            return
            
        _, presets = self._get_presets_data()
        
        selected_p = None
        for p in presets.values():
            if p.get("name") == name:
                selected_p = p
                break
                
        if selected_p:
            p = selected_p
            
            if "codec" in p: self.codec_var.set(p["codec"])
            if "preset" in p: self.preset_var.set(p["preset"])
            if "fps" in p: self.fps_var.set(p["fps"])
            if "resolution" in p: self.resolution_var.set(p["resolution"])
            if "audio_mode" in p: self.audio_mode_var.set(p["audio_mode"])
            if "no_audio" in p: 
                self.audio_var.set(not p["no_audio"])
            if "auto_close" in p: self.auto_close_var.set(p["auto_close"])
            
            if "target_size_mb" in p and p["target_size_mb"] is not None:
                self.mode_var.set("size")
                self.target_size_var.set(str(p["target_size_mb"]))
            elif "target_percent" in p and p["target_percent"] is not None:
                self.mode_var.set("percent")
                if hasattr(self, 'target_percent_var'):
                    self.target_percent_var.set(str(p["target_percent"]))
            elif "cq" in p:
                self.mode_var.set("cq")
                self.quality_var.set(p["cq"])
                self._on_quality_change(p["cq"])
                
            self._on_mode_change()
            self._on_resolution_change()

    def _get_default_presets(self):
        default_path = os.path.join(register_menu.APP_DIR, "default_presets.json")
        default_presets = {}
        if os.path.exists(default_path):
            try:
                with open(default_path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                if register_menu.is_amd_gpu():
                    content = content.replace("NVIDIA NVENC", "AMD AMF")
                    
                default_presets = json.loads(content)
            except Exception:
                pass
        return default_presets

    def _get_user_presets(self):
        presets_path = os.path.join(register_menu.DATA_DIR, "presets.json")
        user_presets = {}
        if os.path.exists(presets_path):
            try:
                with open(presets_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    
                needs_save = False
                migrated_presets = {}
                
                old_default_names = [
                    "Change to 30FPS (High)", "Change to 30FPS (Low)",
                    "Discord Free (10MB)", "Discord Free (10MB) (No Audio)",
                    "Discord Nitro Basic (50MB)", "Discord Nitro Basic (50MB) (No Audio)",
                    "Steam Chat (30MB)", "Steam Chat (30MB) (No Audio)",
                    "X Post (512MB)", "Half Size (50%)",
                    "Discord用 (10MB)", "Discord用 (30MB)", "Discord用 (50MB)",
                    "Steam用", "汎用 (フルHD高画質)", "汎用 (HD標準画質)"
                ]
                
                for key, p in data.items():
                    if len(key) == 36 and key.count('-') == 4:
                        migrated_presets[key] = p
                    else:
                        needs_save = True
                        if key in old_default_names:
                            continue
                        new_id = str(uuid.uuid4())
                        p["name"] = key
                        p["is_custom"] = True
                        migrated_presets[new_id] = p
                        
                user_presets = migrated_presets
                
                if needs_save:
                    try:
                        import shutil
                        shutil.copy2(presets_path, presets_path + ".bak")
                        with open(presets_path, "w", encoding="utf-8") as f:
                            json.dump(user_presets, f, ensure_ascii=False, indent=4)
                    except Exception:
                        pass
                        
            except Exception:
                pass
        return user_presets

    def _get_presets_data(self):
        presets_path = os.path.join(register_menu.DATA_DIR, "presets.json")
        all_presets = {}
        all_presets.update(self._get_default_presets())
        all_presets.update(self._get_user_presets())
        return presets_path, all_presets

    def _get_filtered_presets_data(self):
        path, presets = self._get_presets_data()
        if hasattr(self, 'hide_no_audio_presets_var') and self.hide_no_audio_presets_var.get():
            default_presets = self._get_default_presets()
            filtered = {}
            for uid, p in presets.items():
                if uid in default_presets and p.get("no_audio"):
                    continue
                filtered[uid] = p
            return path, filtered
        return path, presets

    def _save_presets_data(self, presets_path, presets_data):
        try:
            with open(presets_path, "w", encoding="utf-8") as f:
                json.dump(presets_data, f, ensure_ascii=False, indent=4, sort_keys=True)
            register_menu.register_context_menu()
            return True
        except Exception as e:
            messagebox.showerror("エラー", f"保存またはレジストリ更新に失敗しました:\n{e}")
            return False

    def _refresh_preset_list(self):
        self.preset_listbox.delete(0, tk.END)
        _, presets = self._get_filtered_presets_data()
        for p in sorted(presets.values(), key=lambda x: x.get("name", "")):
            self.preset_listbox.insert(tk.END, p.get("name", ""))

    def _on_preset_select(self, event):
        selection = self.preset_listbox.curselection()
        if selection:
            name = self.preset_listbox.get(selection[0])
            self.preset_name_var.set(name)

    def _rename_preset(self):
        selection = self.preset_listbox.curselection()
        if not selection:
            return
        
        old_name = self.preset_listbox.get(selection[0])
        new_name = self.preset_name_var.get().strip()
        
        if not new_name or new_name == old_name:
            return
            
        default_presets = self._get_default_presets()
        for p in default_presets.values():
            if p.get("name") == old_name:
                messagebox.showwarning("警告", "デフォルトのプリセットは名前を変更できません。")
                return
            if p.get("name") == new_name:
                messagebox.showwarning("警告", "その名前はデフォルトのプリセットですでに使われています。")
                return
            
        path, presets = self._get_presets_data()
        for p in presets.values():
            if p.get("name") == new_name:
                messagebox.showwarning("警告", "その名前のプリセットは既に存在します。")
                return
            
        user_presets = self._get_user_presets()
        target_id = None
        for uid, p in user_presets.items():
            if p.get("name") == old_name:
                target_id = uid
                break
                
        if target_id:
            user_presets[target_id]["name"] = new_name
            if self._save_presets_data(path, user_presets):
                self._refresh_preset_list()
                self._update_apply_preset_list()
                self.preset_name_var.set("")
                messagebox.showinfo("完了", "名前を変更し、メニューを更新しました！")

    def _delete_preset(self):
        selection = self.preset_listbox.curselection()
        if not selection:
            return
            
        name = self.preset_listbox.get(selection[0])
        
        default_presets = self._get_default_presets()
        for p in default_presets.values():
            if p.get("name") == name:
                messagebox.showwarning("警告", "デフォルトのプリセットは削除できません。")
                return
            
        if messagebox.askyesno("確認", f"プリセット「{name}」を削除しますか？"):
            path, presets = self._get_presets_data()
            user_presets = self._get_user_presets()
            
            target_id = None
            for uid, p in user_presets.items():
                if p.get("name") == name:
                    target_id = uid
                    break
                    
            if target_id:
                del user_presets[target_id]
                if self._save_presets_data(path, user_presets):
                    self._refresh_preset_list()
                    self._update_apply_preset_list()
                    self.preset_name_var.set("")
                    messagebox.showinfo("完了", "削除し、メニューを更新しました！")

    def _save_preset(self):
        from tkinter import simpledialog
        name = simpledialog.askstring("プリセット名", "プリセットの名前を入力してください\n（例: Discord用、Steam用）", parent=self.root)
        if not name:
            return
        
        default_presets = self._get_default_presets()
        for p in default_presets.values():
            if p.get("name") == name:
                messagebox.showwarning("エラー", "デフォルトのプリセットと同名で保存することはできません。別の名前を指定してください。")
                return
            
        user_presets = self._get_user_presets()
        for p in user_presets.values():
            if p.get("name") == name:
                messagebox.showwarning("エラー", "その名前はすでに使われています。別の名前を指定してください。")
                return
                
        presets_path = os.path.join(register_menu.DATA_DIR, "presets.json")
        new_id = str(uuid.uuid4())
        
        user_presets[new_id] = {
            "name": name,
            "is_custom": True,
            "codec": self.codec_var.get(),
            "preset": self.preset_var.get(),
            "fps": self.fps_var.get(),
            "resolution": self.resolution_var.get(),
            "audio_mode": self.audio_mode_var.get(),
            "no_audio": not self.audio_var.get(),
            "auto_close": self.auto_close_var.get()
        }
        
        if self.mode_var.get() == "size":
            try:
                user_presets[new_id]["target_size_mb"] = float(self.target_size_var.get())
            except ValueError:
                user_presets[new_id]["target_size_mb"] = 10.0
        elif self.mode_var.get() == "percent":
            try:
                user_presets[new_id]["target_percent"] = float(self.target_percent_var.get())
            except ValueError:
                user_presets[new_id]["target_percent"] = 50.0
        else:
            user_presets[new_id]["cq"] = self.quality_var.get()
        
        try:
            with open(presets_path, "w", encoding="utf-8") as f:
                json.dump(user_presets, f, ensure_ascii=False, indent=4, sort_keys=True)
        except Exception as e:
            messagebox.showerror("エラー", f"プリセットの保存に失敗しました:\n{e}")
            return
            
        try:
            register_menu.register_context_menu()
            self._update_apply_preset_list()
            messagebox.showinfo("完了", f"プリセット「{name}」を保存し、右クリックメニューを更新しました！")
            self._toggle_preset_mode()
        except Exception as e:
            messagebox.showerror("エラー", f"レジストリの更新に失敗しました:\n{e}")

    def _start_conversion(self):
        if not self.input_paths and not getattr(self, 'input_path', None) and not self.preset_mode:
            return

        if self.preset_mode:
            self._save_preset()
            return
            
        if hasattr(self, 'resolution_warning_label') and self.resolution_warning_label.cget("text"):
            if not messagebox.askyesno("確認", "⚠️ 警告：目標容量に対して解像度が高すぎるため、容量オーバーになる可能性が高いです。\n\n本当にこのまま変換を開始しますか？\n（確実に収めたい場合は「いいえ」を押して解像度を下げてください）"):
                return

        if self.is_converting:
            return
        self.is_converting = True
        self.is_cancelled = False
        
        self.current_file_index = 0
        self.batch_saved_bytes = 0
        self.batch_orig_bytes = 0
        self.batch_out_bytes = 0
        
        self.convert_btn.configure(state="disabled", text="変換中...", bg=COLORS["text_dim"])
        self.cancel_btn.pack(side="right", padx=(0, 8))

        # タスクバー: 準備状態 (緑のアニメーション)
        self.taskbar_progress.set_state(TBPF_INDETERMINATE)

        self._process_next_file()

    def _process_next_file(self):
        if getattr(self, 'is_cancelled', False):
            return
            
        if self.current_file_index >= len(self.input_paths):
            self._on_batch_finished()
            return
            
        self.input_path = self.input_paths[self.current_file_index]
        self.video_info = get_video_info(self.input_path)
        
        thread = threading.Thread(target=self._run_ffmpeg, daemon=True)
        thread.start()

    def _on_batch_finished(self):
        if len(self.input_paths) > 1:
            orig_total = getattr(self, 'batch_orig_bytes', 0)
            out_total = getattr(self, 'batch_out_bytes', 0)
            saved = getattr(self, 'batch_saved_bytes', 0)
            
            if orig_total > 0 and out_total > 0:
                ratio = out_total / orig_total * 100
                status_text = f"✅ {len(self.input_paths)} 個すべての変換完了！ {format_filesize(orig_total)} → {format_filesize(out_total)} ({ratio:.1f}% / 元サイズ)"
            else:
                status_text = f"✅ {len(self.input_paths)} 個すべての変換が完了しました！"
            
            self._update_status(
                status_text,
                color=COLORS["accent"],
                font_size=11,
                is_bold=True
            )
            
        self._show_success()

    def _cancel_conversion(self):
        if self.is_converting and self.process:
            self.is_cancelled = True
            self.process.terminate()
            self._update_status("❌ 変換が中止されました", color=COLORS["error"])
            self.cancel_btn.pack_forget()

            # タスクバー: エラー状態 (赤色) で中止を表示
            self.taskbar_progress.set_state(TBPF_ERROR)
            self.taskbar_progress.set_value(100, 100)

    def _run_ffmpeg(self, fallback_encoder=None):
        cmd = self._build_ffmpeg_command(fallback_encoder=fallback_encoder)
        duration = self.video_info.get("duration", 0)
        start_time = time.time()

        prefix = f"({self.current_file_index + 1}/{len(self.input_paths)}) " if len(self.input_paths) > 1 else ""
        if fallback_encoder:
            self._update_status(f"再試行中 {prefix}(H.264)... 出力: {Path(self.output_path).name}")
        else:
            self._update_status(f"変換中... {prefix}出力: {Path(self.output_path).name}")
        # 全体の進捗に合わせて初期値を設定
        initial_progress = (self.current_file_index * 100) / max(1, len(self.input_paths))
        self._update_progress(initial_progress)
        self.taskbar_progress.set_value(int(initial_progress * 10), 1000)
        
        skip_finally_reset = False

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                encoding="utf-8",
                errors="replace",
            )

            # FFmpegの進捗はstderrに出力される
            time_pattern = re.compile(r"time=(\d+):(\d+):(\d+)\.(\d+)")

            for line in self.process.stderr:
                if getattr(self, "is_cancelled", False):
                    break
                match = time_pattern.search(line)
                if match and duration > 0:
                    h, m, s, cs = match.groups()
                    current = int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100
                    progress = min(current / duration * 100, 99.9)
                    
                    # バッチ全体での進捗を計算
                    total_files = max(1, len(self.input_paths))
                    overall_progress = (self.current_file_index * 100 + progress) / total_files
                    
                    self._update_progress(overall_progress)
                    
                    # タスクバー: 通常状態 (青/緑) で進捗を更新
                    self.taskbar_progress.set_state(TBPF_NORMAL)
                    self.taskbar_progress.set_value(int(overall_progress * 10), 1000)

                    # 速度情報の抽出
                    speed_match = re.search(r"speed=\s*([\d.]+)x", line)
                    speed_text = f" ({speed_match.group(1)}x)" if speed_match else ""
                    prefix = f"({self.current_file_index + 1}/{len(self.input_paths)}) " if len(self.input_paths) > 1 else ""
                    self._update_status(
                        f"変換中... {prefix}{progress:.1f}%{speed_text}  →  {Path(self.output_path).name}"
                    )

            self.process.wait()
            elapsed_time = time.time() - start_time

            if self.process.returncode == 0:
                completed_progress = ((self.current_file_index + 1) * 100) / max(1, len(self.input_paths))
                self._update_progress(completed_progress)
                self.taskbar_progress.set_value(int(completed_progress * 10), 1000)
                
                # 元のファイルの「更新日時」および「アクセス日時」を引き継ぐ
                if self.keep_metadata_var.get():
                    try:
                        if os.path.exists(self.input_path) and os.path.exists(self.output_path):
                            st = os.stat(self.input_path)
                            os.utime(self.output_path, (st.st_atime, st.st_mtime))
                    except Exception:
                        pass
                
                # 出力ファイルのサイズを取得
                out_size = os.path.getsize(self.output_path) if os.path.exists(self.output_path) else 0
                orig_size = self.video_info.get("filesize", 0)
                
                if orig_size > 0 and out_size > 0:
                    saved_bytes = max(0, orig_size - out_size)
                    self.batch_saved_bytes = getattr(self, 'batch_saved_bytes', 0) + saved_bytes
                    self.batch_orig_bytes = getattr(self, 'batch_orig_bytes', 0) + orig_size
                    self.batch_out_bytes = getattr(self, 'batch_out_bytes', 0) + out_size
                    
                    # 累計節約容量と累計変換数の保存
                    total_saved = 0
                    total_files = 0
                    config_path = os.path.join(register_menu.DATA_DIR, "config.json")
                    config_data = {}
                    if os.path.exists(config_path):
                        try:
                            with open(config_path, "r", encoding="utf-8") as f:
                                config_data = json.load(f)
                                total_saved = config_data.get("total_saved_bytes", 0)
                                total_files = config_data.get("total_converted_files", 0)
                        except Exception:
                            pass
                            
                    total_saved += saved_bytes
                    total_files += 1
                    config_data["total_saved_bytes"] = total_saved
                    config_data["total_converted_files"] = total_files
                    
                    try:
                        with open(config_path, "w", encoding="utf-8") as f:
                            json.dump(config_data, f, ensure_ascii=False, indent=4)
                    except Exception:
                        pass
                        
                    ratio = out_size / orig_size * 100
                    
                    status_text = f"✅ 変換完了！  {format_filesize(orig_size)} → {format_filesize(out_size)}  ({ratio:.1f}% / 元サイズ)"
                else:
                    status_text = f"✅ 変換完了！  {format_filesize(out_size)}"
                    
                self._update_status(
                    status_text,
                    color=COLORS["accent"],
                    font_size=11,
                    is_bold=True
                )
                
                self.current_file_index += 1
                if self.current_file_index < len(self.input_paths):
                    # 次のファイルがあれば少し待ってから実行
                    skip_finally_reset = True
                    self.root.after(1500, self._process_next_file)
                    return
                else:
                    # 全ての処理が完了
                    if len(self.input_paths) == 1:
                        self.root.after(0, self._on_batch_finished)
                    else:
                        self.root.after(1500, self._on_batch_finished)
                    return
                    
            elif getattr(self, "is_cancelled", False):
                # 中止された場合はエラーダイアログを出さずに完了処理へ
                self._update_progress(0)
                self._update_status("❌ 変換が中止されました", color=COLORS["error"])
                if hasattr(self, "output_path") and os.path.exists(self.output_path):
                    try:
                        os.remove(self.output_path)
                    except Exception:
                        pass
            else:
                current_enc = getattr(self, "current_encoder", "")
                if elapsed_time < 2.0 and current_enc in ("hevc_nvenc", "hevc_amf") and not fallback_encoder:
                    if hasattr(self, "output_path") and os.path.exists(self.output_path):
                        try:
                            os.remove(self.output_path)
                        except Exception:
                            pass
                    fallback = "h264_nvenc" if current_enc == "hevc_nvenc" else "h264_amf"
                    self._update_status("H.265非対応の可能性があるため、H.264で再試行します...", color=COLORS["warning"])
                    skip_finally_reset = True
                    self._run_ffmpeg(fallback_encoder=fallback)
                    return

                stderr_out = self.process.stderr.read() if self.process.stderr else ""
                self._update_status(f"❌ 変換失敗 (コード: {self.process.returncode})", color=COLORS["error"])
                self._show_error(f"FFmpegがエラーで終了しました。\n\n終了コード: {self.process.returncode}")

        except Exception as e:
            self._update_status(f"❌ エラー: {str(e)}", color=COLORS["error"])
            self._show_error(str(e))

        finally:
            self.process = None
            if not skip_finally_reset:
                self.is_converting = False
                def _reset_btn():
                    if hasattr(self, "cancel_btn"):
                        self.cancel_btn.pack_forget()
                    self.convert_btn.configure(state="normal", text="⚡ 圧縮開始", bg=COLORS["accent"])
                self.root.after(0, _reset_btn)

    def _update_progress(self, value):
        self.root.after(0, lambda: self.progress_var.set(value))

    def _update_status(self, text, color=None, font_size=9, is_bold=False):
        fg_color = color if color else COLORS["text_dim"]
        font_weight = "bold" if is_bold else "normal"
        self.root.after(0, lambda: self.status_label.configure(text=text, fg=fg_color, font=(APP_FONT, font_size)))

    def _show_success(self):
        def _update():
            self.progress_bar.configure(style="Custom.Horizontal.TProgressbar")
            style = ttk.Style()
            style.configure("Custom.Horizontal.TProgressbar", background=COLORS["success"])
            self.open_btn.pack(side="left")
            
            # タスクバー: 進捗表示をクリア (完了)
            self.taskbar_progress.set_state(TBPF_NOPROGRESS)
            
            if self.auto_close_var.get():
                self.root.destroy()
        self.root.after(0, _update)

    def _show_error(self, message):
        def _update():
            style = ttk.Style()
            style.configure("Custom.Horizontal.TProgressbar", background=COLORS["error"])
            
            # タスクバー: エラー状態 (赤色)
            self.taskbar_progress.set_state(TBPF_ERROR)
            self.taskbar_progress.set_value(100, 100)
            
        self.root.after(0, _update)

    # ─────────────────────────────────────────
    # ウィンドウを閉じるとき
    # ─────────────────────────────────────────
    def on_closing(self):
        if self.is_converting:
            if messagebox.askyesno("確認", "変換中です。中止して閉じますか？"):
                if self.process:
                    self.process.terminate()
                self.root.destroy()
        else:
            self.root.destroy()

    def _check_for_updates(self):
        """GitHub Releases APIから最新バージョンを取得し、24時間に1回確認を行う"""
        config_path = os.path.join(register_menu.DATA_DIR, "config.json")
        now = time.time()
        
        # 24時間キャッシュチェック
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                last_check = config.get("last_update_check", 0)
                if now - last_check < 86400:
                    return
            except Exception:
                pass

        # API通信を実行
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": "QuickCompressor-Updater"})
        
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
                latest_tag = data.get("tag_name", "").strip()
                latest_version = latest_tag.lstrip("v")
                html_url = data.get("html_url", "")
                
                # バージョンが異なれば新しいバージョンありとする
                if latest_version and latest_version != CURRENT_VERSION:
                    self.root.after(0, self._show_update_dialog, latest_version, html_url)
            
            self._save_update_check_time(config_path, now)
        except Exception:
            # ネットワークエラーやAPI制限時は静かにスルーし、無駄な再リクエストを防ぐために時刻のみ記録
            try:
                self._save_update_check_time(config_path, now)
            except Exception:
                pass

    def _save_update_check_time(self, config_path, timestamp):
        """アップデートチェック日時をconfig.jsonに保存する"""
        config = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception:
                pass
        config["last_update_check"] = timestamp
        
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)

    def _show_update_dialog(self, latest_version, html_url):
        """アップデートダイアログを表示し、ブラウザでReleasesページを開く"""
        msg = f"新しいバージョン (v{latest_version}) が見つかりました。\n現在のバージョン: v{CURRENT_VERSION}\n\nダウンロードページを開きますか？"
        if messagebox.askyesno("アップデートのお知らせ", msg):
            try:
                webbrowser.open(html_url)
            except Exception:
                pass


# ─────────────────────────────────────────────
# メイン起動
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", nargs="?", help="入力ファイル")
    parser.add_argument("--preset", default="p4", help="エンコードプリセット")
    parser.add_argument("--fps", default="元のまま", help="フレームレート")
    parser.add_argument("--resolution", default="元のまま", help="解像度 (1080p, 720p, etc.)")
    parser.add_argument("--cq", type=int, default=25, help="画質(CQ値)")
    parser.add_argument("--audio-mode", choices=["copy", "reencode"], default="copy", help="音声処理モード")
    parser.add_argument("--no-audio", action="store_true", help="音声を含めない")
    parser.add_argument("--auto", action="store_true", help="自動変換開始")
    parser.add_argument("--target-size-mb", type=float, default=None, help="目標ファイルサイズ(MB)")
    parser.add_argument("--codec", default=None, help="出力コーデック")
    parser.add_argument("--auto-close", action="store_true", help="変換完了後に自動で閉じる")
    parser.add_argument("--register", action="store_true", help="レジストリにメニューを登録して終了")
    parser.add_argument("--unregister", action="store_true", help="レジストリからメニューを解除して終了")
    
    args, _ = parser.parse_known_args()

    if args.register:
        register_menu.register_context_menu()
        sys.exit(0)
    
    if args.unregister:
        register_menu.unregister_context_menu()
        sys.exit(0)

    if not args.input:
        filepath = None
    else:
        filepath = args.input

    if filepath and not os.path.isfile(filepath):
        messagebox.showerror("エラー", f"ファイルが見つかりません:\n{filepath}")
        sys.exit(1)


    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    app = QuickCompressorApp(
        root, filepath,
        auto_start=args.auto,
        preset=args.preset,
        fps=args.fps,
        resolution=args.resolution,
        cq=args.cq,
        audio_mode=args.audio_mode,
        no_audio=args.no_audio,
        target_size_mb=args.target_size_mb,
        codec=args.codec,
        auto_close=args.auto_close
    )
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
