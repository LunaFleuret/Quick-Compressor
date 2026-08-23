# -*- coding: utf-8 -*-
"""
Quick Compressor - プリセット＆設定マネージャー
JSON形式でのプリセット保存、デフォルトプリセット、右クリックメニュー連携
"""

import os
import json
import uuid
import register_menu

def get_default_presets():
    return {
        "default_generic_fhd": {
            "name": "汎用 (フルHD高画質)", "codec": "自動 (推奨: 環境に合わせて自動選択)",
            "preset": "p4", "fps": "元のまま", "resolution": "1080p", "cq": 23, "is_custom": False
        },
        "default_generic_hd": {
            "name": "汎用 (HD標準画質)", "codec": "自動 (推奨: 環境に合わせて自動選択)",
            "preset": "p4", "fps": "元のまま", "resolution": "720p", "cq": 28, "is_custom": False
        },
        "default_discord_10mb": {
            "name": "Discord用 (10MB)", "codec": "自動 (推奨: 環境に合わせて自動選択)",
            "preset": "p4", "fps": "元のまま", "resolution": "720p", "target_size_mb": 10.0, "is_custom": False
        },
        "default_discord_50mb": {
            "name": "Discord用 (50MB)", "codec": "自動 (推奨: 環境に合わせて自動選択)",
            "preset": "p4", "fps": "元のまま", "resolution": "1080p", "target_size_mb": 50.0, "is_custom": False
        },
        "default_half_size": {
            "name": "容量半減 (50%)", "codec": "自動 (推奨: 環境に合わせて自動選択)",
            "preset": "p4", "fps": "元のまま", "resolution": "元のまま", "target_percent": 50.0, "is_custom": False
        },
        "default_fps30": {
            "name": "30FPS変換 (標準)", "codec": "自動 (推奨: 環境に合わせて自動選択)",
            "preset": "p4", "fps": "30", "resolution": "元のまま", "cq": 26, "is_custom": False
        },
    }

class PresetManager:
    """プリセットおよびアプリケーション設定の永続化マネージャー"""
    def __init__(self):
        self.data_dir = register_menu.DATA_DIR
        self.presets_path = os.path.join(self.data_dir, "presets.json")
        self.config_path = os.path.join(self.data_dir, "config.json")
        os.makedirs(self.data_dir, exist_ok=True)

    def get_user_presets(self) -> dict:
        if os.path.exists(self.presets_path):
            try:
                with open(self.presets_path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}
        return {}

    def get_all_presets(self) -> dict:
        all_p = {}
        all_p.update(get_default_presets())
        all_p.update(self.get_user_presets())
        return all_p

    def save_user_presets(self, user_presets: dict) -> bool:
        try:
            with open(self.presets_path, "w", encoding="utf-8") as f:
                json.dump(user_presets, f, ensure_ascii=False, indent=4, sort_keys=True)
            try:
                register_menu.register_context_menu()
            except Exception:
                pass
            return True
        except Exception:
            return False

    def load_config(self) -> dict:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8-sig") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_config(self, config: dict) -> bool:
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            return True
        except Exception:
            return False
