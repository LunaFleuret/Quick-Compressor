#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import json
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
# バージョン情報とリポジトリ設定
# ─────────────────────────────────────────────
CURRENT_VERSION = "1.0.0"
GITHUB_REPO = "LunaFleuret/Quick-Compressor"

# ─────────────────────────────────────────────
# 定数とパス解決
# ─────────────────────────────────────────────
def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

APP_DIR = get_app_dir()
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
    "warning":      "#ffc107",
    "error":        "#dc3545",
    "border":       "#dee2e6",
    "slider_track": "#e9ecef",
    "progress_trough": "#e9ecef",
}

# コーデック定義
CODECS = {
    "H.264 (NVIDIA NVENC)": {"encoder": "h264_nvenc", "ext": "mp4"},
    "HEVC / H.265 (NVIDIA NVENC)": {"encoder": "hevc_nvenc", "ext": "mp4"},
    "AV1 (NVIDIA NVENC)": {"encoder": "av1_nvenc", "ext": "mp4"},
    "H.264 (AMD AMF)": {"encoder": "h264_amf", "ext": "mp4"},
    "HEVC / H.265 (AMD AMF)": {"encoder": "hevc_amf", "ext": "mp4"},
    "AV1 (AMD AMF)": {"encoder": "av1_amf", "ext": "mp4"},
}

FRAME_RATES = ["元のまま", "24", "30", "60"]
RESOLUTIONS = ["元のまま", "1080p", "720p", "480p"]

# CUVIDデコーダーマッピング（GPU読み込み最適化用）
CUVID_DECODERS = {
    "h264": "h264_cuvid",
    "hevc": "hevc_cuvid",
    "vp9": "vp9_cuvid",
    "av1": "av1_cuvid",
    "mpeg4": "mpeg4_cuvid",
    "mpeg2video": "mpeg2_cuvid",
    "mpeg1video": "mpeg1_cuvid",
    "vp8": "vp8_cuvid",
}

# NVENCプリセット定義
NVENC_PRESETS = [
    ("p1", "最速（ファイル大）"),
    ("p2", "高速"),
    ("p3", "やや速い"),
    ("p4", "標準（バランス）"),
    ("p5", "やや遅い"),
    ("p6", "低速"),
    ("p7", "最遅（ファイル小）"),
]


# ─────────────────────────────────────────────
# ユーティリティ関数
# ─────────────────────────────────────────────
def detect_gpu_and_default_codec() -> str:
    """WindowsのWMI(wmic)を利用してGPUを判別し、最適なデフォルトコーデックを返す"""
    try:
        cmd = ["wmic", "path", "win32_VideoController", "get", "name"]
        result = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=3)
        output = result.stdout.lower()
        if "nvidia" in output or "geforce" in output:
            return "HEVC / H.265 (NVIDIA NVENC)"
        elif "amd" in output or "radeon" in output:
            return "HEVC / H.265 (AMD AMF)"
    except Exception:
        pass
    return "HEVC / H.265 (NVIDIA NVENC)"

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

    info = {
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "fps": fps,
        "bitrate": bitrate,
        "duration": duration,
        "filesize": filesize,
        "codec": video_stream.get("codec_name", "不明"),
        "has_audio": audio_stream is not None,
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
                 cq: int = 24,
                 audio_mode: str = "copy",
                 no_audio: bool = False,
                 target_size_mb: float = None,
                 codec: str = None,
                 auto_close: bool = False):
        self.preset_mode = False
        self.root = root
        self.input_path = input_path
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

        # 詳細設定変数（デフォルト値）
        self.preset_var = tk.StringVar(value=preset)
        self.audio_mode_var = tk.StringVar(value=audio_mode)
        self.auto_close_var = tk.BooleanVar(value=auto_close)

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
        style.map("TCombobox", fieldbackground=[("readonly", COLORS["bg_input"])], selectbackground=[("readonly", COLORS["accent"])], selectforeground=[("readonly", COLORS["text_bright"])])
        style.configure("Horizontal.TScale", background=COLORS["accent"], troughcolor=COLORS["progress_trough"])
        style.map("Horizontal.TScale", background=[("active", COLORS["accent"])])
        style.configure("Custom.Horizontal.TProgressbar", troughcolor=COLORS["progress_trough"], background=COLORS["accent"], thickness=8)

        # UI構築
        self._build_ui()

        # 自動開始処理
        if self._auto_start:
            self.root.after(100, self._start_conversion)

        # ウィンドウをマウスポインターがある位置（画面）に配置（マルチディスプレイ対応）
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        pointer_x, pointer_y = self.root.winfo_pointerxy()
        x = pointer_x - (w // 2)
        y = pointer_y - (h // 2)
        self.root.geometry(f"+{x}+{y}")

        # ウィンドウのどこでもドラッグ移動できるように設定
        self._enable_window_drag()

    def _enable_window_drag(self):
        def start_drag(event):
            ignore_classes = ("Button", "TButton", "TCombobox", "TScale", "Radiobutton", "TRadiobutton", "Checkbutton", "TCheckbutton")
            if event.widget.winfo_class() in ignore_classes:
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

        # アップデートチェック（非同期）
        threading.Thread(target=self._check_for_updates, daemon=True).start()

    # ─────────────────────────────────────────
    # UI構築
    # ─────────────────────────────────────────
    def _build_ui(self):
        # メインコンテナ
        main_frame = tk.Frame(self.root, bg=COLORS["bg_dark"], padx=24, pady=20)
        main_frame.pack(fill="both", expand=True)

        # --- プリセット作成モード バナー (初期は非表示) ---
        self.preset_banner = tk.Frame(main_frame, bg=COLORS["success"], pady=8)
        self.preset_banner_label = tk.Label(
            self.preset_banner, text="🎁 プリセット作成モード：現在の設定をプリセットとして保存できます",
            font=("Segoe UI", 10, "bold"), fg=COLORS["text_bright"], bg=COLORS["success"]
        )
        self.preset_banner_label.pack()

        # --- タイトル ---
        self.title_frame = tk.Frame(main_frame, bg=COLORS["bg_dark"])
        self.title_frame.pack(fill="x", pady=(0, 16))
        title_frame = self.title_frame

        tk.Label(
            title_frame, text="⚡ Quick Compressor",
            font=("Segoe UI", 18, "bold"), fg=COLORS["accent"], bg=COLORS["bg_dark"]
        ).pack(side="left")

        # ピン留めボタン (Always on top)
        self.is_topmost = False
        self.pin_btn = tk.Button(
            title_frame, text="📌 最前面",
            font=("Segoe UI", 9), fg=COLORS["text_dim"],
            bg=COLORS["bg_card"], activebackground=COLORS["bg_input"],
            activeforeground=COLORS["accent"],
            relief="flat", cursor="hand2", padx=8, pady=2,
            highlightbackground=COLORS["border"], highlightthickness=1,
            command=self._toggle_topmost,
        )
        self.pin_btn.pack(side="right", pady=(8, 0))

        # 設定ボタン
        settings_btn = tk.Button(
            title_frame, text="⚙ 設定",
            font=("Segoe UI", 9), fg=COLORS["text_dim"],
            bg=COLORS["bg_card"], activebackground=COLORS["bg_input"],
            activeforeground=COLORS["accent"],
            relief="flat", cursor="hand2", padx=8, pady=2,
            highlightbackground=COLORS["border"], highlightthickness=1,
            command=self._open_settings,
        )
        settings_btn.pack(side="right", pady=(8, 0), padx=(0, 8))

        # プリセット作成ボタン
        self.preset_btn = tk.Button(
            title_frame, text="🎁 プリセット作成",
            font=("Segoe UI", 9), fg=COLORS["success"],
            bg=COLORS["bg_card"], activebackground=COLORS["bg_input"],
            activeforeground=COLORS["success"],
            relief="flat", cursor="hand2", padx=8, pady=2,
            highlightbackground=COLORS["border"], highlightthickness=1,
            command=self._toggle_preset_mode,
        )
        self.preset_btn.pack(side="right", pady=(8, 0), padx=(0, 8))

        preset_manage_btn = tk.Button(
            title_frame, text="📋 プリセット管理",
            font=("Segoe UI", 9), fg=COLORS["accent"],
            bg=COLORS["bg_card"], activebackground=COLORS["bg_input"],
            activeforeground=COLORS["accent"],
            relief="flat", cursor="hand2", padx=8, pady=2,
            highlightbackground=COLORS["border"], highlightthickness=1,
            command=self._open_preset_manager,
        )
        preset_manage_btn.pack(side="right", pady=(8, 0), padx=(0, 8))

        tk.Label(
            title_frame, text="NVIDIA NVENC",
            font=("Segoe UI", 10), fg=COLORS["text_dim"], bg=COLORS["bg_dark"]
        ).pack(side="right", pady=(8, 0), padx=(0, 8))

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
            self.card_frame, text="📁 動画ファイルを選択...",
            font=("Segoe UI", 11, "bold"), fg=COLORS["accent"], bg=COLORS["bg_card"],
            activebackground=COLORS["bg_input"], activeforeground=COLORS["accent_hover"],
            relief="flat", cursor="hand2", pady=8,
            command=self._select_file
        )
        btn.pack(fill="x")

    def _build_populated_file_info(self):
        for widget in self.card_frame.winfo_children():
            widget.destroy()

        # ファイル名
        filename = Path(self.input_path).name
        if len(filename) > 55:
            filename = filename[:52] + "..."
            
        header_frame = tk.Frame(self.card_frame, bg=COLORS["bg_card"])
        header_frame.pack(fill="x")
            
        tk.Label(
            header_frame, text=f"📁 {filename}",
            font=("Segoe UI", 11, "bold"), fg=COLORS["text"], bg=COLORS["bg_card"],
            anchor="w"
        ).pack(side="left")
        
        tk.Button(
            header_frame, text="📁 ファイルを選択",
            font=("Segoe UI", 9), fg=COLORS["accent"], bg=COLORS["bg_card"],
            activebackground=COLORS["bg_input"], activeforeground=COLORS["accent_hover"],
            relief="flat", cursor="hand2", padx=8, pady=0,
            command=self._select_file
        ).pack(side="right")

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
                         bg=COLORS["bg_card"], font=("Segoe UI", 9)).pack(side="left")
            tk.Label(detail_frame, text=detail, fg=COLORS["text_dim"],
                     bg=COLORS["bg_card"], font=("Segoe UI", 9)).pack(side="left")

    def _toggle_topmost(self):
        self.is_topmost = not self.is_topmost
        self.root.attributes("-topmost", self.is_topmost)
        if self.is_topmost:
            self.pin_btn.configure(fg=COLORS["accent"], bg=COLORS["bg_input"], text="📍 固定中")
        else:
            self.pin_btn.configure(fg=COLORS["text_dim"], bg=COLORS["bg_card"], text="📌 最前面")

    def _on_drop(self, event):
        files = self.root.tk.splitlist(event.data)
        if not files:
            return
        filepath = files[0]
        
        self.input_path = filepath
        self.video_info = get_video_info(self.input_path)
        if "error" in self.video_info:
            messagebox.showerror("エラー", f"動画の読み込みに失敗しました:\n{self.video_info['error']}")
            self.input_path = None
            self._build_empty_file_info()
            self._update_ui_state()
            return
            
        self._build_populated_file_info()
        self._update_ui_state()

    def _select_file(self):
        filepath = filedialog.askopenfilename(
            title="変換する動画ファイルを選択",
            filetypes=[
                ("動画ファイル", "*.mp4 *.mkv *.mov *.avi *.webm *.wmv *.flv *.ts *.m2ts"),
                ("すべてのファイル", "*.*"),
            ],
        )
        if filepath:
            self.input_path = filepath
            # 動画情報を再取得
            self.video_info = get_video_info(self.input_path)
            if "error" in self.video_info:
                messagebox.showerror("エラー", f"動画の読み込みに失敗しました:\n{self.video_info['error']}")
                self.input_path = None
                self._build_empty_file_info()
                self._update_ui_state()
                return
                
            self._build_populated_file_info()
            self._update_ui_state()

    def _build_settings(self, parent):
        """設定エリアの構築"""
        settings_frame = tk.Frame(parent, bg=COLORS["bg_dark"])
        settings_frame.pack(fill="x")

        # --- 上段: コーデック + フレームレート（横並び）---
        top_row = tk.Frame(settings_frame, bg=COLORS["bg_dark"])
        top_row.pack(fill="x", pady=(0, 12))

        # 出力コーデック
        codec_frame = tk.Frame(top_row, bg=COLORS["bg_dark"])
        codec_frame.pack(side="left", fill="x", expand=True, padx=(0, 8))

        tk.Label(codec_frame, text="出力コーデック",
                 font=("Segoe UI", 10, "bold"), fg=COLORS["text"], bg=COLORS["bg_dark"]
                 ).pack(anchor="w")

        self.codec_var = tk.StringVar(value=self._init_codec)
        codec_combo = ttk.Combobox(codec_frame, textvariable=self.codec_var,
                                   values=list(CODECS.keys()), state="readonly",
                                   font=("Segoe UI", 10), width=22)
        codec_combo.pack(fill="x", pady=(4, 0))

        # フレームレート
        fps_frame = tk.Frame(top_row, bg=COLORS["bg_dark"])
        fps_frame.pack(side="left", fill="x", expand=True, padx=(8, 0))

        tk.Label(fps_frame, text="フレームレート",
                 font=("Segoe UI", 10, "bold"), fg=COLORS["text"], bg=COLORS["bg_dark"]
                 ).pack(anchor="w")

        self.fps_var = tk.StringVar(value=self._init_fps)
        fps_btn_frame = tk.Frame(fps_frame, bg=COLORS["bg_dark"])
        fps_btn_frame.pack(fill="x", pady=(4, 0))

        for fps_option in FRAME_RATES:
            btn = tk.Radiobutton(
                fps_btn_frame, text=fps_option, variable=self.fps_var, value=fps_option,
                font=("Segoe UI", 9), fg=COLORS["text"], bg=COLORS["bg_dark"],
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
                 font=("Segoe UI", 10, "bold"), fg=COLORS["text"], bg=COLORS["bg_dark"]
                 ).pack(anchor="w")

        self.resolution_var = tk.StringVar(value=self._init_resolution)
        resolution_btn_frame = tk.Frame(resolution_frame, bg=COLORS["bg_dark"])
        resolution_btn_frame.pack(fill="x", pady=(4, 0))

        for res_option in RESOLUTIONS:
            btn = tk.Radiobutton(
                resolution_btn_frame, text=res_option, variable=self.resolution_var, value=res_option,
                font=("Segoe UI", 9), fg=COLORS["text"], bg=COLORS["bg_dark"],
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
            font=("Segoe UI", 9), fg=COLORS["text_dim"], bg=COLORS["bg_dark"]
        )
        self.resolution_preview_label.pack(anchor="w")

        # --- 画質 (CQP) / 容量指定 ---
        quality_frame = tk.Frame(settings_frame, bg=COLORS["bg_dark"])
        quality_frame.pack(fill="x", pady=(0, 12))

        # モード選択ラジオボタン
        mode_frame = tk.Frame(quality_frame, bg=COLORS["bg_dark"])
        mode_frame.pack(fill="x", pady=(0, 8))

        tk.Label(mode_frame, text="設定モード",
                 font=("Segoe UI", 10, "bold"), fg=COLORS["text"], bg=COLORS["bg_dark"]
                 ).pack(side="left", padx=(0, 12))

        self.mode_var = tk.StringVar(value="cq" if not self._target_size_mb else "size")
        
        tk.Radiobutton(
            mode_frame, text="品質優先 (CQ)", variable=self.mode_var, value="cq",
            font=("Segoe UI", 9), fg=COLORS["text"], bg=COLORS["bg_dark"],
            selectcolor=COLORS["bg_input"], activebackground=COLORS["bg_dark"],
            activeforeground=COLORS["accent"], command=self._on_mode_change
        ).pack(side="left", padx=(0, 8))

        tk.Radiobutton(
            mode_frame, text="容量優先 (MB指定)", variable=self.mode_var, value="size",
            font=("Segoe UI", 9), fg=COLORS["text"], bg=COLORS["bg_dark"],
            selectcolor=COLORS["bg_input"], activebackground=COLORS["bg_dark"],
            activeforeground=COLORS["accent"], command=self._on_mode_change
        ).pack(side="left")

        # --- 品質優先(CQ)用UI ---
        self.cq_frame = tk.Frame(quality_frame, bg=COLORS["bg_dark"])
        
        quality_label_frame = tk.Frame(self.cq_frame, bg=COLORS["bg_dark"])
        quality_label_frame.pack(fill="x")

        tk.Label(quality_label_frame, text="画質 (品質優先 ← → ファイルサイズ優先)",
                 font=("Segoe UI", 10, "bold"), fg=COLORS["text"], bg=COLORS["bg_dark"]
                 ).pack(side="left")

        self.quality_value_label = tk.Label(
            quality_label_frame, text="CQ 24 (高画質)",
            font=("Segoe UI", 10, "bold"), fg=COLORS["success"], bg=COLORS["bg_dark"]
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
            font=("Segoe UI", 8), fg=COLORS["text_dim"], bg=COLORS["bg_dark"]
        )
        self.quality_desc_label.pack(anchor="w")

        # --- 容量優先(MB)用UI ---
        self.size_frame = tk.Frame(quality_frame, bg=COLORS["bg_dark"])

        size_label_frame = tk.Frame(self.size_frame, bg=COLORS["bg_dark"])
        size_label_frame.pack(fill="x")
        
        tk.Label(size_label_frame, text="目標ファイルサイズ (MB)",
                 font=("Segoe UI", 10, "bold"), fg=COLORS["text"], bg=COLORS["bg_dark"]
                 ).pack(side="left")

        self.target_size_var = tk.StringVar(value=str(self._target_size_mb) if self._target_size_mb else "10")
        self.size_combo = ttk.Combobox(
            self.size_frame, textvariable=self.target_size_var,
            values=["8", "10", "25", "30", "50", "100"],
            font=("Segoe UI", 10), width=15
        )
        self.size_combo.pack(anchor="w", pady=(4, 0))

        tk.Label(
            self.size_frame,
            text="指定した容量に収まるようにビットレートを自動調整します",
            font=("Segoe UI", 8), fg=COLORS["text_dim"], bg=COLORS["bg_dark"]
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
            font=("Segoe UI", 10), fg=COLORS["text"], bg=COLORS["bg_dark"],
            selectcolor=COLORS["bg_input"], activebackground=COLORS["bg_dark"],
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
            font=("Segoe UI", 9), fg=COLORS["text_dim"], bg=COLORS["bg_dark"],
            anchor="w"
        )
        self.status_label.pack(fill="x")

        # ボタン行
        btn_frame = tk.Frame(progress_frame, bg=COLORS["bg_dark"])
        btn_frame.pack(fill="x", pady=(10, 0))

        # 変換ボタン
        self.convert_btn = tk.Button(
            btn_frame, text="⚡ 圧縮開始",
            font=("Segoe UI", 13, "bold"), fg=COLORS["text_bright"],
            bg=COLORS["accent"], activebackground=COLORS["accent_hover"],
            activeforeground=COLORS["text_bright"],
            disabledforeground=COLORS["text_bright"],
            relief="flat", padx=32, pady=10, cursor="hand2",
            command=self._start_conversion,
        )
        self.convert_btn.pack(side="right")

        # ファイルを開くボタン（変換後に表示）
        self.open_btn = tk.Button(
            btn_frame, text="📂 出力先を開く",
            font=("Segoe UI", 10), fg=COLORS["text"],
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

        pad = tk.Frame(win, bg=COLORS["bg_dark"], padx=20, pady=16)
        pad.pack(fill="both", expand=True)

        tk.Label(
            pad, text="⚙ 詳細設定",
            font=("Segoe UI", 14, "bold"), fg=COLORS["accent"], bg=COLORS["bg_dark"]
        ).pack(anchor="w", pady=(0, 12))

        # --- エンコードプリセット ---
        preset_card = tk.Frame(pad, bg=COLORS["bg_card"], padx=12, pady=10,
                               highlightbackground=COLORS["border"], highlightthickness=1)
        preset_card.pack(fill="x", pady=(0, 10))

        tk.Label(
            preset_card, text="エンコードプリセット",
            font=("Segoe UI", 10, "bold"), fg=COLORS["text"], bg=COLORS["bg_card"]
        ).pack(anchor="w")

        tk.Label(
            preset_card,
            text="速い → ファイルサイズ大  /  遅い → ファイルサイズ小",
            font=("Segoe UI", 8), fg=COLORS["text_dim"], bg=COLORS["bg_card"]
        ).pack(anchor="w", pady=(0, 6))

        for preset_val, preset_name in NVENC_PRESETS:
            rb = tk.Radiobutton(
                preset_card, text=f"{preset_val}  {preset_name}",
                variable=self.preset_var, value=preset_val,
                font=("Segoe UI", 9), fg=COLORS["text"], bg=COLORS["bg_card"],
                selectcolor=COLORS["bg_input"], activebackground=COLORS["bg_card"],
                activeforeground=COLORS["accent"],
            )
            rb.pack(anchor="w")

        # --- 音声処理モード ---
        audio_card = tk.Frame(pad, bg=COLORS["bg_card"], padx=12, pady=10,
                              highlightbackground=COLORS["border"], highlightthickness=1)
        audio_card.pack(fill="x", pady=(0, 10))

        tk.Label(
            audio_card, text="音声処理モード",
            font=("Segoe UI", 10, "bold"), fg=COLORS["text"], bg=COLORS["bg_card"]
        ).pack(anchor="w", pady=(0, 6))

        audio_modes = [
            ("copy", "コピー（そのまま）— 高速・音質劣化なし"),
            ("reencode", "再エンコード（AAC 128kbps）— 互換性が高い"),
        ]
        for mode_val, mode_name in audio_modes:
            rb = tk.Radiobutton(
                audio_card, text=mode_name,
                variable=self.audio_mode_var, value=mode_val,
                font=("Segoe UI", 9), fg=COLORS["text"], bg=COLORS["bg_card"],
                selectcolor=COLORS["bg_input"], activebackground=COLORS["bg_card"],
                activeforeground=COLORS["accent"],
            )
            rb.pack(anchor="w")

        # --- 自動終了オプション ---
        close_option_card = tk.Frame(pad, bg=COLORS["bg_card"], padx=12, pady=10,
                                     highlightbackground=COLORS["border"], highlightthickness=1)
        close_option_card.pack(fill="x", pady=(0, 10))

        tk.Checkbutton(
            close_option_card, text="変換完了後に自動で閉じる",
            variable=self.auto_close_var,
            font=("Segoe UI", 10), fg=COLORS["text"], bg=COLORS["bg_card"],
            selectcolor=COLORS["bg_input"], activebackground=COLORS["bg_card"],
            activeforeground=COLORS["accent"],
        ).pack(anchor="w")

        # 閉じるボタン
        close_btn = tk.Button(
            pad, text="閉じる",
            font=("Segoe UI", 10), fg=COLORS["text"],
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

    def _on_mode_change(self):
        if self.mode_var.get() == "cq":
            self.size_frame.pack_forget()
            self.cq_frame.pack(fill="x")
        else:
            self.cq_frame.pack_forget()
            self.size_frame.pack(fill="x")

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
    def _build_ffmpeg_command(self) -> list:
        codec_name = self.codec_var.get()
        codec_info = CODECS[codec_name]
        encoder = codec_info["encoder"]
        ext = codec_info["ext"]

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
            if use_gpu_decode:
                cmd.extend(["-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
                           "-c:v", cuvid_decoder])
            else:
                cmd.extend(["-hwaccel", "cuda"])
        
            
        cmd.extend(["-i", self.input_path])

        # ビデオ設定
        cmd.extend(["-c:v", encoder])

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

        if target_size_mb is not None and target_size_mb > 0:
            duration = self.video_info.get("duration", 0)
            if duration > 0:
                is_target_size_mode = True
                audio_kbps = 64 if (self.audio_var.get() and self.video_info.get("has_audio")) else 0
                # 容量超過を防ぐため、目標サイズの95%をターゲットにする（メタデータなどのマージン）
                target_total_kbps = (target_size_mb * 0.95 * 8192) / duration
                video_kbps = max(100, int(target_total_kbps - audio_kbps))
                
                if is_amf:
                    # AMFエンコーダーはvbr_peakを使用
                    cmd.extend([
                        "-rc", "vbr_peak",
                        "-b:v", f"{video_kbps}k",
                        "-maxrate", f"{video_kbps}k",
                        "-bufsize", f"{video_kbps * 2}k"
                    ])
                else:
                    cmd.extend([
                        "-rc", "vbr",
                        "-b:v", f"{video_kbps}k",
                        "-maxrate", f"{video_kbps}k",
                        "-bufsize", f"{video_kbps * 2}k"
                    ])
                
        if not is_target_size_mode:
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
            if preset_val in ("p1", "p2", "p3"):
                amf_preset = "speed"
            elif preset_val in ("p5", "p6", "p7"):
                amf_preset = "quality"
            cmd.extend(["-preset", amf_preset])
        else:
            cmd.extend(["-preset", preset_val])

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

        cmd.append(self.output_path)
        return cmd

    # ─────────────────────────────────────────
    # 変換処理
    # ─────────────────────────────────────────
    def _toggle_preset_mode(self):
        self.preset_mode = not self.preset_mode
        if self.preset_mode:
            self.preset_banner.pack(fill="x", pady=(0, 16), before=self.title_frame)
            self.convert_btn.configure(
                text="💾 現在の設定をプリセットとして保存",
                bg=COLORS["success"],
                activebackground="#157347",
            )
            self.preset_btn.configure(
                text="✖ キャンセル",
                fg=COLORS["error"],
                activeforeground=COLORS["error"]
            )
        else:
            self.preset_banner.pack_forget()
            self.convert_btn.configure(
                text="⚡ 圧縮開始",
                bg=COLORS["accent"],
                activebackground=COLORS["accent_hover"],
            )
            self.preset_btn.configure(
                text="🎁 プリセット作成",
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
        win.title("📋 プリセット管理")
        win.configure(bg=COLORS["bg_dark"])
        win.geometry("400x480")
        win.transient(self.root)
        win.grab_set()

        pad = tk.Frame(win, bg=COLORS["bg_dark"], padx=20, pady=16)
        pad.pack(fill="both", expand=True)

        tk.Label(
            pad, text="プリセット一覧",
            font=("Segoe UI", 12, "bold"), fg=COLORS["accent"], bg=COLORS["bg_dark"]
        ).pack(anchor="w", pady=(0, 8))

        list_frame = tk.Frame(pad, bg=COLORS["bg_card"], highlightbackground=COLORS["border"], highlightthickness=1)
        list_frame.pack(fill="both", expand=True, pady=(0, 12))

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")

        self.preset_listbox = tk.Listbox(
            list_frame, font=("Segoe UI", 10), bg=COLORS["bg_input"], fg=COLORS["text"],
            selectbackground=COLORS["accent"], selectforeground=COLORS["text_bright"],
            relief="flat", borderwidth=0, highlightthickness=0,
            yscrollcommand=scrollbar.set
        )
        self.preset_listbox.pack(side="left", fill="both", expand=True, padx=2, pady=2)
        scrollbar.config(command=self.preset_listbox.yview)

        edit_frame = tk.Frame(pad, bg=COLORS["bg_dark"])
        edit_frame.pack(fill="x")

        tk.Label(edit_frame, text="選択中の名前を変更:", font=("Segoe UI", 9), fg=COLORS["text"], bg=COLORS["bg_dark"]).pack(anchor="w")
        
        rename_frame = tk.Frame(edit_frame, bg=COLORS["bg_dark"])
        rename_frame.pack(fill="x", pady=(4, 12))
        
        self.preset_name_var = tk.StringVar()
        name_entry = tk.Entry(
            rename_frame, textvariable=self.preset_name_var,
            font=("Segoe UI", 10), bg=COLORS["bg_input"], fg=COLORS["text"],
            relief="flat", highlightbackground=COLORS["border"], highlightthickness=1,
            insertbackground=COLORS["text"]
        )
        name_entry.pack(side="left", fill="x", expand=True, ipady=4)

        rename_btn = tk.Button(
            rename_frame, text="変更",
            font=("Segoe UI", 9), fg=COLORS["text_bright"], bg=COLORS["accent"],
            activebackground=COLORS["accent_hover"], activeforeground=COLORS["text_bright"],
            relief="flat", cursor="hand2", padx=12,
            command=self._rename_preset
        )
        rename_btn.pack(side="left", padx=(8, 0))

        action_frame = tk.Frame(pad, bg=COLORS["bg_dark"])
        action_frame.pack(fill="x")

        delete_btn = tk.Button(
            action_frame, text="🗑 削除",
            font=("Segoe UI", 9), fg=COLORS["error"], bg=COLORS["bg_card"],
            activebackground=COLORS["bg_input"], activeforeground=COLORS["error"],
            relief="flat", cursor="hand2", padx=12, pady=6,
            highlightbackground=COLORS["border"], highlightthickness=1,
            command=self._delete_preset
        )
        delete_btn.pack(side="left")

        close_btn = tk.Button(
            action_frame, text="閉じる",
            font=("Segoe UI", 9), fg=COLORS["text"], bg=COLORS["bg_card"],
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

    def _get_presets_data(self):
        presets_path = os.path.join(register_menu.DATA_DIR, "presets.json")
        default_path = os.path.join(register_menu.APP_DIR, "default_presets.json")
        
        if not os.path.exists(presets_path) and os.path.exists(default_path):
            try:
                import shutil
                shutil.copy2(default_path, presets_path)
                # コピーした時点で、右クリックメニューのレジストリも最新プリセットで自動更新する
                register_menu.register_context_menu()
            except Exception:
                pass

        presets = {}
        if os.path.exists(presets_path):
            try:
                with open(presets_path, "r", encoding="utf-8") as f:
                    presets = json.load(f)
            except Exception:
                pass
        return presets_path, presets

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
        _, presets = self._get_presets_data()
        for name in sorted(presets.keys()):
            self.preset_listbox.insert(tk.END, name)

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
            
        path, presets = self._get_presets_data()
        if new_name in presets:
            messagebox.showwarning("警告", "その名前のプリセットは既に存在します。")
            return
            
        if old_name in presets:
            presets[new_name] = presets.pop(old_name)
            if self._save_presets_data(path, presets):
                self._refresh_preset_list()
                self.preset_name_var.set("")
                messagebox.showinfo("完了", "名前を変更し、メニューを更新しました！")

    def _delete_preset(self):
        selection = self.preset_listbox.curselection()
        if not selection:
            return
            
        name = self.preset_listbox.get(selection[0])
        if messagebox.askyesno("確認", f"プリセット「{name}」を削除しますか？"):
            path, presets = self._get_presets_data()
            if name in presets:
                del presets[name]
                if self._save_presets_data(path, presets):
                    self._refresh_preset_list()
                    self.preset_name_var.set("")
                    messagebox.showinfo("完了", "削除し、メニューを更新しました！")

    def _save_preset(self):
        from tkinter import simpledialog
        name = simpledialog.askstring("プリセット名", "プリセットの名前を入力してください\n（例: Discord用、Steam用）")
        if not name:
            return
        
        presets_path = os.path.join(register_menu.DATA_DIR, "presets.json")
        user_presets = {}
        if os.path.exists(presets_path):
            try:
                with open(presets_path, "r", encoding="utf-8") as f:
                    user_presets = json.load(f)
            except:
                pass
        
        user_presets[name] = {
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
                user_presets[name]["target_size_mb"] = float(self.target_size_var.get())
            except ValueError:
                user_presets[name]["target_size_mb"] = 10.0
        else:
            user_presets[name]["cq"] = self.quality_var.get()
        
        try:
            with open(presets_path, "w", encoding="utf-8") as f:
                json.dump(user_presets, f, ensure_ascii=False, indent=4, sort_keys=True)
        except Exception as e:
            messagebox.showerror("エラー", f"プリセットの保存に失敗しました:\n{e}")
            return
            
        try:
            register_menu.register_context_menu()
            messagebox.showinfo("完了", f"プリセット「{name}」を保存し、右クリックメニューを更新しました！")
            self._toggle_preset_mode()
        except Exception as e:
            messagebox.showerror("エラー", f"レジストリの更新に失敗しました:\n{e}")

    def _start_conversion(self):
        if not self.input_path and not self.preset_mode:
            return

        if self.preset_mode:
            self._save_preset()
            return

        if self.is_converting:
            return
        self.is_converting = True
        self.convert_btn.configure(state="disabled", text="変換中...", bg=COLORS["text_dim"])

        thread = threading.Thread(target=self._run_ffmpeg, daemon=True)
        thread.start()

    def _run_ffmpeg(self):
        cmd = self._build_ffmpeg_command()
        duration = self.video_info.get("duration", 0)

        self._update_status(f"変換中... 出力: {Path(self.output_path).name}")
        self._update_progress(0)

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                encoding="utf-8",
                errors="replace",
            )

            # FFmpegの進捗はstderrに出力される
            time_pattern = re.compile(r"time=(\d+):(\d+):(\d+)\.(\d+)")

            for line in self.process.stderr:
                match = time_pattern.search(line)
                if match and duration > 0:
                    h, m, s, cs = match.groups()
                    current = int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100
                    progress = min(current / duration * 100, 99.9)
                    self._update_progress(progress)

                    # 速度情報の抽出
                    speed_match = re.search(r"speed=\s*([\d.]+)x", line)
                    speed_text = f" ({speed_match.group(1)}x)" if speed_match else ""
                    self._update_status(
                        f"変換中... {progress:.1f}%{speed_text}  →  {Path(self.output_path).name}"
                    )

            self.process.wait()

            if self.process.returncode == 0:
                self._update_progress(100)
                # 出力ファイルのサイズを取得
                out_size = os.path.getsize(self.output_path) if os.path.exists(self.output_path) else 0
                compression = ""
                if self.video_info["filesize"] > 0 and out_size > 0:
                    ratio = out_size / self.video_info["filesize"] * 100
                    compression = f"  ({ratio:.1f}% / 元サイズ)"
                self._update_status(
                    f"✅ 変換完了！  {format_filesize(out_size)}{compression}"
                )
                self._show_success()
            else:
                stderr_out = self.process.stderr.read() if self.process.stderr else ""
                self._update_status(f"❌ 変換失敗 (コード: {self.process.returncode})")
                self._show_error(f"FFmpegがエラーで終了しました。\n\n終了コード: {self.process.returncode}")

        except Exception as e:
            self._update_status(f"❌ エラー: {str(e)}")
            self._show_error(str(e))

        finally:
            self.is_converting = False
            self.process = None
            self.root.after(0, lambda: self.convert_btn.configure(
                state="normal", text="⚡ 圧縮開始", bg=COLORS["accent"]
            ))

    def _update_progress(self, value):
        self.root.after(0, lambda: self.progress_var.set(value))

    def _update_status(self, text):
        self.root.after(0, lambda: self.status_label.configure(text=text))

    def _show_success(self):
        def _update():
            self.progress_bar.configure(style="Custom.Horizontal.TProgressbar")
            style = ttk.Style()
            style.configure("Custom.Horizontal.TProgressbar", background=COLORS["success"])
            self.open_btn.pack(side="left")
            if self.auto_close_var.get():
                self.root.destroy()
        self.root.after(0, _update)

    def _show_error(self, message):
        def _update():
            style = ttk.Style()
            style.configure("Custom.Horizontal.TProgressbar", background=COLORS["error"])
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
    parser.add_argument("--cq", type=int, default=24, help="画質(CQ値)")
    parser.add_argument("--audio-mode", choices=["copy", "reencode"], default="copy", help="音声処理モード")
    parser.add_argument("--no-audio", action="store_true", help="音声を含めない")
    parser.add_argument("--auto", action="store_true", help="自動変換開始")
    parser.add_argument("--target-size-mb", type=float, default=None, help="目標ファイルサイズ(MB)")
    parser.add_argument("--codec", default=detect_gpu_and_default_codec(), help="出力コーデック")
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
