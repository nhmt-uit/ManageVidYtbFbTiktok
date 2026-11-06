#!/usr/bin/env bash
# Cài công cụ cho bước chỉnh sửa video (Mac Apple Silicon): FFmpeg, whisper.cpp (+ model), Node 22+, HyperFrames.
# Chạy lại nhiều lần được: thứ gì có rồi thì bỏ qua. Cách chạy:  bash tools/install_editor_tools.sh
set -u
TOOLS="${EDITOR_TOOLS_DIR:-$HOME/tools}"
MODEL="${WHISPER_MODEL:-large-v3-turbo}"     # tiny để thử nhanh, large-v3-turbo cho chất lượng tốt (~1,6 GB)
ok()   { printf "  [OK]   %s\n" "$*"; }
bad()  { printf "  [LỖI]  %s\n" "$*"; FAILED=1; }
FAILED=0

echo "== 0. Homebrew"
if ! command -v brew >/dev/null; then
  bad "Chưa có Homebrew. Cài theo https://brew.sh rồi chạy lại script này."; exit 1
fi
ok "brew $(brew --version | head -1)"

echo "== 1. FFmpeg"
command -v ffmpeg >/dev/null || brew install ffmpeg
if ffmpeg -hide_banner -filters 2>/dev/null | grep -q " subtitles " && ffmpeg -hide_banner -encoders 2>/dev/null | grep -q libx264; then
  ok "$(ffmpeg -version | head -1 | cut -c1-40) (có subtitles/libass, libx264)"
else bad "FFmpeg thiếu bộ lọc subtitles hoặc libx264: thử 'brew reinstall ffmpeg'"; fi
ffmpeg -hide_banner -encoders 2>/dev/null | grep -q h264_videotoolbox && ok "có encoder phần cứng h264_videotoolbox"

echo "== 2. Node.js 22+"
need_node=1
if command -v node >/dev/null; then [ "$(node -p 'process.versions.node.split(".")[0]')" -ge 22 ] && need_node=0; fi
if [ $need_node = 1 ]; then brew install node@22 && brew link --overwrite --force node@22; fi
command -v node >/dev/null && [ "$(node -p 'process.versions.node.split(".")[0]')" -ge 22 ] && ok "node $(node -v), npm $(npm -v)" || bad "Cần Node 22+ (hiện: $(node -v 2>/dev/null || echo không có))"

echo "== 3. whisper.cpp (Metal) + model $MODEL"
command -v cmake >/dev/null || brew install cmake
mkdir -p "$TOOLS"
[ -d "$TOOLS/whisper.cpp/.git" ] || git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git "$TOOLS/whisper.cpp"
if [ ! -x "$TOOLS/whisper.cpp/build/bin/whisper-cli" ]; then
  ( cd "$TOOLS/whisper.cpp" && cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j --config Release )
fi
[ -x "$TOOLS/whisper.cpp/build/bin/whisper-cli" ] && ok "whisper-cli: $TOOLS/whisper.cpp/build/bin/whisper-cli" || bad "Biên dịch whisper.cpp thất bại"
if [ ! -f "$TOOLS/whisper.cpp/models/ggml-$MODEL.bin" ]; then
  ( cd "$TOOLS/whisper.cpp" && sh ./models/download-ggml-model.sh "$MODEL" )
fi
[ -f "$TOOLS/whisper.cpp/models/ggml-$MODEL.bin" ] && ok "model ggml-$MODEL.bin" || bad "Chưa tải được model $MODEL"
if [ -x "$TOOLS/whisper.cpp/build/bin/whisper-cli" ] && [ -f "$TOOLS/whisper.cpp/models/ggml-$MODEL.bin" ]; then
  out=$("$TOOLS/whisper.cpp/build/bin/whisper-cli" -m "$TOOLS/whisper.cpp/models/ggml-$MODEL.bin" -f "$TOOLS/whisper.cpp/samples/jfk.wav" -nt 2>&1)
  echo "$out" | grep -qi "ask not what your country" && ok "phiên âm thử file mẫu: đúng" || bad "Phiên âm thử không ra kết quả mong đợi"
  echo "$out" | grep -qi "metal" && ok "đang dùng GPU Metal" || echo "  [!]    không thấy dòng Metal trong log (vẫn chạy được bằng CPU)"
fi

echo "== 4. HyperFrames"
if command -v node >/dev/null; then
  v=$(npx -y hyperframes@latest --version 2>/dev/null | tail -1)
  [ -n "$v" ] && ok "hyperframes $v" || bad "Không chạy được 'npx hyperframes'"
  npx -y hyperframes@latest browser ensure >/dev/null 2>&1 && ok "có trình duyệt headless để render" || echo "  [!]    chưa có trình duyệt headless: chạy 'npx hyperframes browser ensure' để xem hướng dẫn"
fi

echo "== 5. yt-dlp (trong venv của dự án)"
PROJ="$(cd "$(dirname "$0")/.." && pwd)"
if [ -x "$PROJ/.venv/bin/yt-dlp" ]; then ok "yt-dlp $("$PROJ/.venv/bin/yt-dlp" --version)"; else echo "  [!]    không thấy $PROJ/.venv/bin/yt-dlp (app tự quản lý bản cập nhật)"; fi

echo
[ $FAILED = 0 ] && echo "XONG: mọi thứ sẵn sàng." || echo "CÓ LỖI: xem các dòng [LỖI] ở trên."
exit $FAILED
