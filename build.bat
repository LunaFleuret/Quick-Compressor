@echo off
chcp 65001 >nul
echo =======================================
echo Quick Compressor ビルドスクリプト
echo =======================================

where pyinstaller >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [エラー] PyInstallerが見つかりません。
    echo pip install pyinstaller を実行してインストールしてください。
    pause
    exit /b
)

echo.
echo [1] PyInstallerによる実行ファイルの作成を開始します...
pyinstaller --noconsole --onefile --name "QuickCompressor" main.py

echo.
echo [2] 配布用フォルダの準備...
if not exist "dist\bin" mkdir "dist\bin"
copy default_presets.json "dist\"

echo.
echo =======================================
echo ビルド完了！ (dist\QuickCompressor.exe)
echo.
echo 【次のステップ】
echo 1. FFmpeg公式などからWindows版をダウンロードし、
echo    ffmpeg.exe と ffprobe.exe を dist\bin フォルダに入れてください。
echo 2. Inno Setup で build_installer.iss をコンパイルすると、
echo    配布用の setup.exe が完成します！
echo =======================================
pause
