"""Tiếng hiệu ứng khi xuất video: tự tạo bằng ffmpeg (không dính bản quyền), đặt ở lúc hook hiện, lúc chữ lớn bật lên
và lúc đổi cảnh, rồi trộn vào âm thanh sau bước chuẩn hoá âm lượng.

Muốn dùng tiếng của riêng mình: đặt file <tên>.wav / .mp3 / .m4a vào thư mục sfx/ của app (ví dụ sfx/pop.mp3),
file đó được dùng thay cho tiếng tự tạo cùng tên. Tên: xem SOUNDS.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

USER_DIR = Path(__file__).resolve().parent.parent / "sfx"
USER_EXTS = (".wav", ".mp3", ".m4a")
LEVELS = {"soft": 0.6, "normal": 1.0, "loud": 1.4}

# công thức tổng hợp: ("eval", biểu thức aevalsrc, độ dài) hoặc ("noise", màu, độ dài, bộ lọc)
_SPARKLE = "+".join(f"0.22*sin(2*PI*{f}*(t-{d}))*exp(-9*(t-{d}))*gte(t,{d})"
                    for f, d in ((2093, 0), (2637, 0.06), (3136, 0.12), (4186, 0.18), (3520, 0.24)))
RECIPES = {
    "boom": ("eval", "0.9*sin(2*PI*(110-70*t)*t)*exp(-7*t)", 0.6),                       # bụp trầm (hook hiện)
    "pop": ("eval", "0.9*sin(2*PI*(1100-2600*t)*t)*exp(-22*t)", 0.18),                  # pốp
    "ding": ("eval", "0.45*sin(2*PI*1568*t)*exp(-5*t)+0.25*sin(2*PI*3136*t)*exp(-8*t)+0.15*sin(2*PI*2093*t)*exp(-6*t)", 1.0),
    "hit": ("eval", "0.9*sin(2*PI*(160-90*t)*t)*exp(-12*t)+0.35*(random(0)*2-1)*exp(-60*t)", 0.45),   # trống
    "boing": ("eval", "0.6*sin(2*PI*260*t+3*sin(2*PI*14*t)*exp(-3*t))*exp(-4*t)", 0.7),  # lò xo
    "sparkle": ("eval", _SPARKLE, 0.9),                                                  # lấp lánh
    "click": ("eval", "0.8*(random(0)*2-1)*exp(-180*t)+0.5*sin(2*PI*2400*t)*exp(-90*t)", 0.08),
    # tiếng vút đổi cảnh: ngắn (0,3 giây), 3 biến thể dùng xoay vòng để người xem không "quen tai" rồi bỏ qua
    "whoosh": ("noise", "pink", 0.3, "highpass=f=500,lowpass=f=5000,afade=t=in:d=0.18:curve=exp,afade=t=out:st=0.18:d=0.12"),
    "whoosh2": ("noise", "white", 0.3, "highpass=f=900,lowpass=f=3500,afade=t=in:d=0.18:curve=exp,afade=t=out:st=0.18:d=0.12"),
    "whoosh3": ("noise", "pink", 0.3, "highpass=f=1500,lowpass=f=8000,afade=t=in:d=0.18:curve=exp,afade=t=out:st=0.18:d=0.12"),
    "swish": ("noise", "white", 0.25, "highpass=f=1800,lowpass=f=9000,afade=t=in:d=0.12:curve=exp,afade=t=out:st=0.12:d=0.13"),
    "rise": ("noise", "pink", 0.42, "highpass=f=300,lowpass=f=7000,afade=t=in:d=0.4:curve=cub,afade=t=out:st=0.4:d=0.02"),
}
SOUNDS = tuple(RECIPES)
# độ to từng tiếng (đã đo trên nhạc nền chuẩn hoá -16 LUFS: tiếng nhỏ/ngắn phải nâng thì mới nổi)
GAIN = {"boom": 0.55, "whoosh": 3.9, "whoosh2": 1.8, "whoosh3": 4.6, "swish": 2.2, "rise": 3.5, "pop": 1.3, "click": 2.2, "hit": 0.9,
        "sparkle": 1.8, "boing": 0.9, "ding": 0.9}
# tiếng mặc định theo kiểu bật của chữ lớn; slam có thêm tiếng vút lên ngay trước
BY_ANIM = {"pop": "pop", "slide": "swish", "slam": "hit", "stamp": "sparkle", "shake": "boing"}
# tiếng to dần: bắt đầu sớm đúng bằng lúc to nhất (đã đo) để đỉnh tiếng rơi đúng khung hình đổi cảnh / chữ hiện
LEAD = {"whoosh": 0.18, "whoosh2": 0.18, "whoosh3": 0.18, "swish": 0.12, "rise": 0.4}
WHOOSHES = ("whoosh", "whoosh2", "whoosh3")
VARIANT_OF = {"whoosh2": "whoosh", "whoosh3": "whoosh"}   # có file riêng sfx/whoosh.* mà không có biến thể: dùng file đó
HEAVY = ("boom", "hit")  # tiếng trầm mạnh: tối đa MAX_HEAVY lần mỗi video, dùng nhiều thì nhàm
MAX_HEAVY = 2
SCENE_GAP = 2.5          # tiếng vút đổi cảnh cách nhau ít nhất chừng này
CLEAR = 0.6              # không chèn tiếng vút sát một tiếng khác
MAX_EVENTS = 60


def plan(hook_end: float, punches: list[dict], scenes: list[float], out_dur: float, scene_sounds: bool = True) -> list[tuple[float, str]]:
    """Danh sách (giây theo bản xuất, tên tiếng). punches, scenes đã đổi sang giờ của bản xuất."""
    ev: list[tuple[float, str]] = []
    heavy = 0
    if hook_end > 0:
        ev.append((0.0, "boom"))
        heavy += 1
    for p in sorted(punches, key=lambda x: x["t"]):
        name = p.get("sound", "auto")
        if name == "none":
            continue
        auto = name not in RECIPES
        if auto:
            name = BY_ANIM.get(p.get("anim"), "pop")
            if name in HEAVY and heavy >= MAX_HEAVY:   # đã đủ tiếng trầm: chữ "đập xuống" sau đó dùng tiếng pốp
                name = "pop"
            elif p.get("anim") == "slam":
                ev.append((p["t"] - LEAD["rise"], "rise"))
        if name in HEAVY:
            heavy += 1
        ev.append((p["t"] - LEAD.get(name, 0.0), name))
    if scene_sounds:
        last, k = -99.0, 0
        for t in sorted(scenes):
            name = WHOOSHES[k % len(WHOOSHES)]
            st = t - LEAD[name]
            if t < 0.5 or (out_dur and t > out_dur - 0.5) or t - last < SCENE_GAP:
                continue
            if any(abs(st - e) < CLEAR for e, _ in ev):
                continue
            ev.append((st, name))
            last, k = t, k + 1
    ev = [(max(0.0, round(t, 3)), n) for t, n in ev if not out_dur or t < out_dur - 0.05]
    return sorted(ev)[:MAX_EVENTS]


def _own(name: str) -> Path | None:
    return next((USER_DIR / f"{name}{e}" for e in USER_EXTS if (USER_DIR / f"{name}{e}").is_file()), None)


def files(ffmpeg: str, names, tmpdir: Path) -> dict[str, Path]:
    """Đường dẫn file âm thanh cho từng tên: file riêng trong sfx/ nếu có, không thì tạo vào tmpdir."""
    out: dict[str, Path] = {}
    for name in sorted(set(names)):
        own = _own(name) or (_own(VARIANT_OF[name]) if name in VARIANT_OF else None)
        if own:
            out[name] = own
            continue
        r = RECIPES[name]
        dst = tmpdir / f"sfx_{name}.wav"
        if r[0] == "eval":
            cmd = [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", f"aevalsrc='{r[1]}':s=44100:d={r[2]}", "-ac", "2", str(dst)]
        else:
            cmd = [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", f"anoisesrc=color={r[1]}:a=0.8:d={r[2]}:r=44100:seed=7",
                   "-af", r[3] + ",volume=1.4", "-ac", "2", str(dst)]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if p.returncode != 0 or not dst.is_file():
            raise RuntimeError(f"không tạo được tiếng {name}: {p.stderr.strip()[-200:]}")
        out[name] = dst
    return out


def mix_chain(base: str, events: list[tuple[float, str]], index: dict[str, int], level: float, out: str = "a") -> str:
    """Đoạn filter_complex trộn tiếng hiệu ứng vào luồng [base], ra [out]. index: tên tiếng -> số thứ tự đầu vào ffmpeg."""
    parts, labels = [], []
    counts: dict[str, int] = {}
    for _, n in events:
        counts[n] = counts.get(n, 0) + 1
    used = dict.fromkeys(counts, 0)
    for n, k in counts.items():
        parts.append(f"[{index[n]}:a]aresample=44100,aformat=channel_layouts=stereo,asplit={k}" + "".join(f"[fx{n}{i}]" for i in range(k)))
    for i, (t, n) in enumerate(events):
        j = used[n]
        used[n] += 1
        ms = int(t * 1000)
        parts.append(f"[fx{n}{j}]adelay={ms}|{ms},volume={GAIN.get(n, 1.0) * level:.2f}[fxs{i}]")
        labels.append(f"[fxs{i}]")
    parts.append(f"[{base}]aresample=44100,aformat=channel_layouts=stereo,volume=0.85[fxm];[fxm]{''.join(labels)}"
                 f"amix=inputs={len(labels) + 1}:normalize=0:duration=first,alimiter=limit=0.68:level=false[{out}]")
    return ";".join(parts)
