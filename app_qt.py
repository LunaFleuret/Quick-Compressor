# -*- coding: utf-8 -*-
"""
Quick Compressor - PyQt6 + Fluent Widgets Edition
Windows 11 Fluent Design (Dark Theme) 準拠のモダン動画圧縮ツール
"""

import sys
import os
import time
import subprocess
import winsound
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QIcon, QColor, QFont, QPixmap, QPainter, QLinearGradient, QBrush, QPen, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFileDialog, QMessageBox, QFrame, QSizePolicy, QListWidget, QListWidgetItem
)

from qfluentwidgets import (
    FluentWindow, MSFluentWindow, setTheme, Theme,
    PushButton, PrimaryPushButton, TransparentPushButton, PillPushButton,
    ComboBox, Slider, CheckBox, ProgressBar, ProgressRing,
    CardWidget, TitleLabel, BodyLabel, CaptionLabel, SubtitleLabel,
    SegmentedWidget, InfoBadge, Flyout, FlyoutView, InfoBar, InfoBarPosition,
    isDarkTheme
)

from core.encoder import (
    CODECS, FRAME_RATES, RESOLUTIONS, get_video_info, format_filesize,
    detect_gpu_and_default_codec, check_amf_h264_support, build_ffmpeg_command,
    FFMPEG_PATH, get_app_dir
)
from core.gpu_monitor import GpuEngineMonitor
from core.preset_manager import PresetManager, get_default_presets
from ui.dialogs import SettingsDialog, PresetManagerDialog

CURRENT_VERSION = "3.0.0"

# ─────────────────────────────────────────────
# アイコン生成ユーティリティ
# ─────────────────────────────────────────────
def create_video_icon_pixmap(size=28) -> QPixmap:
    """Windows 11 Fluent風の紫グラデーション動画アイコン"""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # 背景角丸グラデーション
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, QColor("#8b5cf6"))
    grad.setColorAt(1.0, QColor("#6366f1"))
    painter.setBrush(QBrush(grad))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(0, 0, size, size, 6, 6)

    # 白色の再生三角形
    painter.setBrush(QBrush(QColor("#ffffff")))
    from PyQt6.QtGui import QPolygonF
    from PyQt6.QtCore import QPointF
    p1 = QPointF(size * 0.38, size * 0.28)
    p2 = QPointF(size * 0.72, size * 0.50)
    p3 = QPointF(size * 0.38, size * 0.72)
    painter.drawPolygon(QPolygonF([p1, p2, p3]))

    painter.end()
    return pix


# ─────────────────────────────────────────────
# エンコード処理ワーカースレッド (QThread)
# ─────────────────────────────────────────────
class EncodingWorker(QThread):
    progress_signal = pyqtSignal(int, float, str)  # file_index, percent, speed_text
    file_finished_signal = pyqtSignal(int, str, bool, str)  # file_index, out_path, success, msg
    all_finished_signal = pyqtSignal()
    log_signal = pyqtSignal(str)

    def __init__(self, items_to_encode, common_settings):
        super().__init__()
        self.items = items_to_encode  # list of (index, path, settings, video_info, out_path)
        self.common_settings = common_settings
        self._is_cancelled = False
        self.current_process = None

    def cancel(self):
        self._is_cancelled = True
        if self.current_process:
            try:
                self.current_process.terminate()
            except Exception:
                pass

    def run(self):
        for idx, in_path, item_settings, v_info, out_path in self.items:
            if self._is_cancelled:
                break

            cmd, encoder_used = build_ffmpeg_command(
                in_path, out_path, item_settings, v_info
            )

            total_duration = v_info.get("duration", 0)
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            try:
                self.current_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE,
                    universal_newlines=True,
                    encoding='utf-8',
                    errors='ignore',
                    startupinfo=startupinfo,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )

                last_time = 0.0
                speed_str = ""

                while True:
                    if self._is_cancelled:
                        self.current_process.terminate()
                        break

                    line = self.current_process.stderr.readline()
                    if not line and self.current_process.poll() is not None:
                        break

                    line_str = line.strip()
                    if "out_time_us=" in line_str:
                        try:
                            us = int(line_str.split("=")[1])
                            cur_secs = us / 1000000.0
                            if total_duration > 0:
                                pct = min(99.0, (cur_secs / total_duration) * 100.0)
                                self.progress_signal.emit(idx, pct, speed_str)
                        except Exception:
                            pass
                    elif "speed=" in line_str:
                        try:
                            speed_str = line_str.split("=")[1].strip()
                        except Exception:
                            pass

                ret = self.current_process.wait()
                if self._is_cancelled:
                    if os.path.exists(out_path):
                        try: os.remove(out_path)
                        except Exception: pass
                    self.file_finished_signal.emit(idx, out_path, False, "ユーザーにより中止されました")
                elif ret == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                    self.progress_signal.emit(idx, 100.0, "")
                    self.file_finished_signal.emit(idx, out_path, True, "完了")
                else:
                    self.file_finished_signal.emit(idx, out_path, False, f"エラーコード: {ret}")

            except Exception as e:
                self.file_finished_signal.emit(idx, out_path, False, str(e))

        self.all_finished_signal.emit()


# ─────────────────────────────────────────────
# カスタムファイルアイテム行ウィジェット
# ─────────────────────────────────────────────
class FileItemWidget(QWidget):
    def __init__(self, filepath: str, video_info: dict, parent=None):
        super().__init__(parent)
        self.filepath = filepath
        self.video_info = video_info

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        # アイコン
        self.icon_lbl = QLabel(self)
        self.icon_lbl.setPixmap(create_video_icon_pixmap(28))
        layout.addWidget(self.icon_lbl)

        # テキスト情報
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(2)

        fname = Path(filepath).name
        if len(fname) > 28:
            fname = fname[:25] + "..."
        self.name_lbl = QLabel(fname, self)
        self.name_lbl.setStyleSheet("font-weight: bold; color: #f1f5f9; font-size: 12px;")
        info_layout.addWidget(self.name_lbl)

        sz_str = format_filesize(video_info.get("filesize", 0))
        self.status_lbl = QLabel(sz_str, self)
        self.status_lbl.setStyleSheet("color: #94a3b8; font-size: 11px;")
        info_layout.addWidget(self.status_lbl)

        layout.addLayout(info_layout)
        layout.addStretch()

        self.badge = InfoBadge.info("待機中", self)
        self.badge.setVisible(False)
        layout.addWidget(self.badge)

    def set_status(self, text: str, badge_type="info"):
        sz_str = format_filesize(self.video_info.get("filesize", 0))
        self.status_lbl.setText(f"{sz_str} | {text}")
        if "完了" in text:
            self.status_lbl.setStyleSheet("color: #10b981; font-size: 11px; font-weight: bold;")
        elif "エラー" in text or "失敗" in text:
            self.status_lbl.setStyleSheet("color: #ef4444; font-size: 11px; font-weight: bold;")
        elif "変換中" in text:
            self.status_lbl.setStyleSheet("color: #52b6ff; font-size: 11px; font-weight: bold;")


# ─────────────────────────────────────────────
# メインアプリケーションウィンドウ (PyQt6 + Fluent)
# ─────────────────────────────────────────────
class QuickCompressorQtApp(QWidget):
    def __init__(self, initial_files=None):
        super().__init__()
        self.preset_mgr = PresetManager()
        self.gpu_monitor = GpuEngineMonitor()
        
        self.input_paths = []
        self.video_info_map = {}
        self.is_converting = False
        self.worker = None

        self._init_ui()
        self._setup_gpu_timer()

        if initial_files:
            self.add_files(initial_files)

    def _init_ui(self):
        self.setWindowTitle(f"Quick Compressor v{CURRENT_VERSION}")
        self.setMinimumSize(920, 620)
        self.resize(920, 620)
        self.setStyleSheet("""
            QWidget {
                background-color: #151821;
                color: #e2e8f0;
                font-family: 'Yu Gothic UI', 'Segoe UI', sans-serif;
            }
            QListWidget {
                background-color: #1a1d26;
                border: 1px solid #2d3345;
                border-radius: 8px;
                outline: none;
            }
            QListWidget::item {
                border-radius: 6px;
                margin-bottom: 4px;
            }
            QListWidget::item:selected {
                background-color: #2d3446;
                border: 1px solid #52b6ff;
            }
        """)

        # メインレイアウト
        main_vbox = QVBoxLayout(self)
        main_vbox.setContentsMargins(18, 16, 18, 16)
        main_vbox.setSpacing(12)

        # ── 1. タイトル ＆ ヘッダーバー ──
        header_hbox = QHBoxLayout()
        
        title_lbl = QLabel(f"Quick Compressor  v{CURRENT_VERSION}", self)
        title_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #52b6ff;")
        header_hbox.addWidget(title_lbl)
        header_hbox.addStretch()

        self.pin_btn = PushButton("最前面固定", self)
        self.pin_btn.setCheckable(True)
        self.pin_btn.clicked.connect(self._toggle_topmost)
        self.pin_btn.setFixedSize(110, 30)
        header_hbox.addWidget(self.pin_btn)
        main_vbox.addLayout(header_hbox)

        # ── 2. 上段左右 2 カラム ──
        top_hbox = QHBoxLayout()
        top_hbox.setSpacing(12)

        # ［左カラム］対象動画リスト (幅 350px)
        left_card = CardWidget(self)
        left_card.setFixedWidth(350)
        left_card.setStyleSheet("background-color: #212532; border: 1px solid #2d3345; border-radius: 12px;")
        left_vbox = QVBoxLayout(left_card)
        left_vbox.setContentsMargins(12, 10, 12, 10)
        left_vbox.setSpacing(8)

        # リストヘッダー
        lh_box = QHBoxLayout()
        lh_lbl = QLabel("対象動画:", self)
        lh_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #ffffff; border: none;")
        lh_box.addWidget(lh_lbl)
        lh_box.addStretch()

        self.btn_select = PushButton("ファイル選択", self)
        self.btn_select.setFixedHeight(28)
        self.btn_select.clicked.connect(self._on_select_files)
        lh_box.addWidget(self.btn_select)

        self.btn_clear = PushButton("クリア", self)
        self.btn_clear.setFixedHeight(28)
        self.btn_clear.clicked.connect(self._on_clear_files)
        lh_box.addWidget(self.btn_clear)
        left_vbox.addLayout(lh_box)

        # リストウィジェット（ドラッグ＆ドロップ対応）
        self.file_list = QListWidget(self)
        self.file_list.setAcceptDrops(True)
        self.setAcceptDrops(True)
        left_vbox.addWidget(self.file_list)

        self.file_count_lbl = QLabel("対象動画: 0 件", self)
        self.file_count_lbl.setStyleSheet("font-size: 12px; color: #94a3b8; border: none;")
        left_vbox.addWidget(self.file_count_lbl)
        top_hbox.addWidget(left_card)

        # ［右カラム］プリセット ＆ 3連カードボタン ＆ 詳細設定
        right_vbox = QVBoxLayout()
        right_vbox.setSpacing(10)

        # モードカード
        mode_card = CardWidget(self)
        mode_card.setStyleSheet("background-color: #212532; border: 1px solid #2d3345; border-radius: 12px;")
        mode_vbox = QVBoxLayout(mode_card)
        mode_vbox.setContentsMargins(14, 12, 14, 12)
        mode_vbox.setSpacing(10)

        # プリセット選択コンボ
        p_box = QHBoxLayout()
        p_lbl = QLabel("プリセット選択:", self)
        p_lbl.setStyleSheet("font-size: 12px; font-weight: bold; color: #ffffff; border: none;")
        p_box.addWidget(p_lbl)

        self.preset_combo = ComboBox(self)
        self.preset_combo.setFixedHeight(30)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        p_box.addWidget(self.preset_combo, 1)
        mode_vbox.addLayout(p_box)

        # 3連モード選択カードボタン (CQ / % / MB)
        self.mode_btn_row = QHBoxLayout()
        self.mode_btn_row.setSpacing(8)

        self.btn_mode_cq = PushButton("品質優先 (CQ)", self)
        self.btn_mode_pct = PushButton("割合指定 (%)", self)
        self.btn_mode_size = PushButton("容量優先 (MB)", self)

        for btn, m_val in [(self.btn_mode_cq, "cq"), (self.btn_mode_pct, "percent"), (self.btn_mode_size, "size")]:
            btn.setFixedHeight(36)
            btn.clicked.connect(lambda checked, val=m_val: self._select_mode(val))
            self.mode_btn_row.addWidget(btn)

        mode_vbox.addLayout(self.mode_btn_row)

        # モードごとの設定エリア
        # --- CQ ---
        self.cq_widget = QWidget(self)
        cq_w_vbox = QVBoxLayout(self.cq_widget)
        cq_w_vbox.setContentsMargins(0, 0, 0, 0)
        cq_w_vbox.setSpacing(4)

        cq_top = QHBoxLayout()
        cq_lbl = QLabel("品質レベル:", self)
        cq_lbl.setStyleSheet("font-size: 12px; font-weight: bold; color: #94a3b8; border: none;")
        cq_top.addWidget(cq_lbl)
        cq_top.addStretch()

        self.cq_badge = QLabel("CQ 25 (高画質)", self)
        self.cq_badge.setStyleSheet("background-color: #10b981; color: #ffffff; font-size: 11px; font-weight: bold; padding: 2px 8px; border-radius: 6px;")
        cq_top.addWidget(self.cq_badge)
        cq_w_vbox.addLayout(cq_top)

        self.cq_slider = Slider(Qt.Orientation.Horizontal, self)
        self.cq_slider.setRange(15, 40)
        self.cq_slider.setValue(25)
        self.cq_slider.valueChanged.connect(self._on_cq_slider_changed)
        cq_w_vbox.addWidget(self.cq_slider)

        cq_desc = QLabel("※ CQ/QVBR値が低いほど高画質・大ファイル、高いほど低画質・小ファイルになります", self)
        cq_desc.setStyleSheet("font-size: 10px; color: #94a3b8; border: none;")
        cq_w_vbox.addWidget(cq_desc)
        mode_vbox.addWidget(self.cq_widget)

        # --- 割合 (%) ---
        self.pct_widget = QWidget(self)
        pct_w_vbox = QVBoxLayout(self.pct_widget)
        pct_w_vbox.setContentsMargins(0, 0, 0, 0)
        pct_w_vbox.setSpacing(4)

        pct_top = QHBoxLayout()
        pct_lbl = QLabel("目標割合:", self)
        pct_lbl.setStyleSheet("font-size: 12px; font-weight: bold; color: #94a3b8; border: none;")
        pct_top.addWidget(pct_lbl)
        pct_top.addStretch()

        self.pct_badge = QLabel("50%", self)
        self.pct_badge.setStyleSheet("background-color: #52b6ff; color: #000000; font-size: 11px; font-weight: bold; padding: 2px 8px; border-radius: 6px;")
        pct_top.addWidget(self.pct_badge)
        pct_w_vbox.addLayout(pct_top)

        self.pct_slider = Slider(Qt.Orientation.Horizontal, self)
        self.pct_slider.setRange(10, 90)
        self.pct_slider.setValue(50)
        self.pct_slider.valueChanged.connect(lambda v: self.pct_badge.setText(f"{v}%"))
        pct_w_vbox.addWidget(self.pct_slider)
        mode_vbox.addWidget(self.pct_widget)
        self.pct_widget.setVisible(False)

        # --- 容量 (MB) ---
        self.size_widget = QWidget(self)
        size_w_vbox = QVBoxLayout(self.size_widget)
        size_w_vbox.setContentsMargins(0, 0, 0, 0)
        size_w_vbox.setSpacing(6)

        s_box = QHBoxLayout()
        s_lbl = QLabel("目標サイズ:", self)
        s_lbl.setStyleSheet("font-size: 12px; font-weight: bold; color: #94a3b8; border: none;")
        s_box.addWidget(s_lbl)

        self.size_combo = ComboBox(self)
        self.size_combo.addItems(["10 MB", "25 MB", "50 MB", "100 MB", "500 MB"])
        self.size_combo.setCurrentText("25 MB")
        self.size_combo.setFixedHeight(28)
        s_box.addWidget(self.size_combo, 1)
        size_w_vbox.addLayout(s_box)
        mode_vbox.addWidget(self.size_widget)
        self.size_widget.setVisible(False)

        right_vbox.addWidget(mode_card)

        # 詳細設定カード
        settings_card = CardWidget(self)
        settings_card.setStyleSheet("background-color: #212532; border: 1px solid #2d3345; border-radius: 12px;")
        settings_vbox = QVBoxLayout(settings_card)
        settings_vbox.setContentsMargins(14, 10, 14, 10)
        settings_vbox.setSpacing(8)

        st_title = QLabel("詳細設定", self)
        st_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #ffffff; border: none;")
        settings_vbox.addWidget(st_title)

        # コーデック
        codec_box = QHBoxLayout()
        c_lbl = QLabel("出力コーデック:", self)
        c_lbl.setStyleSheet("font-size: 11px; color: #e2e8f0; border: none;")
        codec_box.addWidget(c_lbl)

        self.codec_combo = ComboBox(self)
        self.codec_combo.addItems(list(CODECS.keys()))
        self.codec_combo.setFixedHeight(28)
        codec_box.addWidget(self.codec_combo, 1)
        settings_vbox.addLayout(codec_box)

        # 解像度 SegmentedWidget
        res_box = QHBoxLayout()
        r_lbl = QLabel("解像度変換:", self)
        r_lbl.setStyleSheet("font-size: 11px; color: #e2e8f0; border: none;")
        res_box.addWidget(r_lbl)

        self.res_seg = SegmentedWidget(self)
        for r in RESOLUTIONS:
            self.res_seg.addItem(r, r)
        self.res_seg.setCurrentItem("元のまま")
        res_box.addWidget(self.res_seg, 1)
        settings_vbox.addLayout(res_box)

        # FPS SegmentedWidget
        fps_box = QHBoxLayout()
        f_lbl = QLabel("フレームレート:", self)
        f_lbl.setStyleSheet("font-size: 11px; color: #e2e8f0; border: none;")
        fps_box.addWidget(f_lbl)

        self.fps_seg = SegmentedWidget(self)
        for f in FRAME_RATES:
            self.fps_seg.addItem(f, f)
        self.fps_seg.setCurrentItem("元のまま")
        fps_box.addWidget(self.fps_seg, 1)
        settings_vbox.addLayout(fps_box)

        # チェックボックス
        chk_box = QHBoxLayout()
        chk_box.setSpacing(14)
        self.chk_audio = CheckBox("音声あり", self)
        self.chk_audio.setChecked(True)
        self.chk_audio.setStyleSheet("font-size: 10px;")
        chk_box.addWidget(self.chk_audio)

        self.chk_auto_delete = CheckBox("元ファイルを自動でゴミ箱へ移動 ⓘ", self)
        self.chk_auto_delete.setStyleSheet("font-size: 10px; color: #94a3b8;")
        chk_box.addWidget(self.chk_auto_delete)
        chk_box.addStretch()
        settings_vbox.addLayout(chk_box)

        right_vbox.addWidget(settings_card)
        top_hbox.addLayout(right_vbox, 1)
        main_vbox.addLayout(top_hbox, 1)

        # ── 3. 進行状況 ＆ GPU 計器 ──
        prog_card = CardWidget(self)
        prog_card.setStyleSheet("background-color: #212532; border: 1px solid #2d3345; border-radius: 12px;")
        prog_hbox = QHBoxLayout(prog_card)
        prog_hbox.setContentsMargins(14, 10, 14, 10)
        prog_hbox.setSpacing(16)

        # 左側プログレスバー
        prog_left = QVBoxLayout()
        prog_left.setSpacing(4)

        p_title = QLabel("プログレスバー:", self)
        p_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #ffffff; border: none;")
        prog_left.addWidget(p_title)

        self.progress_bar = ProgressBar(self)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setValue(0)
        prog_left.addWidget(self.progress_bar)

        st_sub = QHBoxLayout()
        self.status_lbl = QLabel("準備完了", self)
        self.status_lbl.setStyleSheet("font-size: 11px; color: #94a3b8; border: none;")
        st_sub.addWidget(self.status_lbl)
        st_sub.addStretch()

        self.pct_lbl = QLabel("0%", self)
        self.pct_lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #ffffff; border: none;")
        st_sub.addWidget(self.pct_lbl)
        prog_left.addLayout(st_sub)
        prog_hbox.addLayout(prog_left, 1)

        # 右側 GPU 円形メーター (3D / Encode)
        gpu_hbox = QHBoxLayout()
        gpu_hbox.setSpacing(14)

        # 3D
        g3d_box = QHBoxLayout()
        g3d_lbl = QLabel("3D", self)
        g3d_lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #94a3b8; border: none;")
        g3d_box.addWidget(g3d_lbl)
        self.ring_3d = ProgressRing(self)
        self.ring_3d.setFixedSize(44, 44)
        self.ring_3d.setValue(0)
        self.ring_3d.setTextVisible(False)
        g3d_box.addWidget(self.ring_3d)
        gpu_hbox.addLayout(g3d_box)

        # Encode
        genc_box = QHBoxLayout()
        genc_lbl = QLabel("Encode", self)
        genc_lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #94a3b8; border: none;")
        genc_box.addWidget(genc_lbl)
        self.ring_enc = ProgressRing(self)
        self.ring_enc.setFixedSize(44, 44)
        self.ring_enc.setValue(0)
        self.ring_enc.setTextVisible(False)
        genc_box.addWidget(self.ring_enc)
        gpu_hbox.addLayout(genc_box)

        prog_hbox.addLayout(gpu_hbox)
        main_vbox.addWidget(prog_card)

        # ── 4. ボトムアクションバー ──
        bot_hbox = QHBoxLayout()
        bot_hbox.setSpacing(8)

        self.btn_settings = PushButton("設定", self)
        self.btn_settings.setFixedHeight(36)
        self.btn_settings.clicked.connect(self._open_settings)
        bot_hbox.addWidget(self.btn_settings)

        self.btn_preset_mgr = PushButton("プリセット管理", self)
        self.btn_preset_mgr.setFixedHeight(36)
        self.btn_preset_mgr.clicked.connect(self._open_preset_manager)
        bot_hbox.addWidget(self.btn_preset_mgr)

        bot_hbox.addStretch()

        self.btn_open_folder = PushButton("フォルダを開く", self)
        self.btn_open_folder.setFixedHeight(36)
        self.btn_open_folder.setVisible(False)
        self.btn_open_folder.clicked.connect(self._on_open_folder)
        bot_hbox.addWidget(self.btn_open_folder)

        self.btn_cancel = PushButton("中止", self)
        self.btn_cancel.setFixedHeight(36)
        self.btn_cancel.setStyleSheet("background-color: #ef4444; color: #ffffff; font-weight: bold;")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._on_cancel)
        bot_hbox.addWidget(self.btn_cancel)

        self.btn_start = PrimaryPushButton("圧縮開始", self)
        self.btn_start.setFixedHeight(38)
        self.btn_start.setFixedWidth(140)
        self.btn_start.setStyleSheet("background-color: #52b6ff; color: #000000; font-size: 13px; font-weight: bold; border-radius: 8px;")
        self.btn_start.clicked.connect(self._on_start_compression)
        bot_hbox.addWidget(self.btn_start)

        main_vbox.addLayout(bot_hbox)

        # 初期モード選択
        self.current_mode = "cq"
        self._select_mode("cq")
        self._refresh_preset_combo()
        self._update_ui_state()

    # ─────────────────────────────────────────
    # モード選択 ＆ スタイル制御
    # ─────────────────────────────────────────
    def _select_mode(self, mode: str):
        self.current_mode = mode
        buttons = [
            (self.btn_mode_cq, "cq"),
            (self.btn_mode_pct, "percent"),
            (self.btn_mode_size, "size"),
        ]
        for btn, m_val in buttons:
            if m_val == mode:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #1e2c38;
                        border: 1.5px solid #52b6ff;
                        color: #52b6ff;
                        font-weight: bold;
                        border-radius: 6px;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #1a1d26;
                        border: 1px solid #2d3345;
                        color: #94a3b8;
                        border-radius: 6px;
                    }
                    QPushButton:hover {
                        background-color: #2c3242;
                        color: #ffffff;
                    }
                """)

        self.cq_widget.setVisible(mode == "cq")
        self.pct_widget.setVisible(mode == "percent")
        self.size_widget.setVisible(mode == "size")

    def _on_cq_slider_changed(self, val: int):
        if val <= 20: desc = "最高画質"
        elif val <= 25: desc = "高画質"
        elif val <= 30: desc = "標準"
        elif val <= 35: desc = "低画質"
        else: desc = "最低画質"
        self.cq_badge.setText(f"CQ {val} ({desc})")

    # ─────────────────────────────────────────
    # ファイル管理 ＆ リスト操作
    # ─────────────────────────────────────────
    def add_files(self, filepaths: list):
        for path in filepaths:
            if path and os.path.exists(path) and path not in self.input_paths:
                v_info = get_video_info(path)
                if "error" not in v_info:
                    self.input_paths.append(path)
                    self.video_info_map[path] = v_info
                    
                    item = QListWidgetItem(self.file_list)
                    widget = FileItemWidget(path, v_info)
                    item.setSizeHint(widget.sizeHint())
                    self.file_list.addItem(item)
                    self.file_list.setItemWidget(item, widget)

        self.file_count_lbl.setText(f"対象動画: {len(self.input_paths)} 件")
        self._update_ui_state()

    def _on_select_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "変換する動画ファイルを選択", "",
            "動画ファイル (*.mp4 *.mkv *.mov *.avi *.webm *.wmv *.flv *.ts *.m2ts);;すべてのファイル (*.*)"
        )
        if paths:
            self.add_files(paths)

    def _on_clear_files(self):
        self.input_paths.clear()
        self.video_info_map.clear()
        self.file_list.clear()
        self.file_count_lbl.setText("対象動画: 0 件")
        self._update_ui_state()

    # ドラッグ＆ドロップイベント
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        paths = [u.toLocalFile() for u in urls if u.isLocalFile()]
        if paths:
            self.add_files(paths)

    # ─────────────────────────────────────────
    # プリセット連携
    # ─────────────────────────────────────────
    def _refresh_preset_combo(self):
        self.preset_combo.clear()
        self.preset_combo.addItem("選択してください...")
        all_presets = self.preset_mgr.get_all_presets()
        for p in sorted(all_presets.values(), key=lambda x: x.get("name", "")):
            self.preset_combo.addItem(p.get("name", ""))

    def _on_preset_selected(self, index: int):
        name = self.preset_combo.currentText()
        if name == "選択してください..." or not name:
            return
        all_presets = self.preset_mgr.get_all_presets()
        for p in all_presets.values():
            if p.get("name") == name:
                if "codec" in p: self.codec_combo.setCurrentText(p["codec"])
                if "resolution" in p: self.res_seg.setCurrentItem(p["resolution"])
                if "fps" in p: self.fps_seg.setCurrentItem(p["fps"])
                if "cq" in p:
                    self._select_mode("cq")
                    self.cq_slider.setValue(p["cq"])
                elif "target_percent" in p:
                    self._select_mode("percent")
                    self.pct_slider.setValue(int(p["target_percent"]))
                elif "target_size_mb" in p:
                    self._select_mode("size")
                    self.size_combo.setCurrentText(f"{int(p['target_size_mb'])} MB")
                break

    # ─────────────────────────────────────────
    # GPU メーター更新タイマー
    # ─────────────────────────────────────────
    def _setup_gpu_timer(self):
        self.gpu_timer = QTimer(self)
        self.gpu_timer.setInterval(250)
        self.gpu_timer.timeout.connect(self._update_gpu_meters)
        self.gpu_timer.start()

    def _update_gpu_meters(self):
        u_3d, u_enc = self.gpu_monitor.get_utilization()
        self.ring_3d.setValue(int(u_3d))
        self.ring_enc.setValue(int(u_enc))

    # ─────────────────────────────────────────
    # 圧縮開始 ＆ ワーカー制御
    # ─────────────────────────────────────────
    def _capture_current_settings(self) -> dict:
        res_item = self.res_seg.currentItem()
        res_val = res_item.routeKey() if (res_item and hasattr(res_item, 'routeKey')) else (res_item.text() if res_item else "元のまま")

        fps_item = self.fps_seg.currentItem()
        fps_val = fps_item.routeKey() if (fps_item and hasattr(fps_item, 'routeKey')) else (fps_item.text() if fps_item else "元のまま")

        settings = {
            "mode": self.current_mode,
            "codec": self.codec_combo.currentText(),
            "resolution": res_val,
            "fps": fps_val,
            "audio_enabled": self.chk_audio.isChecked(),
            "keep_metadata": True,
            "cq": self.cq_slider.value()
        }
        if self.current_mode == "percent":
            settings["target_percent"] = float(self.pct_slider.value())
        elif self.current_mode == "size":
            try:
                settings["target_size_mb"] = float(self.size_combo.currentText().replace("MB", "").strip())
            except ValueError:
                settings["target_size_mb"] = 25.0
        return settings

    def _on_start_compression(self):
        if not self.input_paths or self.is_converting:
            return

        self.is_converting = True
        self.btn_start.setEnabled(False)
        self.btn_start.setText("変換中...")
        self.btn_cancel.setVisible(True)
        self.btn_open_folder.setVisible(False)

        items_to_encode = []
        settings = self._capture_current_settings()

        for idx, in_path in enumerate(self.input_paths):
            p = Path(in_path)
            ext = "mp4"
            out_path = str(p.parent / f"{p.stem}_converted.{ext}")
            c = 1
            while os.path.exists(out_path):
                out_path = str(p.parent / f"{p.stem}_converted_{c}.{ext}")
                c += 1
            v_info = self.video_info_map.get(in_path, {})
            items_to_encode.append((idx, in_path, settings, v_info, out_path))

        self.worker = EncodingWorker(items_to_encode, settings)
        self.worker.progress_signal.connect(self._on_worker_progress)
        self.worker.file_finished_signal.connect(self._on_worker_file_finished)
        self.worker.all_finished_signal.connect(self._on_worker_all_finished)
        self.worker.start()

    def _on_worker_progress(self, idx: int, pct: float, speed: str):
        total_files = len(self.input_paths)
        overall_pct = int(((idx + (pct / 100.0)) / total_files) * 100.0)
        self.progress_bar.setValue(overall_pct)
        self.pct_lbl.setText(f"{overall_pct}%")
        self.status_lbl.setText(f"変換中 ({idx + 1}/{total_files}) {pct:.0f}% {speed}")

        widget = self.file_list.itemWidget(self.file_list.item(idx))
        if widget:
            widget.set_status(f"変換中 {pct:.0f}%")

    def _on_worker_file_finished(self, idx: int, out_path: str, success: bool, msg: str):
        widget = self.file_list.itemWidget(self.file_list.item(idx))
        if widget:
            widget.set_status("完了" if success else f"失敗 ({msg})")
        self.last_output_path = out_path

    def _on_worker_all_finished(self):
        self.is_converting = False
        self.progress_bar.setValue(100)
        self.pct_lbl.setText("100%")
        self.status_lbl.setText("全ファイルの変換が完了しました")
        self.btn_start.setEnabled(True)
        self.btn_start.setText("圧縮開始")
        self.btn_cancel.setVisible(False)
        self.btn_open_folder.setVisible(True)

        try:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass

    def _on_cancel(self):
        if self.worker and self.is_converting:
            self.worker.cancel()
            self.status_lbl.setText("中止しました")

    def _on_open_folder(self):
        if hasattr(self, 'last_output_path') and os.path.exists(self.last_output_path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(self.last_output_path)], creationflags=subprocess.CREATE_NO_WINDOW)

    def _toggle_topmost(self):
        is_on = self.pin_btn.isChecked()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, is_on)
        self.show()

    def _open_settings(self):
        dlg = SettingsDialog(self)
        dlg.exec()

    def _open_preset_manager(self):
        dlg = PresetManagerDialog(self)
        dlg.exec()
        self._refresh_preset_combo()

    def _update_ui_state(self):
        has_files = len(self.input_paths) > 0
        self.btn_start.setEnabled(has_files and not self.is_converting)


# ─────────────────────────────────────────────
# エントリポイント
# ─────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    setTheme(Theme.DARK)

    # DPI設定
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    window = QuickCompressorQtApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
