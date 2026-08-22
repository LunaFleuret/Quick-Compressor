# Quick Compressor

[日本語](README.md) | [English](README.en.md) | [简体中文](README.zh-CN.md)

---

## Overview

A lightweight and high-speed video compression tool designed for platforms with strict file size limits, such as Discord (10MB) and Steam Chat (30MB).

**GPU hardware encoding is required (CPU-only encoding is not supported).**

![Quick Compressor](images/screenshot.png)

---

## Key Features

- **Target File Size Mode (Size Priority)**: Specify a target file size (e.g., "within 10MB"), and the tool automatically calculates the optimal bitrate to compress within the limit.
- **Percentage Compression Mode**: Compresses the video to fit within a specified percentage of its original size.
- **Windows Context Menu & Preset Integration**: Right-click any video file and choose a preset (e.g., "For Discord") to start compressing immediately.
- **Custom Presets**: Save your custom resolution, codec, and target settings as new presets that automatically sync with the Windows context menu.
- **Always on Top (Default: On)**: Keeps the window visible above other applications so you can drag and drop files even when File Explorer is maximized.
- **Drag Anywhere**: Click and hold anywhere on the window background to move it freely.
- **Batch Processing (Queue)**: Queue multiple video files to process them sequentially.

---

## How to Use

### A: Quick Compression via Right-Click (Using Presets)

1. Select and right-click the video file (`.mp4`, `.mkv`, `.mov`, etc.).
2. On Windows 11, click "Show more options" and select your desired preset from **"Quick Compressor (Presets)"** (e.g., "For Discord").
3. Settings are loaded automatically, and compression begins.
   *(※Whether to launch minimized can be changed in the Settings dialog.)*

![Context Menu](images/right_click_menu.png)

### B: Compression & Preset Management via GUI

1. Open the GUI by launching the executable directly or selecting "Quick Compressor" from the context menu.
2. Choose from pre-configured presets or manually fine-tune resolution, codec, and target size.
3. Click **"Start Compression"** to begin conversion.
4. Click **"Create Preset"** to save current settings as a new preset registered in the Windows context menu.
5. Click **"Manage Presets"** to rename, delete, or toggle visibility of existing presets.

---

## Installation

1. Download the latest `QuickCompressor_Setup.exe` from [GitHub Releases](https://github.com/LunaFleuret/Quick-Compressor/releases).
2. Run the downloaded installer and follow the setup instructions.
3. Upon completion, context menu integration is automatically configured in Windows File Explorer.

### Uninstallation

Go to Windows **Settings** > **Apps** > **Installed apps**, select **Quick Compressor**, and click **Uninstall**. Context menu registry entries will be automatically removed.

---

## System Requirements & Performance

### System Requirements

- **OS**: Windows 11 (64-bit)
- **GPU**: NVIDIA Graphics Card (NVENC support) or AMD Graphics Card (AMF support)
- **Dependencies**: None (standalone executable)

> [!WARNING]
> This application cannot be used on PC environments without a supported GPU hardware encoder.

---

### Factors Affecting Compression Time

Because Quick Compressor utilizes GPU hardware encoding, compression speed depends on:

1. **Source Video Length**: Processing time scales with the total number of frames in the video.
2. **GPU Performance**: The speed of your hardware encoder (NVENC/AMF) directly affects encoding speed (CPU bottlenecks may also limit maximum throughput).
3. **Resolution & Frame Rate**: Higher resolutions (4K) and frame rates (60FPS) process more pixels per second, increasing workload.
4. **Encoding Preset (P1 to P7)**: `P1` (Speed priority) to `P7` (Quality priority) — higher quality presets require more GPU computation.
5. **Codec**: HEVC (H.265) and AV1 offer superior compression efficiency compared to H.264, but demand higher computational power.
6. **Storage Speed**: Reading very large source files from slower storage drives may limit processing speed.

*※Videos that are already heavily compressed (such as those downloaded from YouTube) may not shrink further and could potentially increase in size.*

---

## Advanced Settings

![Advanced Settings](images/detail_settings.png)

- **Encode Preset (P1 - P7)**:
  - Lower numbers increase speed at the cost of larger file size.
  - Higher numbers produce smaller files with better quality at slower encoding speeds.
  - *(※On AMD GPUs: P1-P3 map to Speed, P4 to Balance, P5-P7 to Quality).*
- **Audio Encoding**: Choose between copying original audio stream or re-encoding to AAC 124kbps.
- **Auto-close on Completion**: Automatically closes Quick Compressor once the compression finishes.
- **Always on Top**: Toggle window pin state via the pin icon in the top right.
- **Preset Management**: Show/hide audio-less presets, rename, or delete presets.

---

## License

MIT License
