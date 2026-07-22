@echo off
chcp 65001 >nul
echo =======================================
echo Quick Compressor ビルドスクリプト
echo =======================================

python -m PyInstaller --version >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [エラー] PyInstallerが見つかりません。
    echo pip install pyinstaller を実行してインストールしてください。
    pause
    exit /b
)

echo.
echo [1] PyInstallerによる実行ファイルの作成を開始します...
python -m PyInstaller --noconsole --onefile --name "QuickCompressor" main.py

echo.
echo [2] 配布用フォルダの準備...
if not exist "dist\bin" mkdir "dist\bin"
copy default_presets.json "dist\"
xcopy "りぃポップ角riipopkr" "dist\りぃポップ角riipopkr\" /E /I /Y

echo.
echo [3] FFmpeg バイナリの確認...
if not exist "dist\bin\ffmpeg.exe" (
    echo [警告] dist\bin\ffmpeg.exe が見つかりません。インストーラーにFFmpegが含まれません。
) else (
    echo OK: dist\bin\ffmpeg.exe
)

echo.
echo [4] Inno Setup によるインストーラーの作成...
set ISCC=
where ISCC.exe >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set ISCC=ISCC.exe
) else if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" (
    set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
) else if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
    set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
) else if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" (
    set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
)

if exist %ISCC% (
    %ISCC% build_installer.iss
    echo.
    echo =======================================
    echo ビルド大成功！ Output\QuickCompressor_Setup.exe が作成されました。
    echo =======================================
    echo Outputフォルダを開きます...
    explorer Output
) else (
    echo [エラー] Inno Setup ^(ISCC.exe^) が見つかりません。
    echo インストーラーの作成をスキップしました。手動で build_installer.iss をコンパイルしてください。
    echo =======================================
)
pause
