#!/usr/bin/env bash
# Chạy app nền trên macOS bằng launchd, không cần mở terminal.
#
#   ./service.sh on            bật: app tự chạy mỗi khi đăng nhập máy, tự bật lại nếu bị sập
#   ./service.sh on --awake    như trên, nhưng giữ máy không tự ngủ khi rảnh (caffeinate)
#   ./service.sh off           tắt và gỡ hẳn, máy không còn tự chạy app
#   ./service.sh restart       chạy lại app (dùng sau khi cập nhật code)
#   ./service.sh status        xem đang chạy hay không
#   ./service.sh logs [-f]     xem nhật ký (-f: theo dõi liên tục)
#
# Chỉ ghi vào ~/Library/LaunchAgents của riêng bạn, không cần quyền admin.
set -u
cd "$(dirname "$0")" || exit 1
DIR="$(pwd -P)"
LABEL="com.managevideos.app"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$DIR/logs"
LOG="$LOG_DIR/server.log"
PORT="${PORT:-5173}"
URL="http://127.0.0.1:$PORT"
DOMAIN="gui/$(id -u)"
TARGET="$DOMAIN/$LABEL"

say() { printf '%s\n' "$*"; }
die() { printf 'Lỗi: %s\n' "$*" >&2; exit 1; }

xml() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

need_macos() {
  [ "$(uname)" = "Darwin" ] || die "Script này chỉ dùng trên macOS (cần launchd)."
  command -v launchctl >/dev/null 2>&1 || die "Không tìm thấy launchctl."
}

is_loaded() { launchctl print "$TARGET" >/dev/null 2>&1; }

service_pid() {
  launchctl print "$TARGET" 2>/dev/null | awk '/^[[:space:]]*pid = /{print $3; exit}'
}

port_pid() {
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null | head -n 1
}

app_up() { curl -fsS -m 3 -o /dev/null "$URL/" 2>/dev/null; }

ensure_venv() {
  if [ ! -x .venv/bin/python ]; then
    say "Tạo môi trường ảo .venv (lần đầu)..."
    python3 -m venv .venv || die "Không tạo được .venv. Cài Python 3 rồi thử lại."
  fi
  .venv/bin/pip install -q -r requirements.txt || say "Cảnh báo: chưa cài đủ thư viện (kiểm tra mạng). Nếu app không lên, chạy ./run.sh một lần."
}

rotate_log() {
  mkdir -p "$LOG_DIR"
  if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 5242880 ]; then
    mv -f "$LOG" "$LOG.1"
  fi
}

write_plist() {
  local awake="$1" args
  if [ "$awake" = "1" ]; then
    args="    <string>/usr/bin/caffeinate</string>
    <string>-i</string>
    <string>$(xml "$DIR/.venv/bin/python")</string>
    <string>$(xml "$DIR/app.py")</string>"
  else
    args="    <string>$(xml "$DIR/.venv/bin/python")</string>
    <string>$(xml "$DIR/app.py")</string>"
  fi
  mkdir -p "$(dirname "$PLIST")"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
$args
  </array>
  <key>WorkingDirectory</key>
  <string>$(xml "$DIR")</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>NO_BROWSER</key>
    <string>1</string>
    <key>PORT</key>
    <string>$(xml "$PORT")</string>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>15</integer>
  <key>StandardOutPath</key>
  <string>$(xml "$LOG")</string>
  <key>StandardErrorPath</key>
  <string>$(xml "$LOG")</string>
</dict>
</plist>
EOF
  chmod 644 "$PLIST"
}

wait_port_free() {
  local i=0
  while [ "$i" -lt 10 ] && [ -n "$(port_pid)" ]; do sleep 1; i=$((i + 1)); done
}

wait_up() {
  local i=0
  while [ "$i" -lt 20 ]; do
    app_up && return 0
    sleep 1; i=$((i + 1))
  done
  return 1
}

cmd_on() {
  need_macos
  local awake=0
  [ "${1:-}" = "--awake" ] && awake=1
  [ -f app.py ] || die "Không thấy app.py. Chạy script này trong thư mục ManageVideosTool."
  ensure_venv
  if is_loaded; then
    launchctl bootout "$TARGET" >/dev/null 2>&1
    wait_port_free
  fi
  local other
  other="$(port_pid)"
  if [ -n "$other" ]; then
    die "Cổng $PORT đang được tiến trình $other dùng (có thể bạn đang chạy ./run.sh). Tắt nó (Ctrl+C) rồi chạy lại ./service.sh on."
  fi
  rotate_log
  write_plist "$awake"
  launchctl bootstrap "$DOMAIN" "$PLIST" || die "launchctl không đăng ký được. Thử ./service.sh off rồi ./service.sh on."
  if wait_up; then
    say "Đã bật. App chạy nền tại $URL (mở bằng trình duyệt, nên lưu bookmark)."
    [ "$awake" = "1" ] && say "Chế độ --awake: máy không tự ngủ khi rảnh (gập màn hình vẫn làm máy ngủ)."
    say "Từ giờ app tự chạy khi bạn đăng nhập máy. Tắt: ./service.sh off"
  else
    say "Đã đăng ký nhưng app chưa trả lời sau 20 giây. Nhật ký gần nhất:"
    tail -n 20 "$LOG" 2>/dev/null
    exit 1
  fi
}

cmd_off() {
  need_macos
  local had=0
  if is_loaded; then
    had=1
    launchctl bootout "$TARGET" >/dev/null 2>&1
    wait_port_free
  fi
  if [ -f "$PLIST" ]; then
    had=1
    rm -f "$PLIST"
  fi
  if [ "$had" = "1" ]; then
    say "Đã tắt và gỡ. App không còn tự chạy. Chạy tay: ./run.sh. Bật lại: ./service.sh on"
  else
    say "Dịch vụ chưa được bật, không có gì để gỡ."
  fi
}

cmd_restart() {
  need_macos
  is_loaded || die "Dịch vụ chưa bật. Chạy ./service.sh on."
  ensure_venv
  rotate_log
  launchctl kickstart -k "$TARGET" >/dev/null 2>&1 || die "Không khởi động lại được."
  if wait_up; then say "Đã chạy lại. App tại $URL"; else say "App chưa trả lời sau 20 giây."; tail -n 20 "$LOG" 2>/dev/null; exit 1; fi
}

cmd_status() {
  need_macos
  if is_loaded; then
    local pid
    pid="$(service_pid)"
    if [ -n "$pid" ] && app_up; then
      say "Đang chạy (pid $pid). Mở $URL"
    elif [ -n "$pid" ]; then
      say "Tiến trình đang chạy (pid $pid) nhưng chưa trả lời tại $URL. Xem ./service.sh logs"
    else
      say "Đã bật nhưng app đang không chạy (có thể vừa bị sập và đang chờ tự bật lại). Xem ./service.sh logs"
    fi
  elif [ -f "$PLIST" ]; then
    say "Có file cấu hình nhưng chưa nạp. Chạy ./service.sh on."
  else
    say "Chưa bật. Bật: ./service.sh on"
  fi
}

cmd_logs() {
  [ -f "$LOG" ] || die "Chưa có nhật ký ($LOG)."
  if [ "${1:-}" = "-f" ]; then tail -n 50 -f "$LOG"; else tail -n 100 "$LOG"; fi
}

case "${1:-}" in
  on) shift; cmd_on "${1:-}" ;;
  off) cmd_off ;;
  restart) cmd_restart ;;
  status) cmd_status ;;
  logs) shift; cmd_logs "${1:-}" ;;
  *)
    sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
