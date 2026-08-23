# -*- coding: utf-8 -*-
"""
Quick Compressor - PyQt6 Fluent Design ダイアログ群
設定ダイアログ、プリセット管理ダイアログ
"""

import os
import json
import uuid
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QWidget,
    QListWidget, QListWidgetItem, QMessageBox
)

from qfluentwidgets import (
    PushButton, PrimaryPushButton, LineEdit, ComboBox,
    Slider, CheckBox, CardWidget, SubtitleLabel, BodyLabel,
    SegmentedWidget, InfoBar, InfoBarPosition
)

from core.encoder import CODECS, FRAME_RATES, RESOLUTIONS, detect_gpu_and_default_codec
from core.preset_manager import PresetManager, get_default_presets
import register_menu


class SettingsDialog(QDialog):
    """設定ダイアログ (Fluent Design)"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.preset_mgr = PresetManager()
        self.setWindowTitle("設定")
        self.setMinimumWidth(480)
        self.setStyleSheet("""
            QDialog {
                background-color: #151821;
                color: #e2e8f0;
            }
            QLabel {
                color: #e2e8f0;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # タイトル
        title = SubtitleLabel("アプリケーション設定", self)
        title.setStyleSheet("color: #ffffff; font-weight: bold;")
        layout.addWidget(title)

        # カード: 右クリックメニュー登録
        menu_card = CardWidget(self)
        menu_card.setStyleSheet("background-color: #212532; border: 1px solid #2d3345; border-radius: 8px;")
        m_vbox = QVBoxLayout(menu_card)
        m_vbox.setContentsMargins(14, 12, 14, 12)
        m_vbox.setSpacing(8)

        m_title = QLabel("Windows 右クリックメニュー連携:", self)
        m_title.setStyleSheet("font-weight: bold; color: #ffffff;")
        m_vbox.addWidget(m_title)

        m_btn_box = QHBoxLayout()
        self.btn_reg_menu = PushButton("右クリックメニューに登録", self)
        self.btn_reg_menu.clicked.connect(self._register_menu)
        m_btn_box.addWidget(self.btn_reg_menu)

        self.btn_unreg_menu = PushButton("登録解除", self)
        self.btn_unreg_menu.clicked.connect(self._unregister_menu)
        m_btn_box.addWidget(self.btn_unreg_menu)
        m_vbox.addLayout(m_btn_box)
        layout.addWidget(menu_card)

        # カード: デフォルトコーデック
        codec_card = CardWidget(self)
        codec_card.setStyleSheet("background-color: #212532; border: 1px solid #2d3345; border-radius: 8px;")
        c_vbox = QVBoxLayout(codec_card)
        c_vbox.setContentsMargins(14, 12, 14, 12)
        c_vbox.setSpacing(8)

        c_title = QLabel("優先コーデック系統:", self)
        c_title.setStyleSheet("font-weight: bold; color: #ffffff;")
        c_vbox.addWidget(c_title)

        self.codec_combo = ComboBox(self)
        self.codec_combo.addItems(["HEVC / H.265 (自動判定)", "H.264 (互換性優先)", "AV1 (高圧縮率)"])
        c_vbox.addWidget(self.codec_combo)
        layout.addWidget(codec_card)

        layout.addStretch()

        # フッターボタン
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_close = PrimaryPushButton("閉じる", self)
        btn_close.clicked.connect(self.accept)
        btn_box.addWidget(btn_close)
        layout.addLayout(btn_box)

    def _register_menu(self):
        try:
            register_menu.register_context_menu()
            InfoBar.success(
                title="成功", content="Windows 右クリックメニューに登録しました。",
                parent=self, position=InfoBarPosition.TOP
            )
        except Exception as e:
            InfoBar.error(
                title="エラー", content=f"登録に失敗しました: {e}",
                parent=self, position=InfoBarPosition.TOP
            )

    def _unregister_menu(self):
        try:
            register_menu.unregister_context_menu()
            InfoBar.success(
                title="成功", content="右クリックメニューから解除しました。",
                parent=self, position=InfoBarPosition.TOP
            )
        except Exception as e:
            InfoBar.error(
                title="エラー", content=f"解除に失敗しました: {e}",
                parent=self, position=InfoBarPosition.TOP
            )


class PresetManagerDialog(QDialog):
    """プリセット管理ダイアログ (Fluent Design)"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.preset_mgr = PresetManager()
        self.setWindowTitle("設定プリセット管理")
        self.setMinimumSize(600, 420)
        self.setStyleSheet("""
            QDialog {
                background-color: #151821;
                color: #e2e8f0;
            }
            QListWidget {
                background-color: #1a1d26;
                border: 1px solid #2d3345;
                border-radius: 8px;
            }
            QListWidget::item {
                padding: 6px;
                border-radius: 4px;
            }
            QListWidget::item:selected {
                background-color: #2d3446;
                border: 1px solid #52b6ff;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        title = SubtitleLabel("プリセット一覧", self)
        title.setStyleSheet("color: #ffffff; font-weight: bold;")
        layout.addWidget(title)

        # プリセット一覧リスト
        self.preset_list = QListWidget(self)
        layout.addWidget(self.preset_list, 1)

        # アクションボタン群
        btn_box = QHBoxLayout()
        self.btn_delete = PushButton("選択項目を削除", self)
        self.btn_delete.clicked.connect(self._delete_preset)
        btn_box.addWidget(self.btn_delete)

        btn_box.addStretch()

        btn_close = PrimaryPushButton("閉じる", self)
        btn_close.clicked.connect(self.accept)
        btn_box.addWidget(btn_close)
        layout.addLayout(btn_box)

        self._refresh_list()

    def _refresh_list(self):
        self.preset_list.clear()
        all_presets = self.preset_mgr.get_all_presets()
        for p_id, p in sorted(all_presets.items(), key=lambda x: x[1].get("name", "")):
            is_custom = p.get("is_custom", True)
            prefix = "[カスタム] " if is_custom else "[標準] "
            desc = f"{prefix}{p.get('name', '')} ({p.get('resolution', '元のまま')}, {p.get('codec', '自動')})"
            item = QListWidgetItem(desc)
            item.setData(Qt.ItemDataRole.UserRole, (p_id, is_custom))
            self.preset_list.addItem(item)

    def _delete_preset(self):
        cur_item = self.preset_list.currentItem()
        if not cur_item:
            return
        p_id, is_custom = cur_item.data(Qt.ItemDataRole.UserRole)
        if not is_custom:
            InfoBar.warning(title="注意", content="標準プリセットは削除できません。", parent=self, position=InfoBarPosition.TOP)
            return

        user_presets = self.preset_mgr.get_user_presets()
        if p_id in user_presets:
            del user_presets[p_id]
            self.preset_mgr.save_user_presets(user_presets)
            self._refresh_list()
            InfoBar.success(title="完了", content="プリセットを削除しました。", parent=self, position=InfoBarPosition.TOP)
