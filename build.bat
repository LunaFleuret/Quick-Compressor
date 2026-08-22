@echo off
setlocal
echo =======================================
echo Quick Compressor Build Script
echo =======================================

where pyinstaller >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [Error] PyInstaller not found.
    echo Please install PyInstaller via pip.
    exit /b 1
)

echo.
echo [1] Building executable with PyInstaller...
python -m PyInstaller --noconsole --onefile --name "QuickCompressor" main.py
if %ERRORLEVEL% neq 0 (
    echo [Error] PyInstaller build failed.
    exit /b 1
)

echo.
echo [2] Preparing distribution folder...
if not exist "dist\bin" mkdir "dist\bin"
copy /Y default_presets.json "dist\" >nul
xcopy "りぃポップ角riipopkr" "dist\りぃポップ角riipopkr\" /E /I /Y >nul

echo.
echo [3] Checking FFmpeg binaries...
if not exist "dist\bin\ffmpeg.exe" (
    echo [Warning] dist\bin\ffmpeg.exe not found. FFmpeg will not be included.
) else (
    echo OK: dist\bin\ffmpeg.exe
)

echo.
echo [4] Creating installer with Inno Setup...
set "ISCC="
where ISCC.exe >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set "ISCC=ISCC.exe"
) else if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" (
    set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
) else if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
    set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
) else if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" (
    set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
)

if not "%ISCC%"=="" (
    "%ISCC%" build_installer.iss
    if %ERRORLEVEL% equ 0 (
        echo.
        echo =======================================
        echo Build succeeded! Output\QuickCompressor_Setup.exe created.
        echo =======================================
    ) else (
        echo.
        echo [Error] Inno Setup compilation failed.
        exit /b 1
    )
) else (
    echo.
    echo [Error] Inno Setup (ISCC.exe) not found.
    echo Skipping installer creation.
    exit /b 1
)

endlocal
