#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#必要ライブラリのインポート
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
from PIL import Image, ImageDraw, ImageTk, ImageFont
import customtkinter as ctk
import register_menu

# CustomTkinter テーマ設定 
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

#ドラッグアンドドロップ用ライブラリ try:～except:でエラー回避
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False

# タスクバー進捗表示用 (Windows API)
import ctypes
from ctypes import wintypes

TBPF_NOPROGRESS = 0
TBPF_INDETERMINATE = 1  # 準備 (緑)
TBPF_NORMAL = 2         # 通常 (システム設定色, デフォルトで緑または青)
TBPF_ERROR = 4          # エラー (赤)
TBPF_PAUSED = 8         # 一時停止 (黄)

#プログレスバーをpythonから操作
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


#Windowsタスクバーのアイコン部分に進捗バーや状態（カラー）を表示するための制御クラス
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


# ─────────────────────────────────────────
# GPU エンジン使用率監視 (3D & Video Encode)
# ─────────────────────────────────────────
class GpuEngineMonitor:
    """Windows PDH API を用いて 3D および Video Encode エンジンの使用率を低負荷・動的に取得するクラス"""
    def __init__(self):
        self.h_query = None
        self._active_counters = {}  # path -> handle
        self._last_refresh_time = 0
        self._pdh = None
        self._pdh_available = False
        try:
            self._pdh = ctypes.windll.pdh
            self._pdh_available = True
            self._init_query()
        except Exception:
            self._pdh_available = False

    def _init_query(self):
        self.close()
        try:
            h_q = wintypes.HANDLE()
            if self._pdh.PdhOpenQueryW(None, 0, ctypes.byref(h_q)) == 0:
                self.h_query = h_q
                self.refresh_counters()
                self._pdh.PdhCollectQueryData(self.h_query)
        except Exception:
            pass

    def refresh_counters(self):
        """プロセス起動・終了に伴う動的 GPU エンジンカウンターを検出・追従"""
        if not self._pdh_available or not self.h_query:
            return
        try:
            sz_wildcard = "\\GPU Engine(*)\\Utilization Percentage"
            pcch_len = wintypes.DWORD(0)
            self._pdh.PdhExpandWildCardPathW(None, sz_wildcard, None, ctypes.byref(pcch_len), 0)
            if pcch_len.value == 0:
                return

            buf = ctypes.create_unicode_buffer(pcch_len.value)
            if self._pdh.PdhExpandWildCardPathW(None, sz_wildcard, buf, ctypes.byref(pcch_len), 0) != 0:
                return

            raw_bytes = ctypes.string_at(ctypes.byref(buf), pcch_len.value * 2)
            raw_str = raw_bytes.decode('utf-16le')
            paths = set(p for p in raw_str.split('\x00') if p)

            # 3D または Video Encode / Codec Engine を対象に抽出
            filtered_paths = set()
            for p in paths:
                p_lower = p.lower()
                if "engtype_3d" in p_lower or any(k in p_lower for k in ("engtype_video encode", "engtype_videoencode", "engtype_video codec engine", "engtype_video_codec")):
                    filtered_paths.add(p)

            # 新規プロセスのカウンターを追加
            added = False
            for p in filtered_paths:
                if p not in self._active_counters:
                    hc = wintypes.HANDLE()
                    if self._pdh.PdhAddEnglishCounterW(self.h_query, p, 0, ctypes.byref(hc)) == 0:
                        self._active_counters[p] = hc
                        added = True

            # 終了したプロセスのカウンターを削除
            for p in list(self._active_counters.keys()):
                if p not in filtered_paths:
                    try:
                        self._pdh.PdhRemoveCounter(self._active_counters[p])
                    except Exception:
                        pass
                    del self._active_counters[p]

            self._last_refresh_time = time.time()
            if added:
                self._pdh.PdhCollectQueryData(self.h_query)
        except Exception:
            pass

    def get_utilization(self):
        """(util_3d: float, util_encode: float) を返す"""
        if not self._pdh_available:
            return 0.0, 0.0
        try:
            if not self.h_query:
                self._init_query()
                return 0.0, 0.0

            # 1.5秒ごとに新規プロセス（FFmpeg等）をスキャンして自動追従
            if time.time() - self._last_refresh_time >= 1.5:
                self.refresh_counters()

            if self._pdh.PdhCollectQueryData(self.h_query) != 0:
                return 0.0, 0.0

            class PDH_FMT_COUNTERVALUE(ctypes.Structure):
                class _U(ctypes.Union):
                    _fields_ = [
                        ("longValue", wintypes.LONG),
                        ("doubleValue", ctypes.c_double),
                        ("strValue", wintypes.LPCWSTR),
                        ("AnsiStrValue", wintypes.LPCSTR),
                    ]
                _anonymous_ = ("_u",)
                _fields_ = [
                    ("CStatus", wintypes.DWORD),
                    ("_u", _U)
                ]

            PDH_FMT_DOUBLE = 0x00000200
            val = PDH_FMT_COUNTERVALUE()

            u_3d = 0.0
            u_enc = 0.0

            for p, hc in list(self._active_counters.items()):
                if self._pdh.PdhGetFormattedCounterValue(hc, PDH_FMT_DOUBLE, None, ctypes.byref(val)) == 0:
                    if val.CStatus == 0 and val.doubleValue > 0:
                        p_lower = p.lower()
                        if "engtype_3d" in p_lower:
                            u_3d += val.doubleValue
                        else:
                            u_enc += val.doubleValue

            return min(100.0, u_3d), min(100.0, u_enc)
        except Exception:
            return 0.0, 0.0

    def close(self):
        if self._pdh and self.h_query:
            try:
                self._pdh.PdhCloseQuery(self.h_query)
            except Exception:
                pass
        self.h_query = None
        self._active_counters = {}


# バージョン情報とリポジトリ設定
# バージョン情報から
CURRENT_VERSION = "2.1.0"
GITHUB_REPO = "LunaFleuret/Quick-Compressor"

# 定数とパス解決
def get_app_dir():
    """アプリケーション実行階層を取得"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_resource_path(relative_path):
    """
    リソースファイルのパスを取得（二段構え探索構造）
    1. PyInstaller Exe 同階層 (os.path.dirname(sys.executable))
    2. Temp ディレクトリ (_MEIPASS)
    3. スクリプト同階層
    """
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        exe_path = os.path.join(exe_dir, relative_path)
        if os.path.exists(exe_path):
            return exe_path
        
        meipass_dir = getattr(sys, '_MEIPASS', exe_dir)
        meipass_path = os.path.join(meipass_dir, relative_path)
        if os.path.exists(meipass_path):
            return meipass_path
        
        return exe_path
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(script_dir, relative_path)

_bundled_ffmpeg = get_resource_path(os.path.join("bin", "ffmpeg.exe"))
_bundled_ffprobe = get_resource_path(os.path.join("bin", "ffprobe.exe"))

FFMPEG_PATH = _bundled_ffmpeg if os.path.exists(_bundled_ffmpeg) else "ffmpeg"
FFPROBE_PATH = _bundled_ffprobe if os.path.exists(_bundled_ffprobe) else "ffprobe"

# カラーパレット (画像デザイン完全再現パレット)
# 1. 基本情報/テキスト: 白 (#ffffff) / クリーンホワイト (#e2e8f0) / ライトスレート (#94a3b8)
# 2. システムアクセント: スカイシアンブルー (#52b6ff)
# 3. 状態/注意: 成功 (#10b981) / 警告 (#f59e0b) / 破壊・エラー (#ef4444)
COLORS = {
    "bg_dark":         "#151821",  # ベース背景（ディープスレートネイビー）
    "bg_card":         "#212532",  # カード・パネル背景
    "bg_input":        "#1a1d26",  # 入力・リストコンテナ背景
    "bg_btn":          "#2c3242",  # サブボタン背景
    "bg_btn_hover":    "#384054",  # サブボタンホバー
    "accent":          "#52b6ff",  # システムアクセント（爽やかなスカイシアンブルー）
    "accent_hover":    "#38a5f5",
    "accent_press":    "#2093e6",
    "text":            "#e2e8f0",  # 基本テキスト
    "text_dim":        "#94a3b8",  # 補足・ディムテキスト
    "text_bright":     "#ffffff",  # 強調テキスト（ピュアホワイト）
    "success":         "#10b981",  # 成功 / 完了
    "success_hover":   "#059669",
    "warning":         "#f59e0b",  # 警告 / 注意喚起
    "warning_hover":   "#d97706",
    "error":           "#ef4444",  # 危険 / 破壊的操作 / エラー / 中止
    "border":          "#2d3345",  # カード境界線
    "border_light":    "#3e475e",  # コントロール枠線
    "border_card":     "#2d3345",  # カード枠線
    "slider_track":    "#1a1d26",  # スライダートラック
    "progress_trough": "#1a1d26",  # プログレストラック
    "selected_bg":     "#2d3446",  # リストアイテム選択中背景
}

# 高視認性UIフォント (Windows標準の滑らかな Yu Gothic UI)
APP_FONT = "Yu Gothic UI"


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

FRAME_RATES = ["元のまま", "60", "30", "24"]
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
def parse_version(v_str: str) -> tuple:
    """バージョン文字列 ('v2.1.0' 等) を数値タプルに変換"""
    import re
    if not v_str:
        return (0,)
    v_clean = str(v_str).lstrip("vV").strip()
    match = re.search(r"^(\d+(?:\.\d+)*)", v_clean)
    if match:
        return tuple(int(n) for n in match.group(1).split("."))
    return (0,)


def detect_gpu_and_default_codec() -> str:
    """初期選択のデフォルトコーデックを返す"""
    return "自動 (推奨: 環境に合わせて自動選択)"


def set_dark_titlebar(window):
    """Windows 10/11 のタイトルバーをダークモードに設定し、角丸を適用する"""
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        if not hwnd:
            hwnd = window.winfo_id()
        # DWMWA_USE_IMMERSIVE_DARK_MODE: 20 (Win11 / Win10 20H1+), 19 (Win10 older)
        value = ctypes.c_int(1)
        res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
        )
        if res != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 19, ctypes.byref(value), ctypes.sizeof(value)
            )
        # DWMWA_WINDOW_CORNER_PREFERENCE: 33 (2 = DWMWCP_ROUND)
        corner_val = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 33, ctypes.byref(corner_val), ctypes.sizeof(corner_val)
        )
    except Exception:
        pass


_icon_cache = {}

def get_file_icon_image(size=28, is_selected=False):
    """モックアップ画像に準拠した紫グラデーションの動画ファイルアイコン画像を生成"""
    key = (size, is_selected)
    if key in _icon_cache:
        return _icon_cache[key]
    
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # 角丸ドキュメント四角形 (紫ベース)
    pad = int(2 * scale)
    r = int(4 * scale)
    bg_c = "#7c3aed" if not is_selected else "#8b5cf6"
    draw.rounded_rectangle((pad, pad, s - pad - 1, s - pad - 1), radius=r, fill=bg_c)
    
    # フィルム風の小さな白い四角（上下）
    hole_w = int(2.5 * scale)
    hole_h = int(2.5 * scale)
    y_top = pad + int(2 * scale)
    y_bot = s - pad - hole_h - int(2 * scale)
    for x_i in range(pad + int(3 * scale), s - pad - int(3 * scale), int(6 * scale)):
        draw.rectangle((x_i, y_top, x_i + hole_w, y_top + hole_h), fill="#ffffff")
        draw.rectangle((x_i, y_bot, x_i + hole_w, y_bot + hole_h), fill="#ffffff")
    
    # 中央に白い再生三角 ▶
    cx, cy = s // 2, s // 2
    tr_s = int(4 * scale)
    points = [
        (cx - int(tr_s * 0.8), cy - tr_s),
        (cx - int(tr_s * 0.8), cy + tr_s),
        (cx + int(tr_s * 1.2), cy),
    ]
    draw.polygon(points, fill="#ffffff")
    
    smooth_img = img.resize((size, size), Image.Resampling.LANCZOS)
    tk_img = ImageTk.PhotoImage(smooth_img)
    _icon_cache[key] = tk_img
    return tk_img




def send_to_recycle_bin(filepath):
    try:
        import ctypes
        from ctypes.wintypes import HWND, UINT, LPCWSTR
        FO_DELETE = 3
        FOF_ALLOWUNDO = 0x40
        FOF_NOCONFIRMATION = 0x0010

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [
                ("hwnd", HWND),
                ("wFunc", UINT),
                ("pFrom", LPCWSTR),
                ("pTo", LPCWSTR),
                ("fFlags", ctypes.c_uint16),
                ("fAnyOperationsAborted", ctypes.c_bool),
                ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", LPCWSTR)
            ]

        pFrom = os.path.abspath(filepath) + '\0\0'
        shf = SHFILEOPSTRUCTW()
        shf.hwnd = None
        shf.wFunc = FO_DELETE
        shf.pFrom = pFrom
        shf.pTo = None
        shf.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION
        shf.fAnyOperationsAborted = False
        shf.hNameMappings = None
        shf.lpszProgressTitle = None
        
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(shf))
        return result == 0
    except Exception:
        try:
            os.remove(filepath)
            return True
        except Exception:
            return False

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

    # ビデオストリームを探す (カバーアートなどの添付画像を除外判定)
    video_stream = None
    audio_stream = None
    for stream in data.get("streams", []):
        disposition = stream.get("disposition") or {}
        codec_name = (stream.get("codec_name") or "").lower()
        is_attached = (
            disposition.get("attached_pic") == 1
            or codec_name in ("mjpeg", "png", "bmp")
        )
        if stream.get("codec_type") == "video" and not is_attached and video_stream is None:
            video_stream = stream
        elif stream.get("codec_type") == "audio" and audio_stream is None:
            audio_stream = stream

    if not video_stream:
        return {"error": "動画ストリームが見つかりません"}

    # ヘルパー関数: "N/A", None や不正な文字列を安全に int / float に変換
    def safe_int(val, default=0):
        if val is None or str(val).strip().upper() == "N/A":
            return default
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return default

    def safe_float(val, default=0.0):
        if val is None or str(val).strip().upper() == "N/A":
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    # フレームレート解析
    fps_str = video_stream.get("r_frame_rate", "0/1")
    try:
        num, den = fps_str.split("/")
        fps = round(int(num) / int(den), 2)
    except (ValueError, ZeroDivisionError):
        fps = 0

    duration = safe_float(data.get("format", {}).get("duration", 0))
    filesize = safe_int(data.get("format", {}).get("size", 0))

    # ビットレート ("N/A" や 0 の場合は format や概算から補正)
    v_bitrate = safe_int(video_stream.get("bit_rate"))
    f_bitrate = safe_int(data.get("format", {}).get("bit_rate"))

    bitrate = v_bitrate or f_bitrate
    if bitrate <= 0 and duration > 0 and filesize > 0:
        # 概算ビットレート自動補正 (bps = filesize * 8 / duration)
        bitrate = int((filesize * 8) / duration)

    width = max(1, safe_int(video_stream.get("width", 0)))
    height = max(1, safe_int(video_stream.get("height", 0)))

    # 回転情報の取得と 360 度正規化
    rotation = 0
    tags = video_stream.get("tags", {})
    if "rotate" in tags:
        try:
            rotation = int(float(tags["rotate"]))
        except (ValueError, TypeError):
            pass
    for side_data in video_stream.get("side_data_list", []):
        if "rotation" in side_data:
            try:
                rotation = int(float(side_data["rotation"]))
            except (ValueError, TypeError):
                pass
                
    normalized_rotation = (rotation % 360 + 360) % 360
    if normalized_rotation in (90, 270):
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
        "rotation": normalized_rotation,
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


class StudioCard(tk.LabelFrame):
    """Studio Pro スタイルの堅牢・軽量カードコンテナ"""
    def __init__(self, parent, title="", bg=None, card_bg=None, border=None):
        card_bg = card_bg or COLORS["bg_card"]
        border_color = border or COLORS["border_card"]
        super().__init__(
            parent, text=f" {title} " if title else "",
            font=(APP_FONT, 10, "bold"), fg=COLORS["text_dim"],
            bg=card_bg, labelanchor="nw",
            highlightbackground=border_color, highlightcolor=border_color,
            highlightthickness=1, bd=0, padx=12, pady=8
        )
        self.inner = self


class CircularProgressMeter(tk.Label):
    """Pillow 4xスーパーサンプリングによる完全アンチエイリアス円形ドーナツメーター"""
    def __init__(self, parent, size=48, line_width=4, track_color=None, fill_color=None, bg=None, **kwargs):
        self.size = size
        self.line_width = line_width
        self.track_color = track_color or COLORS["bg_input"]
        self.fill_color = fill_color or COLORS["accent"]
        self.parent_bg = bg or COLORS["bg_card"]
        self.current_value = 0.0

        super().__init__(parent, bg=self.parent_bg, bd=0, highlightthickness=0, **kwargs)
        self._render(0.0)

    def _render(self, value):
        scale = 4
        sw, sh = self.size * scale, self.size * scale
        lw = self.line_width * scale
        margin = lw // 2 + int(2 * scale)
        x0, y0 = margin, margin
        x1, y1 = sw - margin, sh - margin

        img = Image.new("RGBA", (sw, sh), self.parent_bg)
        draw = ImageDraw.Draw(img)

        # 1. 背景トラック円
        draw.ellipse((x0, y0, x1, y1), outline=self.track_color, width=lw)

        # 2. 進捗円弧 (上部 270度から時計回り)
        if value > 0:
            start_deg = 270
            end_deg = start_deg + int((value / 100.0) * 360)
            draw.arc((x0, y0, x1, y1), start=start_deg, end=end_deg, fill=self.fill_color, width=lw)

        # 3. 中央パーセントテキスト
        text = f"{value:.1f}%" if value < 99.9 else f"{int(value)}%"
        font_size = int(8.5 * scale)
        font_candidates = [
            "C:/Windows/Fonts/YuGothB.ttc",
            "C:/Windows/Fonts/meiryo.ttc",
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/arial.ttf"
        ]
        pil_font = None
        for fpath in font_candidates:
            try:
                pil_font = ImageFont.truetype(fpath, font_size)
                break
            except Exception:
                continue
        if pil_font is None:
            pil_font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=pil_font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = (sw - tw) // 2 - bbox[0]
        ty = (sh - th) // 2 - bbox[1]
        draw.text((tx, ty), text, font=pil_font, fill=COLORS["text_bright"])

        smooth_img = img.resize((self.size, self.size), Image.Resampling.LANCZOS)
        tk_img = ImageTk.PhotoImage(smooth_img)
        self.configure(image=tk_img)
        self.image = tk_img

    def set_value(self, value):
        self.current_value = max(0.0, min(100.0, float(value)))
        self._render(self.current_value)


class PillButton(tk.Label):
    """Pillowの4xスーパーサンプリングによる完全アンチエイリアス角丸ピルボタン"""
    _img_cache = {}

    def __init__(self, parent, text="", command=None, width=50, height=22, radius=11,
                 bg_color=None, fg_color=None,
                 active_bg=None, active_fg=None,
                 parent_bg=None, font=None, **kwargs):
        self.btn_text = text
        self.command = command
        self.w = width
        self.h = height
        self.radius = radius
        self.bg_color = bg_color or COLORS["bg_btn"]
        self.fg_color = fg_color or COLORS["text"]
        self.active_bg = active_bg or COLORS["accent"]
        self.active_fg = active_fg or "#000000"
        self.hover_bg = COLORS["bg_btn_hover"]
        self.parent_bg = parent_bg or COLORS["bg_card"]
        self.btn_font = font or (APP_FONT, 8, "bold")
        self.is_selected = False
        self.is_hovered = False

        super().__init__(parent, bg=self.parent_bg, bd=0, highlightthickness=0, cursor="hand2", **kwargs)

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

        self._render()

    def _get_image(self, fill_hex, text_color_hex):
        scale = 4  # 4倍解像度でアンチエイリアス生成
        key = (self.btn_text, self.w, self.h, self.radius, fill_hex, text_color_hex, self.parent_bg, self.btn_font)
        if key in self._img_cache:
            return self._img_cache[key]

        sw, sh = self.w * scale, self.h * scale
        sr = self.radius * scale

        img = Image.new("RGBA", (sw, sh), self.parent_bg)
        draw = ImageDraw.Draw(img)

        # 角丸四角形を高解像度描画
        draw.rounded_rectangle((0, 0, sw - 1, sh - 1), radius=sr, fill=fill_hex)

        # フォント取得
        font_size = int(self.btn_font[1] * scale)
        font_candidates = [
            "C:/Windows/Fonts/YuGothB.ttc",
            "C:/Windows/Fonts/YuGothM.ttc",
            "C:/Windows/Fonts/meiryo.ttc",
            "C:/Windows/Fonts/msgothic.ttc",
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/arial.ttf"
        ]
        pil_font = None
        for fpath in font_candidates:
            try:
                pil_font = ImageFont.truetype(fpath, font_size)
                break
            except Exception:
                continue
        if pil_font is None:
            pil_font = ImageFont.load_default()

        # テキストの中央配置計算
        bbox = draw.textbbox((0, 0), self.btn_text, font=pil_font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = (sw - tw) // 2 - bbox[0]
        ty = (sh - th) // 2 - bbox[1]
        draw.text((tx, ty), self.btn_text, font=pil_font, fill=text_color_hex)

        # LANCZOS高品質リサンプリングで滑らかに縮小
        smooth_img = img.resize((self.w, self.h), Image.Resampling.LANCZOS)
        tk_img = ImageTk.PhotoImage(smooth_img)
        self._img_cache[key] = tk_img
        return tk_img

    def _render(self):
        if self.is_selected:
            fill = self.active_bg
            txt_color = self.active_fg
        elif self.is_hovered:
            fill = self.hover_bg
            txt_color = COLORS["text_bright"]
        else:
            fill = self.bg_color
            txt_color = self.fg_color

        img = self._get_image(fill, txt_color)
        self.configure(image=img)
        self.image = img

    def set_selected(self, selected: bool):
        self.is_selected = selected
        self._render()

    def _on_enter(self, e):
        self.is_hovered = True
        self._render()

    def _on_leave(self, e):
        self.is_hovered = False
        self._render()

    def _on_click(self, e):
        if self.command:
            self.command()


class TopmostToggle(tk.Label):
    """Pillowの4xスーパーサンプリングによる完全アンチエイリアス最前面ピントグルスイッチ"""
    _img_cache = {}

    def __init__(self, parent, is_on=False, command=None, width=142, height=26, radius=13,
                 bg_color=None, border_color=None, accent_color=None,
                 parent_bg=None, font=None, **kwargs):
        self.is_on = is_on
        self.command = command
        self.w = width
        self.h = height
        self.radius = radius
        self.bg_color = bg_color or COLORS["bg_card"]
        self.border_color = border_color or COLORS["border_light"]
        self.accent_color = accent_color or COLORS["accent"]
        self.parent_bg = parent_bg or COLORS["bg_dark"]
        self.btn_font = font or (APP_FONT, 9)
        self.is_hovered = False

        super().__init__(parent, bg=self.parent_bg, bd=0, highlightthickness=0, cursor="hand2", **kwargs)

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

        self._render()

    def _get_image(self, is_on, is_hovered):
        scale = 4  # 4倍解像度でアンチエイリアス生成
        key = (is_on, is_hovered, self.w, self.h, self.radius, self.bg_color, self.border_color, self.accent_color, self.parent_bg, self.btn_font)
        if key in self._img_cache:
            return self._img_cache[key]

        sw, sh = self.w * scale, self.h * scale
        sr = self.radius * scale

        img = Image.new("RGBA", (sw, sh), self.parent_bg)
        draw = ImageDraw.Draw(img)

        bg = COLORS["bg_btn_hover"] if is_hovered else self.bg_color
        border = self.accent_color if is_on else self.border_color
        line_w = int(1.2 * scale)

        # 1. 外枠バッジ (角丸長方形)
        draw.rounded_rectangle((0, 0, sw - 1, sh - 1), radius=sr, fill=bg, outline=border, width=line_w)

        # 2. ピンアイコン ＆ テキスト
        font_size = int(self.btn_font[1] * scale)
        font_candidates = [
            "C:/Windows/Fonts/YuGothB.ttc" if is_on else "C:/Windows/Fonts/YuGothM.ttc",
            "C:/Windows/Fonts/meiryo.ttc",
            "C:/Windows/Fonts/msgothic.ttc",
            "C:/Windows/Fonts/arial.ttf"
        ]
        pil_font = None
        for fpath in font_candidates:
            try:
                pil_font = ImageFont.truetype(fpath, font_size)
                break
            except Exception:
                continue
        if pil_font is None:
            pil_font = ImageFont.load_default()

        pin_icon = "📌 "
        txt = "固定中 (最前面)" if is_on else "最前面固定"
        txt_color = COLORS["text_bright"] if is_on else COLORS["text_dim"]
        full_text = f"{pin_icon}{txt}"

        bbox = draw.textbbox((0, 0), full_text, font=pil_font)
        th = bbox[3] - bbox[1]
        ty = (sh - th) // 2 - bbox[1]
        tx = int(10 * scale)
        draw.text((tx, ty), full_text, font=pil_font, fill=txt_color)

        # 3. 右側スライドトグルスイッチ (幅 24px, 高さ 14px)
        sw_w = int(24 * scale)
        sw_h = int(14 * scale)
        sw_x = sw - sw_w - int(8 * scale)
        sw_y = (sh - sw_h) // 2
        sw_r = sw_h // 2

        track_fill = self.accent_color if is_on else "#384054"
        draw.rounded_rectangle((sw_x, sw_y, sw_x + sw_w, sw_y + sw_h), radius=sw_r, fill=track_fill)

        # トグルスイッチノブ (白丸)
        knob_d = sw_h - int(4 * scale)
        knob_y = sw_y + int(2 * scale)
        if is_on:
            knob_x = sw_x + sw_w - knob_d - int(2 * scale)
        else:
            knob_x = sw_x + int(2 * scale)
        draw.ellipse((knob_x, knob_y, knob_x + knob_d, knob_y + knob_d), fill="#ffffff")

        # LANCZOS高品質リサンプリングで滑らかに縮小
        smooth_img = img.resize((self.w, self.h), Image.Resampling.LANCZOS)
        tk_img = ImageTk.PhotoImage(smooth_img)
        self._img_cache[key] = tk_img
        return tk_img

    def _render(self):
        img = self._get_image(self.is_on, self.is_hovered)
        self.configure(image=img)
        self.image = img

    def set_state(self, is_on: bool):
        self.is_on = is_on
        self._render()

    def _on_enter(self, e):
        self.is_hovered = True
        self._render()

    def _on_leave(self, e):
        self.is_hovered = False
        self._render()

    def _on_click(self, e):
        if self.command:
            self.command()


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
        if isinstance(input_path, list):
            self.input_paths = [p for p in input_path if p]
            self.input_path = self.input_paths[0] if self.input_paths else None
        else:
            self.input_paths = [input_path] if input_path else []
            self.input_path = input_path
        self.current_file_index = 0
        self.batch_saved_bytes = 0
        self._queue_data = {}  # ファイルパス → {status, progress, orig_size, out_size, settings}
        self._queue_widget_cache = {}  # キュー描画キャッシュ用
        self._selected_queue_path = None  # キューで現在選択中のファイル
        self._is_applying_settings = False  # 設定適用中の重複traceガード
        self._drop_overlay_timer = None  # ドロップオーバーレイタイマー
        self._trace_preset_id = None
        self._trace_codec_id = None
        self._trace_audio_id = None
        self.is_converting = False
        self.process = None
        self._gpu_monitor = None
        self._gpu_monitor_thread = None
        self._gpu_monitor_running = False

        if codec is None:
            codec = detect_gpu_and_default_codec()

        # ウィンドウ設定
        self.root.title(f"Quick Compressor v{CURRENT_VERSION}")
        self.root.configure(bg=COLORS["bg_dark"])
        self.root.resizable(False, False)
        set_dark_titlebar(self.root)


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
                with open(config_path, "r", encoding="utf-8-sig") as f:
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

        # Tkinter全体の標準フォントを約20%拡大して視認性を向上（Yu Gothic UI 10pt）
        try:
            import tkinter.font as tkfont
            for fn in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont", "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont"):
                try:
                    f = tkfont.nametofont(fn)
                    f.configure(family=APP_FONT, size=10, weight="normal")
                except Exception:
                    pass
        except Exception:
            pass

        # UI用ttkスタイルの設定（ドロップダウン立体浮き出し ＆ 20%スケール）
        self.root.option_add("*TCombobox*Listbox.background", "#212532")
        self.root.option_add("*TCombobox*Listbox.foreground", COLORS["text_bright"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", COLORS["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#000000")
        self.root.option_add("*TCombobox*Listbox.font", (APP_FONT, 12))
        self.root.option_add("*TCombobox*Listbox.relief", "solid")
        self.root.option_add("*TCombobox*Listbox.borderWidth", 1)
        self.root.option_add("*TCombobox*Listbox.highlightThickness", 2)
        self.root.option_add("*TCombobox*Listbox.highlightBackground", COLORS["accent"])
        self.root.option_add("*TCombobox*Listbox.highlightColor", COLORS["accent"])

        style = ttk.Style()
        style.theme_use("default")
        style.configure(".", background=COLORS["bg_dark"], foreground=COLORS["text"], 
                        fieldbackground=COLORS["bg_input"], selectbackground=COLORS["accent"], 
                        selectforeground="#000000", bordercolor=COLORS["border"], 
                        darkcolor=COLORS["border"], lightcolor=COLORS["border"])
        style.configure("TCombobox", background=COLORS["bg_card"], foreground=COLORS["text"],
                        fieldbackground=COLORS["bg_input"], bordercolor=COLORS["border_light"],
                        arrowcolor=COLORS["text_dim"], darkcolor=COLORS["border"], lightcolor=COLORS["border"])
        style.map("TCombobox",
                  fieldbackground=[("readonly", COLORS["bg_input"])],
                  selectbackground=[("readonly", COLORS["bg_input"])],
                  selectforeground=[("readonly", COLORS["text"])],
                  bordercolor=[("focus", COLORS["accent"]), ("hover", COLORS["border_light"])])
        style.configure("Vertical.TScrollbar", background="#262c3a", troughcolor=COLORS["bg_card"],
                        bordercolor=COLORS["bg_card"], arrowcolor=COLORS["text_dim"])
        style.map("Vertical.TScrollbar",
                  background=[("active", "#363e52"), ("pressed", "#424b63")],
                  arrowcolor=[("active", COLORS["text_bright"])])
        style.configure("Horizontal.TScale", background=COLORS["accent"], troughcolor=COLORS["slider_track"])
        style.map("Horizontal.TScale", background=[("active", COLORS["accent_hover"])])
        style.configure("Custom.Horizontal.TProgressbar", troughcolor=COLORS["progress_trough"], background=COLORS["accent"], thickness=10)

        # ドロップダウン展開時の半透明バックドロップオーバーレイ制御
        self._dropdown_overlay = None

        def _show_dropdown_backdrop():
            if self._dropdown_overlay is not None:
                return
            try:
                ov = tk.Toplevel(self.root)
                ov.overrideredirect(True)
                ov.configure(bg="#000000")
                ov.attributes("-alpha", 0.65)  # 65%半透明の薄暗い黒
                
                # メインウィンドウの位置とサイズに合わせる
                rx = self.root.winfo_rootx()
                ry = self.root.winfo_rooty()
                rw = self.root.winfo_width()
                rh = self.root.winfo_height()
                ov.geometry(f"{rw}x{rh}+{rx}+{ry}")
                
                # オーバーレイクリック時にも閉じる
                ov.bind("<ButtonPress-1>", lambda e: _hide_dropdown_backdrop())
                self._dropdown_overlay = ov
                ov.lift(self.root)
            except Exception:
                self._dropdown_overlay = None

        def _hide_dropdown_backdrop():
            if self._dropdown_overlay is not None:
                try:
                    self._dropdown_overlay.destroy()
                except Exception:
                    pass
                self._dropdown_overlay = None

        self._show_dropdown_backdrop = _show_dropdown_backdrop
        self._hide_dropdown_backdrop = _hide_dropdown_backdrop

        try:
            self.root.createcommand("py_show_dropdown_backdrop", _show_dropdown_backdrop)
            self.root.createcommand("py_hide_dropdown_backdrop", _hide_dropdown_backdrop)

            # Comboboxのドロップダウン制御 (プリセット選択および出力コーデックに全幅 ＆ 半透明適用、他は標準)
            self.root.tk.eval("""
set custom_wide_combos [list]
proc ttk::combobox::PlacePopdown {cb popdown} {
    global custom_wide_combos
    
    set is_wide 0
    if {[info exists custom_wide_combos] && [lsearch -exact $custom_wide_combos $cb] >= 0} {
        set is_wide 1
    }
    
    if {$is_wide} {
        set toplevel [winfo toplevel $cb]
        set root_x [winfo rootx $toplevel]
        set root_w [winfo width $toplevel]
        
        # 右半分エリア（ウィンドウ中央から右端マージンまで）
        set margin 18
        set half_x [expr {$root_x + ($root_w / 2) + 4}]
        set half_w [expr {($root_w / 2) - $margin - 4}]
        
        if {$half_w < [winfo width $cb]} {
            set target_w [winfo width $cb]
            set target_x [winfo rootx $cb]
        } else {
            set target_x $half_x
            set target_w $half_w
        }
        
        set y [winfo rooty $cb]
        set h [winfo height $cb]
        set H [winfo reqheight $popdown]
        if {$y + $h + $H > [winfo screenheight $popdown]} {
            set Y [expr {$y - $H}]
        } else {
            set Y [expr {$y + $h}]
        }
        wm geometry $popdown ${target_w}x${H}+${target_x}+${Y}
        
        # ドロップダウンメニュー自体を半透明（アルファ 0.90）に設定
        catch {wm attributes $popdown -alpha 0.90}
        
        # 背後メイン画面を半透明に暗転
        py_show_dropdown_backdrop
        after idle [list raise $popdown]
        bind $popdown <Unmap> {+py_hide_dropdown_backdrop}
    } else {
        # その他のプルダウンは通常の標準Tk挙動
        catch {wm attributes $popdown -alpha 1.0}
        
        set x [winfo rootx $cb]
        set y [winfo rooty $cb]
        set w [winfo width $cb]
        set h [winfo height $cb]
        set style [$cb cget -style]
        if { $style eq {} } {
            set style TCombobox
        }
        set postoffset [ttk::style lookup $style -postoffset {} {0 0 0 0}]
        foreach var {x y w h} delta $postoffset {
            incr $var $delta
        }
        set H [winfo reqheight $popdown]
        if {$y + $h + $H > [winfo screenheight $popdown]} {
            set Y [expr {$y - $H}]
        } else {
            set Y [expr {$y + $h}]
        }
        wm geometry $popdown ${w}x${H}+${x}+${Y}
    }
}
""")
        except Exception:
            pass

        # UI構築
        self._build_ui()
        
        # タスクバー進捗用オブジェクトの初期化
        self.taskbar_progress = TaskbarProgress(self.root)

        # 自動開始処理
        if self._auto_start:
            self.root.after(100, self._start_conversion)
            if self.minimize_on_right_click_var.get():
                self.root.iconify()

        # モードに応じたウィンドウサイズと配置
        if getattr(self, '_is_hud_mode', False):
            self._switch_to_hud()
        else:
            self._switch_to_full_gui()

        # ウィンドウのどこでもドラッグ移動できるように設定
        self._enable_window_drag()

    def _enable_window_drag(self):
        def start_drag(event):
            ignore_classes = ("Button", "TButton", "TCombobox", "TScale", "Radiobutton", "TRadiobutton", "Checkbutton", "TCheckbutton", "Canvas", "Scrollbar", "TScrollbar", "Listbox", "Entry", "TEntry", "Text")
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

        if HAS_DND and hasattr(self.root, 'drop_target_register'):
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind('<<Drop>>', self._on_drop)
            self.root.dnd_bind('<<DropEnter>>', self._on_drop_enter)
            self.root.dnd_bind('<<DropPosition>>', self._on_drop_enter)

        # アップデートチェック（非同期）
        threading.Thread(target=self._check_for_updates, daemon=True).start()

        # アプリ終了時のリソース解放
        self.root.protocol("WM_DELETE_WINDOW", self._on_app_close)

        # GPU使用率監視を開始（アイドル時・変換中問わず常時モニタリング）
        self._start_gpu_monitor()

    def _on_app_close(self):
        """アプリ終了処理"""
        self._stop_gpu_monitor()
        try:
            self.root.destroy()
        except Exception:
            pass

    # ─────────────────────────────────────────
    # ─────────────────────────────────────────
    # UI構築 (Studio Pro 高密度・コンパクトデザイン)
    # ─────────────────────────────────────────
    def _create_group_box(self, parent, title_text):
        """Studio Pro スタイルの堅牢・軽量カードコンテナを作成"""
        card = StudioCard(parent, title=title_text)
        card.pack(fill="x", pady=(0, 6))
        return card

    def _create_btn(self, parent, text, command, fg=None, bg=None, padx=12, pady=5, font_size=10, is_bold=False, width=None, height=28):
        """CustomTkinter スタイルの統一ボタン"""
        fg_c = fg or COLORS["text"]
        bg_c = bg or COLORS["bg_btn"]
        weight = "bold" if is_bold else "normal"
        btn = ctk.CTkButton(
            parent, text=text, command=command,
            font=ctk.CTkFont(family=APP_FONT, size=font_size, weight=weight),
            text_color=fg_c, fg_color=bg_c, hover_color=COLORS["bg_btn_hover"],
            corner_radius=8, width=width or 70, height=height
        )
        return btn

    def _build_ui(self):
        # 状態変数を先に初期化（HUDと通常GUI両方で参照）
        self.progress_var = tk.DoubleVar(value=0)
        self.is_topmost = False

        # 外側の水平コンテナ
        self.outer_frame = ctk.CTkFrame(self.root, fg_color=COLORS["bg_dark"])
        self.outer_frame.pack(fill="both", expand=True)

        # --- HUDモード用フレーム（右クリック起動時専用ミニ画面） ---
        self.hud_frame = ctk.CTkFrame(self.outer_frame, fg_color=COLORS["bg_dark"])
        self._build_hud_section(self.hud_frame)

        # メインコンテナ（通常GUI 2カラムダッシュボード）
        self.main_frame = ctk.CTkFrame(self.outer_frame, fg_color=COLORS["bg_dark"])
        main_frame = self.main_frame

        # --- プリセット作成モード バナー (初期は非表示) ---
        self.preset_banner = ctk.CTkFrame(main_frame, fg_color=COLORS["success"], corner_radius=6)
        self.preset_banner_label = ctk.CTkLabel(
            self.preset_banner, text="プリセット作成モード：現在の設定をプリセットとして保存できます",
            font=ctk.CTkFont(family=APP_FONT, size=11, weight="bold"), text_color="#000000"
        )
        self.preset_banner_label.pack(pady=4)

        # --- 1. タイトル & ヘッダーバー ---
        self.title_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        self.title_frame.pack(fill="x", pady=(0, 8))

        title_left = ctk.CTkFrame(self.title_frame, fg_color="transparent")
        title_left.pack(side="left")

        ctk.CTkLabel(
            title_left, text="Quick Compressor",
            font=ctk.CTkFont(family=APP_FONT, size=20, weight="bold"), text_color=COLORS["accent"]
        ).pack(side="left")

        ctk.CTkLabel(
            title_left, text=f" v{CURRENT_VERSION}",
            font=ctk.CTkFont(family=APP_FONT, size=12), text_color=COLORS["text_dim"]
        ).pack(side="left", padx=(6, 0), pady=(4, 0))

        # 最前面固定トグルスイッチ (モックアップ完全準拠の角丸ピル型バッジ)
        self.pin_btn = TopmostToggle(
            self.title_frame, is_on=self.is_topmost, command=self._toggle_topmost,
            width=150, height=28, radius=14
        )
        self.pin_btn.pack(side="right")

        # --- 2. 上段 左右2カラムコンテナ ---
        top_cols = ctk.CTkFrame(main_frame, fg_color="transparent")
        top_cols.pack(fill="both", expand=True, pady=(0, 8))

        # 左カラム: 対象動画リスト (幅 340px)
        left_col = ctk.CTkFrame(top_cols, fg_color="transparent", width=340)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 6))
        left_col.pack_propagate(False)
        self._build_file_section(left_col)

        # 右カラム: プリセット選択 ＆ 詳細設定 (幅約 420px)
        right_col = ctk.CTkFrame(top_cols, fg_color="transparent")
        right_col.pack(side="right", fill="both", expand=True, padx=(6, 0))
        self._build_mode_section(right_col)
        self._build_settings_section(right_col)

        # --- 3. 中段: 進行状況 & GPU円形計器 ---
        self._build_progress_section(main_frame)

        # --- 4. 最下部: ボトムアクションバー ---
        self._build_bottom_bar(main_frame)

        # UI変数のリアルタイム同期トレースの登録
        self._setup_settings_traces()

        # 初期モードの適用（右クリック起動時はHUD、通常起動時は通常GUI）
        self._is_hud_mode = bool(self._auto_start)
        if self._is_hud_mode:
            self._switch_to_hud()
        else:
            self._switch_to_full_gui()

    def _build_hud_section(self, parent):
        """右クリック起動専用のHUDミニ画面を構築"""
        # ヘッダー行
        h_row = tk.Frame(parent, bg=COLORS["bg_dark"])
        h_row.pack(fill="x", pady=(0, 10))

        tk.Label(
            h_row, text="Quick Compressor (HUD)",
            font=(APP_FONT, 12, "bold"), fg=COLORS["accent"], bg=COLORS["bg_dark"]
        ).pack(side="left")

        self.hud_pin_btn = TopmostToggle(
            h_row, is_on=self.is_topmost, command=self._toggle_topmost,
            width=140, height=26, radius=13
        )
        self.hud_pin_btn.pack(side="right")

        # HUD情報カードコンテナ
        card = tk.Frame(
            parent, bg=COLORS["bg_card"],
            highlightbackground=COLORS["border"], highlightthickness=1,
            padx=16, pady=14
        )
        card.pack(fill="x", pady=(0, 10))

        # 1行目: ファイル名 & 元サイズ
        self.hud_file_label = tk.Label(
            card, text="対象: 読み込み中...",
            font=(APP_FONT, 10, "bold"), fg=COLORS["text_bright"], bg=COLORS["bg_card"],
            anchor="w"
        )
        self.hud_file_label.pack(fill="x", pady=(0, 8))

        # 2行目: プログレスバー
        self.hud_progress_bar = ttk.Progressbar(
            card, variable=self.progress_var,
            maximum=100, style="Custom.Horizontal.TProgressbar"
        )
        self.hud_progress_bar.pack(fill="x", pady=(0, 8))

        # 3行目: 進捗率 & 速度 & 残り時間
        self.hud_speed_eta_label = tk.Label(
            card, text="準備中...",
            font=(APP_FONT, 10, "bold"), fg=COLORS["accent"], bg=COLORS["bg_card"],
            anchor="w"
        )
        self.hud_speed_eta_label.pack(fill="x", pady=(0, 5))

        # 4行目: GPU使用率 (3D & Encode)
        self.hud_gpu_label = tk.Label(
            card, text="3D:  0.0%  |  Encode:  0.0%",
            font=(APP_FONT, 10, "bold"), fg=COLORS["text_dim"], bg=COLORS["bg_card"],
            anchor="w"
        )
        self.hud_gpu_label.pack(fill="x", pady=(0, 5))

        # 5行目: 容量削減見込み / 結果
        self.hud_reduction_label = tk.Label(
            card, text="容量削減: 計算中...",
            font=(APP_FONT, 9), fg=COLORS["text_dim"], bg=COLORS["bg_card"],
            anchor="w"
        )
        self.hud_reduction_label.pack(fill="x")

        # ボトムバー (通常GUI切り替え ＆ 中止)
        b_row = tk.Frame(parent, bg=COLORS["bg_dark"])
        b_row.pack(fill="x")

        self.switch_to_gui_btn = self._create_btn(
            b_row, "通常GUIに切り替え", self._switch_to_full_gui,
            fg=COLORS["text"], bg=COLORS["bg_btn"], padx=12, pady=5, font_size=10
        )
        self.switch_to_gui_btn.pack(side="left")

        self.hud_cancel_btn = tk.Button(
            b_row, text="中止",
            font=(APP_FONT, 10, "bold"), fg=COLORS["text_bright"],
            bg=COLORS["error"], activebackground="#e11d48",
            relief="flat", cursor="hand2", padx=16, pady=5,
            command=self._cancel_conversion, bd=0
        )
        self.hud_cancel_btn.pack(side="right")

    def _switch_to_full_gui(self):
        """HUDミニ画面から通常GUI画面へ切り替える"""
        self._is_hud_mode = False
        if hasattr(self, 'hud_frame'):
            self.hud_frame.pack_forget()
        if hasattr(self, 'main_frame'):
            self.main_frame.pack(side="left", fill="both", expand=True, padx=18, pady=16)

        self.root.update_idletasks()
        w = 900
        h = 600

        # 画面中央に配置
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(0, (screen_w - w) // 2)
        y = max(0, (screen_h - h) // 2)

        self.root.minsize(w, h)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self._refresh_file_list_display()

    def _switch_to_hud(self):
        """通常GUI画面からHUDミニ画面へ切り替える"""
        self._is_hud_mode = True
        if hasattr(self, 'main_frame'):
            self.main_frame.pack_forget()
        if hasattr(self, 'hud_frame'):
            self.hud_frame.pack(side="left", fill="both", expand=True, padx=18, pady=16)
        
        self.root.update_idletasks()
        w = 540
        h = max(275, self.hud_frame.winfo_reqheight() + 10)
        
        # 画面中央に配置
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(0, (screen_w - w) // 2)
        y = max(0, (screen_h - h) // 2)

        self.root.minsize(w, h)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self._update_hud_display()

    def _update_hud_display(self):
        """HUDミニ画面の情報表示を更新"""
        if not getattr(self, '_is_hud_mode', False) or not hasattr(self, 'hud_file_label'):
            return
        if self.input_path and hasattr(self, 'video_info'):
            fname = Path(self.input_path).name
            sz = format_filesize(self.video_info.get("filesize", 0))
            self.hud_file_label.configure(text=f"対象: {fname} ({sz})")
        else:
            self.hud_file_label.configure(text="対象: ファイル未選択")

    def _build_file_section(self, parent):
        """左カラム: 対象動画リストパネル"""
        card = ctk.CTkFrame(
            parent, fg_color=COLORS["bg_card"], corner_radius=12,
            border_width=1, border_color=COLORS["border"]
        )
        card.pack(fill="both", expand=True)
        self.file_card = card

        # ヘッダー行: 「対象動画:」 ｜ [🔍 ファイル選択] [🗑 クリア]
        h_row = ctk.CTkFrame(card, fg_color="transparent")
        h_row.pack(fill="x", padx=12, pady=(10, 6))

        ctk.CTkLabel(
            h_row, text="対象動画:",
            font=ctk.CTkFont(family=APP_FONT, size=14, weight="bold"), text_color=COLORS["text_bright"]
        ).pack(side="left")

        ctk.CTkButton(
            h_row, text="🗑 クリア", command=self._clear_input,
            fg_color=COLORS["bg_btn"], hover_color="#ef4444", corner_radius=6,
            font=ctk.CTkFont(family=APP_FONT, size=11, weight="bold"), width=66, height=28
        ).pack(side="right")

        ctk.CTkButton(
            h_row, text="🔍 ファイル選択", command=self._select_file,
            fg_color=COLORS["bg_btn"], hover_color=COLORS["bg_btn_hover"], corner_radius=6,
            font=ctk.CTkFont(family=APP_FONT, size=11, weight="bold"), width=100, height=28
        ).pack(side="right", padx=(0, 6))

        # スクロール可能ファイルリストコンテナ
        self.file_list_scroll = ctk.CTkScrollableFrame(card, fg_color=COLORS["bg_input"], corner_radius=8)
        self.file_list_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        # フッター行: 対象動画件数
        self.file_count_label = ctk.CTkLabel(
            card, text="対象動画: 0 件",
            font=ctk.CTkFont(family=APP_FONT, size=12), text_color=COLORS["text_dim"]
        )
        self.file_count_label.pack(anchor="w", padx=12, pady=(0, 8))

        self.file_path_var = tk.StringVar(value="")
        self._refresh_file_list_display()

    def _refresh_file_list_display(self):
        """左カラムのファイル一覧を描画更新"""
        if not hasattr(self, 'file_list_scroll'):
            return

        for w in self.file_list_scroll.winfo_children():
            w.destroy()

        paths = getattr(self, 'input_paths', [])
        count = len(paths)
        if hasattr(self, 'file_count_label'):
            self.file_count_label.configure(text=f"対象動画: {count} 件")

        if count == 0:
            empty_lbl = ctk.CTkLabel(
                self.file_list_scroll,
                text="ここに動画ファイルを\nドラッグ＆ドロップ",
                font=ctk.CTkFont(family=APP_FONT, size=13), text_color=COLORS["text_dim"],
                justify="center"
            )
            empty_lbl.pack(fill="both", expand=True, pady=46)
            return

        for idx, path in enumerate(paths):
            p = Path(path)
            is_selected = (path == getattr(self, 'input_path', None))
            item_bg = COLORS["selected_bg"] if is_selected else COLORS["bg_card"]
            border_c = COLORS["accent"] if is_selected else COLORS["border"]

            item_card = ctk.CTkFrame(
                self.file_list_scroll, fg_color=item_bg, corner_radius=6,
                border_width=1, border_color=border_c, cursor="hand2"
            )
            item_card.pack(fill="x", pady=(0, 4))

            # 左側: モックアップ準拠の紫グラデーション動画アイコン
            icon_img = get_file_icon_image(size=28, is_selected=is_selected)
            icon_lbl = tk.Label(
                item_card, image=icon_img, bg=item_bg, bd=0, highlightthickness=0
            )
            icon_lbl.image = icon_img
            icon_lbl.pack(side="left", padx=(8, 6), pady=6)

            # 中央: ファイル名 ＆ 容量
            info_f = ctk.CTkFrame(item_card, fg_color="transparent")
            info_f.pack(side="left", fill="x", expand=True, pady=4)

            fname = p.name
            if len(fname) > 28:
                fname = fname[:25] + "..."

            name_lbl = ctk.CTkLabel(
                info_f, text=fname,
                font=ctk.CTkFont(family=APP_FONT, size=12, weight="bold"), text_color=COLORS["text_bright"],
                anchor="w"
            )
            name_lbl.pack(fill="x")

            # 容量の取得
            sz_str = ""
            if os.path.exists(path):
                sz_str = format_filesize(os.path.getsize(path))

            q_info = self._queue_data.get(path, {})
            status = q_info.get("status", "waiting")
            status_str = ""
            status_fg = COLORS["text_dim"]
            if status == "converting":
                prog = q_info.get("progress", 0)
                status_str = f" | 変換中 {prog:.0f}%"
                status_fg = COLORS["accent"]
            elif status == "done":
                status_str = " | 完了"
                status_fg = COLORS["success"]
            elif status == "error":
                status_str = " | 失敗"
                status_fg = COLORS["error"]

            sub_lbl = ctk.CTkLabel(
                info_f, text=f"{sz_str}{status_str}",
                font=ctk.CTkFont(family=APP_FONT, size=11), text_color=status_fg,
                anchor="w"
            )
            sub_lbl.pack(fill="x")

            # クリックイベントのバインド
            def _select_this(event=None, target_path=path):
                self._select_queue_item(target_path)

            for widget in (item_card, icon_lbl, info_f, name_lbl, sub_lbl):
                widget.bind("<ButtonPress-1>", _select_this)

    def _update_file_info_display(self):
        """ファイル選択時の情報表示更新"""
        self._refresh_file_list_display()
        self._update_hud_display()

    def _clear_input(self):
        """入力ファイルをクリア"""
        self.input_path = None
        self.input_paths = []
        self._queue_data = {}
        self._update_file_info_display()
        self._update_ui_state()

    def _build_mode_section(self, parent):
        """右カラム上段: 変換モード / プリセット"""
        card = ctk.CTkFrame(
            parent, fg_color=COLORS["bg_card"], corner_radius=12,
            border_width=1, border_color=COLORS["border"]
        )
        card.pack(fill="x", pady=(0, 8))

        # 1行目: プリセット選択プルダウン（全幅展開）
        p_row = ctk.CTkFrame(card, fg_color="transparent")
        p_row.pack(fill="x", padx=12, pady=(10, 6))

        ctk.CTkLabel(
            p_row, text="プリセット選択:",
            font=ctk.CTkFont(family=APP_FONT, size=12, weight="bold"), text_color=COLORS["text_bright"]
        ).pack(side="left", padx=(0, 8))

        self.apply_preset_var = tk.StringVar(value="選択してください...")
        self.preset_apply_combo = ctk.CTkComboBox(
            p_row, variable=self.apply_preset_var,
            values=["選択してください..."], command=self._on_preset_apply_select,
            state="readonly",
            font=ctk.CTkFont(family=APP_FONT, size=12),
            fg_color=COLORS["bg_input"], border_color=COLORS["border_light"],
            button_color=COLORS["bg_btn"], button_hover_color=COLORS["bg_btn_hover"],
            dropdown_fg_color=COLORS["bg_card"], dropdown_hover_color=COLORS["bg_btn"],
            corner_radius=6, height=30
        )
        self.preset_apply_combo.pack(side="left", fill="x", expand=True)

        # プルダウン全体をクリックしても反応するようにバインド
        if hasattr(self.preset_apply_combo, "_entry"):
            self.preset_apply_combo._entry.configure(cursor="hand2")
            self.preset_apply_combo._entry.bind(
                "<ButtonPress-1>",
                lambda e: self.preset_apply_combo._open_dropdown_menu() if hasattr(self.preset_apply_combo, "_open_dropdown_menu") else None
            )

        # 2行目: 3連モード選択カードボタン群 (CQ / % / MB)
        self.mode_var = tk.StringVar(value="cq" if not self._target_size_mb else "size")

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(0, 6))

        self.mode_buttons = {}
        modes = [
            ("品質優先 (CQ)", "cq"),
            ("割合指定 (%)", "percent"),
            ("容量優先 (MB)", "size"),
        ]
        for text, val in modes:
            btn = ctk.CTkButton(
                btn_row, text=text,
                font=ctk.CTkFont(family=APP_FONT, size=11, weight="bold"),
                height=34, corner_radius=6,
                command=lambda v=val: self._select_mode(v)
            )
            btn.pack(side="left", fill="x", expand=True, padx=3)
            self.mode_buttons[val] = btn

        # 3行目: モードごとの設定コンテナ
        self.mode_content_frame = ctk.CTkFrame(card, fg_color="transparent")
        self.mode_content_frame.pack(fill="x", padx=12, pady=(0, 8))

        # --- 品質優先 (CQ) ---
        self.cq_frame = ctk.CTkFrame(self.mode_content_frame, fg_color="transparent")
        
        cq_top = ctk.CTkFrame(self.cq_frame, fg_color="transparent")
        cq_top.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            cq_top, text="品質レベル:",
            font=ctk.CTkFont(family=APP_FONT, size=12, weight="bold"), text_color=COLORS["text_dim"]
        ).pack(side="left")

        self.quality_value_label = ctk.CTkLabel(
            cq_top, text="CQ 25 (高画質)",
            font=ctk.CTkFont(family=APP_FONT, size=11, weight="bold"),
            text_color=COLORS["text_bright"], fg_color=COLORS["success"],
            corner_radius=6, padx=8, pady=2
        )
        self.quality_value_label.pack(side="right")

        self.quality_var = tk.IntVar(value=self._init_cq)
        self.quality_slider = ctk.CTkSlider(
            self.cq_frame, from_=15, to=40, number_of_steps=25, variable=self.quality_var,
            command=lambda v: self._on_quality_change(int(float(v))),
            progress_color=COLORS["accent"], button_color=COLORS["accent"], button_hover_color=COLORS["accent_hover"],
            fg_color=COLORS["bg_input"], height=10, button_length=14, button_corner_radius=7
        )
        self.quality_slider.pack(fill="x", pady=(2, 2))

        self.quality_desc_label = ctk.CTkLabel(
            self.cq_frame, text="※ CQ/QVBR値が低いほど高画質・大ファイル、高いほど低画質・小ファイルになります",
            font=ctk.CTkFont(family=APP_FONT, size=10), text_color=COLORS["text_dim"]
        )
        self.quality_desc_label.pack(anchor="w")

        # --- 割合指定 (%) ---
        self.percent_frame = ctk.CTkFrame(self.mode_content_frame, fg_color="transparent")
        
        pct_top = ctk.CTkFrame(self.percent_frame, fg_color="transparent")
        pct_top.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            pct_top, text="目標割合:",
            font=ctk.CTkFont(family=APP_FONT, size=12, weight="bold"), text_color=COLORS["text_dim"]
        ).pack(side="left")

        self.percent_label = ctk.CTkLabel(
            pct_top, text="50%",
            font=ctk.CTkFont(family=APP_FONT, size=11, weight="bold"),
            text_color=COLORS["text_bright"], fg_color=COLORS["accent"],
            corner_radius=6, padx=8, pady=2
        )
        self.percent_label.pack(side="right")

        self.percent_var = tk.IntVar(value=50)
        self.target_percent_var = self.percent_var
        self.percent_slider = ctk.CTkSlider(
            self.percent_frame, from_=10, to=90, number_of_steps=80, variable=self.percent_var,
            command=lambda v: self._on_percent_change(int(float(v))),
            progress_color=COLORS["accent"], button_color=COLORS["accent"], button_hover_color=COLORS["accent_hover"],
            fg_color=COLORS["bg_input"], height=10, button_length=14, button_corner_radius=7
        )
        self.percent_slider.pack(fill="x", pady=(2, 0))

        # --- 容量優先 (MB) ---
        self.size_frame = ctk.CTkFrame(self.mode_content_frame, fg_color="transparent")
        
        s_row = ctk.CTkFrame(self.size_frame, fg_color="transparent")
        s_row.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(
            s_row, text="目標サイズ:",
            font=ctk.CTkFont(family=APP_FONT, size=12, weight="bold"), text_color=COLORS["text_dim"]
        ).pack(side="left", padx=(0, 8))

        self.target_size_var = tk.StringVar(value=str(int(self._target_size_mb)) if self._target_size_mb else "25")
        self.target_size_entry = ctk.CTkEntry(
            s_row, textvariable=self.target_size_var,
            font=ctk.CTkFont(family=APP_FONT, size=12), fg_color=COLORS["bg_input"],
            border_color=COLORS["border_light"], width=60, height=28, corner_radius=6
        )
        self.target_size_entry.pack(side="left", padx=(0, 4))
        ctk.CTkLabel(s_row, text="MB", font=ctk.CTkFont(family=APP_FONT, size=12), text_color=COLORS["text_dim"]).pack(side="left", padx=(0, 8))

        for mb in [10, 25, 50, 100]:
            ctk.CTkButton(
                s_row, text=f"{mb}MB", command=lambda v=mb: self.target_size_var.set(str(v)),
                fg_color=COLORS["bg_btn"], hover_color=COLORS["bg_btn_hover"],
                corner_radius=6, font=ctk.CTkFont(family=APP_FONT, size=11, weight="bold"),
                width=50, height=26
            ).pack(side="left", padx=(0, 3))

        self.root.after(100, self._update_apply_preset_list)
        self._on_mode_change()

    def _build_settings_section(self, parent):
        """右カラム下段: 詳細設定"""
        card = ctk.CTkFrame(
            parent, fg_color=COLORS["bg_card"], corner_radius=12,
            border_width=1, border_color=COLORS["border"]
        )
        card.pack(fill="x")

        # ヘッダー (詳細設定 ⌃)
        s_hdr = ctk.CTkFrame(card, fg_color="transparent")
        s_hdr.pack(fill="x", padx=12, pady=(10, 6))
        ctk.CTkLabel(
            s_hdr, text="詳細設定",
            font=ctk.CTkFont(family=APP_FONT, size=14, weight="bold"), text_color=COLORS["text_bright"]
        ).pack(side="left")
        ctk.CTkLabel(
            s_hdr, text="⌃",
            font=ctk.CTkFont(family=APP_FONT, size=13, weight="bold"), text_color=COLORS["text_dim"]
        ).pack(side="right")

        # 1行目: 出力コーデック (フル幅)
        row1_codec = ctk.CTkFrame(card, fg_color="transparent")
        row1_codec.pack(fill="x", padx=12, pady=(0, 6))

        ctk.CTkLabel(
            row1_codec, text="出力コーデック:",
            font=ctk.CTkFont(family=APP_FONT, size=12), text_color=COLORS["text"]
        ).pack(side="left", padx=(0, 8))
        self.codec_var = tk.StringVar(value=self._init_codec)
        codec_combo = ctk.CTkComboBox(
            row1_codec, variable=self.codec_var,
            values=list(CODECS.keys()), state="readonly",
            font=ctk.CTkFont(family=APP_FONT, size=12),
            fg_color=COLORS["bg_input"], border_color=COLORS["border_light"],
            button_color=COLORS["bg_btn"], button_hover_color=COLORS["bg_btn_hover"],
            dropdown_fg_color=COLORS["bg_card"], dropdown_hover_color=COLORS["bg_btn"],
            corner_radius=6, height=30
        )
        codec_combo.pack(side="left", fill="x", expand=True)

        # 2行目: 解像度変換 (モダンSegmentedButton)
        row2_res = ctk.CTkFrame(card, fg_color="transparent")
        row2_res.pack(fill="x", padx=12, pady=(0, 6))

        ctk.CTkLabel(
            row2_res, text="解像度変換:",
            font=ctk.CTkFont(family=APP_FONT, size=12), text_color=COLORS["text"],
            width=76, anchor="w"
        ).pack(side="left", padx=(0, 6))

        self.resolution_var = tk.StringVar(value=self._init_resolution)

        def _on_res_change(val):
            self.resolution_var.set(val)
            self._on_resolution_change()

        self.res_seg = ctk.CTkSegmentedButton(
            row2_res, values=RESOLUTIONS, command=_on_res_change,
            selected_color=COLORS["accent"], selected_hover_color=COLORS["accent_hover"],
            unselected_color=COLORS["bg_btn"], unselected_hover_color=COLORS["bg_btn_hover"],
            font=ctk.CTkFont(family=APP_FONT, size=11, weight="bold"),
            corner_radius=12, height=26
        )
        self.res_seg.set(self._init_resolution if self._init_resolution in RESOLUTIONS else "元のまま")
        self.res_seg.pack(side="left", fill="x", expand=True)

        # 3行目: フレームレート (モダンSegmentedButton)
        row3_fps = ctk.CTkFrame(card, fg_color="transparent")
        row3_fps.pack(fill="x", padx=12, pady=(0, 6))

        ctk.CTkLabel(
            row3_fps, text="フレームレート:",
            font=ctk.CTkFont(family=APP_FONT, size=12), text_color=COLORS["text"],
            width=76, anchor="w"
        ).pack(side="left", padx=(0, 6))

        self.fps_var = tk.StringVar(value=self._init_fps)

        def _on_fps_change(val):
            self.fps_var.set(val)

        self.fps_seg = ctk.CTkSegmentedButton(
            row3_fps, values=FRAME_RATES, command=_on_fps_change,
            selected_color=COLORS["accent"], selected_hover_color=COLORS["accent_hover"],
            unselected_color=COLORS["bg_btn"], unselected_hover_color=COLORS["bg_btn_hover"],
            font=ctk.CTkFont(family=APP_FONT, size=11, weight="bold"),
            corner_radius=12, height=26
        )
        self.fps_seg.set(self._init_fps if self._init_fps in FRAME_RATES else "元のまま")
        self.fps_seg.pack(side="left", fill="x", expand=True)

        # 4行目: チェックボックス (音声、元ファイル削除)
        row4_chk = ctk.CTkFrame(card, fg_color="transparent")
        row4_chk.pack(fill="x", padx=12, pady=(4, 10))

        self.audio_var = tk.BooleanVar(value=not self._init_no_audio)
        self.audio_check_btn = ctk.CTkCheckBox(
            row4_chk, text="音声あり",
            variable=self.audio_var,
            font=ctk.CTkFont(family=APP_FONT, size=10), text_color=COLORS["text"],
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            checkbox_width=18, checkbox_height=18, border_width=2,
            corner_radius=4
        )
        self.audio_check_btn.pack(side="left", padx=(0, 14))

        self.auto_delete_var = tk.BooleanVar(value=False)
        self.auto_delete_check_btn = ctk.CTkCheckBox(
            row4_chk, text="元ファイルを自動でゴミ箱へ移動 ⓘ",
            variable=self.auto_delete_var,
            font=ctk.CTkFont(family=APP_FONT, size=10), text_color=COLORS["text_dim"],
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            checkbox_width=18, checkbox_height=18, border_width=2,
            corner_radius=4
        )
        self.auto_delete_check_btn.pack(side="left")

        # 警告ラベルのみ不可視で保持
        self.resolution_warning_label = ctk.CTkLabel(
            card, text="",
            font=ctk.CTkFont(family=APP_FONT, size=11, weight="bold"), text_color=COLORS["error"]
        )

        self._on_resolution_change()
        self._on_quality_change(self._init_cq)

    def _build_progress_section(self, parent):
        """グループ 4: 進行状況 & GPU計器ダッシュボード"""
        card = ctk.CTkFrame(
            parent, fg_color=COLORS["bg_card"], corner_radius=12,
            border_width=1, border_color=COLORS["border"]
        )
        card.pack(fill="x", pady=(0, 8))

        p_container = ctk.CTkFrame(card, fg_color="transparent")
        p_container.pack(fill="x", padx=14, pady=10)

        # --- 左側: プログレスバー & ステータス ---
        left_prog = ctk.CTkFrame(p_container, fg_color="transparent")
        left_prog.pack(side="left", fill="both", expand=True, padx=(0, 16))

        ctk.CTkLabel(
            left_prog, text="プログレスバー:",
            font=ctk.CTkFont(family=APP_FONT, size=13, weight="bold"), text_color=COLORS["text_bright"]
        ).pack(anchor="w", pady=(0, 4))

        self.progress_bar = ctk.CTkProgressBar(
            left_prog, progress_color=COLORS["accent"], fg_color=COLORS["bg_input"],
            height=8, corner_radius=4
        )
        self.progress_bar.set(0.0)
        self.progress_bar.pack(fill="x", pady=(0, 4))

        status_subrow = ctk.CTkFrame(left_prog, fg_color="transparent")
        status_subrow.pack(fill="x")

        self.status_label = ctk.CTkLabel(
            status_subrow, text="準備完了",
            font=ctk.CTkFont(family=APP_FONT, size=12), text_color=COLORS["text_dim"],
            anchor="w"
        )
        self.status_label.pack(side="left", fill="x", expand=True)

        self.progress_pct_label = ctk.CTkLabel(
            status_subrow, text="0%",
            font=ctk.CTkFont(family=APP_FONT, size=12, weight="bold"), text_color=COLORS["text_bright"],
            anchor="e"
        )
        self.progress_pct_label.pack(side="right")

        # --- 右側: GPU 3D / Encode 円形メーター計器 ---
        right_gauges = ctk.CTkFrame(p_container, fg_color="transparent")
        right_gauges.pack(side="right")

        # 3D 計器
        g_3d_box = ctk.CTkFrame(right_gauges, fg_color="transparent")
        g_3d_box.pack(side="left", padx=(0, 14))

        ctk.CTkLabel(g_3d_box, text="3D", font=ctk.CTkFont(family=APP_FONT, size=12, weight="bold"), text_color=COLORS["text_dim"]).pack(side="left", padx=(0, 6))
        self.gpu_3d_meter = CircularProgressMeter(g_3d_box, size=46, line_width=4, fill_color=COLORS["accent"], bg=COLORS["bg_card"])
        self.gpu_3d_meter.pack(side="left")

        # Encode 計器
        g_enc_box = ctk.CTkFrame(right_gauges, fg_color="transparent")
        g_enc_box.pack(side="left")

        ctk.CTkLabel(g_enc_box, text="Encode", font=ctk.CTkFont(family=APP_FONT, size=12, weight="bold"), text_color=COLORS["text_dim"]).pack(side="left", padx=(0, 6))
        self.gpu_enc_meter = CircularProgressMeter(g_enc_box, size=46, line_width=4, fill_color=COLORS["accent"], bg=COLORS["bg_card"])
        self.gpu_enc_meter.pack(side="left")

    def _build_bottom_bar(self, parent):
        """ボトムアクションバー"""
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.pack(fill="x", pady=(2, 0))

        # 左側サブボタン群
        left_f = ctk.CTkFrame(bar, fg_color="transparent")
        left_f.pack(side="left")

        self._create_btn(left_f, "設定", self._open_settings, font_size=12, is_bold=True, width=86, height=36).pack(side="left", padx=(0, 6))
        self._create_btn(left_f, "プリセット管理", self._open_preset_manager, font_size=12, is_bold=True, width=120, height=36).pack(side="left")

        # 右側アクションボタングループ
        right_f = ctk.CTkFrame(bar, fg_color="transparent")
        right_f.pack(side="right")

        self.delete_btn = self._create_btn(
            right_f, "元ファイルを削除", self._delete_original_file,
            fg=COLORS["error"], font_size=12, width=122, height=36
        )

        self.open_btn = self._create_btn(
            right_f, "フォルダを開く", self._open_output_folder,
            fg=COLORS["text"], font_size=12, width=112, height=36
        )

        self.cancel_btn = ctk.CTkButton(
            right_f, text="中止", command=self._cancel_conversion,
            font=ctk.CTkFont(family=APP_FONT, size=12, weight="bold"),
            text_color="#ffffff", fg_color=COLORS["error"], hover_color="#dc2626",
            corner_radius=8, width=80, height=36
        )

        self.convert_btn = ctk.CTkButton(
            right_f, text="圧縮開始", command=self._start_conversion,
            font=ctk.CTkFont(family=APP_FONT, size=14, weight="bold"),
            text_color="#000000", fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            corner_radius=8, width=140, height=38
        )
        self.convert_btn.pack(side="right", padx=(6, 0))

        self._update_ui_state()

    def _open_context_menu_dialog(self):
        """右クリックメニュー登録・解除のダイアログ"""
        win = tk.Toplevel(self.root)
        win.title("右クリックメニュー設定")
        win.configure(bg=COLORS["bg_dark"])
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        pad = tk.Frame(win, bg=COLORS["bg_dark"], padx=20, pady=16)
        pad.pack(fill="both", expand=True)

        tk.Label(
            pad, text="右クリックメニュー設定",
            font=(APP_FONT, 12, "bold"), fg=COLORS["accent"], bg=COLORS["bg_dark"]
        ).pack(anchor="w", pady=(0, 6))

        desc = "Windowsのエクスプローラーで動画ファイルを右クリックした際、\n本ツールを直接起動するメニューを登録・解除します。\n（現在のユーザー登録のため管理者権限は不要です）"
        tk.Label(
            pad, text=desc, font=(APP_FONT, 10), fg=COLORS["text_dim"], bg=COLORS["bg_dark"],
            justify="left"
        ).pack(anchor="w", pady=(0, 10))

        status_lbl = tk.Label(pad, text="", font=(APP_FONT, 10, "bold"), bg=COLORS["bg_dark"])
        status_lbl.pack(anchor="w", pady=(0, 10))

        def update_status():
            try:
                reg = register_menu.check_registration_status()
                if reg.get("registered"):
                    status_lbl.configure(text="現在の状態: 登録済み", fg=COLORS["success"])
                else:
                    status_lbl.configure(text="現在の状態: 未登録", fg=COLORS["warning"])
            except Exception:
                status_lbl.configure(text="現在の状態: 確認中", fg=COLORS["text_dim"])

        update_status()

        btn_row = tk.Frame(pad, bg=COLORS["bg_dark"])
        btn_row.pack(fill="x", pady=(0, 12))

        def do_reg():
            try:
                register_menu.register_context_menu()
                messagebox.showinfo("成功", "右クリックメニューに登録しました。", parent=win)
            except Exception as e:
                messagebox.showerror("エラー", f"登録に失敗しました: {e}", parent=win)
            update_status()

        def do_unreg():
            try:
                register_menu.unregister_context_menu()
                messagebox.showinfo("成功", "右クリックメニューを解除しました。", parent=win)
            except Exception as e:
                messagebox.showerror("エラー", f"解除に失敗しました: {e}", parent=win)
            update_status()

        self._create_btn(btn_row, "右クリックメニューに追加", do_reg, fg=COLORS["text_bright"], bg=COLORS["accent"]).pack(side="left", padx=(0, 8))
        self._create_btn(btn_row, "右クリックメニュー削除", do_unreg, fg=COLORS["error"]).pack(side="left")

        self._create_btn(pad, "閉じる", win.destroy).pack(anchor="e")

        win.update_idletasks()
        x = self.root.winfo_x() + 50
        y = self.root.winfo_y() + 50
        win.geometry(f"+{x}+{y}")

    def _toggle_topmost(self):
        if hasattr(self, 'pin_btn') and isinstance(self.pin_btn, ctk.CTkSwitch):
            self.is_topmost = bool(self.pin_btn.get())
        else:
            self.is_topmost = not self.is_topmost
        self.root.attributes("-topmost", self.is_topmost)
        if hasattr(self, 'pin_btn'):
            if isinstance(self.pin_btn, ctk.CTkSwitch):
                if self.pin_btn.get() != (1 if self.is_topmost else 0):
                    self.pin_btn.select() if self.is_topmost else self.pin_btn.deselect()
            elif hasattr(self.pin_btn, 'set_state'):
                self.pin_btn.set_state(self.is_topmost)
        if hasattr(self, 'hud_pin_btn') and hasattr(self.hud_pin_btn, 'set_state'):
            self.hud_pin_btn.set_state(self.is_topmost)

    def _on_drop_enter(self, event):
        if getattr(self, 'is_converting', False):
            return
        if getattr(self, '_drop_overlay', None) is not None and self._drop_overlay.winfo_exists():
            return event.action

        self._drop_overlay = tk.Frame(self.root, bg=COLORS["bg_dark"], highlightbackground=COLORS["accent"], highlightthickness=3)
        self._drop_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)

        self._drop_overlay.bind("<ButtonPress-1>", lambda e: self._close_drop_overlay())
        self.root.bind("<Escape>", self._on_esc_drop_overlay, add="+")

        inner_frame = tk.Frame(self._drop_overlay, bg=COLORS["bg_dark"])
        inner_frame.pack(expand=True)
        inner_frame.bind("<ButtonPress-1>", lambda e: self._close_drop_overlay())

        lbl_txt = tk.Label(inner_frame, text="[ ここに動画ファイルをドロップ ]", font=(APP_FONT, 12, "bold"), fg=COLORS["accent"], bg=COLORS["bg_dark"])
        lbl_txt.pack(pady=12)
        lbl_txt.bind("<ButtonPress-1>", lambda e: self._close_drop_overlay())

        if HAS_DND:
            self._drop_overlay.drop_target_register(DND_FILES)
            self._drop_overlay.dnd_bind('<<Drop>>', self._on_drop_from_overlay)
            self._drop_overlay.dnd_bind('<<DropLeave>>', self._on_overlay_drop_leave)

        if getattr(self, '_drop_overlay_timer', None):
            try: self.root.after_cancel(self._drop_overlay_timer)
            except Exception: pass
        self._drop_overlay_timer = self.root.after(4000, self._close_drop_overlay)

        return event.action

    def _close_drop_overlay(self):
        if getattr(self, '_drop_overlay_timer', None):
            try: self.root.after_cancel(self._drop_overlay_timer)
            except Exception: pass
            self._drop_overlay_timer = None
        if getattr(self, '_drop_overlay', None) is not None and self._drop_overlay.winfo_exists():
            self._drop_overlay.destroy()
            self._drop_overlay = None

    def _on_esc_drop_overlay(self, event):
        self._close_drop_overlay()

    def _on_overlay_drop_leave(self, event):
        self._close_drop_overlay()

    def _on_drop_from_overlay(self, event):
        self._close_drop_overlay()
        self._on_drop(event)

    def _set_input_files(self, filepaths: list):
        """複数ファイルの個別エラーハンドリングを行い、正常ファイルのみセットする"""
        valid_paths = []
        error_messages = []
        for path in filepaths:
            if not path or not os.path.exists(path):
                continue
            info = get_video_info(path)
            if "error" in info:
                error_messages.append(f"{Path(path).name}: {info['error']}")
            else:
                valid_paths.append(path)

        if error_messages:
            msg = "以下のファイルの読み込みに失敗しました:\n" + "\n".join(error_messages[:5])
            if len(error_messages) > 5:
                msg += f"\n...他 {len(error_messages) - 5} 件"
            messagebox.showwarning("ファイル読み込み警告", msg, parent=self.root)

        if not valid_paths:
            if not getattr(self, 'input_paths', None):
                self.input_path = None
                self.input_paths = []
                self._update_file_info_display()
                self._update_ui_state()
            return

        self.input_paths = valid_paths
        self.input_path = valid_paths[0]
        self.video_info = get_video_info(self.input_path)
        self._update_file_info_display()
        self._sync_queue_data()
        self._update_ui_state()

    def _on_drop(self, event):
        self._close_drop_overlay()
        files = self.root.tk.splitlist(event.data)
        if not files:
            return
        self._set_input_files(list(files))

    def _select_file(self):
        filepaths = filedialog.askopenfilenames(
            title="変換する動画ファイルを選択（複数選択可）",
            filetypes=[
                ("動画ファイル", "*.mp4 *.mkv *.mov *.avi *.webm *.wmv *.flv *.ts *.m2ts"),
                ("すべてのファイル", "*.*"),
            ],
        )
        if filepaths:
            self._set_input_files(list(filepaths))

    def _update_ui_state(self):
        if not self.input_path:
            self.convert_btn.configure(state="disabled", fg_color="#2c3242", text_color=COLORS["text_dim"])
        else:
            self.convert_btn.configure(state="normal", fg_color=COLORS["accent"], text_color="#000000")
            self._on_resolution_change()
            if hasattr(self, 'audio_check_btn'):
                if not self.video_info.get("has_audio"):
                    self.audio_check_btn.configure(state="disabled", text="音声あり (音声なし)")
                    self.audio_var.set(False)
                else:
                    self.audio_check_btn.configure(state="normal", text="音声あり")

    # ─────────────────────────────────────────
    # バッチキューパネル
    # ─────────────────────────────────────────
    def _build_queue_panel(self, parent):
        """右側バッチキューパネルの構築"""
        self.queue_panel = tk.Frame(parent, bg=COLORS["bg_dark"])
        self.queue_panel.pack(side="left", fill="y")
        self.queue_panel.pack_propagate(False)
        self.queue_panel.configure(width=220)

        pad = tk.Frame(self.queue_panel, bg=COLORS["bg_dark"])
        pad.pack(fill="both", expand=True, padx=10, pady=12)

        # ヘッダー行
        header_row = tk.Frame(pad, bg=COLORS["bg_dark"])
        header_row.pack(fill="x", pady=(0, 8))

        tk.Label(
            header_row, text="変換キュー",
            font=(APP_FONT, 10, "bold"), fg=COLORS["accent"], bg=COLORS["bg_dark"]
        ).pack(side="left")

        self._queue_count_label = tk.Label(
            header_row, text="",
            font=(APP_FONT, 9), fg=COLORS["text_dim"], bg=COLORS["bg_dark"]
        )
        self._queue_count_label.pack(side="right")

        # スクロール可能なリストエリア
        list_container = tk.Frame(pad, bg=COLORS["bg_card"],
                                  highlightbackground=COLORS["border"], highlightthickness=1)
        list_container.pack(fill="both", expand=True)

        self._queue_scrollbar = ttk.Scrollbar(list_container, orient="vertical")
        self._queue_scrollbar.pack(side="right", fill="y")

        self._queue_canvas = tk.Canvas(
            list_container, bg=COLORS["bg_card"],
            highlightthickness=0, bd=0,
            yscrollcommand=self._queue_scrollbar.set
        )
        self._queue_canvas.pack(side="left", fill="both", expand=True)
        self._queue_scrollbar.configure(command=self._queue_canvas.yview)

        self._queue_inner = tk.Frame(self._queue_canvas, bg=COLORS["bg_card"])
        self._queue_canvas_win_id = self._queue_canvas.create_window(
            (0, 0), window=self._queue_inner, anchor="nw"
        )

        self._queue_inner.bind("<Configure>", self._on_queue_inner_configure)
        self._queue_canvas.bind("<Configure>", self._on_queue_canvas_configure)

        def _on_mousewheel(event):
            self._queue_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self._queue_canvas.bind("<MouseWheel>", _on_mousewheel)
        self._queue_inner.bind("<MouseWheel>", _on_mousewheel)

        # 下部サマリーラベル
        self._queue_summary_label = tk.Label(
            pad, text="ファイルを追加してください",
            font=(APP_FONT, 8), fg=COLORS["text_dim"], bg=COLORS["bg_dark"],
            justify="left", anchor="w"
        )
        self._queue_summary_label.pack(anchor="w", pady=(6, 0))

        # ヒントラベル
        self._queue_hint_label = tk.Label(
            pad, text="クリックして個別設定",
            font=(APP_FONT, 8), fg=COLORS["text_dim"], bg=COLORS["bg_dark"],
            justify="left", anchor="w"
        )
        self._queue_hint_label.pack(anchor="w", pady=(1, 0))

        self._refresh_queue_display()

    def _update_queue_panel_visibility(self):
        """2個以上のファイルが存在する場合のみ変換キューパネルを表示し、1個以下の場合は非表示にしてコンパクト化"""
        if getattr(self, '_is_hud_mode', False):
            return
        count = len(getattr(self, 'input_paths', []))
        if not hasattr(self, 'queue_panel') or not hasattr(self, 'queue_separator'):
            return

        if count >= 2:
            self.queue_separator.pack(side="left", fill="y")
            self.queue_panel.pack(side="left", fill="y")
        else:
            self.queue_panel.pack_forget()
            self.queue_separator.pack_forget()

        self.root.update_idletasks()
        req_w = self.root.winfo_reqwidth()
        req_h = self.root.winfo_reqheight()
        self.root.minsize(req_w, req_h)
        self.root.maxsize(req_w, 9999)
        self.root.geometry(f"{req_w}x{req_h}")

    def _on_queue_inner_configure(self, event):
        self._queue_canvas.configure(scrollregion=self._queue_canvas.bbox("all"))

    def _on_queue_canvas_configure(self, event):
        self._queue_canvas.itemconfig(self._queue_canvas_win_id, width=event.width)

    def _sync_queue_data(self):
        """input_paths と _queue_data を同期する"""
        new_queue = {}
        for path in self.input_paths:
            if path in self._queue_data:
                new_queue[path] = self._queue_data[path]
            else:
                new_queue[path] = {
                    "status": "waiting",
                    "progress": 0.0,
                    "orig_size": 0,
                    "out_size": 0,
                    "settings": self._capture_current_settings(),  # 現在のUI設定を初期値として保存
                }
        self._queue_data = new_queue
        self._refresh_queue_display()
        self._update_queue_panel_visibility()

    def _setup_settings_traces(self):
        """UI変数変更時のリアルタイム設定同期トレースを設定する"""
        vars_to_trace = [
            "codec_var", "preset_var", "quality_var", "fps_var", "resolution_var",
            "mode_var", "audio_var", "audio_mode_var", "auto_delete_var",
            "target_size_var", "target_percent_var"
        ]
        for var_name in vars_to_trace:
            var = getattr(self, var_name, None)
            if var and hasattr(var, "trace_add"):
                try:
                    var.trace_add("write", self._on_ui_setting_changed_sync)
                except Exception:
                    pass

    def _on_ui_setting_changed_sync(self, *args):
        """UI変数変更時に選択中キューアイテムの設定をリアルタイム自動同期する"""
        if getattr(self, "_is_applying_settings", False):
            return
        path = getattr(self, "_selected_queue_path", None)
        if path and path in self._queue_data:
            self._queue_data[path]["settings"] = self._capture_current_settings()

    def _refresh_queue_display(self):
        """キューパネルの表示を差分更新（キャッシュ化）する"""
        if not hasattr(self, '_queue_inner'):
            return

        if not hasattr(self, '_queue_widget_cache'):
            self._queue_widget_cache = {}

        selected_path = getattr(self, '_selected_queue_path', None)
        is_converting = getattr(self, 'is_converting', False)
        current_paths = getattr(self, 'input_paths', [])

        if not current_paths:
            for cache in list(self._queue_widget_cache.values()):
                try:
                    cache["outer"].destroy()
                    if cache.get("sep"):
                        cache["sep"].destroy()
                except Exception:
                    pass
            self._queue_widget_cache.clear()

            if not hasattr(self, '_queue_empty_label') or not self._queue_empty_label.winfo_exists():
                self._queue_empty_label = tk.Label(
                    self._queue_inner,
                    text="ファイルを\n追加してください",
                    font=(APP_FONT, 10), fg=COLORS["text_dim"], bg=COLORS["bg_card"],
                    justify="center"
                )
            self._queue_empty_label.pack(expand=True, pady=30)

            if hasattr(self, '_queue_count_label'):
                self._queue_count_label.configure(text="")
            if hasattr(self, '_queue_summary_label'):
                self._queue_summary_label.configure(text="ファイルを追加してください", fg=COLORS["text_dim"])
            if hasattr(self, '_queue_hint_label'):
                self._queue_hint_label.configure(text="")
            self._queue_canvas.configure(scrollregion=self._queue_canvas.bbox("all"))
            return
        else:
            if hasattr(self, '_queue_empty_label') and self._queue_empty_label.winfo_exists():
                self._queue_empty_label.pack_forget()

        STATUS_MAP = {
            "waiting":    ("[待機]", COLORS["text_dim"]),
            "converting": ("[変換]", COLORS["accent"]),
            "done":       ("[完了]", COLORS["success"]),
            "error":      ("[失敗]", COLORS["error"]),
            "cancelled":  ("[中止]", COLORS["warning"]),
        }

        # 存在しなくなったパスのキャッシュウィジェット破棄
        cached_paths = list(self._queue_widget_cache.keys())
        for path in cached_paths:
            if path not in current_paths:
                try:
                    self._queue_widget_cache[path]["outer"].destroy()
                    if self._queue_widget_cache[path].get("sep"):
                        self._queue_widget_cache[path]["sep"].destroy()
                except Exception:
                    pass
                del self._queue_widget_cache[path]

        self._queue_progress_bars = {}
        self._queue_percent_labels = {}

        def _bind_click(widget, path):
            widget.bind("<ButtonPress-1>", lambda e, p=path: self._on_queue_item_click(p))
            if not is_converting:
                widget.configure(cursor="hand2")
            for child in widget.winfo_children():
                _bind_click(child, path)

        for i, path in enumerate(current_paths):
            data = self._queue_data.get(path, {"status": "waiting", "progress": 0.0})
            status = data.get("status", "waiting")
            icon, icon_color = STATUS_MAP.get(status, ("[待機]", COLORS["text_dim"]))
            is_selected = (path == selected_path)
            bg_color = COLORS["selected_bg"] if is_selected else COLORS["bg_card"]

            if path not in self._queue_widget_cache:
                sep = tk.Frame(self._queue_inner, bg=COLORS["border"], height=1) if i > 0 else None
                outer = tk.Frame(self._queue_inner, bg=COLORS["bg_card"])
                accent_line = tk.Frame(outer, bg=COLORS["accent"], width=3)
                item_frame = tk.Frame(outer, bg=bg_color)

                row1 = tk.Frame(item_frame, bg=bg_color)
                row1.pack(fill="x")

                icon_lbl = tk.Label(row1, text=icon, font=(APP_FONT, 9), fg=icon_color, bg=bg_color)
                icon_lbl.pack(side="left", padx=(3, 2))

                filename = Path(path).name
                MAX_LEN = 13
                if len(filename) > MAX_LEN:
                    ext = Path(path).suffix
                    stem_len = MAX_LEN - len(ext) - 3
                    filename = Path(path).stem[:stem_len] + "..." + ext if stem_len > 0 else filename[:MAX_LEN - 3] + "..."

                name_lbl = tk.Label(row1, text=filename, font=(APP_FONT, 9, "bold"), fg=COLORS["text"], bg=bg_color, anchor="w")
                name_lbl.pack(side="left", fill="x", expand=True, padx=(0, 2))

                row2 = tk.Frame(item_frame, bg=bg_color)
                row2.pack(fill="x", padx=(16, 4), pady=(1, 2))

                pb = ttk.Progressbar(row2, maximum=100, value=0, style="Custom.Horizontal.TProgressbar")
                status_lbl = tk.Label(row2, text="", font=(APP_FONT, 8), fg=COLORS["text_dim"], bg=bg_color, anchor="w")
                pct_lbl = tk.Label(row2, text="0%", font=(APP_FONT, 8), fg=COLORS["accent"], bg=bg_color, anchor="w")

                cache = {
                    "sep": sep, "outer": outer, "accent_line": accent_line, "item_frame": item_frame,
                    "row1": row1, "row2": row2, "icon_lbl": icon_lbl, "name_lbl": name_lbl,
                    "status_lbl": status_lbl, "pb": pb, "pct_lbl": pct_lbl
                }
                self._queue_widget_cache[path] = cache
                _bind_click(outer, path)
            else:
                cache = self._queue_widget_cache[path]

            outer = cache["outer"]
            accent_line = cache["accent_line"]
            item_frame = cache["item_frame"]
            row1 = cache["row1"]
            row2 = cache["row2"]
            icon_lbl = cache["icon_lbl"]
            name_lbl = cache["name_lbl"]
            status_lbl = cache["status_lbl"]
            pb = cache["pb"]
            pct_lbl = cache["pct_lbl"]

            if i == 0:
                if cache.get("sep"):
                    cache["sep"].pack_forget()
            else:
                if not cache.get("sep"):
                    cache["sep"] = tk.Frame(self._queue_inner, bg=COLORS["border"], height=1)
                cache["sep"].pack(fill="x", padx=6)
            outer.pack(fill="x", padx=6, pady=(5, 3))

            if is_selected:
                accent_line.pack(side="left", fill="y")
            else:
                accent_line.pack_forget()
            item_frame.pack(side="left", fill="both", expand=True)

            item_frame.configure(bg=bg_color)
            row1.configure(bg=bg_color)
            row2.configure(bg=bg_color)
            icon_lbl.configure(text=icon, fg=icon_color, bg=bg_color)
            name_lbl.configure(fg=COLORS["accent"] if is_selected else COLORS["text"], bg=bg_color)

            if status == "converting":
                status_lbl.pack_forget()
                progress = data.get("progress", 0.0)
                pb.configure(value=progress)
                pct_lbl.configure(text=f"{progress:.0f}%", bg=bg_color)
                pb.pack(fill="x", pady=(1, 2))
                pct_lbl.pack(fill="x")
                self._queue_progress_bars[path] = pb
                self._queue_percent_labels[path] = pct_lbl
            else:
                pb.pack_forget()
                pct_lbl.pack_forget()
                status_lbl.configure(bg=bg_color)
                status_lbl.pack(fill="x")
                if status == "done":
                    orig = data.get("orig_size", 0)
                    out = data.get("out_size", 0)
                    info_text = f"{format_filesize(orig)}→{format_filesize(out)} ({out/orig*100:.0f}%)" if orig > 0 and out > 0 else "完了"
                    status_lbl.configure(text=info_text, fg=COLORS["success"])
                elif status == "error":
                    status_lbl.configure(text="変換失敗", fg=COLORS["error"])
                elif status == "cancelled":
                    status_lbl.configure(text="中止されました", fg=COLORS["warning"])
                else:  # waiting
                    if is_selected:
                        status_lbl.configure(text="← 左側で設定中", fg=COLORS["accent"], font=(APP_FONT, 9, "bold"))
                    else:
                        status_lbl.configure(text="待機中", fg=COLORS["text_dim"], font=(APP_FONT, 9))

        done_c = sum(1 for d in self._queue_data.values() if d.get("status") == "done")
        total = len(current_paths)
        if hasattr(self, '_queue_count_label'):
            self._queue_count_label.configure(text=f"{done_c}/{total}")

        if hasattr(self, '_queue_summary_label'):
            waiting_c = sum(1 for d in self._queue_data.values() if d.get("status") == "waiting")
            conv_c    = sum(1 for d in self._queue_data.values() if d.get("status") == "converting")
            err_c     = sum(1 for d in self._queue_data.values() if d.get("status") in ("error", "cancelled"))
            if total == 1:
                st = self._queue_data.get(current_paths[0], {}).get("status", "waiting")
                if st == "done": self._queue_summary_label.configure(text="変換完了", fg=COLORS["success"])
                elif st == "converting": self._queue_summary_label.configure(text="変換中...", fg=COLORS["accent"])
                elif st == "error": self._queue_summary_label.configure(text="変換失敗", fg=COLORS["error"])
                elif st == "cancelled": self._queue_summary_label.configure(text="中止されました", fg=COLORS["warning"])
                else: self._queue_summary_label.configure(text="", fg=COLORS["text_dim"])
            elif conv_c > 0: self._queue_summary_label.configure(text=f"変換中... {done_c}完了 / 残り {waiting_c}件", fg=COLORS["accent"])
            elif done_c == total: self._queue_summary_label.configure(text=f"すべて完了 ({total}件)", fg=COLORS["success"])
            elif err_c > 0: self._queue_summary_label.configure(text=f"{done_c}完了, {err_c}件失敗", fg=COLORS["error"])
            else: self._queue_summary_label.configure(text=f"{total}件 待機中", fg=COLORS["text_dim"])

        if hasattr(self, '_queue_hint_label'):
            if is_converting: self._queue_hint_label.configure(text="")
            elif selected_path:
                fname = Path(selected_path).stem[:10] + ("…" if len(Path(selected_path).stem) > 10 else "")
                self._queue_hint_label.configure(text=f"{fname} の設定中", fg=COLORS["accent"])
            else: self._queue_hint_label.configure(text="項目クリックで個別に設定", fg=COLORS["text_dim"])

        self._queue_canvas.configure(scrollregion=self._queue_canvas.bbox("all"))

    def _update_queue_item_progress(self, filepath, progress):
        """変換中ファイルの進捗バーのみを軽量更新する"""
        if filepath in self._queue_data:
            self._queue_data[filepath]["progress"] = progress
        cache = getattr(self, '_queue_widget_cache', {}).get(filepath)
        if cache:
            pb = cache.get("pb")
            if pb and pb.winfo_exists():
                pb.configure(value=progress)
            pct_lbl = cache.get("pct_lbl")
            if pct_lbl and pct_lbl.winfo_exists():
                pct_lbl.configure(text=f"{progress:.0f}%")

    def _capture_current_settings(self) -> dict:
        """現在のUI設定を辞書として取得する"""
        s = {
            "codec":         getattr(self, 'codec_var',      None) and self.codec_var.get(),
            "preset":        getattr(self, 'preset_var',     None) and self.preset_var.get(),
            "fps":           getattr(self, 'fps_var',        None) and self.fps_var.get(),
            "resolution":    getattr(self, 'resolution_var', None) and self.resolution_var.get(),
            "mode":          getattr(self, 'mode_var',       None) and self.mode_var.get() or "cq",
            "cq":            getattr(self, 'quality_var',    None) and self.quality_var.get() or 25,
            "audio":         getattr(self, 'audio_var',      None) and self.audio_var.get(),
            "audio_mode":    getattr(self, 'audio_mode_var', None) and self.audio_mode_var.get() or "copy",
            "auto_delete":   getattr(self, 'auto_delete_var',None) and self.auto_delete_var.get() or False,
            "keep_metadata": getattr(self, 'keep_metadata_var', None) and self.keep_metadata_var.get() if hasattr(self, 'keep_metadata_var') else True,
        }
        if hasattr(self, 'target_size_var'):
            try:
                s["target_size_mb"] = float(self.target_size_var.get())
            except (ValueError, Exception):
                s["target_size_mb"] = 10.0
        if hasattr(self, 'target_percent_var'):
            try:
                s["target_percent"] = float(self.target_percent_var.get())
            except (ValueError, Exception):
                s["target_percent"] = 50.0
        return s

    def _apply_settings(self, settings: dict, completion_event: threading.Event = None):
        """設定辞書をUI変数に反映する"""
        if not settings:
            if completion_event:
                completion_event.set()
            return
        self._is_applying_settings = True
        try:
            if settings.get("codec")      and hasattr(self, 'codec_var'):      self.codec_var.set(settings["codec"])
            if settings.get("preset")     and hasattr(self, 'preset_var'):     self.preset_var.set(settings["preset"])
            if settings.get("fps")        and hasattr(self, 'fps_var'):        self.fps_var.set(settings["fps"])
            if settings.get("resolution") and hasattr(self, 'resolution_var'): self.resolution_var.set(settings["resolution"])
            if "audio"       in settings  and hasattr(self, 'audio_var'):      self.audio_var.set(settings["audio"])
            if "audio_mode"  in settings  and hasattr(self, 'audio_mode_var'): self.audio_mode_var.set(settings["audio_mode"])
            if "auto_delete" in settings  and hasattr(self, 'auto_delete_var'):self.auto_delete_var.set(settings["auto_delete"])
            if "keep_metadata" in settings and hasattr(self, 'keep_metadata_var'):self.keep_metadata_var.set(settings["keep_metadata"])
            if "mode"        in settings  and hasattr(self, 'mode_var'):       self.mode_var.set(settings["mode"])
            if "cq"          in settings  and hasattr(self, 'quality_var'):
                self.quality_var.set(settings["cq"])
                if hasattr(self, '_on_quality_change'): self._on_quality_change(settings["cq"])
            if "target_size_mb" in settings and hasattr(self, 'target_size_var'):
                self.target_size_var.set(str(settings["target_size_mb"]))
            if "target_percent" in settings and hasattr(self, 'target_percent_var'):
                self.target_percent_var.set(str(settings["target_percent"]))
            if hasattr(self, '_on_mode_change'):       self._on_mode_change()
            if hasattr(self, '_on_resolution_change'): self._on_resolution_change()
        finally:
            self._is_applying_settings = False
            if completion_event:
                completion_event.set()

    def _on_queue_item_click(self, path: str):
        """キューアイテムのクリック処理—設定の保存切替え"""
        if getattr(self, 'is_converting', False):
            return  # 変換中は操作不可

        prev = getattr(self, '_selected_queue_path', None)

        # 前の選択ファイルの設定を保存
        if prev and prev in self._queue_data:
            self._queue_data[prev]["settings"] = self._capture_current_settings()

        if prev == path:
            # 同じファイルを再クリック → 選択解除
            self._selected_queue_path = None
        else:
            self._selected_queue_path = path
            # 選択ファイルの設定をUIに反映
            file_settings = self._queue_data.get(path, {}).get("settings")
            if file_settings:
                self._apply_settings(file_settings)

        self._refresh_queue_display()
        self._refresh_file_list_display()

    def _select_queue_item(self, path: str):
        """左カラムファイルアイテムのクリック処理"""
        self._on_queue_item_click(path)

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
        win.title("詳細設定")
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

        # ウィンドウ初期サイズ（縦長になりすぎないコンパクトな高さ）
        win_w, win_h = 560, 520
        win.geometry(f"{win_w}x{win_h}")

        # --- 上部固定ヘッダー ---
        top_bar = tk.Frame(win, bg=COLORS["bg_dark"], padx=16, pady=10)
        top_bar.pack(fill="x")

        tk.Label(
            top_bar, text="詳細設定",
            font=(APP_FONT, 12, "bold"), fg=COLORS["accent"], bg=COLORS["bg_dark"]
        ).pack(side="left")

        # --- 下部固定フッター（閉じるボタン） ---
        bottom_bar = tk.Frame(win, bg=COLORS["bg_dark"], padx=16, pady=8)
        bottom_bar.pack(side="bottom", fill="x")

        # --- 中央スクロール領域 ---
        scroll_container = tk.Frame(win, bg=COLORS["bg_dark"])
        scroll_container.pack(fill="both", expand=True, padx=(12, 4), pady=(0, 4))

        scrollbar = ttk.Scrollbar(scroll_container, orient="vertical", style="Vertical.TScrollbar")
        scrollbar.pack(side="right", fill="y")

        canvas = tk.Canvas(
            scroll_container, bg=COLORS["bg_dark"],
            highlightthickness=0, bd=0,
            yscrollcommand=scrollbar.set
        )
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=canvas.yview)

        pad = tk.Frame(canvas, bg=COLORS["bg_dark"], padx=4)
        canvas_win_id = canvas.create_window((0, 0), window=pad, anchor="nw")

        def _on_pad_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event):
            canvas.itemconfig(canvas_win_id, width=event.width)

        pad.bind("<Configure>", _on_pad_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        
        def _bind_mousewheel_recursive(widget):
            widget.bind("<MouseWheel>", _on_mousewheel, add="+")
            for child in widget.winfo_children():
                _bind_mousewheel_recursive(child)

        canvas.bind("<MouseWheel>", _on_mousewheel)
        pad.bind("<MouseWheel>", _on_mousewheel)
        win.bind("<MouseWheel>", _on_mousewheel)

        # --- 統計情報 ---
        config_path = os.path.join(register_menu.DATA_DIR, "config.json")
        total_saved = 0
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8-sig") as f:
                    config_data = json.load(f)
                    total_saved = config_data.get("total_saved_bytes", 0)
            except Exception:
                pass
                
        if total_saved >= 0:
            stats_card = tk.Frame(pad, bg=COLORS["bg_card"], padx=10, pady=8,
                                   highlightbackground=COLORS["success"], highlightthickness=1)
            stats_card.pack(fill="x", pady=(0, 8))
            
            tk.Label(
                stats_card, text="統計情報",
                font=(APP_FONT, 10, "bold"), fg=COLORS["success"], bg=COLORS["bg_card"]
            ).pack(anchor="w")
            
            tk.Label(
                stats_card, text=f"これまでの累計節約容量： {format_filesize(total_saved)}",
                font=(APP_FONT, 9), fg=COLORS["text"], bg=COLORS["bg_card"]
            ).pack(anchor="w", pady=(2, 0))

            total_files = config_data.get("total_converted_files", 0) if 'config_data' in locals() else 0
            tk.Label(
                stats_card, text=f"これまでの累計変換数： {total_files} 個",
                font=(APP_FONT, 9), fg=COLORS["text"], bg=COLORS["bg_card"]
            ).pack(anchor="w", pady=(1, 0))

        # --- エンコードプリセット ---
        preset_card = tk.Frame(pad, bg=COLORS["bg_card"], padx=10, pady=8,
                               highlightbackground=COLORS["border"], highlightthickness=1)
        preset_card.pack(fill="x", pady=(0, 8))

        tk.Label(
            preset_card, text="エンコードプリセット",
            font=(APP_FONT, 11, "bold"), fg=COLORS["text"], bg=COLORS["bg_card"]
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
        self._trace_preset_id = self.preset_var.trace_add("write", _update_preset_display)
        self._trace_codec_id = self.codec_var.trace_add("write", _update_preset_display)
        
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
            
        self._trace_audio_id = self.audio_mode_var.trace_add("write", _sync_audio_cbs)

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

        # --- プリセットコーデック一括変更 ---
        bulk_card = tk.Frame(pad, bg=COLORS["bg_card"], padx=12, pady=10,
                             highlightbackground=COLORS["border"], highlightthickness=1)
        bulk_card.pack(fill="x", pady=(0, 10))

        tk.Label(
            bulk_card, text="プリセットのコーデックを一括変更",
            font=(APP_FONT, 11, "bold"), fg=COLORS["text"], bg=COLORS["bg_card"]
        ).pack(anchor="w")

        tk.Label(
            bulk_card,
            text="カスタムプリセット全件の出力コーデックを変更します。\n（デフォルトプリセットは変更されません）",
            font=(APP_FONT, 9), fg=COLORS["text_dim"], bg=COLORS["bg_card"],
            justify="left"
        ).pack(anchor="w", pady=(2, 6))

        # 「自動」を除いたコーデック一覧を選択肢として提示
        bulk_codec_choices = [k for k in CODECS.keys() if CODECS[k]["encoder"] != "auto"]
        bulk_codec_var = tk.StringVar(value=bulk_codec_choices[0])

        bulk_row = tk.Frame(bulk_card, bg=COLORS["bg_card"])
        bulk_row.pack(anchor="w", fill="x")

        ttk.Combobox(
            bulk_row, textvariable=bulk_codec_var,
            values=bulk_codec_choices, state="readonly",
            font=(APP_FONT, 10), width=30
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            bulk_row, text="一括変更する",
            font=(APP_FONT, 10, "bold"), fg=COLORS["text_bright"],
            bg=COLORS["warning"], activebackground=COLORS["warning_hover"],
            activeforeground=COLORS["text_bright"],
            relief="flat", padx=14, pady=4, cursor="hand2",
            command=lambda: self._batch_update_preset_codecs(bulk_codec_var.get(), win)
        ).pack(side="left")

        # --- デフォルトプリセットのコーデック種別 ---
        default_codec_card = tk.Frame(pad, bg=COLORS["bg_card"], padx=12, pady=10,
                                      highlightbackground=COLORS["border"], highlightthickness=1)
        default_codec_card.pack(fill="x", pady=(0, 10))

        tk.Label(
            default_codec_card, text="デフォルトプリセットのコーデック種別",
            font=(APP_FONT, 11, "bold"), fg=COLORS["text"], bg=COLORS["bg_card"]
        ).pack(anchor="w")

        tk.Label(
            default_codec_card,
            text="Discord・ Steam・Xなどのデフォルトプリセットが使うコーデックを一括変更します。\n"
            "（ファイルを変更せず、起動時に動的に変換するため再インストールしても設定が保持されます）",
            font=(APP_FONT, 9), fg=COLORS["text_dim"], bg=COLORS["bg_card"],
            justify="left"
        ).pack(anchor="w", pady=(2, 6))

        # config.json から現在の設定を読む
        _config_path = os.path.join(register_menu.DATA_DIR, "config.json")
        _current_dc_type = "HEVC"
        if os.path.exists(_config_path):
            try:
                with open(_config_path, "r", encoding="utf-8-sig") as f:
                    _current_dc_type = json.load(f).get("default_codec_type", "HEVC")
            except Exception:
                pass

        default_codec_type_var = tk.StringVar(value=_current_dc_type)

        dc_row = tk.Frame(default_codec_card, bg=COLORS["bg_card"])
        dc_row.pack(anchor="w", pady=(0, 4))

        for label, val in [("HEVC / H.265 (推奨)", "HEVC"), ("AV1 (容量最小)", "AV1"), ("H.264 (互換性最大)", "H.264")]:
            tk.Radiobutton(
                dc_row, text=label, variable=default_codec_type_var, value=val,
                font=(APP_FONT, 10), fg=COLORS["text"], bg=COLORS["bg_card"],
                selectcolor=COLORS["bg_card"], activebackground=COLORS["bg_card"],
                activeforeground=COLORS["accent"],
                command=lambda: self._save_default_codec_type(default_codec_type_var.get())
            ).pack(side="left", padx=(0, 12))

        def _close_settings():
            try:
                if getattr(self, '_trace_preset_id', None):
                    self.preset_var.trace_remove("write", self._trace_preset_id)
                    self._trace_preset_id = None
                if getattr(self, '_trace_codec_id', None):
                    self.codec_var.trace_remove("write", self._trace_codec_id)
                    self._trace_codec_id = None
                if getattr(self, '_trace_audio_id', None):
                    self.audio_mode_var.trace_remove("write", self._trace_audio_id)
                    self._trace_audio_id = None
            except Exception:
                pass
            try:
                if win.winfo_exists():
                    win.grab_release()
            except Exception:
                pass
            try:
                if win.winfo_exists():
                    win.destroy()
            except Exception:
                pass

        win.protocol("WM_DELETE_WINDOW", _close_settings)

        # 閉じるボタン（下部固定バーに配置）
        close_btn = self._create_btn(
            bottom_bar, "閉じる", _close_settings,
            fg=COLORS["text"], bg=COLORS["bg_btn"],
            padx=24, pady=6, font_size=11
        )
        close_btn.pack(side="right")

        # マウスホイールを全子ウィジェットにバインドしてスムーズなスクロールを実現
        win.update_idletasks()
        _bind_mousewheel_recursive(pad)

        # ウィンドウを親の近くに配置
        x = self.root.winfo_x() + 40
        y = self.root.winfo_y() + 40
        win.geometry(f"{win_w}x{win_h}+{x}+{y}")

    def _save_app_config(self, *args):
        config_path = os.path.join(register_menu.DATA_DIR, "config.json")
        config = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8-sig") as f:
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
    # プリセットコーデック一括変更
    # ─────────────────────────────────────────
    def _batch_update_preset_codecs(self, target_codec_name: str, parent_win=None):
        """カスタムプリセット全件のコーデックを一括で変更する"""
        if target_codec_name not in CODECS:
            return

        parent = parent_win or self.root

        # 確認ダイアログ
        if not messagebox.askyesno(
            "確認",
            f"すべてのカスタムプリセットの出力コーデックを\n「{target_codec_name}」に変更します。\n\n"
            f"※デフォルトプリセットは変更されません。\nよろしいですか？",
            parent=parent
        ):
            return

        presets_path = os.path.join(register_menu.DATA_DIR, "presets.json")
        if not os.path.exists(presets_path):
            messagebox.showinfo("情報", "変更するカスタムプリセットがありません。", parent=parent)
            return

        try:
            with open(presets_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("エラー", f"プリセットの読み込みに失敗しました:\n{e}", parent=parent)
            return

        target_encoder = CODECS[target_codec_name]["encoder"]
        target_is_amf  = "amf"   in target_encoder
        target_is_nvenc = "nvenc" in target_encoder

        # プリセット値の変換マッピング
        nvenc_to_amf = {
            "p1": "speed", "p2": "speed", "p3": "speed",
            "p4": "balanced",
            "p5": "quality", "p6": "quality", "p7": "quality",
        }
        amf_to_nvenc = {"speed": "p2", "balanced": "p4", "quality": "p6"}

        changed_count = 0
        for uid, preset in data.items():
            # is_custom=False のデフォルトプリセットは対象外
            if not preset.get("is_custom", True):
                continue

            old_codec = preset.get("codec", "")
            old_is_amf   = "amf"   in old_codec.lower()
            old_is_nvenc = "nvenc" in old_codec.lower()

            preset["codec"] = target_codec_name

            # エンコーダー系統が変わる場合、preset 値も変換する
            preset_val = preset.get("preset", "")
            if isinstance(preset_val, str):
                if target_is_amf and old_is_nvenc:
                    # NVENC p1-p7 → AMF speed/balanced/quality
                    preset["preset"] = nvenc_to_amf.get(preset_val.lower(), "balanced")
                elif target_is_nvenc and old_is_amf:
                    # AMF speed/balanced/quality → NVENC p2/p4/p6
                    preset["preset"] = amf_to_nvenc.get(preset_val.lower(), "p4")

            changed_count += 1

        if changed_count == 0:
            messagebox.showinfo("情報", "変更するカスタムプリセットが見つからませんでした。", parent=parent)
            return
        try:
            with open(presets_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            messagebox.showerror("エラー", f"プリセットの保存に失敗しました:\n{e}", parent=parent)
            return

        # 右クリックメニューとメイン画面のプリセットリストを更新
        try:
            register_menu.register_context_menu()
        except Exception:
            pass
        self._update_apply_preset_list()

        messagebox.showinfo(
            "完了",
            f"{changed_count} 件のカスタムプリセットのコーデックを\n「{target_codec_name}」に変更しました。",
            parent=parent
        )

    def _save_default_codec_type(self, codec_type: str):
        """config.json に default_codec_type を保存し、プリセットリストを更新する"""
        config_path = os.path.join(register_menu.DATA_DIR, "config.json")
        config = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8-sig") as f:
                    config = json.load(f)
            except Exception:
                pass
        config["default_codec_type"] = codec_type
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
        except Exception:
            pass
        # プリセットリストと右クリックメニューを即時更新
        self._update_apply_preset_list()
        try:
            register_menu.register_context_menu()
        except Exception:
            pass

    # ─────────────────────────────────────────
    # イベントハンドラ
    # ─────────────────────────────────────────
    def _on_resolution_change(self, *args):
        if not hasattr(self, 'video_info') or not self.input_path:
            return
        res_val = self.resolution_var.get()
        orig_w = max(1, self.video_info.get("width", 1920))
        orig_h = max(1, self.video_info.get("height", 1080))
        
        if res_val == "元のまま":
            new_w = orig_w
            new_h = orig_h
        else:
            target_res = int(res_val.replace("p", ""))
            orig_short = max(1, min(orig_w, orig_h))
            orig_long = max(1, max(orig_w, orig_h))
            if orig_short != target_res:
                scale_factor = target_res / orig_short
                new_short = target_res
                new_long = int(orig_long * scale_factor)
                if orig_w < orig_h:
                    new_w = new_short
                    new_h = new_long
                else:
                    new_w = new_long
                    new_h = new_short
                # 偶数丸め
                new_w = (new_w // 2) * 2
                new_h = (new_h // 2) * 2
            else:
                new_w = orig_w
                new_h = orig_h

        if hasattr(self, 'resolution_preview_label') and self.resolution_preview_label.winfo_exists():
            self.resolution_preview_label.configure(
                text=f"{orig_w}×{orig_h} → {new_w}×{new_h}"
            )
        self._check_resolution_warning(new_h, new_w)

    def _check_resolution_warning(self, new_h=None, new_w=None):
        if not hasattr(self, 'resolution_warning_label') or not hasattr(self, 'video_info'):
            return
            
        if new_h is None or new_w is None:
            res_val = self.resolution_var.get()
            orig_w = max(1, self.video_info.get("width", 1920))
            orig_h = max(1, self.video_info.get("height", 1080))
            if res_val == "元のまま":
                new_w, new_h = orig_w, orig_h
            else:
                target_res = int(res_val.replace("p", ""))
                orig_short = max(1, min(orig_w, orig_h))
                orig_long = max(1, max(orig_w, orig_h))
                if orig_short != target_res:
                    scale_factor = target_res / orig_short
                    new_short = target_res
                    new_long = int(orig_long * scale_factor)
                    if orig_w < orig_h:
                        new_w, new_h = new_short, new_long
                    else:
                        new_w, new_h = new_long, new_short
                else:
                    new_w, new_h = orig_w, orig_h

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
                    mb_to_kbps_factor = (1024 * 1024 * 8) / 1000.0
                    target_total_kbps = (target_size_mb * 0.95 * mb_to_kbps_factor) / duration
                    has_audio_var = hasattr(self, 'audio_var') and self.audio_var.get()
                    audio_kbps = 64 if (has_audio_var and self.video_info.get("has_audio")) else 0
                    video_kbps = target_total_kbps - audio_kbps
                    
                    short_side = min(new_w, new_h)
                    if short_side >= 2160:
                        required_kbps = 6000
                        rec_res = "1080pまたは720p"
                    elif short_side >= 1440:
                        required_kbps = 3000
                        rec_res = "1080pまたは720p"
                    elif short_side >= 1080:
                        required_kbps = 1500
                        rec_res = "720p以下"
                    else:
                        required_kbps = 0
                        rec_res = ""
                    
                    if required_kbps > 0 and video_kbps < required_kbps:
                        warning_text = f"[警告] 目標容量が小さいため、現在の解像度では容量オーバーになる可能性が高いです。\n    {rec_res}への変更を推奨します。"
                        
        self.resolution_warning_label.configure(text=warning_text)

    def _on_percent_change(self, value):
        p = int(float(value))
        if hasattr(self, 'percent_label'):
            self.percent_label.configure(text=f"{p}%")
        self._check_resolution_warning()

    def _on_percent_mousewheel(self, event):
        """割合スライダー上でマウススクロールにより1%ずつ増減（上スクロールで減少、下スクロールで増加）"""
        delta = -1 if event.delta > 0 else 1
        cur_val = self.percent_var.get()
        new_val = max(10, min(90, cur_val + delta))
        if new_val != cur_val:
            self.percent_var.set(new_val)
            self._on_percent_change(new_val)

    def _on_quality_mousewheel(self, event):
        """CQ/QVBRスライダー上でマウススクロールにより1ずつ数値を増減（上スクロールで減少、下スクロールで増加）"""
        delta = -1 if event.delta > 0 else 1
        cur_val = self.quality_var.get()
        new_val = max(15, min(40, cur_val + delta))
        if new_val != cur_val:
            self.quality_var.set(new_val)
            self._on_quality_change(new_val)

    def _select_mode(self, mode: str):
        self.mode_var.set(mode)
        self._on_mode_change()

    def _on_mode_change(self, *args):
        mode = self.mode_var.get()

        # 3連カードボタンの選択状態ハイライトを更新
        if hasattr(self, 'mode_buttons'):
            for m_key, btn in self.mode_buttons.items():
                if m_key == mode:
                    btn.configure(
                        fg_color="#1e2c38",
                        border_color=COLORS["accent"],
                        border_width=1.5,
                        text_color=COLORS["accent"],
                        hover_color="#263847"
                    )
                else:
                    btn.configure(
                        fg_color=COLORS["bg_input"],
                        border_color=COLORS["border"],
                        border_width=1,
                        text_color=COLORS["text_dim"],
                        hover_color=COLORS["bg_btn_hover"]
                    )

        if hasattr(self, 'size_frame'):
            self.size_frame.pack_forget()
        if hasattr(self, 'percent_frame'):
            self.percent_frame.pack_forget()
        if hasattr(self, 'cq_frame'):
            self.cq_frame.pack_forget()

        if mode == "cq":
            if hasattr(self, 'cq_frame'):
                self.cq_frame.pack(fill="x")
        elif mode == "size":
            if hasattr(self, 'size_frame'):
                self.size_frame.pack(fill="x")
        elif mode == "percent":
            if hasattr(self, 'percent_frame'):
                self.percent_frame.pack(fill="x")

        self._check_resolution_warning()

    def _on_quality_change(self, value):
        cq = int(float(value))
        if cq <= 20:
            desc = "最高画質"
        elif cq <= 25:
            desc = "高画質"
        elif cq <= 30:
            desc = "標準"
        elif cq <= 35:
            desc = "低画質"
        else:
            desc = "最低画質"
        self.quality_value_label.configure(text=f"CQ {cq} ({desc})")

    def _open_output_folder(self):
        if hasattr(self, "output_path") and os.path.exists(self.output_path):
            subprocess.Popen(
                ["explorer", "/select,", os.path.normpath(self.output_path)],
                creationflags=subprocess.CREATE_NO_WINDOW
            )

    # ─────────────────────────────────────────
    # FFmpegコマンド生成
    # ─────────────────────────────────────────
    def _build_ffmpeg_command(self, settings: dict = None, fallback_encoder=None) -> list:
        if settings is None:
            settings = self._capture_current_settings()

        codec_name = settings.get("codec") or self._init_codec
        codec_info = CODECS.get(codec_name, CODECS[detect_gpu_and_default_codec()])
        encoder = fallback_encoder if fallback_encoder else codec_info["encoder"]
        ext = codec_info["ext"]

        if encoder == "auto":
            try:
                if register_menu.is_amd_gpu():
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

        # GPU最適化: 入力コーデックに対応するデコーダーで読み込み高速化
        is_nvenc = "nvenc" in encoder
        is_amf = "amf" in encoder

        cmd = [FFMPEG_PATH, "-y"]
        use_gpu_decode = False

        if is_nvenc:
            input_codec = self.video_info.get("codec", "")
            cuvid_decoder = CUVID_DECODERS.get(input_codec)
            has_rotation = (self.video_info.get("rotation", 0) % 360) != 0
            if cuvid_decoder and not has_rotation:
                use_gpu_decode = True
                cmd.extend(["-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
                           "-c:v", cuvid_decoder])
            else:
                use_gpu_decode = False
                cmd.extend(["-hwaccel", "auto"])

        elif is_amf:
            cmd.extend(["-hwaccel", "d3d11va"])

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
                if target_size_mb <= 55.0:
                    margin = 0.85 if is_amf else 0.90
                else:
                    margin = 0.90 if is_amf else 0.95
                
                mb_to_kbps_factor = (1024 * 1024 * 8) / 1000.0
                target_total_kbps = (target_size_mb * margin * mb_to_kbps_factor) / duration
                video_kbps = max(100, int(target_total_kbps - audio_kbps))
                
                buf_multiplier = 1 if target_size_mb <= 55.0 else 2
                
                if is_amf:
                    amf_rc = "vbr" if encoder == "av1_amf" else "vbr_peak"
                    cmd.extend([
                        "-rc", amf_rc,
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
                # スマートCQ / QVBRモード: 元のビットレートを上限としてロック
                if encoder in ("h264_nvenc", "hevc_nvenc", "av1_nvenc"):
                    cmd.extend([
                        "-rc", "vbr",
                        "-cq", str(cq),
                        "-b:v", "0",
                        "-maxrate", f"{orig_video_kbps}k",
                        "-bufsize", f"{orig_video_kbps * 2}k"
                    ])
                elif is_amf:
                    # AMD AMF の QVBR (Quality VBR) + 上限ロック
                    cmd.extend([
                        "-rc", "qvbr",
                        "-qvbr_quality_level", str(cq),
                        "-maxrate", f"{orig_video_kbps}k",
                        "-bufsize", f"{orig_video_kbps * 2}k"
                    ])
            else:
                # 元のビットレートが取得できない場合
                if encoder in ("h264_nvenc", "hevc_nvenc", "av1_nvenc"):
                    cmd.extend(["-rc", "vbr", "-cq", str(cq), "-b:v", "0"])
                elif is_amf:
                    # AMD AMF の QVBR (Quality VBR) モード
                    cmd.extend(["-rc", "qvbr", "-qvbr_quality_level", str(cq)])

        # AMF / NVENC プリセット（設定ダイアログから取得）
        preset_val = self.preset_var.get()
        if is_amf:
            amf_preset = "balanced"
            if preset_val.lower() in ("p1", "p2", "p3", "speed"):
                amf_preset = "speed"
            elif preset_val.lower() in ("p5", "p6", "p7", "quality"):
                amf_preset = "quality"
            elif preset_val.lower() in ("p4", "balanced"):
                amf_preset = "balanced"
            if encoder == "av1_amf" and amf_preset == "quality":
                amf_preset = "balanced"
            cmd.extend(["-preset", amf_preset])
            if encoder == "av1_amf":
                cmd.extend(["-usage", "transcoding"])
        else:
            cmd.extend(["-preset", preset_val.lower()])

        # ビデオフィルター
        filters = []

        # 解像度スケーリング
        res_val = settings.get("resolution", "元のまま")
        orig_w = max(1, self.video_info.get("width", 1920))
        orig_h = max(1, self.video_info.get("height", 1080))
        orig_short = max(1, min(orig_w, orig_h))
        orig_long = max(1, max(orig_w, orig_h))
        
        # 容量指定モードで「元のまま」かつビットレートが低すぎる場合は自動ダウンスケール
        if is_target_size_mode and res_val == "元のまま":
            if video_kbps < 500:
                res_val = "480p" if orig_short > 480 else res_val
            elif video_kbps < 1500:
                res_val = "720p" if orig_short > 720 else res_val
        
        if res_val != "元のまま":
            target_res = int(res_val.replace("p", ""))
            if orig_short != target_res:
                scale_factor = target_res / orig_short
                new_short = target_res
                new_long = int(orig_long * scale_factor)
                if orig_w < orig_h:
                    new_w = new_short
                    new_h = new_long
                else:
                    new_w = new_long
                    new_h = new_short
                new_w = (new_w // 2) * 2
                new_h = (new_h // 2) * 2
                if use_gpu_decode:
                    filters.append(f"scale_cuda={new_w}:{new_h}")
                else:
                    filters.append(f"scale={new_w}:{new_h}")

        if filters:
            cmd.extend(["-vf", ",".join(filters)])

        # フレームレート
        fps_val = settings.get("fps", "元のまま")
        if fps_val != "元のまま":
            cmd.extend(["-r", fps_val])

        # 音声
        audio_enabled = settings.get("audio", True)
        if audio_enabled and self.video_info.get("has_audio"):
            if is_target_size_mode:
                # 目標サイズモード時は強制的に AAC 64kbps にして容量節約
                cmd.extend(["-c:a", "aac", "-b:a", "64k"])
            elif settings.get("audio_mode", "copy") == "copy":
                cmd.extend(["-c:a", "copy"])
            else:
                cmd.extend(["-c:a", "aac", "-b:a", "128k"])
        else:
            cmd.append("-an")

        # オリジナルのメタデータ（内部撮影日時・GPS等）をすべて引き継ぐ
        if settings.get("keep_metadata", True):
            cmd.extend(["-map_metadata", "0"])

        cmd.extend(["-movflags", "+faststart"])

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
                text="現在の設定をプリセットとして保存",
                bg=COLORS["success"],
                activebackground=COLORS["success_hover"],
                state="normal"
            )
            self.preset_btn.configure(
                text="キャンセル",
                fg=COLORS["error"],
                activeforeground=COLORS["error"]
            )
        else:
            self.preset_banner.pack_forget()
            self.main_frame.configure(highlightbackground=COLORS["bg_dark"])
            bg_color = COLORS["accent"] if self.input_path else COLORS["bg_btn"]
            btn_state = "normal" if self.input_path else "disabled"
            self.convert_btn.configure(
                text="圧縮開始",
                bg=bg_color,
                activebackground=COLORS["accent_hover"],
                state=btn_state
            )
            self.preset_btn.configure(
                text="新規プリセット保存",
                fg=COLORS["success"],
                activeforeground=COLORS["success"]
            )

    def _get_default_presets(self):
        default_path = register_menu.get_resource_path("default_presets.json")
        default_presets = {}
        if os.path.exists(default_path):
            try:
                with open(default_path, "r", encoding="utf-8-sig") as f:
                    content = f.read()

                # ① GPU ブランド置換（NVIDIA NVENC → AMD AMF）
                if register_menu.is_amd_gpu():
                    content = content.replace("NVIDIA NVENC", "AMD AMF")

                # ② コーデック種別置換（config.json の設定に従う）
                #    "HEVC / H.265 (〇〇)" を "AV1 (〇〇)" や "H.264 (〇〇)" へ動的に変換する
                config_path = os.path.join(register_menu.DATA_DIR, "config.json")
                default_codec_type = "HEVC"  # デフォルトは変換なし
                if os.path.exists(config_path):
                    try:
                        with open(config_path, "r", encoding="utf-8-sig") as f:
                            cfg = json.load(f)
                            default_codec_type = cfg.get("default_codec_type", "HEVC")
                    except Exception:
                        pass

                if default_codec_type == "AV1":
                    content = content.replace("HEVC / H.265", "AV1")
                elif default_codec_type == "H.264":
                    content = content.replace("HEVC / H.264", "H.264")
                # "HEVC" の場合は変換なし（デフォルトのまま）

                default_presets = json.loads(content)
            except Exception:
                pass
        return default_presets

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
            action_frame, text="削除",
            font=(APP_FONT, 9), fg=COLORS["error"], bg=COLORS["bg_card"],
            activebackground=COLORS["bg_input"], activeforeground=COLORS["error"],
            relief="flat", cursor="hand2", padx=12, pady=6,
            highlightbackground=COLORS["border"], highlightthickness=1,
            command=self._delete_preset
        )
        delete_btn.pack(side="left")

        def _close_preset_manager():
            try:
                if win.winfo_exists():
                    win.grab_release()
            except Exception:
                pass
            try:
                if win.winfo_exists():
                    win.destroy()
            except Exception:
                pass

        win.protocol("WM_DELETE_WINDOW", _close_preset_manager)

        close_btn = tk.Button(
            action_frame, text="閉じる",
            font=(APP_FONT, 9), fg=COLORS["text"], bg=COLORS["bg_card"],
            activebackground=COLORS["bg_input"], activeforeground=COLORS["text_bright"],
            relief="flat", cursor="hand2", padx=16, pady=6,
            command=_close_preset_manager
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
                    with open(config_path, "r", encoding="utf-8-sig") as f:
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


    def _get_user_presets(self):
        presets_path = os.path.join(register_menu.DATA_DIR, "presets.json")
        user_presets = {}
        if os.path.exists(presets_path):
            try:
                with open(presets_path, "r", encoding="utf-8-sig") as f:
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
        self._batch_start_time = time.time()  # バッチ全体の開始時刻を記録
        
        self.current_file_index = 0
        self.batch_saved_bytes = 0
        self.batch_orig_bytes = 0
        self.batch_out_bytes = 0

        # 現在選択中ファイルの設定を保存
        if self._selected_queue_path and self._selected_queue_path in self._queue_data:
            self._queue_data[self._selected_queue_path]["settings"] = self._capture_current_settings()
        self._selected_queue_path = None  # 変換開始時は選択を解除

        # キューを全て「待機中」にリセット
        for path in self.input_paths:
            self._queue_data[path] = {
                "status": "waiting", "progress": 0.0,
                "orig_size": 0, "out_size": 0,
            }
        self.root.after(0, self._refresh_queue_display)
        
        # 成功時のボタンを非表示にし、削除ボタンを初期化
        self.open_btn.pack_forget()
        self.delete_btn.pack_forget()
        self.delete_btn.configure(text="元ファイルを削除", state="normal")

        self.convert_btn.configure(state="disabled", text="変換中...", fg_color=COLORS["bg_btn"])
        self.cancel_btn.pack(side="right", padx=(0, 8))

        # タスクバー: 準備状態 (緑のアニメーション)
        self.taskbar_progress.set_state(TBPF_INDETERMINATE)

        # GPU使用率監視を開始
        self._start_gpu_monitor()

        # サブスレッドでバッチ処理ワーカーを開始（再帰排除）
        thread = threading.Thread(target=self._conversion_worker, daemon=True)
        thread.start()

    def _start_gpu_monitor(self):
        """GPU (3D & Encode) 使用率の常時監視を開始（アイドル時・変換中問わず自動更新）"""
        if getattr(self, '_gpu_monitor_running', False):
            return
        self._gpu_monitor_running = True
        self._gpu_monitor = GpuEngineMonitor()

        def _worker():
            self._gpu_monitor.refresh_counters()
            while getattr(self, '_gpu_monitor_running', False):
                interval = 1.0 if getattr(self, 'is_converting', False) else 2.0
                time.sleep(interval)
                if not getattr(self, '_gpu_monitor_running', False):
                    break
                u_3d, u_enc = self._gpu_monitor.get_utilization()
                def _update(d=u_3d, e=u_enc):
                    is_conv = getattr(self, 'is_converting', False)
                    fg_c = COLORS["accent"] if is_conv or e > 5.0 or d > 10.0 else COLORS["text_dim"]
                    if hasattr(self, 'gpu_3d_meter') and self.gpu_3d_meter.winfo_exists():
                        self.gpu_3d_meter.set_value(d)
                    if hasattr(self, 'gpu_enc_meter') and self.gpu_enc_meter.winfo_exists():
                        self.gpu_enc_meter.set_value(e)
                    if hasattr(self, 'gpu_status_label') and self.gpu_status_label.winfo_exists():
                        self.gpu_status_label.configure(
                            text=f"3D: {d:4.1f}%  |  Encode: {e:4.1f}%",
                            fg=fg_c
                        )
                    if hasattr(self, 'hud_gpu_label') and self.hud_gpu_label.winfo_exists():
                        self.hud_gpu_label.configure(
                            text=f"3D Engine: {d:4.1f}%  |  Video Encode: {e:4.1f}%",
                            fg=fg_c
                        )
                if hasattr(self, 'root') and self.root:
                    try:
                        self.root.after(0, _update)
                    except Exception:
                        break

        self._gpu_monitor_thread = threading.Thread(target=_worker, daemon=True)
        self._gpu_monitor_thread.start()

    def _stop_gpu_monitor(self):
        """GPU 監視を停止"""
        self._gpu_monitor_running = False
        if hasattr(self, '_gpu_monitor') and self._gpu_monitor:
            self._gpu_monitor.close()
            self._gpu_monitor = None

    def _conversion_worker(self):
        """サブスレッドで全ファイルをループ処理するワーカー"""
        try:
            while self.current_file_index < len(self.input_paths):
                if getattr(self, "is_cancelled", False):
                    break

                self.input_path = self.input_paths[self.current_file_index]
                self.video_info = get_video_info(self.input_path)

                # 個別設定を取得（無ければ現在のデフォルト設定）
                file_settings = self._queue_data.get(self.input_path, {}).get("settings")
                if not file_settings:
                    file_settings = self._capture_current_settings()

                # 個別設定をUI変数へ反映（threading.Eventで完了同期）
                evt = threading.Event()
                def _do_apply(s=file_settings, e=evt):
                    self._apply_settings(s, completion_event=e)
                self.root.after(0, _do_apply)
                evt.wait()

                if self.input_path in self._queue_data:
                    self._queue_data[self.input_path]["status"] = "converting"
                    self._queue_data[self.input_path]["progress"] = 0.0
                self.root.after(0, self._refresh_queue_display)

                fallback_encoder = None
                while True:
                    if getattr(self, "is_cancelled", False):
                        break

                    success, should_retry, next_fallback = self._execute_single_ffmpeg(file_settings, fallback_encoder)
                    if success:
                        self.current_file_index += 1
                        break
                    elif should_retry:
                        fallback_encoder = next_fallback
                        continue
                    else:
                        # 失敗（バッチは継続）
                        self.current_file_index += 1
                        break

                if not getattr(self, "is_cancelled", False) and self.current_file_index < len(self.input_paths):
                    time.sleep(0.5)

            if not getattr(self, "is_cancelled", False):
                self.root.after(0, self._on_batch_finished)

        except Exception as e:
            self._update_status(f"エラー: {str(e)}", color=COLORS["error"])
            self._show_error(str(e))
        finally:
            self.process = None
            self.is_converting = False
            self.taskbar_progress.set_state(TBPF_NOPROGRESS)
            def _reset_btn():
                if hasattr(self, "cancel_btn"):
                    self.cancel_btn.pack_forget()
                self.convert_btn.configure(state="normal", text="⚡ 圧縮開始", fg_color=COLORS["accent"])
            self.root.after(0, _reset_btn)

    def _execute_single_ffmpeg(self, settings: dict, fallback_encoder=None) -> tuple[bool, bool, str]:
        """単一ファイルのFFmpeg変換を実行する。(成功, 再試行可否, 次のフォールバック)"""
        cmd = self._build_ffmpeg_command(settings=settings, fallback_encoder=fallback_encoder)
        duration = self.video_info.get("duration", 0)
        start_time = time.time()

        prefix = f"({self.current_file_index + 1}/{len(self.input_paths)}) " if len(self.input_paths) > 1 else ""
        if fallback_encoder:
            self._update_status(f"再試行中 {prefix}(H.264)... 出力: {Path(self.output_path).name}")
        else:
            self._update_status(f"変換中... {prefix}出力: {Path(self.output_path).name}")

        initial_progress = (self.current_file_index * 100) / max(1, len(self.input_paths))
        self._update_progress(initial_progress)
        self.root.after(0, lambda: self.taskbar_progress.set_value(int(initial_progress * 10), 1000))

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

            time_pattern = re.compile(r"time=(\d+):(\d+):(\d+)\.(\d+)")
            last_update_time = 0

            for line in self.process.stderr:
                if getattr(self, "is_cancelled", False):
                    break
                match = time_pattern.search(line)
                if match and duration > 0:
                    h, m, s, cs = match.groups()
                    current = int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100
                    progress = min(current / duration * 100, 99.9)

                    now = time.time()
                    # 0.1秒以上のインターバルでのスロットリング
                    if now - last_update_time >= 0.1 or progress == 0 or progress >= 99.0:
                        last_update_time = now
                        total_files = max(1, len(self.input_paths))
                        overall_progress = (self.current_file_index * 100 + progress) / total_files

                        speed_match = re.search(r"speed=\s*([\d.]+)x", line)
                        speed_text = f" ({speed_match.group(1)}x)" if speed_match else ""
                        eta_text = ""
                        speed_str_short = f"{speed_match.group(1)}x" if speed_match else "-"
                        eta_str_short = "-"
                        if speed_match:
                            try:
                                speed_val = float(speed_match.group(1))
                                if speed_val > 0.1:
                                    eta_sec = max(0, (duration - current) / speed_val)
                                    eta_m = int(eta_sec // 60)
                                    eta_s = int(eta_sec % 60)
                                    eta_text = f"  残り約 {eta_m}分{eta_s:02d}秒" if eta_m > 0 else f"  残り約 {eta_s}秒"
                                    eta_str_short = f"{eta_m:02d}:{eta_s:02d}" if eta_m > 0 else f"00:{eta_s:02d}"
                            except ValueError:
                                pass

                        prefix_str = f"({self.current_file_index + 1}/{len(self.input_paths)}) " if len(self.input_paths) > 1 else ""
                        status_str = f"変換中... {prefix_str}{progress:.1f}%{speed_text}{eta_text}  →  {Path(self.output_path).name}"

                        _fp = self.input_path
                        self.root.after(0, lambda p=overall_progress, fp=_fp, p_item=progress, st=status_str, sp=speed_str_short, et=eta_str_short: self._update_throttled_ui(p, fp, p_item, st, sp, et))

            self.process.wait()
            elapsed_time = time.time() - start_time

            if self.process.returncode == 0:
                completed_progress = ((self.current_file_index + 1) * 100) / max(1, len(self.input_paths))
                self._update_progress(completed_progress)
                self.root.after(0, lambda: self.taskbar_progress.set_value(int(completed_progress * 10), 1000))

                # 元のファイルの「更新日時」および「アクセス日時」を引き継ぐ
                if settings.get("keep_metadata", True):
                    try:
                        if os.path.exists(self.input_path) and os.path.exists(self.output_path):
                            st = os.stat(self.input_path)
                            os.utime(self.output_path, (st.st_atime, st.st_mtime))
                    except Exception:
                        pass

                # 元ファイルの自動削除
                if settings.get("auto_delete", False):
                    if os.path.exists(self.input_path):
                        send_to_recycle_bin(self.input_path)

                out_size = os.path.getsize(self.output_path) if os.path.exists(self.output_path) else 0
                orig_size = self.video_info.get("filesize", 0)

                _done_path = self.input_path
                if _done_path in self._queue_data:
                    self._queue_data[_done_path].update({
                        "status": "done", "progress": 100.0,
                        "orig_size": orig_size, "out_size": out_size,
                    })
                self.root.after(0, self._refresh_queue_display)

                if orig_size > 0 and out_size > 0:
                    saved_bytes = max(0, orig_size - out_size)
                    self.batch_saved_bytes = getattr(self, 'batch_saved_bytes', 0) + saved_bytes
                    self.batch_orig_bytes = getattr(self, 'batch_orig_bytes', 0) + orig_size
                    self.batch_out_bytes = getattr(self, 'batch_out_bytes', 0) + out_size

                    # 累計節約容量と累計変換数の保存
                    self._update_cumulative_stats(saved_bytes)

                    ratio = out_size / orig_size * 100
                    el = int(elapsed_time)
                    elapsed_str = f"{el // 60}分{el % 60:02d}秒" if el >= 60 else f"{el}秒"
                    status_text = f"変換完了: {format_filesize(orig_size)} → {format_filesize(out_size)} ({ratio:.1f}% / 元サイズ) 所要時間: {elapsed_str}"
                    if hasattr(self, 'hud_reduction_label'):
                        self.root.after(0, lambda o=orig_size, n=out_size, r=ratio: self.hud_reduction_label.configure(
                            text=f"削減結果: {format_filesize(o)} -> {format_filesize(n)} (-{100-r:.1f}%)"
                        ))
                else:
                    el = int(elapsed_time)
                    elapsed_str = f"{el // 60}分{el % 60:02d}秒" if el >= 60 else f"{el}秒"
                    status_text = f"変換完了: {format_filesize(out_size)} 所要時間: {elapsed_str}"

                if hasattr(self, 'hud_speed_eta_label'):
                    self.root.after(0, lambda: self.hud_speed_eta_label.configure(
                        text=f"所要時間: {elapsed_str}", fg=COLORS["text_dim"]
                    ))

                self._update_status(status_text, color=COLORS["success"])

                # 個別完了通知サウンドの再生（バッチ完了時は除く）
                if self.current_file_index + 1 < len(self.input_paths):
                    self._play_notification_sound()

                return True, False, None

            elif getattr(self, "is_cancelled", False):
                self._update_progress(0)
                self._update_status("変換が中止されました", color=COLORS["error"])
                if hasattr(self, 'hud_speed_eta_label'):
                    self.root.after(0, lambda: self.hud_speed_eta_label.configure(
                        text="[中止] 変換が中止されました", fg=COLORS["warning"]
                    ))
                if hasattr(self, "output_path") and os.path.exists(self.output_path):
                    try: os.remove(self.output_path)
                    except Exception: pass
                return False, False, None
            else:
                current_enc = getattr(self, "current_encoder", "")
                actual_enc = fallback_encoder if fallback_encoder else current_enc

                if elapsed_time < 2.0 and actual_enc in ("av1_nvenc", "av1_amf", "hevc_nvenc", "hevc_amf"):
                    if hasattr(self, "output_path") and os.path.exists(self.output_path):
                        try: os.remove(self.output_path)
                        except Exception: pass

                    if actual_enc in ("av1_nvenc", "av1_amf"):
                        fallback = "hevc_nvenc" if "nvenc" in actual_enc else "hevc_amf"
                        msg = "AV1非対応の可能性があるため、H.265(HEVC)で再試行します..."
                    else:
                        fallback = "h264_nvenc" if "nvenc" in actual_enc else "h264_amf"
                        msg = "H.265非対応の可能性があるため、H.264で再試行します..."

                    self._update_status(msg, color=COLORS["warning"])
                    return False, True, fallback

                self._update_status(f"変換失敗 (コード: {self.process.returncode})", color=COLORS["error"])
                if hasattr(self, 'hud_speed_eta_label'):
                    self.root.after(0, lambda: self.hud_speed_eta_label.configure(
                        text="[エラー] 変換失敗", fg=COLORS["error"]
                    ))
                if self.input_path in self._queue_data:
                    self._queue_data[self.input_path]["status"] = "error"
                self.root.after(0, self._refresh_queue_display)
                self._show_error(f"FFmpegがエラーで終了しました。\n\n終了コード: {self.process.returncode}")
                return False, False, None

        except Exception as e:
            self._update_status(f"エラー: {str(e)}", color=COLORS["error"])
            if hasattr(self, 'hud_speed_eta_label'):
                self.root.after(0, lambda: self.hud_speed_eta_label.configure(
                    text="[エラー] 変換エラー発生", fg=COLORS["error"]
                ))
            self._show_error(str(e))
            return False, False, None

    def _update_throttled_ui(self, overall_progress, file_path, file_progress, status_str, speed_str="-", eta_str="-"):
        """スロットリングされたUI更新（メインスレッド用）"""
        self.progress_var.set(overall_progress)
        if hasattr(self, 'progress_bar') and isinstance(self.progress_bar, ctk.CTkProgressBar):
            self.progress_bar.set(min(1.0, max(0.0, overall_progress / 100.0)))
        self.taskbar_progress.set_state(TBPF_NORMAL)
        self.taskbar_progress.set_value(int(overall_progress * 10), 1000)
        self._update_queue_item_progress(file_path, file_progress)
        self.status_label.configure(text=status_str, text_color=COLORS["text_dim"])
        if hasattr(self, 'progress_pct_label') and self.progress_pct_label.winfo_exists():
            self.progress_pct_label.configure(text=f"{overall_progress:.0f}%")
        if hasattr(self, 'hud_speed_eta_label') and self.hud_speed_eta_label.winfo_exists():
            self.hud_speed_eta_label.configure(
                text=f"進捗: {overall_progress:4.1f}%  |  速度: {speed_str}  |  残り: {eta_str}",
                fg=COLORS["accent"]
            )

    def _update_cumulative_stats(self, saved_bytes):
        """累計変換統計の更新"""
        total_saved = 0
        total_files = 0
        config_path = os.path.join(register_menu.DATA_DIR, "config.json")
        config_data = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8-sig") as f:
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

    def _on_batch_finished(self):
        if len(self.input_paths) > 1:
            orig_total = getattr(self, 'batch_orig_bytes', 0)
            out_total = getattr(self, 'batch_out_bytes', 0)
            batch_elapsed = int(time.time() - getattr(self, '_batch_start_time', time.time()))
            batch_elapsed_str = f"{batch_elapsed}秒" if batch_elapsed < 60 else f"{batch_elapsed // 60}分{batch_elapsed % 60:02d}秒"
            
            if orig_total > 0 and out_total > 0:
                ratio = out_total / orig_total * 100
                status_text = (
                    f"{len(self.input_paths)} 個すべての変換完了: "
                    f"{format_filesize(orig_total)} → {format_filesize(out_total)}"
                    f" ({ratio:.1f}% / 元サイズ)  所要時間: {batch_elapsed_str}"
                )
            else:
                status_text = f"{len(self.input_paths)} 個すべての変換が完了しました。  所要時間: {batch_elapsed_str}"
            
            self._update_status(status_text, color=COLORS["accent"], font_size=11, is_bold=True)
            
        self._show_success()

    def _delete_original_file(self):
        success_count = 0
        for p in getattr(self, "input_paths", []):
            if os.path.exists(p):
                if send_to_recycle_bin(p):
                    success_count += 1
                    
        if success_count > 0:
            self.delete_btn.configure(text="削除しました", state="disabled")

    def _cancel_conversion(self):
        if self.is_converting and self.process:
            self.is_cancelled = True
            self.process.terminate()
            self._update_status("変換が中止されました", color=COLORS["error"])
            self.cancel_btn.pack_forget()

            for path, data in self._queue_data.items():
                if data.get("status") in ("converting", "waiting"):
                    data["status"] = "cancelled"
            self.root.after(0, self._refresh_queue_display)

            self.taskbar_progress.set_state(TBPF_ERROR)
            self.taskbar_progress.set_value(100, 100)

    def _update_progress(self, value):
        def _update():
            self.progress_var.set(value)
            if hasattr(self, 'progress_bar') and isinstance(self.progress_bar, ctk.CTkProgressBar):
                self.progress_bar.set(min(1.0, max(0.0, value / 100.0)))
            if hasattr(self, 'progress_pct_label') and self.progress_pct_label.winfo_exists():
                self.progress_pct_label.configure(text=f"{value:.0f}%")
        self.root.after(0, _update)

    def _update_status(self, text, color=None, font_size=11, is_bold=False):
        fg_color = color if color else COLORS["text_dim"]
        self.root.after(0, lambda: self.status_label.configure(text=text, text_color=fg_color))

    def _show_success(self):
        def _update():
            if hasattr(self, 'progress_bar') and isinstance(self.progress_bar, ctk.CTkProgressBar):
                self.progress_bar.set(1.0)
            if hasattr(self, 'progress_pct_label') and self.progress_pct_label.winfo_exists():
                self.progress_pct_label.configure(text="100%")

            # 右側グループ内で右詰めで整然と並べる
            self.cancel_btn.pack_forget()
            self.convert_btn.pack(side="right", padx=(8, 0))
            if getattr(self, "auto_delete_var", None) and self.auto_delete_var.get():
                self.delete_btn.configure(text="削除しました", state="disabled")
            else:
                self.delete_btn.configure(text="元ファイルを削除", state="normal")
            self.delete_btn.pack(side="right", padx=(6, 0))
            self.open_btn.pack(side="right", padx=(6, 0))
            
            self.taskbar_progress.set_state(TBPF_NOPROGRESS)
            self._play_notification_sound()
            
            if self.auto_close_var.get():
                self.root.destroy()
        self.root.after(0, _update)

    def _show_error(self, message):
        def _update():
            self.taskbar_progress.set_state(TBPF_ERROR)
            self.taskbar_progress.set_value(100, 100)
            self.status_label.configure(text=f"エラー: {message}", text_color=COLORS["error"])
            messagebox.showerror("エラー", message, parent=self.root)
            
        self.root.after(0, _update)

    def _play_notification_sound(self):
        """変換完了時の通知音を再生"""
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass

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
                with open(config_path, "r", encoding="utf-8-sig") as f:
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
                data = json.loads(response.read().decode("utf-8-sig"))
                latest_tag = data.get("tag_name", "").strip()
                latest_version = latest_tag.lstrip("v")
                html_url = data.get("html_url", "")
                
                # バージョンが大きければ新しいバージョンありとする
                if latest_version and parse_version(latest_version) > parse_version(CURRENT_VERSION):
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
                with open(config_path, "r", encoding="utf-8-sig") as f:
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
    parser.add_argument("input", nargs="*", help="入力ファイル (複数可)")
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
        filepaths = []
    elif isinstance(args.input, list):
        filepaths = [f for f in args.input if f]
    else:
        filepaths = [args.input]

    invalid_files = [f for f in filepaths if not os.path.isfile(f)]
    if invalid_files:
        messagebox.showerror("エラー", f"ファイルが見つかりません:\n" + "\n".join(invalid_files))
        sys.exit(1)


    # DPI対応 (Tkinterの文字が滲まないようSystem DPI Awareを設定)
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    class MainAppWindow(ctk.CTk, (TkinterDnD.DnDWrapper if HAS_DND else object)):
        def __init__(self):
            super().__init__()
            if HAS_DND:
                self.TkdndVersion = TkinterDnD._require(self)

    root = MainAppWindow()
    app = QuickCompressorApp(
        root, filepaths,
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
