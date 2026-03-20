name: Build macOS App (ARM64)

on:
  push:
    branches: [ main ]
  workflow_dispatch:

jobs:

  build-arm:
    runs-on: macos-14

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install Python dependencies
        run: |
          python -m pip install --upgrade pip
          pip install pyinstaller \
                      customtkinter \
                      requests \
                      beautifulsoup4 \
                      opencv-python-headless \
                      pillow \
                      pillow-heif \
                      urllib3

      - name: Download ARM64 FFmpeg & FFprobe
        run: |
          mkdir -p bin
          brew install ffmpeg
          cp "$(which ffmpeg)"  bin/ffmpeg
          cp "$(which ffprobe)" bin/ffprobe
          chmod +x bin/ffmpeg bin/ffprobe
          file bin/ffmpeg

      - name: Build ARM64 App
        run: |
          pyinstaller --noconfirm --onedir --windowed \
            --name "CharmDateBot" \
            --add-data "bin:bin" \
            --hidden-import PIL.ImageTk \
            --hidden-import cv2 \
            --hidden-import pillow_heif \
            --hidden-import bs4 \
            --hidden-import urllib3 \
            --hidden-import requests \
            --collect-all customtkinter \
            --collect-all pillow_heif \
            FinalBot.py

      - name: Create launcher script
        run: |
          python3 -c "
          content = '''#!/bin/bash
          DIR=\"\$( cd \"\$( dirname \"\${BASH_SOURCE[0]}\" )\" && pwd )\"
          APP=\"\$DIR/CharmDateBot.app\"
          xattr -rd com.apple.quarantine \"\$DIR/Запустити_Mac.command\" 2>/dev/null || true
          xattr -rd com.apple.quarantine \"\$APP\" 2>/dev/null || sudo xattr -rd com.apple.quarantine \"\$APP\" 2>/dev/null || true
          open \"\$APP\"
          '''
          with open('dist/Запустити_Mac.command', 'w') as f:
              f.write(content.replace('          ', ''))
          "
          chmod +x "dist/Запустити_Mac.command"

      - name: Package ZIP
        run: |
          find dist/CharmDateBot.app -name "*.pyc" -delete
          find dist/CharmDateBot.app -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
          cd dist
          zip -r -y ../CharmDateBot_ARM64.zip \
            "CharmDateBot.app" \
            "Запустити_Mac.command"

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: CharmDateBot_ARM64
          path: CharmDateBot_ARM64.zip
          retention-days: 3
