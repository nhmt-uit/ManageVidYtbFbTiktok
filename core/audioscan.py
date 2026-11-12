"""Phân tích âm thanh của video để gợi ý chế độ "Làm sạch âm thanh" (xem editor.AUDIO_CLEAN).

Chỉ đo bằng số (ffmpeg + numpy), không "nghe" được. Ngưỡng bên dưới là kinh nghiệm, chưa được hiệu chỉnh trên nhiều
video thật; app luôn để người dùng tự đổi lựa chọn và nghe lại bản nháp trước khi duyệt.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone

import numpy as np

FILE = "audioscan.json"
RATE = 32000                 # 32 kHz: thấy được tới 16 kHz, đủ để đo tiếng "xì" ở dải cao
FRAME = RATE // 20           # khung 50 ms
NFFT = 2048
MAX_SECONDS = 180            # chỉ đo tối đa 3 phút đầu cho nhanh
SILENT_DB = -60              # mức tiếng lớn nhất dưới ngưỡng này coi như im lặng


class ScanError(Exception):
    """Lỗi hiện cho người dùng."""


def _decode(ffmpeg: str, path, seconds: float) -> np.ndarray:
    cmd = [ffmpeg, "-nostdin", "-v", "error", "-i", str(path), "-t", f"{seconds:.1f}", "-vn", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ScanError(f"Không chạy được FFmpeg: {exc}") from exc
    if r.returncode != 0 and not r.stdout:
        raise ScanError("FFmpeg không đọc được âm thanh: " + r.stderr.decode(errors="replace")[-300:])
    return np.frombuffer(r.stdout[: len(r.stdout) // 4 * 4], dtype="<f4")


def _loudness(ffmpeg: str, path, seconds: float) -> dict:
    cmd = [ffmpeg, "-nostdin", "-hide_banner", "-nostats", "-i", str(path), "-t", f"{seconds:.1f}", "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"]
    try:
        err = subprocess.run(cmd, capture_output=True, text=True, timeout=180, errors="replace").stderr
    except (OSError, subprocess.SubprocessError):
        return {}
    tail = err[err.rfind("Summary:"):] if "Summary:" in err else ""
    out = {}
    for key, pat in (("lufs", r"I:\s+(-?[\d.]+) LUFS"), ("lra", r"LRA:\s+(-?[\d.]+) LU"), ("true_peak", r"Peak:\s+(-?[\d.]+) dBFS")):
        m = re.search(pat, tail)
        if m:
            out[key] = float(m[1])
    return out


def _db(x) -> np.ndarray:
    return 20 * np.log10(np.maximum(x, 1e-5))


def _band(spec: np.ndarray, lo: float, hi: float) -> float:
    freqs = np.fft.rfftfreq(NFFT, 1 / RATE)
    return float(spec[(freqs >= lo) & (freqs < hi)].sum())


def scan(ffmpeg: str, path, has_audio: bool = True, seconds: float = MAX_SECONDS) -> dict:
    """Đo âm thanh của `path` và gợi ý chế độ làm sạch. Trả về dict gồm: has_audio, metrics, recommend (off|light|voice), reasons."""
    now = datetime.now(timezone.utc).isoformat()
    if not has_audio:
        return {"has_audio": False, "recommend": "off", "reasons": ["Video không có âm thanh."], "metrics": {}, "scanned_at": now}
    x = _decode(ffmpeg, path, seconds)
    if x.size < FRAME * 10:
        return {"has_audio": False, "recommend": "off", "reasons": ["Âm thanh quá ngắn để phân tích."], "metrics": {}, "scanned_at": now}
    n = x.size // FRAME
    frames = x[: n * FRAME].reshape(n, FRAME)
    level = _db(np.sqrt((frames ** 2).mean(axis=1)))           # mức từng khung 50 ms, dBFS
    p10, p50, p90 = (float(np.percentile(level, q)) for q in (10, 50, 90))
    metrics = {"seconds": round(x.size / RATE, 1), "noise_floor_db": round(p10, 1), "speech_level_db": round(p90, 1),
               "snr_db": round(p90 - p10, 1), "sample_peak_db": round(float(_db(np.abs(x).max())), 1),
               "clipped_pct": round(float((np.abs(x) >= 0.99).mean() * 100), 3)}
    metrics.update({k: v for k, v in _loudness(ffmpeg, path, seconds).items()})
    reasons: list[str] = []
    if p90 < SILENT_DB:
        return {"has_audio": True, "recommend": "off", "metrics": metrics, "scanned_at": now,
                "reasons": [f"Âm thanh gần như im lặng (tiếng lớn nhất khoảng {p90:.0f} dB), không có gì để làm sạch."]}

    # phổ trung bình của các khung "chỉ có nền" (20% khung nhỏ nhất)
    win = np.hanning(NFFT)
    def avg_spec(idx):
        sel = frames[idx][:, :NFFT] if FRAME >= NFFT else np.pad(frames[idx], ((0, 0), (0, NFFT - FRAME)))
        if sel.size == 0:
            return np.zeros(NFFT // 2 + 1)
        return (np.abs(np.fft.rfft(sel * win, axis=1)) ** 2).mean(axis=0)
    quiet = level <= np.percentile(level, 20)
    s_quiet = avg_spec(quiet)
    hum_ratio = _band(s_quiet, 0, 100) / max(_band(s_quiet, 0, 16000), 1e-12)
    hiss_ratio = _band(s_quiet, 6000, 16000) / max(_band(s_quiet, 0, 16000), 1e-12)
    metrics.update(hum_pct=round(hum_ratio * 100), hiss_pct=round(hiss_ratio * 100))

    audible = p10 > -50     # nền dưới mức này thì tiếng ù/xì không nghe thấy, bỏ qua
    noisy = p10 > -45 or (p90 - p10) < 22
    hum = audible and hum_ratio > 0.35
    hiss = audible and hiss_ratio > 0.35
    # nền liên tục: gần như không có chỗ nghỉ (nhạc nền hoặc ồn lớn). Khi đó giảm ồn mạnh dễ làm méo nên chỉ gợi ý mức nhẹ.
    continuous = (p90 - p10) < 10 or p10 > -30
    if noisy:
        reasons.append(f"Nền khá ồn: tiếng nền khoảng {p10:.0f} dB, chênh với tiếng nói {p90 - p10:.0f} dB (video sạch thường chênh trên 30 dB).")
    if hum:
        reasons.append(f"Có tiếng ù trầm ở nền ({hum_ratio * 100:.0f}% năng lượng nền dưới 100 Hz).")
    if hiss:
        reasons.append(f"Có tiếng xì ở dải cao ({hiss_ratio * 100:.0f}% năng lượng nền trên 6 kHz).")
    if metrics.get("clipped_pct", 0) > 0.1:
        reasons.append(f"Âm thanh bị vỡ (méo) ở {metrics['clipped_pct']}% mẫu. Làm sạch không sửa được lỗi này.")
    if noisy or hum or hiss:
        if continuous:
            mode = "light"
            reasons.append("Âm thanh liên tục, gần như không có chỗ nghỉ (thường là nhạc nền hoặc ồn lớn) nên gợi ý \"Nhẹ\" để khỏi làm méo nhạc.")
        else:
            mode = "voice"
            reasons.append("Có các quãng nghỉ giữa các câu nói nên gợi ý \"Rõ giọng nói\". Nếu video có nhạc nền, hãy chọn \"Nhẹ\".")
    else:
        mode = "off"
        reasons.append(f"Âm thanh khá sạch (nền {p10:.0f} dB, chênh {p90 - p10:.0f} dB so với tiếng nói) nên không cần làm sạch.")
    lufs = metrics.get("lufs")
    if lufs is not None and lufs < -24:
        reasons.append(f"Tiếng khá nhỏ ({lufs:.0f} LUFS). Giữ tick \"Chuẩn hóa âm lượng\" để nâng lên mức nghe thoải mái.")
    return {"has_audio": True, "recommend": mode, "reasons": reasons, "metrics": metrics, "scanned_at": now}


def compare(before: dict, after: dict) -> str:
    """Một câu so sánh trước/sau khi xuất, dựa trên độ chênh tiếng nói - nền (không phụ thuộc việc chuẩn hóa âm lượng)."""
    b, a = before.get("metrics", {}), after.get("metrics", {})
    if "snr_db" not in b or "snr_db" not in a:
        return ""
    d = a["snr_db"] - b["snr_db"]
    return (f"Độ chênh tiếng nói so với nền: {b['snr_db']:.0f} dB trước, {a['snr_db']:.0f} dB sau ({d:+.0f} dB). "
            + ("Nền đã giảm rõ." if d >= 3 else "Thay đổi nhỏ, nghe lại bản nháp để quyết định."))
