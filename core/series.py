"""Nhận diện "phim nhiều tập" từ tiêu đề video để nhóm các tập lại và hẹn giờ đúng thứ tự.

Đọc tên phim và số tập từ tiêu đề, ví dụ:
  "Hoa Đán Tuổi Thanh Xuân | Tập 12 #phimngan"   -> phim "Hoa Đán Tuổi Thanh Xuân", tập 12
  "Tập 5: Vợ Tôi Là CEO"                         -> phim "Vợ Tôi Là CEO", tập 5
  "Vợ Tôi Là CEO (7/30)", "Phim X - Ep 3", "X Phần 2 Tập 4" (mùa 2, tập 4)

Tự nhận sai thì sửa tay: file series.json trong thư mục video ({"name": "...", "episode": 5}) thắng cả tiêu đề.
Video không có số tập (và chưa sửa tay) không thuộc nhóm nào.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

OVERRIDE_FILE = "series.json"
MAX_EPISODE = 9999
MAX_NAME = 120

_TAG = re.compile(r"[#@][\ẁ-ͯ]+", re.UNICODE)
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0000FE00-\U0000FE0F\U0000200D\U00002B00-\U00002BFF\U0001F1E6-\U0001F1FF]")
_EDGE = " \t|-–—:•·/\\[](){}<>.,;!?~*_\"'“”‘’…+"
_EP = re.compile(r"(?<![\w])(?:tập|tap|episode|ep)\s*[.:#\-]?\s*(\d{1,4})(?:\s*[/／]\s*(\d{1,4}))?(?!\d)", re.I | re.U)
_EP_ZH = re.compile(r"第\s*(\d{1,4})\s*[集话話]")   # 第12集
_EP_SHORT = re.compile(r"(?<![\w])e(\d{1,3})(?!\d)", re.I | re.U)
_SEASON = re.compile(r"(?<![\w])(?:(?:mùa|mua|season)\s*[.:#\-]?\s*|s)(\d{1,2})(?!\d)", re.I | re.U)
_PART = re.compile(r"(?<![\w])(?:(?:phần|phan|part|pt)\s*[.:#\-]?\s*|p)(\d{1,3})(?!\d)", re.I | re.U)
_FRACTION = re.compile(r"[\(\[]\s*(\d{1,3})\s*/\s*(\d{1,3})\s*[\)\]]")
_FINAL = re.compile(r"(?<![\w])(?:tập\s*cuối|tap\s*cuoi|cuối\s*cùng|final|finale)(?![\w])", re.I | re.U)
_SPLIT = re.compile(r"\s*(?:\||–|—|•|·|\s-\s|:\s)\s*")


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text or "")


def _plain(text: str) -> str:
    text = _EMOJI.sub(" ", _nfc(text))
    text = _TAG.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _letters(s: str) -> int:
    return sum(1 for c in s if c.isalpha())


def _segment(s: str, last: bool) -> str:
    """Cắt quanh dấu | - : lấy một đoạn có chữ: đoạn cuối (sát chỗ ghi số tập) hoặc đoạn đầu."""
    s = s.strip(_EDGE)
    parts = [p.strip(_EDGE) for p in _SPLIT.split(s)]
    parts = [p for p in parts if _letters(p) >= 2]
    if not parts:
        return ""
    return parts[-1] if last else parts[0]


def key_of(name: str) -> str:
    """Khóa so sánh tên phim: không dấu, không hoa thường, không ký tự lạ, bỏ chữ "phim" đứng đầu."""
    s = unicodedata.normalize("NFD", _nfc(name).replace("đ", "d").replace("Đ", "D"))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"^(review\s+)?phim\s+", "", s.strip())
    return re.sub(r"[^a-z0-9]+", "", s)


def parse_title(title: str) -> dict:
    """{"name", "episode", "season", "total", "final"}; episode None nếu tiêu đề không ghi số tập."""
    text = _plain(title)
    out = {"name": "", "episode": None, "season": None, "total": None, "final": bool(_FINAL.search(text))}
    spans: list[tuple[int, int]] = []

    m = _EP.search(text) or _EP_ZH.search(text) or _EP_SHORT.search(text)
    if m:
        out["episode"] = int(m.group(1))
        if m.re is _EP and m.group(2):
            out["total"] = int(m.group(2))
        spans.append(m.span())
    else:
        f = _FRACTION.search(text)
        if f and 1 <= int(f.group(1)) <= int(f.group(2)):
            out["episode"], out["total"] = int(f.group(1)), int(f.group(2))
            spans.append(f.span())
    season = _SEASON.search(text)
    part = _PART.search(text)
    if season:
        out["season"] = int(season.group(1))
        spans.append(season.span())
    if part:
        if out["episode"] is not None:        # có cả "Phần" và "Tập": phần = mùa
            if out["season"] is None:
                out["season"] = int(part.group(1))
            spans.append(part.span())
        else:                                  # chỉ có "Phần N": coi là số tập
            out["episode"] = int(part.group(1))
            spans.append(part.span())
    if out["episode"] is not None and not 0 <= out["episode"] <= MAX_EPISODE:
        out["episode"] = None
    if out["total"] is not None and out["total"] < (out["episode"] or 0):
        out["total"] = None

    if not spans and out["final"]:   # "Tên phim | Tập cuối": không có số tập nhưng vẫn là một tập của phim
        spans.append(_FINAL.search(text).span())
    if spans:
        first = min(s for s, _ in spans)
        last = max(e for _, e in spans)
        before, after = text[:first], text[last:]
        name = _segment(before, last=True) if _letters(before) >= 2 else _segment(after, last=False)
        if _FINAL.search(name):
            name = ""
        out["name"] = name[:MAX_NAME].strip()
    return out


def read_override(folder: Path) -> dict:
    try:
        d = json.loads((Path(folder) / OVERRIDE_FILE).read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return d if isinstance(d, dict) else {}


def write_override(folder: Path, name, episode, set_name: bool, set_episode: bool) -> dict:
    """Sửa tay. name "" / episode None = bỏ phần sửa đó (quay về tự nhận). Chỉ ghi phần được yêu cầu."""
    cur = read_override(folder)
    if set_name:
        n = re.sub(r"\s+", " ", str(name or "")).strip()[:MAX_NAME]
        if n:
            cur["name"] = n
        else:
            cur.pop("name", None)
    if set_episode:
        if episode in (None, ""):
            cur.pop("episode", None)
        else:
            try:
                e = int(episode)
            except (TypeError, ValueError) as exc:
                raise ValueError("Số tập phải là số nguyên.") from exc
            if not 0 <= e <= MAX_EPISODE:
                raise ValueError(f"Số tập phải từ 0 đến {MAX_EPISODE}.")
            cur["episode"] = e
    path = Path(folder) / OVERRIDE_FILE
    if cur:
        path.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        path.unlink(missing_ok=True)
    return cur


def _title_of(folder: Path) -> str:
    try:
        t = (Path(folder) / "title.txt").read_text(encoding="utf-8").strip()
    except OSError:
        t = ""
    return t


def info_for(folder: Path) -> dict:
    """Thông tin phim/tập thô của một video (chưa gộp nhóm; gộp ở finalize)."""
    p = parse_title(_title_of(folder))
    ov = read_override(folder)
    name = str(ov["name"]).strip() if isinstance(ov.get("name"), str) and ov["name"].strip() else p["name"]
    episode = p["episode"]
    if isinstance(ov.get("episode"), int) and 0 <= ov["episode"] <= MAX_EPISODE:
        episode = ov["episode"]
    return {"_name": name, "episode": episode, "season": p["season"], "episode_total": p["total"], "final": p["final"],
            "series_manual": bool(ov.get("name") or isinstance(ov.get("episode"), int))}


def finalize(videos: list[dict]) -> None:
    """Gộp các video của MỘT thư mục kênh thành nhóm phim và điền series_key / series_name vào từng video.

    - Thư mục kênh nào mỗi Page chỉ có một phim thì tên chỉ có số tập vẫn được gộp theo tên thư mục.
    - Các tên có cùng phần đầu (khóa này là phần đầu của khóa kia, từ 6 ký tự) được gộp làm một.
    """
    cand = []
    for v in videos:
        name = v.pop("_name", "")
        has = v.get("episode") is not None or bool(name)
        if has and not name:
            name = v.get("channel") or "Không rõ phim"
        cand.append((v, name, key_of(name) if has else ""))
    keys = sorted({k for _, _, k in cand if k}, key=len)
    canon: dict[str, str] = {}
    for k in keys:
        root = next((c for c in canon.values() if len(c) >= 6 and k.startswith(c)), k)
        canon[k] = root
    names: dict[str, dict[str, int]] = {}
    for v, name, k in cand:
        if k:
            names.setdefault(canon[k], {}).setdefault(name, 0)
            names[canon[k]][name] += 1
    for v, name, k in cand:
        if not k:
            v["series_key"], v["series_name"] = "", ""
            continue
        root = canon[k]
        counts = names[root]
        v["series_key"] = root
        v["series_name"] = sorted(counts, key=lambda n: (-counts[n], len(n)))[0]   # tên hay gặp nhất, ngang nhau thì tên ngắn hơn


def order_key(info: dict) -> tuple:
    """Khóa sắp xếp tập trong một phim: mùa, số tập, tập cuối sau cùng, rồi để nguyên thứ tự."""
    return (info.get("season") or 0, 1 if info.get("episode") is None else 0,
            info.get("episode") if info.get("episode") is not None else (MAX_EPISODE + 1 if info.get("final") else MAX_EPISODE))
