#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPU Video Converter - NVIDIA NVENC
右クリックメニューから起動し、GPU(NVENC)で高速・高画質な動画変換を行うツール。
"""

import sys
import os
import json
import argparse
import subprocess
import threading
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

# ─────────────────────────────────────────────
# 定数
# ─────────────────────────────────────────────
FFMPEG_PATH = "ffmpeg"
FFPROBE_PATH = "ffprobe"

# カラーパレット（ライト・シンプルモード）
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
    "H.264 (NVENC)": {"encoder": "h264_nvenc", "ext": "mp4"},
    "HEVC / H.265 (NVENC)": {"encoder": "hevc_nvenc", "ext": "mp4"},
    "AV1 (NVENC)": {"encoder": "av1_nvenc", "ext": "mp4"},
}

FRAME_RATES = ["元のまま", "24", "30", "60"]

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
class GPUConverterApp:
    def __init__(self, root: tk.Tk, input_path: str,
                 auto_start: bool = False,
                 preset: str = "p4",
                 fps: str = "元のまま",
                 scale: int = 100,
                 cq: int = 24,
                 audio_mode: str = "copy",
                 no_audio: bool = False):
        self.root = root
        self.input_path = input_path
        self.is_converting = False
        self.process = None

        # ウィンドウ設定
        self.root.title("GPU動画コンバーター")
        self.root.configure(bg=COLORS["bg_dark"])
        self.root.resizable(False, False)

        # DPI対応
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        # 動画情報を取得
        self.video_info = get_video_info(input_path)
        if "error" in self.video_info:
            messagebox.showerror("エラー", f"動画の読み込みに失敗しました:\n{self.video_info['error']}")
            sys.exit(1)

        # 詳細設定変数（デフォルト値）
        self.preset_var = tk.StringVar(value=preset)
        self.audio_mode_var = tk.StringVar(value=audio_mode)

        # UI用初期値保持
        self._init_fps = fps
        self._init_scale = scale
        self._init_cq = cq
        self._init_no_audio = no_audio
        self._auto_start = auto_start

        # UI用ttkスタイルの設定（完全ダークモード専用）
        style = ttk.Style()
        style.theme_use("default")
        style.configure(".", background=COLORS["bg_dark"], foreground=COLORS["text"], 
                        fieldbackground=COLORS["bg_input"], selectbackground=COLORS["accent"], 
                        selectforeground=COLORS["text_bright"], bordercolor=COLORS["border"], 
                        darkcolor=COLORS["border"], lightcolor=COLORS["border"])
        style.map("TCombobox", fieldbackground=[("readonly", COLORS["bg_input"])], selectbackground=[("readonly", COLORS["accent"])], selectforeground=[("readonly", COLORS["text_bright"])])
        style.configure("Horizontal.TScale", background=COLORS["accent"], troughcolor=COLORS["progress_trough"])
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

    # ─────────────────────────────────────────
    # UI構築
    # ─────────────────────────────────────────
    def _build_ui(self):
        # メインコンテナ
        main_frame = tk.Frame(self.root, bg=COLORS["bg_dark"], padx=24, pady=20)
        main_frame.pack(fill="both", expand=True)

        # --- タイトル ---
        title_frame = tk.Frame(main_frame, bg=COLORS["bg_dark"])
        title_frame.pack(fill="x", pady=(0, 16))

        tk.Label(
            title_frame, text="⚡ GPU動画コンバーター",
            font=("Segoe UI", 18, "bold"), fg=COLORS["accent"], bg=COLORS["bg_dark"]
        ).pack(side="left")

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
        settings_btn.pack(side="right", pady=(8, 0))

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
        card = tk.Frame(parent, bg=COLORS["bg_card"], padx=16, pady=12,
                        highlightbackground=COLORS["border"], highlightthickness=1)
        card.pack(fill="x", pady=(0, 4))

        # ファイル名
        filename = Path(self.input_path).name
        if len(filename) > 55:
            filename = filename[:52] + "..."
        tk.Label(
            card, text=f"📁 {filename}",
            font=("Segoe UI", 11, "bold"), fg=COLORS["text"], bg=COLORS["bg_card"],
            anchor="w"
        ).pack(fill="x")

        # 詳細情報行
        info = self.video_info
        detail_frame = tk.Frame(card, bg=COLORS["bg_card"])
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

        self.codec_var = tk.StringVar(value="HEVC / H.265 (NVENC)")
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

        # --- 解像度スケール ---
        scale_frame = tk.Frame(settings_frame, bg=COLORS["bg_dark"])
        scale_frame.pack(fill="x", pady=(0, 12))

        scale_label_frame = tk.Frame(scale_frame, bg=COLORS["bg_dark"])
        scale_label_frame.pack(fill="x")

        tk.Label(scale_label_frame, text="解像度スケール",
                 font=("Segoe UI", 10, "bold"), fg=COLORS["text"], bg=COLORS["bg_dark"]
                 ).pack(side="left")

        self.scale_value_label = tk.Label(
            scale_label_frame, text="100%",
            font=("Segoe UI", 10, "bold"), fg=COLORS["accent"], bg=COLORS["bg_dark"]
        )
        self.scale_value_label.pack(side="right")

        self.scale_var = tk.IntVar(value=self._init_scale)
        self.scale_slider = ttk.Scale(
            scale_frame, from_=25, to=100, orient="horizontal",
            variable=self.scale_var, length=400,
            command=self._on_scale_change
        )
        self.scale_slider.pack(fill="x", pady=(4, 0))

        # 解像度変換後のプレビュー表示
        self.scale_preview_label = tk.Label(
            scale_frame,
            text=f"{self.video_info['width']}×{self.video_info['height']} → {self.video_info['width']}×{self.video_info['height']}",
            font=("Segoe UI", 9), fg=COLORS["text_dim"], bg=COLORS["bg_dark"]
        )
        self.scale_preview_label.pack(anchor="w")

        # --- 画質 (CQP) ---
        quality_frame = tk.Frame(settings_frame, bg=COLORS["bg_dark"])
        quality_frame.pack(fill="x", pady=(0, 12))

        quality_label_frame = tk.Frame(quality_frame, bg=COLORS["bg_dark"])
        quality_label_frame.pack(fill="x")

        tk.Label(quality_label_frame, text="画質 (品質優先 ← → ファイルサイズ優先)",
                 font=("Segoe UI", 10, "bold"), fg=COLORS["text"], bg=COLORS["bg_dark"]
                 ).pack(side="left")

        self.quality_value_label = tk.Label(
            quality_label_frame, text="CQ 24 (高画質)",
            font=("Segoe UI", 10, "bold"), fg=COLORS["success"], bg=COLORS["bg_dark"]
        )
        self.quality_value_label.pack(side="right")

        # CQP/CQスライダー: 値が小さいほど高画質（範囲: 15〜40）
        # UIでは左=高画質(15)、右=低画質(40) の直感的な操作にする
        self.quality_var = tk.IntVar(value=self._init_cq)
        self.quality_slider = ttk.Scale(
            quality_frame, from_=15, to=40, orient="horizontal",
            variable=self.quality_var, length=400,
            command=self._on_quality_change
        )
        self.quality_slider.pack(fill="x", pady=(4, 0))

        # 画質プレビュー
        self.quality_desc_label = tk.Label(
            quality_frame,
            text="CQ値が低い ← 高画質・大ファイル ｜ 低画質・小ファイル → CQ値が高い",
            font=("Segoe UI", 8), fg=COLORS["text_dim"], bg=COLORS["bg_dark"]
        )
        self.quality_desc_label.pack(anchor="w")

        # --- 音声 ---
        audio_frame = tk.Frame(settings_frame, bg=COLORS["bg_dark"])
        audio_frame.pack(fill="x", pady=(0, 4))

        self.audio_var = tk.BooleanVar(value=not self._init_no_audio)
        audio_check = tk.Checkbutton(
            audio_frame, text="音声を含める",
            variable=self.audio_var,
            font=("Segoe UI", 10), fg=COLORS["text"], bg=COLORS["bg_dark"],
            selectcolor=COLORS["bg_input"], activebackground=COLORS["bg_dark"],
            activeforeground=COLORS["accent"],
        )
        audio_check.pack(anchor="w")

        if not self.video_info.get("has_audio"):
            audio_check.configure(state="disabled")
            self.audio_var.set(False)
            audio_check.configure(text="音声を含める (元の動画に音声なし)")

        # 初期値に基づくラベル表示の更新
        self._on_scale_change(self._init_scale)
        self._on_quality_change(self._init_cq)

    def _build_progress_area(self, parent):
        """進捗と変換ボタンの構築"""
        progress_frame = tk.Frame(parent, bg=COLORS["bg_dark"])
        progress_frame.pack(fill="x", pady=(4, 0))

        # 進捗バー
        self.progress_var = tk.DoubleVar(value=0)

        # ttkスタイルは__init__で設定済み

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
    def _on_scale_change(self, value):
        pct = int(float(value))
        self.scale_value_label.configure(text=f"{pct}%")
        new_w = int(self.video_info["width"] * pct / 100)
        new_h = int(self.video_info["height"] * pct / 100)
        # 偶数にする (FFmpegの制約)
        new_w = new_w - (new_w % 2)
        new_h = new_h - (new_h % 2)
        self.scale_preview_label.configure(
            text=f"{self.video_info['width']}×{self.video_info['height']} → {new_w}×{new_h}"
        )

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
        input_codec = self.video_info.get("codec", "")
        cuvid_decoder = CUVID_DECODERS.get(input_codec)
        use_gpu_decode = cuvid_decoder is not None

        cmd = [FFMPEG_PATH, "-y"]
        if use_gpu_decode:
            cmd.extend(["-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
                       "-c:v", cuvid_decoder])
        else:
            cmd.extend(["-hwaccel", "cuda"])
        cmd.extend(["-i", self.input_path])

        # ビデオ設定
        cmd.extend(["-c:v", encoder])

        # CQP (品質)
        cq = self.quality_var.get()
        if encoder in ("h264_nvenc", "hevc_nvenc"):
            cmd.extend(["-rc", "constqp", "-qp", str(cq)])
        elif encoder == "av1_nvenc":
            cmd.extend(["-cq", str(cq)])

        # NVENC プリセット（設定ダイアログから取得）
        cmd.extend(["-preset", self.preset_var.get()])

        # ビデオフィルター
        filters = []

        # 解像度スケール
        scale_pct = self.scale_var.get()
        if scale_pct < 100:
            new_w = int(self.video_info["width"] * scale_pct / 100)
            new_h = int(self.video_info["height"] * scale_pct / 100)
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
            if self.audio_mode_var.get() == "copy":
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
    def _start_conversion(self):
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


# ─────────────────────────────────────────────
# メイン起動
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", nargs="?", help="入力ファイル")
    parser.add_argument("--preset", default="p4", help="エンコードプリセット")
    parser.add_argument("--fps", default="元のまま", help="フレームレート")
    parser.add_argument("--scale", type=int, default=100, help="解像度スケール(%)")
    parser.add_argument("--cq", type=int, default=24, help="画質(CQ値)")
    parser.add_argument("--audio-mode", choices=["copy", "reencode"], default="copy", help="音声処理モード")
    parser.add_argument("--no-audio", action="store_true", help="音声を含めない")
    parser.add_argument("--auto", action="store_true", help="自動変換開始")
    
    args, _ = parser.parse_known_args()

    if not args.input:
        # 引数がない場合はファイル選択ダイアログを表示
        temp_root = tk.Tk()
        temp_root.withdraw()
        filepath = filedialog.askopenfilename(
            title="変換する動画ファイルを選択",
            filetypes=[
                ("動画ファイル", "*.mp4 *.mkv *.mov *.avi *.webm *.wmv *.flv *.ts *.m2ts"),
                ("すべてのファイル", "*.*"),
            ],
        )
        temp_root.destroy()
        if not filepath:
            sys.exit(0)
    else:
        filepath = args.input

    if not os.path.isfile(filepath):
        messagebox.showerror("エラー", f"ファイルが見つかりません:\n{filepath}")
        sys.exit(1)

    root = tk.Tk()
    app = GPUConverterApp(
        root, filepath,
        auto_start=args.auto,
        preset=args.preset,
        fps=args.fps,
        scale=args.scale,
        cq=args.cq,
        audio_mode=args.audio_mode,
        no_audio=args.no_audio
    )
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
