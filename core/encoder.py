# -*- coding: utf-8 -*-
"""
Quick Compressor - エンコーダー・FFmpegコアモジュール
GPU自動検出、動画メタデータ取得、FFmpegコマンド生成、ビットレート計算
"""

import sys
import os
import json
import subprocess
from pathlib import Path

# アプリケーションパス解決
def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_resource_path(relative_path):
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
        app_dir = get_app_dir()
        return os.path.join(app_dir, relative_path)

_bundled_ffmpeg = get_resource_path(os.path.join("bin", "ffmpeg.exe"))
_bundled_ffprobe = get_resource_path(os.path.join("bin", "ffprobe.exe"))

FFMPEG_PATH = _bundled_ffmpeg if os.path.exists(_bundled_ffmpeg) else "ffmpeg"
FFPROBE_PATH = _bundled_ffprobe if os.path.exists(_bundled_ffprobe) else "ffprobe"

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

CUVID_DECODERS = {
    "h264": "h264_cuvid",
    "hevc": "hevc_cuvid",
    "vp9": "vp9_cuvid",
    "mpeg4": "mpeg4_cuvid",
    "mpeg2video": "mpeg2_cuvid",
    "mpeg1video": "mpeg1_cuvid",
    "vp8": "vp8_cuvid",
}

NVENC_PRESETS = [
    ("p1", "最速（ファイルサイズ大）"),
    ("p2", "高速"),
    ("p3", "やや速い"),
    ("p4", "標準（バランス）"),
    ("p5", "やや遅い"),
    ("p6", "低速"),
    ("p7", "最遅（ファイルサイズ小）"),
]

def format_filesize(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}" if unit != 'B' else f"{size_bytes} B"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"

def detect_gpu_type():
    """NVIDIA / AMD / Intel / CPU を検出"""
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
            startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW
        ).decode('utf-8', errors='ignore').lower()
        if "nvidia" in out:
            return "nvidia"
        if "amd" in out or "radeon" in out:
            return "amd"
        if "intel" in out:
            return "intel"
    except Exception:
        pass
    return "cpu"

def detect_gpu_and_default_codec():
    gpu = detect_gpu_type()
    if gpu == "amd":
        return "HEVC / H.265 (AMD AMF)"
    elif gpu == "nvidia":
        return "HEVC / H.265 (NVIDIA NVENC)"
    return "自動 (推奨: 環境に合わせて自動選択)"

def check_amf_h264_support():
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        out = subprocess.check_output(
            [FFMPEG_PATH, "-hide_banner", "-encoders"],
            startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW
        ).decode('utf-8', errors='ignore')
        return "h264_amf" in out
    except Exception:
        return False

def get_video_info(filepath: str) -> dict:
    """ffprobe を用いて動画のメタデータを高速取得"""
    if not filepath or not os.path.exists(filepath):
        return {"error": "ファイルが存在しません"}

    cmd = [
        FFPROBE_PATH,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        filepath
    ]

    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        res = subprocess.run(
            cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore',
            startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW
        )
        if res.returncode != 0:
            return {"error": "メタデータの読み取りに失敗しました"}

        data = json.loads(res.stdout)
        streams = data.get("streams", [])
        video_stream = None
        has_audio = False

        for s in streams:
            codec_type = s.get("codec_type")
            if codec_type == "video" and not video_stream:
                if s.get("disposition", {}).get("attached_pic") != 1:
                    video_stream = s
            elif codec_type == "audio":
                has_audio = True

        if not video_stream:
            for s in streams:
                if s.get("codec_type") == "video":
                    video_stream = s
                    break

        if not video_stream:
            return {"error": "動画ストリームが見つかりません"}

        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))

        rotation = 0
        side_data_list = video_stream.get("side_data_list", [])
        for sd in side_data_list:
            if "rotation" in sd:
                try: rotation = int(float(sd["rotation"]))
                except Exception: pass
        if rotation == 0:
            tags = video_stream.get("tags", {})
            if "rotate" in tags:
                try: rotation = int(float(tags["rotate"]))
                except Exception: pass

        rotation = rotation % 360
        if rotation in (90, 270):
            width, height = height, width

        fps = 0.0
        r_fps = video_stream.get("r_frame_rate", "0/0")
        if "/" in r_fps:
            num, den = r_fps.split("/")
            if float(den) > 0:
                fps = float(num) / float(den)
        if fps <= 0:
            avg_fps = video_stream.get("avg_frame_rate", "0/0")
            if "/" in avg_fps:
                num, den = avg_fps.split("/")
                if float(den) > 0:
                    fps = float(num) / float(den)

        duration = float(data.get("format", {}).get("duration", video_stream.get("duration", 0)))
        filesize = int(data.get("format", {}).get("size", os.path.getsize(filepath)))
        bitrate = int(data.get("format", {}).get("bit_rate", video_stream.get("bit_rate", 0)))
        codec = video_stream.get("codec_name", "unknown")

        return {
            "width": width, "height": height, "fps": fps,
            "duration": duration, "filesize": filesize, "bitrate": bitrate,
            "codec": codec, "has_audio": has_audio, "rotation": rotation
        }
    except Exception as e:
        return {"error": str(e)}

def build_ffmpeg_command(input_path: str, output_path: str, settings: dict, video_info: dict, fallback_encoder=None) -> tuple:
    """
    FFmpeg コマンド引数リストとエンコーダー名を生成
    戻り値: (cmd_list: list, encoder_name: str)
    """
    codec_name = settings.get("codec", "自動 (推奨: 環境に合わせて自動選択)")
    codec_info = CODECS.get(codec_name, CODECS[detect_gpu_and_default_codec()])
    encoder = fallback_encoder if fallback_encoder else codec_info["encoder"]
    
    if encoder == "auto":
        gpu = detect_gpu_type()
        encoder = "hevc_amf" if gpu == "amd" else "hevc_nvenc"

    is_nvenc = "nvenc" in encoder
    is_amf = "amf" in encoder

    cmd = [FFMPEG_PATH, "-y"]
    use_gpu_decode = False

    if is_nvenc:
        input_codec = video_info.get("codec", "")
        cuvid_decoder = CUVID_DECODERS.get(input_codec)
        has_rotation = (video_info.get("rotation", 0) % 360) != 0
        if cuvid_decoder and not has_rotation:
            use_gpu_decode = True
            cmd.extend(["-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-c:v", cuvid_decoder])
        else:
            cmd.extend(["-hwaccel", "auto"])
    elif is_amf:
        cmd.extend(["-hwaccel", "d3d11va"])

    cmd.extend(["-i", input_path])
    cmd.extend(["-c:v", encoder])

    if not use_gpu_decode:
        cmd.extend(["-pix_fmt", "yuv420p"])

    if "hevc" in encoder:
        cmd.extend(["-tag:v", "hvc1"])

    # 品質/ビットレート設定
    mode = settings.get("mode", "cq")
    cq = settings.get("cq", 25)
    target_size_mb = settings.get("target_size_mb")
    target_percent = settings.get("target_percent")
    duration = video_info.get("duration", 0)
    filesize = video_info.get("filesize", 0)

    is_target_size_mode = False
    video_kbps = 0

    if mode == "size" and target_size_mb:
        is_target_size_mode = True
        if duration > 0:
            target_bytes = target_size_mb * 1048576.0
            margin = 0.85 if is_amf else 0.90
            target_total_kbps = (target_bytes * margin * 8.0) / (duration * 1000.0)
            has_audio = settings.get("audio_enabled", True) and video_info.get("has_audio", True)
            audio_kbps = 64 if has_audio else 0
            video_kbps = max(50, int(target_total_kbps - audio_kbps))
    elif mode == "percent" and target_percent:
        is_target_size_mode = True
        if duration > 0 and filesize > 0:
            target_bytes = filesize * (target_percent / 100.0)
            margin = 0.85 if is_amf else 0.90
            target_total_kbps = (target_bytes * margin * 8.0) / (duration * 1000.0)
            has_audio = settings.get("audio_enabled", True) and video_info.get("has_audio", True)
            audio_kbps = 64 if has_audio else 0
            video_kbps = max(50, int(target_total_kbps - audio_kbps))

    preset_val = settings.get("preset", "p4")
    if is_nvenc:
        cmd.extend(["-preset", preset_val])
        if is_target_size_mode:
            cmd.extend([
                "-rc", "vbr",
                "-b:v", f"{video_kbps}k",
                "-maxrate", f"{int(video_kbps * 1.5)}k",
                "-bufsize", f"{int(video_kbps * 2.0)}k",
                "-multipass", "qres"
            ])
        else:
            cmd.extend(["-rc", "constqp", "-qp", str(cq)])
    elif is_amf:
        amf_preset = {"p1":"speed","p2":"speed","p3":"speed","p4":"balanced","p5":"quality","p6":"quality","p7":"quality"}.get(preset_val, "balanced")
        cmd.extend(["-quality", amf_preset])
        if is_target_size_mode:
            cmd.extend([
                "-rc", "vbr_peak",
                "-b:v", f"{video_kbps}k",
                "-maxrate", f"{int(video_kbps * 1.3)}k",
                "-bufsize", f"{int(video_kbps * 2.0)}k",
                "-min_qp_i", "18", "-min_qp_p", "18"
            ])
        else:
            cmd.extend(["-rc", "cqp", "-qp_i", str(cq), "-qp_p", str(cq)])

    # 解像度 & FPS フィルター
    vf_filters = []
    res_val = settings.get("resolution", "元のまま")
    if res_val != "元のまま":
        target_res = int(res_val.replace("p", ""))
        orig_w = video_info.get("width", 1920)
        orig_h = video_info.get("height", 1080)
        if orig_w < orig_h:
            vf_filters.append(f"scale={target_res}:-2:flags=bicubic")
        else:
            vf_filters.append(f"scale=-2:{target_res}:flags=bicubic")

    fps_val = settings.get("fps", "元のまま")
    if fps_val != "元のまま":
        vf_filters.append(f"fps={fps_val}")

    if vf_filters:
        cmd.extend(["-vf", ",".join(vf_filters)])

    # 音声設定
    audio_enabled = settings.get("audio_enabled", True)
    if not audio_enabled or not video_info.get("has_audio", True):
        cmd.append("-an")
    else:
        if is_target_size_mode:
            cmd.extend(["-c:a", "aac", "-b:a", "64k"])
        else:
            cmd.extend(["-c:a", "copy"])

    # メタデータ保持
    if settings.get("keep_metadata", True):
        cmd.extend(["-map_metadata", "0"])

    cmd.extend(["-progress", "pipe:2", output_path])
    return cmd, encoder
