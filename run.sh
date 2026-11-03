#!/usr/bin/env bash
# Chạy app: tự tạo môi trường ảo và cài thư viện ở lần đầu.
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Tạo môi trường ảo..."
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

command -v ffmpeg >/dev/null || echo "CẢNH BÁO: chưa cài ffmpeg (brew install ffmpeg), video sẽ không ghép được."
command -v deno >/dev/null || echo "Gợi ý: brew install deno để yt-dlp lấy đủ định dạng chất lượng cao."

python app.py
