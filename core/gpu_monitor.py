# -*- coding: utf-8 -*-
"""
Quick Compressor - GPU エンジン使用率監視モジュール
Windows PDH API を用いて 3D および Video Encode エンジンの使用率を低負荷・動的に取得
"""

import time
import ctypes
from ctypes import wintypes

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
