#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPU Video Converter - レジストリ登録スクリプト
右クリックメニュー（コンテキストメニュー）に「GPU動画変換で圧縮」を追加・削除します。

HKEY_CURRENT_USER\\Software\\Classes を使用するため管理者権限は不要です。
"""

import sys
import os
import winreg
import ctypes
import tkinter as tk
from tkinter import messagebox

# ─────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────
MENU_NAME = "GPU動画変換で圧縮..."
MENU_NAME_PRESET = "GPU動画変換 (プリセット)"
REGISTRY_KEY_NAME = "GPUVideoConverter"
REGISTRY_KEY_NAME_PRESET = "GPUVideoConverterPreset"

# 登録する動画拡張子
VIDEO_EXTENSIONS = [
    ".mp4", ".mkv", ".mov", ".avi", ".webm",
    ".wmv", ".flv", ".ts", ".m2ts", ".m4v",
]

# main.py のパスを自動検出
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_SCRIPT = os.path.join(SCRIPT_DIR, "main.py")

# Python実行ファイルのパス（pythonw.exe を使うとコンソール窓が出ない）
PYTHON_EXE = sys.executable
PYTHONW_EXE = PYTHON_EXE.replace("python.exe", "pythonw.exe")
if not os.path.exists(PYTHONW_EXE):
    PYTHONW_EXE = PYTHON_EXE  # pythonw が見つからない場合は python を使用

# レジストリのルート（HKCU\Software\Classes は管理者権限不要）
REG_ROOT = winreg.HKEY_CURRENT_USER
REG_ROOT_PATH = r"Software\Classes"


def register_context_menu():
    """右クリックメニューに登録（HKCU - 管理者権限不要）"""
    # GUI起動用
    cmd_gui = f'"{PYTHONW_EXE}" "{MAIN_SCRIPT}" "%1"'
    # CQ35最小サイズ用
    cmd_preset1 = f'"{PYTHONW_EXE}" "{MAIN_SCRIPT}" "%1" --auto --fps 24 --scale 100 --preset p7 --audio-mode reencode --cq 35'

    registered = []
    errors = []

    # 先に ExtendedSubCommandsKey の内容 (GPUVideoConverter.Menu) を作成する
    try:
        menu_key_path = rf"{REG_ROOT_PATH}\{REGISTRY_KEY_NAME}.Menu"
        
        # プリセット1: CQ35最小サイズ
        preset1_path = rf"{menu_key_path}\shell\Preset1"
        key_p1 = winreg.CreateKey(REG_ROOT, preset1_path)
        winreg.SetValueEx(key_p1, "MUIVerb", 0, winreg.REG_SZ, "CQ35最小サイズ")
        winreg.CloseKey(key_p1)
        
        cmd_p1 = winreg.CreateKey(REG_ROOT, rf"{preset1_path}\command")
        winreg.SetValueEx(cmd_p1, "", 0, winreg.REG_SZ, cmd_preset1)
        winreg.CloseKey(cmd_p1)
    except Exception as e:
        errors.append(f"Menu Definition: {str(e)}")
        return [], errors

    for ext in VIDEO_EXTENSIONS:
        try:
            # 1. 単独GUIメニューの登録
            key_path = rf"{REG_ROOT_PATH}\SystemFileAssociations\{ext}\shell\{REGISTRY_KEY_NAME}"
            key = winreg.CreateKey(REG_ROOT, key_path)
            winreg.SetValueEx(key, "MUIVerb", 0, winreg.REG_SZ, MENU_NAME)
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, "shell32.dll,176")
            winreg.CloseKey(key)

            cmd_key = winreg.CreateKey(REG_ROOT, rf"{key_path}\command")
            winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, cmd_gui)
            winreg.CloseKey(cmd_key)

            # 2. カスケード(プリセット)メニューの登録
            preset_key_path = rf"{REG_ROOT_PATH}\SystemFileAssociations\{ext}\shell\{REGISTRY_KEY_NAME_PRESET}"
            key_preset = winreg.CreateKey(REG_ROOT, preset_key_path)
            winreg.SetValueEx(key_preset, "MUIVerb", 0, winreg.REG_SZ, MENU_NAME_PRESET)
            winreg.SetValueEx(key_preset, "Icon", 0, winreg.REG_SZ, "shell32.dll,176")
            winreg.SetValueEx(key_preset, "ExtendedSubCommandsKey", 0, winreg.REG_SZ, f"{REGISTRY_KEY_NAME}.Menu")
            winreg.CloseKey(key_preset)

            registered.append(ext)
        except Exception as e:
            errors.append(f"{ext}: {str(e)}")

    # 方法2: 全ファイル対象のフォールバック（*\shell に登録）
    try:
        applies_to = " OR ".join([f'System.FileName:~<"{ext}"' for ext in VIDEO_EXTENSIONS])
        
        # 1. 単独GUIメニュー
        star_key_path = rf"{REG_ROOT_PATH}\*\shell\{REGISTRY_KEY_NAME}"
        key = winreg.CreateKey(REG_ROOT, star_key_path)
        winreg.SetValueEx(key, "MUIVerb", 0, winreg.REG_SZ, MENU_NAME)
        winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, "shell32.dll,176")
        winreg.SetValueEx(key, "AppliesTo", 0, winreg.REG_SZ, applies_to)
        winreg.CloseKey(key)
        cmd_key = winreg.CreateKey(REG_ROOT, rf"{star_key_path}\command")
        winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, cmd_gui)
        winreg.CloseKey(cmd_key)

        # 2. カスケードメニュー
        star_preset_path = rf"{REG_ROOT_PATH}\*\shell\{REGISTRY_KEY_NAME_PRESET}"
        key_preset = winreg.CreateKey(REG_ROOT, star_preset_path)
        winreg.SetValueEx(key_preset, "MUIVerb", 0, winreg.REG_SZ, MENU_NAME_PRESET)
        winreg.SetValueEx(key_preset, "Icon", 0, winreg.REG_SZ, "shell32.dll,176")
        winreg.SetValueEx(key_preset, "ExtendedSubCommandsKey", 0, winreg.REG_SZ, f"{REGISTRY_KEY_NAME}.Menu")
        winreg.SetValueEx(key_preset, "AppliesTo", 0, winreg.REG_SZ, applies_to)
        winreg.CloseKey(key_preset)
    except Exception as e:
        errors.append(f"*: {str(e)}")

    return registered, errors


def unregister_context_menu():
    """右クリックメニューから削除"""
    removed = []
    errors = []

    # メニュー定義キーの削除
    menu_key_path = rf"{REG_ROOT_PATH}\{REGISTRY_KEY_NAME}.Menu"
    try:
        try:
            winreg.DeleteKey(REG_ROOT, rf"{menu_key_path}\shell\Preset1\command")
            winreg.DeleteKey(REG_ROOT, rf"{menu_key_path}\shell\Preset1")
        except FileNotFoundError: pass
        try:
            winreg.DeleteKey(REG_ROOT, rf"{menu_key_path}\shell\GUI\command")
            winreg.DeleteKey(REG_ROOT, rf"{menu_key_path}\shell\GUI")
        except FileNotFoundError: pass
        try:
            winreg.DeleteKey(REG_ROOT, rf"{menu_key_path}\shell")
        except FileNotFoundError: pass
        try:
            winreg.DeleteKey(REG_ROOT, menu_key_path)
        except FileNotFoundError: pass
    except Exception as e:
        pass # 無視

    for ext in VIDEO_EXTENSIONS:
        try:
            # 1. 単独メニューの削除
            key_path = rf"{REG_ROOT_PATH}\SystemFileAssociations\{ext}\shell\{REGISTRY_KEY_NAME}"
            try: winreg.DeleteKey(REG_ROOT, rf"{key_path}\command")
            except FileNotFoundError: pass
            try: winreg.DeleteKey(REG_ROOT, key_path)
            except FileNotFoundError: pass

            # 2. プリセットメニューの削除
            preset_key_path = rf"{REG_ROOT_PATH}\SystemFileAssociations\{ext}\shell\{REGISTRY_KEY_NAME_PRESET}"
            try: winreg.DeleteKey(REG_ROOT, rf"{preset_key_path}\command")
            except FileNotFoundError: pass
            try: winreg.DeleteKey(REG_ROOT, preset_key_path)
            except FileNotFoundError: pass

            removed.append(ext)
        except Exception as e:
            errors.append(f"{ext}: {str(e)}")

    # * キーも削除
    try:
        star_key_path = rf"{REG_ROOT_PATH}\*\shell\{REGISTRY_KEY_NAME}"
        try: winreg.DeleteKey(REG_ROOT, rf"{star_key_path}\command")
        except FileNotFoundError: pass
        try: winreg.DeleteKey(REG_ROOT, star_key_path)
        except FileNotFoundError: pass

        star_preset_path = rf"{REG_ROOT_PATH}\*\shell\{REGISTRY_KEY_NAME_PRESET}"
        try: winreg.DeleteKey(REG_ROOT, rf"{star_preset_path}\command")
        except FileNotFoundError: pass
        try: winreg.DeleteKey(REG_ROOT, star_preset_path)
        except FileNotFoundError: pass

        removed.append("*")
    except Exception as e:
        errors.append(f"*: {str(e)}")

    return removed, errors


def check_registration_status() -> dict:
    """現在の登録状態をチェック"""
    status = {}

    # 拡張子ベース
    for ext in VIDEO_EXTENSIONS:
        key_path = rf"{REG_ROOT_PATH}\SystemFileAssociations\{ext}\shell\{REGISTRY_KEY_NAME}"
        try:
            key = winreg.OpenKey(REG_ROOT, key_path)
            winreg.CloseKey(key)
            status[ext] = True
        except FileNotFoundError:
            status[ext] = False

    # * ベース
    star_key_path = rf"{REG_ROOT_PATH}\*\shell\{REGISTRY_KEY_NAME}"
    try:
        key = winreg.OpenKey(REG_ROOT, star_key_path)
        winreg.CloseKey(key)
        status["* (全ファイル)"] = True
    except FileNotFoundError:
        status["* (全ファイル)"] = False

    return status


# ─────────────────────────────────────────────
# GUI
# ─────────────────────────────────────────────
class RegistrationApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("GPU動画コンバーター - メニュー登録")
        self.root.configure(bg="#f0f2f5")
        self.root.resizable(False, False)

        # DPI対応
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        self._build_ui()

        # ウィンドウを画面中央に配置
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
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

    def _build_ui(self):
        main = tk.Frame(self.root, bg="#f0f2f5", padx=24, pady=20)
        main.pack(fill="both", expand=True)

        # タイトル
        tk.Label(main, text="⚡ GPU動画コンバーター",
                 font=("Segoe UI", 16, "bold"), fg="#005fb8", bg="#f0f2f5"
                 ).pack(anchor="w", pady=(0, 4))

        tk.Label(main, text="右クリックメニューへの登録・解除（管理者権限不要）",
                 font=("Segoe UI", 10), fg="#6c757d", bg="#f0f2f5"
                 ).pack(anchor="w", pady=(0, 16))

        # 情報カード
        info_card = tk.Frame(main, bg="#ffffff", padx=12, pady=10,
                             highlightbackground="#dee2e6", highlightthickness=1)
        info_card.pack(fill="x", pady=(0, 12))

        tk.Label(info_card, text=f"Python: {PYTHONW_EXE}",
                 font=("Segoe UI", 8), fg="#6c757d", bg="#ffffff", anchor="w",
                 wraplength=450).pack(fill="x")
        tk.Label(info_card, text=f"Script: {MAIN_SCRIPT}",
                 font=("Segoe UI", 8), fg="#6c757d", bg="#ffffff", anchor="w",
                 wraplength=450).pack(fill="x")
        tk.Label(info_card, text="登録先: HKEY_CURRENT_USER\\Software\\Classes（管理者権限不要）",
                 font=("Segoe UI", 8), fg="#198754", bg="#ffffff", anchor="w").pack(fill="x", pady=(4, 0))

        # 現在の登録状態
        status = check_registration_status()
        status_card = tk.Frame(main, bg="#ffffff", padx=12, pady=10,
                               highlightbackground="#dee2e6", highlightthickness=1)
        status_card.pack(fill="x", pady=(0, 16))

        tk.Label(status_card, text="登録状態:",
                 font=("Segoe UI", 10, "bold"), fg="#212529", bg="#ffffff"
                 ).pack(anchor="w", pady=(0, 4))

        for ext, is_registered in status.items():
            color = "#198754" if is_registered else "#6c757d"
            symbol = "●" if is_registered else "○"
            tk.Label(status_card, text=f"  {symbol}  {ext}",
                     font=("Segoe UI", 9), fg=color, bg="#ffffff"
                     ).pack(anchor="w")

        # ボタン
        btn_frame = tk.Frame(main, bg="#f0f2f5")
        btn_frame.pack(fill="x", pady=(8, 0))

        register_btn = tk.Button(
            btn_frame, text="✅ 登録する",
            font=("Segoe UI", 12, "bold"), fg="#ffffff",
            bg="#198754", activebackground="#157347",
            relief="flat", padx=24, pady=8, cursor="hand2",
            command=self._register,
        )
        register_btn.pack(side="left", padx=(0, 8))

        unregister_btn = tk.Button(
            btn_frame, text="❌ 解除する",
            font=("Segoe UI", 12, "bold"), fg="#ffffff",
            bg="#dc3545", activebackground="#bb2d3b",
            relief="flat", padx=24, pady=8, cursor="hand2",
            command=self._unregister,
        )
        unregister_btn.pack(side="left")

        # ステータスラベル
        self.status_label = tk.Label(
            main, text="",
            font=("Segoe UI", 9), fg="#6c757d", bg="#f0f2f5",
            wraplength=450, anchor="w"
        )
        self.status_label.pack(fill="x", pady=(12, 0))

    def _register(self):
        registered, errors = register_context_menu()
        if registered:
            msg = f"✅ {len(registered)} 個の拡張子に登録しました: {', '.join(registered)}"
            if errors:
                msg += f"\n⚠️ 一部エラー: {'; '.join(errors)}"
            self.status_label.configure(text=msg, fg="#198754")
        elif errors:
            self.status_label.configure(
                text=f"❌ 登録に失敗しました: {'; '.join(errors)}", fg="#dc3545"
            )

        # UIを更新
        self.root.destroy()
        new_root = tk.Tk()
        RegistrationApp(new_root)
        new_root.mainloop()

    def _unregister(self):
        removed, errors = unregister_context_menu()
        if removed:
            msg = f"✅ {len(removed)} 個の拡張子から解除しました: {', '.join(removed)}"
            self.status_label.configure(text=msg, fg="#198754")
        elif errors:
            self.status_label.configure(
                text=f"❌ 解除に失敗しました: {'; '.join(errors)}", fg="#dc3545"
            )

        # UIを更新
        self.root.destroy()
        new_root = tk.Tk()
        RegistrationApp(new_root)
        new_root.mainloop()


def main():
    # コマンドライン引数で直接登録・解除も可能
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ("--register", "-r"):
            registered, errors = register_context_menu()
            print(f"登録完了: {', '.join(registered)}")
            if errors:
                print(f"エラー: {'; '.join(errors)}")
            return
        elif arg in ("--unregister", "-u"):
            removed, errors = unregister_context_menu()
            print(f"解除完了: {', '.join(removed)}")
            if errors:
                print(f"エラー: {'; '.join(errors)}")
            return
        elif arg in ("--status", "-s"):
            status = check_registration_status()
            for ext, is_registered in status.items():
                symbol = "●" if is_registered else "○"
                print(f"  {symbol}  {ext}")
            return

    root = tk.Tk()
    app = RegistrationApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
