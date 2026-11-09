"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));

async function api(path, method = "GET", body) {
  const opt = { method, headers: {} };
  if (method !== "GET") {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body || {});
  }
  const r = await fetch(path, opt);
  let data = {};
  try { data = await r.json(); } catch (e) { /* không phải JSON */ }
  if (method !== "GET" && !path.startsWith("/api/fb/") && typeof fbuSoon === "function") fbuSoon();   // thao tác có thể đã dùng lượt gọi Facebook
  if (!r.ok) {
    const err = new Error(data.error || "Lỗi " + r.status);
    err.data = data;
    throw err;
  }
  return data;
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function toast(msg, ms = 3500) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.hidden = true; }, ms);
}

/* ---------- Lượt gọi Facebook (giới hạn của app, xem core/fbgate.py) ---------- */
const fbu = { data: null, soon: null };
function renderFbu(u) {
  fbu.data = u;
  $("#fbu-chip").className = "fbu-chip " + (u.level || "ok");
  $("#fbu-text").textContent = u.paused_minutes ? `Facebook: tạm dừng ${u.paused_minutes} phút` : `Facebook: ${u.used}/${u.budget}`;
  const bar = $("#fbu-bar");
  bar.max = Math.max(u.budget, 1);
  bar.value = Math.min(u.used, u.budget);
  $("#fbu-main").textContent = `Đã dùng ${u.used}/${u.budget} lượt, còn ${u.remaining}.` +
    (u.remaining <= 0 && u.next_free_minutes ? ` Có chỗ trống lại sau khoảng ${u.next_free_minutes} phút.` : "");
  $("#fbu-split").textContent = `Bạn thao tác: ${u.user_used} · Kiểm tra trạng thái nền: ${u.poll_used} · Comment: ${u.comment_used}`;
  const f = u.usage || {};
  const pct = (x) => Math.round(Math.max(x.call_count || 0, x.total_cputime || 0, x.total_time || 0));
  const bits = [];
  if (f.app) bits.push(`app ${pct(f.app)}%`);
  if (f.page) bits.push(`Page ${pct(f.page)}%`);
  $("#fbu-fb").textContent = bits.length ? `Facebook báo đã dùng: ${bits.join(", ")} hạn mức.` : "Facebook chưa báo mức dùng.";
  const p = $("#fbu-pause");
  p.hidden = !u.paused_minutes;
  p.textContent = u.paused_minutes
    ? `App đang tạm dừng mọi lệnh gọi Facebook khoảng ${u.paused_minutes} phút${u.paused_reason ? " (" + u.paused_reason + ")" : ""}. Hết thời gian này app tự chạy lại.` : "";
  $("#fbu-clear").hidden = !u.paused_minutes;
  const c = u.costs || {};
  $("#fbu-cost").textContent = `Ước tính mỗi video: hẹn giờ ${c.schedule} lượt, huỷ ${c.cancel}, đổi giờ ${c.retime}, kiểm tra trạng thái ${c.check}, comment ${c.comment}.`;
}
async function loadFbUsage() {
  try { renderFbu(await api("/api/fb/usage")); } catch (e) { /* app chưa chạy hoặc mất kết nối: giữ số cũ */ }
}
function fbuSoon() {   // sau một thao tác: cập nhật số đếm (gộp nhiều lần gọi liên tiếp)
  clearTimeout(fbu.soon);
  fbu.soon = setTimeout(loadFbUsage, 700);
}
function fbuPopup(open) {
  $("#fbu-pop").hidden = !open;
  $("#fbu-chip").setAttribute("aria-expanded", open ? "true" : "false");
  if (open) loadFbUsage();
}
$("#fbu-chip").addEventListener("click", (e) => { e.stopPropagation(); fbuPopup($("#fbu-pop").hidden); });
document.addEventListener("click", (e) => { if (!$("#fbu-pop").hidden && !e.target.closest("#fbu")) fbuPopup(false); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#fbu-pop").hidden) fbuPopup(false); });
$("#fbu-clear").addEventListener("click", async () => {
  if (!confirm("Bỏ trạng thái tạm dừng?\n\nChỉ nên bỏ khi bạn chắc Facebook đã hết giới hạn (ví dụ đã chờ đủ thời gian). Bỏ sớm mà Facebook vẫn đang giới hạn thì thời gian bị chặn có thể kéo dài thêm.")) return;
  try { renderFbu(await api("/api/fb/usage/clear", "POST")); toast("Đã bỏ trạng thái tạm dừng."); } catch (e) { toast(e.message, 6000); }
});
setInterval(() => { if (!document.hidden) loadFbUsage(); }, 20000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) loadFbUsage(); });
loadFbUsage();

const STATUS_LABEL = { running: "Đang chạy", done: "Hoàn tất", error: "Lỗi", cancelled: "Đã dừng" };

/* ---------- Theo dõi tác vụ nền ---------- */
function follow(jobId, pre, bar, onDone) {
  let since = 0;
  pre.hidden = false;
  pre.textContent = "";
  if (bar) { bar.hidden = false; bar.value = 0; bar.max = 1; }
  const tick = async () => {
    try {
      const j = await api(`/api/jobs/${jobId}?since=${since}`);
      since = j.next;
      if (j.logs.length) {
        pre.textContent += j.logs.join("\n") + "\n";
        pre.scrollTop = pre.scrollHeight;
      }
      if (bar) { bar.max = Math.max(j.progress.total, 1); bar.value = j.progress.done; }
      if (j.status === "running") {
        setTimeout(tick, 1200);
      } else {
        fbuSoon();
        pre.textContent += `— ${STATUS_LABEL[j.status] || j.status}: ${j.result}\n`;
        pre.scrollTop = pre.scrollHeight;
        if (onDone) onDone(j);
      }
    } catch (e) {
      pre.textContent += "Lỗi: " + e.message + "\n";
      if (onDone) onDone({ status: "error" });
    }
  };
  tick();
}

/* ---------- Điều hướng: Tổng quan -> chọn Fanpage -> làm việc trong Fanpage đó ---------- */
// app.page = Fanpage đang làm việc ("" = các màn hình chung: Tổng quan, Kết nối Fanpage, Cài đặt chung, Nhật ký)
const app = { page: "", tab: "", last: "" };   // last = Page làm việc gần nhất (giữ lựa chọn khi qua Tổng quan rồi quay lại)
const PAGE_TABS = ["download", "library", "calendar", "stats", "pagesettings", "jobs"];
const GLOBAL_VIEWS = ["overview", "fanpages", "settings", "jobs"];
const DEFAULT_TZ = "Asia/Ho_Chi_Minh";

function curPage() { return pg.list.find((p) => p.id === app.page); }
function pageTz(p = curPage()) { return (p && p.effective && p.effective.tz) || DEFAULT_TZ; }
function setHash(h) { history.replaceState(null, "", "#" + h); }

const SUBS = ["comment", "token", "notify", "translate", "general"];
function showSub(sub) {
  if (!SUBS.includes(sub)) sub = "comment";
  $$("#subtabs button").forEach((b) => b.classList.toggle("active", b.dataset.sub === sub));
  $$(".subpanel").forEach((p) => p.classList.toggle("active", p.id === "sub-" + sub));
  setHash("settings/" + sub);
}
$("#subtabs").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (b) showSub(b.dataset.sub);
});

function activateSection(name) {
  const id = name === "fanpages" ? "fanpage" : name;   // màn hình "Kết nối Fanpage" nằm trong #tab-fanpage
  $$(".tab").forEach((s) => s.classList.toggle("active", s.id === "tab-" + id));
}
function applyMode() {
  const inPage = !!app.page;
  $("#gtabs").hidden = inPage;
  $("#ctx").hidden = !inPage;
  document.body.classList.toggle("in-page", inPage);
}

// Màn hình chung (không thuộc Fanpage nào)
async function showView(name, sub) {
  if (name === "comment" || name === "token") { sub = name; name = "settings"; }   // đường dẫn cũ
  if (!GLOBAL_VIEWS.includes(name)) name = "overview";
  app.page = "";
  app.tab = "";
  applyMode();
  activateSection(name);
  $$("#gtabs button").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  setHash(name);
  if (name === "overview") loadOverview();
  if (name === "fanpages") loadPages().then(renderFanpage);
  if (name === "settings") { loadSettings(); showSub(sub || ($("#subtabs .active") || {}).dataset?.sub); }
  if (name === "jobs") loadJobs();
}
$("#gtabs").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (b) showView(b.dataset.view);
});

// Làm việc trong một Fanpage
async function showPageTab(id, tab) {
  if (!pg.list.length) await loadPages();
  if (!pg.list.some((p) => p.id === id)) { showView("overview"); return; }
  if (!PAGE_TABS.includes(tab)) tab = "library";
  const prev = app.page || app.last || "";
  if (prev && prev !== id) {
    const busy = busyMsg();
    if (busy) { toast(busy, 6000); renderCtx(); return; }
  }
  app.page = id;
  app.tab = tab;
  if (app.last !== id) resetForPage();
  app.last = id;
  applyMode();
  renderCtx();
  activateSection(tab);
  $$("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  setHash(`p/${encodeURIComponent(id)}/${tab}`);
  window.scrollTo(0, 0);
  if (tab === "download") renderDlHeader();
  if (tab === "library") loadLibrary();
  if (tab === "calendar") loadCalendar();
  if (tab === "stats") loadStats();
  if (tab === "pagesettings") { await loadPages(); renderCtx(); renderPageSettings(); loadPool(); }
  if (tab === "jobs") loadJobs();
}
$("#tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (b) showPageTab(app.page, b.dataset.tab);
});
$("#ctx-home").addEventListener("click", () => showView("overview"));
$("#ctx-page").addEventListener("change", () => showPageTab($("#ctx-page").value, app.tab));

// Đổi Fanpage thì mọi trạng thái của Page cũ (video đã chọn, bộ lọc, khung lên lịch) được dọn đi
function resetForPage() {
  lib.selected.clear();
  lib.status = "all";
  lib.videos = [];
  $("#lib-channel").value = "__all";
  selMsg("", true);
  $("#sel-menu").open = false;
  if ($("#sched-dlg").open) $("#sched-dlg").close();
  resetSchedPanel();
  cal.start = "";
  $("#dl-log").hidden = true;
}

function ruleText(p) {
  const r = p.schedule || {};
  if (!r.slots || !r.slots.length) return "chưa có khung giờ đăng (thêm ở tab Cài đặt Page)";
  const n = Math.min(r.slots.length, r.max_per_day || r.slots.length);
  const off = (r.days_off || []).length ? `, nghỉ ${r.days_off.map((i) => DAY_SHORT[i]).join(", ")}` : "";
  return `${n} bài/ngày (khung giờ ${r.slots.join(", ")}${off})`;
}
function renderCtx() {
  const s = $("#ctx-page");
  s.innerHTML = pageOptions(app.page);
  s.value = app.page;
  const p = curPage();
  if (!p) { $("#ctx-hint").textContent = ""; return; }
  const blocked = p.blocked_until ? ` · Facebook đang giới hạn tần suất của Page này đến ${fmtShort(p.blocked_until, pageTz(p))}` : "";
  $("#ctx-hint").textContent = `Quy tắc đăng: ${ruleText(p)} · Múi giờ ${pageTz(p)}${blocked}`;
  $("#ctx-hint").classList.toggle("bad", !!p.blocked_until);
}

/* ---------- Tải video (cho Fanpage đang làm việc) ---------- */
function dlHeaderText() {
  const p = curPage();
  return p ? `Video tải về được lưu vào thư mục thuộc Fanpage "${p.name}". Mỗi thư mục chỉ thuộc một Page.` : "";
}
function renderDlHeader() {
  $("#dl-page").textContent = dlHeaderText();
  loadDlFolders();
}
// Gợi ý các thư mục đang thuộc Page này để tải thêm video vào đúng thư mục đó
async function loadDlFolders() {
  const pageId = app.page;
  if (!pageId) return;
  try {
    const d = await api("/api/library?page_id=" + encodeURIComponent(pageId));
    if (pageId !== app.page) return;
    $("#dl-folders").innerHTML = d.channels.map((c) => `<option value="${esc(c)}"></option>`).join("");
    $("#dl-page").textContent = dlHeaderText() + (d.channels.length
      ? ` Thư mục hiện có của Page: ${d.channels.join(", ")}. Gõ hoặc chọn tên đó để tải thêm vào thư mục có sẵn, bỏ trống để tạo thư mục mới theo tên kênh.`
      : "");
  } catch (e) { /* bỏ qua, chỉ là gợi ý */ }
}
let dlJob = null;
let dlRunning = false;
function busyMsg() {
  if (schedRunning) return "Đang hẹn lịch cho Page hiện tại, đợi xong rồi hãy chuyển Page.";
  if (dlRunning) return "Đang tải video cho Page hiện tại, đợi xong (hoặc bấm Dừng) rồi hãy chuyển Page.";
  return "";
}
$("#dl-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("#dl-btn");
  btn.disabled = true;
  dlRunning = true;
  try {
    const r = await api("/api/download", "POST", {
      url: $("#dl-url").value,
      folder: $("#dl-folder").value,
      kind: $("#dl-kind").value,
      format: $("#dl-format").value,
      limit: $("#dl-limit").value,
      note: $("#dl-note").value,
      confirm: $("#dl-confirm").checked,
      page_id: app.page,
    });
    dlJob = r.job;
    $("#dl-cancel").hidden = false;
    follow(r.job, $("#dl-log"), $("#dl-bar"), (j) => {
      dlRunning = false;
      btn.disabled = false;
      $("#dl-cancel").hidden = true;
      if (j.status === "done") toast($("#dl-format").value === "audio" ? "Tải xong MP3. File audio.mp3 nằm trong thư mục từng video." : "Tải xong. Xem trong tab Thư viện.");
    });
  } catch (err) {
    dlRunning = false;
    btn.disabled = false;
    toast(err.message);
  }
});
$("#dl-cancel").addEventListener("click", () => {
  if (dlJob) api(`/api/jobs/${dlJob}/cancel`, "POST").then(() => toast("Đang dừng sau video hiện tại..."));
});

/* ---------- Danh sách Fanpage (dùng chung) ---------- */
const pg = { list: [] };
const DAY_SHORT = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
async function loadPages() {
  try {
    pg.list = (await api("/api/pages")).pages;
  } catch (e) {
    toast(e.message);
  }
  return pg.list;
}
function pageOptions(selected) {
  return pg.list.map((p) => `<option value="${esc(p.id)}"${p.id === selected ? " selected" : ""}>${esc(p.name)}</option>`).join("");
}
function rememberPage(key, id) { try { localStorage.setItem(key, id); } catch (e) { /* bỏ qua */ } }
function recalledPage(key) { try { return localStorage.getItem(key) || ""; } catch (e) { return ""; } }

/* ---------- Thư viện ---------- */
const lib = { videos: [], channels: [], selected: new Set(), root: "", status: "all", reelcheck: { available: true, enabled: true } };
// Video đã kiểm tra mà không đạt yêu cầu Reels: không chọn được, app cũng bỏ qua khi hẹn giờ
function isBadReel(v) { return !v.scheduled && !!v.reel_check && v.reel_check.state === "error"; }
// Loại thao tác hàng loạt áp dụng được cho video: new = lên lịch, cancel = huỷ lịch (đã hẹn, chưa đăng), rebook = hẹn lại (lỗi / không thấy), "" = không chọn được
function selKind(v) {
  if (!v.scheduled) return isBadReel(v) ? "" : "new";
  if (v.scheduled === "?" || v.publish_status === "published") return "";
  return ["error", "missing"].includes(v.publish_status) ? "rebook" : "cancel";
}
// Nút "Chọn tất cả" của từng tab chọn loại nào (tab Tất cả chỉ chọn video chưa lên lịch để không lỡ huỷ lịch hàng loạt)
const SELALL_KINDS = { all: ["new"], new: ["new"], pending: ["cancel"], problem: ["cancel", "rebook"], published: [] };
const SELALL_TIP = {
  all: "Chọn mọi video chưa lên lịch đang hiển thị. Muốn chọn video đã hẹn hoặc bị lỗi, mở tab Chờ đăng hoặc Lỗi / quá giờ.",
  new: "Chọn mọi video chưa lên lịch đang hiển thị",
  pending: "Chọn mọi video đang chờ đăng đang hiển thị (để huỷ lịch)",
  problem: "Chọn mọi video lỗi / quá giờ đang hiển thị (để hẹn lại hoặc huỷ lịch)",
  published: "Video đã đăng không có thao tác hàng loạt",
};
// Nút công cụ nào có nghĩa ở tab nào: Kiểm tra Reels soát file video CHƯA hẹn giờ; Kiểm tra trạng thái hỏi Facebook về bài ĐÃ hẹn (bỏ qua bài đã đăng)
const TAB_TOOLS = {
  all: { reels: true, check: true },
  new: { reels: true, check: false },
  pending: { reels: false, check: true },
  problem: { reels: false, check: true },
  published: { reels: false, check: false },
};
const TAB_HINT = {
  all: "Kiểm tra Reels: soát video chưa hẹn có đạt yêu cầu Reels không. Kiểm tra trạng thái: hỏi Facebook về các bài đã hẹn.",
  new: "Video chưa hẹn giờ: chọn rồi bấm Lên lịch. Kiểm tra Reels soát video có đạt yêu cầu Reels (dọc 9:16, 3 đến 90 giây) trước khi hẹn.",
  pending: "Bài đã hẹn, đang chờ đến giờ đăng. Kiểm tra trạng thái hỏi Facebook xem bài còn trên lịch không (phát hiện bài bạn đã xóa). Chọn bài rồi bấm Huỷ lịch để xóa hẹn.",
  problem: "Bài báo lỗi, quá giờ mà chưa đăng, hoặc không còn trên Facebook. Kiểm tra trạng thái để cập nhật lại; chọn bài rồi bấm Hẹn lại (hoặc Huỷ lịch với bài quá giờ).",
  published: "Bài đã đăng thành công. Tab này không có thao tác hàng loạt và không cần kiểm tra thêm.",
};
function selectedBy(kind) {
  const byRel = new Map(lib.videos.map((v) => [v.rel, v]));
  return [...lib.selected].filter((r) => byRel.has(r) && selKind(byRel.get(r)) === kind);
}
function reelBadge(v) {
  const rc = v.reel_check;
  if (v.scheduled || !rc || !rc.state || rc.state === "ok") return "";
  const tip = esc(rc.messages.join(" "));
  return rc.state === "error"
    ? `<span class="badge bad" title="${tip}">Không đạt yêu cầu Reels</span>`
    : `<span class="badge warn" title="${tip}">Cần xem lại (Reels)</span>`;
}
let observer = null;

function mediaUrl(rel) {
  return "/media/" + rel.split("/").map(encodeURIComponent).join("/");
}

async function loadLibrary() {
  if (!app.page) return;
  try {
    const pageId = app.page;
    const d = await api("/api/library?page_id=" + encodeURIComponent(pageId));
    if (pageId !== app.page) return;   // đã chuyển sang Page khác trong lúc chờ
    lib.videos = d.videos;
    lib.channels = d.channels;
    lib.root = d.root;
    lib.reelcheck = d.reelcheck || lib.reelcheck;
    const valid = new Set(d.videos.filter((v) => selKind(v)).map((v) => v.rel));  // video không còn thao tác được (đã đăng...) thì tự bỏ chọn
    lib.selected = new Set([...lib.selected].filter((r) => valid.has(r)));
    const sel = $("#lib-channel");
    const cur = sel.value;
    const hasRoot = d.videos.some((v) => !v.channel);
    sel.innerHTML =
      '<option value="__all">Tất cả thư mục</option>' +
      (hasRoot ? '<option value="__root">(thư mục gốc)</option>' : "") +
      d.channels.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
    if ([...sel.options].some((o) => o.value === cur)) sel.value = cur;
    // Bộ lọc thư mục chỉ có ích khi Page có từ 2 thư mục trở lên
    const many = d.channels.length + (hasRoot ? 1 : 0) > 1;
    sel.hidden = !many;
    if (!many) sel.value = "__all";
    $("#lib-root").textContent = "Thư mục video: " + d.root;
    const un = $("#lib-unassigned");
    un.hidden = !d.unassigned.length;
    if (d.unassigned.length) un.textContent = `Có ${d.unassigned.length} thư mục chưa thuộc Page nào (${d.unassigned.map((i) => i.name).join(", ")}). Về Tổng quan để gán Page cho chúng.`;
    await loadPages();
    renderCtx();
    renderLibrary();
    loadFbStatus();
  } catch (e) {
    toast(e.message);
  }
}

// Mỗi video thuộc đúng một nhóm: new (chưa lên lịch), published (đã đăng), problem (lỗi hoặc quá giờ chưa đăng), pending (đã hẹn, đang chờ đăng)
function videoGroup(v) {
  if (!v.scheduled) return "new";
  if (v.publish_status === "published") return "published";
  if (["error", "missing"].includes(v.publish_status) || v.overdue) return "problem";
  return "pending";
}

function channelVideos() {
  const ch = $("#lib-channel").value || "__all";
  return lib.videos.filter((v) => {
    if (ch === "__root") return !v.channel;
    return ch === "__all" || v.channel === ch;
  });
}

function filteredVideos() {
  return channelVideos().filter((v) => lib.status === "all" || videoGroup(v) === lib.status);
}

// Số video của từng nhóm (theo thư mục đang chọn) hiện ngay trên nút lọc
function renderStatusBar() {
  const counts = { all: 0, new: 0, pending: 0, published: 0, problem: 0 };
  channelVideos().forEach((v) => { counts.all++; counts[videoGroup(v)]++; });
  $$("#lib-status button").forEach((b) => {
    const st = b.dataset.st;
    b.classList.toggle("active", st === lib.status);
    b.classList.toggle("alert", st === "problem" && counts.problem > 0);
    $("b", b).textContent = counts[st];
  });
}

// Giờ luôn hiển thị theo múi giờ của Fanpage (không theo múi giờ của trình duyệt)
function fmtShort(iso, tz) {
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const o = { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" };
  try { return d.toLocaleString("vi-VN", { ...o, timeZone: tz || (app.page ? pageTz() : undefined) }); }
  catch (e) { return d.toLocaleString("vi-VN", o); }
}

function fmtSched(iso) {
  if (!iso || iso === "?") return "Đã lên lịch";
  const s = fmtShort(iso);
  return s ? "Hẹn " + s : "Đã lên lịch";
}

function safeLink(u) {
  return /^https:\/\/(www\.)?facebook\.com\//i.test(u || "") ? u : "";
}

function publishBadge(v) {
  if (!v.scheduled) return '<span class="badge">Chưa lên lịch</span>';
  const when = fmtSched(v.scheduled);
  switch (v.publish_status) {
    case "published": return `<span class="badge ok">Đã đăng · ${esc(when.replace(/^Hẹn /, ""))}</span>`;
    case "error": return `<span class="badge warn" title="${esc(v.publish_detail)}">Lỗi đăng</span>`;
    case "missing": return `<span class="badge warn" title="${esc(v.publish_detail)}">Không thấy trên Facebook</span>`;
    default:
      return v.overdue
        ? `<span class="badge warn" title="Đã quá giờ hẹn nhưng Facebook vẫn báo chưa đăng. Bấm Kiểm tra trạng thái để cập nhật.">Quá giờ chưa đăng · ${esc(when)}</span>`
        : `<span class="badge ok">${esc(when)}</span>`;
  }
}

function commentBadge(v) {
  const e = esc(v.comment_error || "");
  switch (v.comment_status) {
    case "done": return '<span class="badge ok">Đã comment</span>';
    case "pending": return '<span class="badge">Chờ comment</span>';
    case "retry": return `<span class="badge warn" title="${e}">Đang thử lại comment</span>`;
    case "error": return `<span class="badge warn" title="${e}">Lỗi comment</span>`;
    case "skipped": return `<span class="badge warn" title="${esc(v.publish_detail || "")}">${v.publish_status === "missing" ? "Không comment (bài đã xóa)" : "Không comment (bài lỗi)"}</span>`;
    case "expired": return '<span class="badge warn" title="Quá 3 ngày sau giờ đăng nên app bỏ qua">Quá hạn comment</span>';
    default: return "";
  }
}

async function commentNow(rel) {
  if (!confirm("Gửi comment ngay? Chỉ thành công khi bài đã được đăng trên Fanpage.")) return;
  try {
    const r = await api("/api/comment-now", "POST", { rel });
    toast(r.ok ? "Đã comment." : "Chưa comment được: " + r.message);
    loadLibrary();
  } catch (e) {
    toast(e.message);
  }
}

function renderLibrary() {
  const list = filteredVideos();
  // Chỉ giữ lại những video đang thấy trên màn hình, để thao tác hàng loạt (nhất là Huỷ lịch) đúng với những gì bạn nhìn thấy
  const visible = new Set(list.filter((v) => selKind(v)).map((v) => v.rel));
  lib.selected = new Set([...lib.selected].filter((r) => visible.has(r)));
  const grid = $("#lib-grid");
  $("#lib-empty").hidden = lib.videos.length > 0;
  grid.innerHTML = list.map((v) => `
    <article class="card${lib.selected.has(v.rel) ? " sel" : ""}" data-rel="${esc(v.rel)}">
      ${v.scheduled && !selKind(v) ? "" : `<label class="pick"><input type="checkbox" ${lib.selected.has(v.rel) ? "checked" : ""} ${selKind(v) ? "" : "disabled"}></label>`}
      <video data-src="${esc(mediaUrl(v.rel) + ("?e=" + v.size_mb))}" controls playsinline muted preload="none"></video>
      <div class="meta">
        <h4 title="${esc(v.title)}">${esc(v.title)}</h4>
        <p class="sub">${esc(v.date)} · ${v.size_mb} MB${v.channel ? " · " + esc(v.channel) : ""}</p>
        <div class="badges">
          ${publishBadge(v)}
          ${reelBadge(v)}
          ${v.scheduled && v.page_name ? `<span class="badge">${esc(v.page_name)}</span>` : ""}
          ${v.affiliate ? '<span class="badge">Có link affiliate</span>' : ""}
          ${v.has_audio ? '<span class="badge" title="Đã tải kèm file audio.mp3 trong thư mục video này">Có MP3</span>' : ""}
          ${v.custom_caption ? '<span class="badge">Đã sửa nội dung</span>' : ""}
          ${v.has_draft ? '<span class="badge warn" title="Có bản chỉnh sửa nháp chưa duyệt. Hẹn giờ vẫn dùng video hiện tại. Mở Chỉnh sửa video để xem và duyệt.">Chờ duyệt bản chỉnh</span>' : ""}
          ${v.edited ? '<span class="badge ok" title="Video này đã được chỉnh sửa và duyệt (đã thay video gốc)">Đã chỉnh sửa video</span>' : ""}
          ${commentBadge(v)}
          ${v.has_permission ? "" :'<span class="badge warn" title="Chưa có ghi chú đồng ý của chủ kênh trong thư mục này">Chưa ghi nhận quyền</span>'}
        </div>
        <button class="link edit" type="button">Sửa nội dung</button>
        ${v.scheduled ? "" : '<button class="link vedit" type="button">Chỉnh sửa video</button>'}
        ${safeLink(v.permalink) ? `<a class="link" href="${esc(safeLink(v.permalink))}" target="_blank" rel="noopener">Xem bài trên Facebook</a>` : ""}
        ${["error", "missing"].includes(v.publish_status) ? '<button class="link resched" type="button">Hẹn lại</button>' : ""}
        ${canManage(v) ? '<button class="link retime" type="button">Đổi giờ</button> <button class="link cancelsch" type="button">Huỷ lịch</button>' : ""}
        ${["pending", "retry", "error", "expired"].includes(v.comment_status) ? '<button class="link cnow" type="button">Comment ngay</button>' : ""}
      </div>
    </article>`).join("");
  renderStatusBar();
  $("#lib-count").textContent = `Hiển thị ${list.length} video`;
  const kinds = SELALL_KINDS[lib.status] || [];
  const sa = $("#lib-selall");
  sa.disabled = !list.some((v) => kinds.includes(selKind(v)));
  sa.title = SELALL_TIP[lib.status] || "";
  // "Chọn đủ cho..." chỉ có nghĩa với video chưa lên lịch
  const daysOk = ["all", "new"].includes(lib.status);
  const sm = $("#sel-menu");
  $("summary", sm).classList.toggle("disabled", !daysOk);
  $("summary", sm).title = daysOk
    ? "Tự chọn đủ số video cho 1 tuần, 2 tuần hoặc 1 tháng, tính theo số bài mỗi ngày của Fanpage đang làm việc"
    : "Chỉ dùng ở tab Tất cả hoặc Chưa lên lịch (chọn video để lên lịch)";
  if (!daysOk) sm.open = false;
  const rb = $("#lib-reels");
  rb.disabled = !lib.reelcheck.available;
  rb.title = lib.reelcheck.available
    ? "Kiểm tra các video chưa lên lịch có đạt yêu cầu Reels không (dọc 9:16, 3 đến 90 giây, tối thiểu 540x960). Giữ Shift khi bấm để kiểm tra lại tất cả."
    : "Chưa cài ffprobe (đi kèm ffmpeg) nên không kiểm tra được.";
  // Mỗi nút công cụ chỉ hiện ở tab có việc cho nó làm; Làm mới dùng được ở mọi tab
  const tools = TAB_TOOLS[lib.status] || TAB_TOOLS.all;
  rb.hidden = !tools.reels;
  $("#lib-check").hidden = !tools.check;
  $("#lib-tabhint").textContent = (TAB_HINT[lib.status] || "") + " Làm mới: đọc lại thư mục video trên máy, không hỏi Facebook.";
  updateSchedCount();

  if (observer) observer.disconnect();
  observer = new IntersectionObserver((entries) => {
    entries.forEach((en) => {
      if (en.isIntersecting) {
        const vid = en.target;
        vid.preload = "metadata";
        vid.src = vid.dataset.src + "#t=0.5";
        observer.unobserve(vid);
      }
    });
  }, { rootMargin: "200px" });
  $$("video", grid).forEach((v) => observer.observe(v));
}

// Fanpage đang làm việc (chọn ở thanh trên cùng, trước khi vào Thư viện)
function libPageId() {
  return app.page;
}

function updateSchedCount() {
  const nNew = selectedBy("new").length, nCancel = selectedBy("cancel").length, nRebook = selectedBy("rebook").length;
  const n = lib.selected.size;
  $("#sc-count").textContent = `Đã chọn ${nNew} video`;
  const parts = [];
  if (nNew) parts.push(`${nNew} chưa lên lịch`);
  if (nCancel) parts.push(`${nCancel} đã hẹn`);
  if (nRebook) parts.push(`${nRebook} lỗi`);
  $("#selbar-count").textContent = `Đã chọn ${n} video` + (parts.length > 1 ? ` (${parts.join(", ")})` : "");
  $("#selbar").hidden = n === 0;
  $("#selbar-go").hidden = nNew === 0;
  $("#selbar-go").textContent = `Lên lịch (${nNew})...`;
  $("#selbar-cancel").hidden = nCancel === 0;
  $("#selbar-cancel").textContent = `Huỷ lịch (${nCancel})`;
  $("#selbar-rebook").hidden = nRebook === 0;
  $("#selbar-rebook").textContent = `Hẹn lại (${nRebook})`;
  // Nút Lên lịch ở thanh trên chỉ hiện ở tab có video chưa lên lịch (hoặc khi đang chọn video loại đó)
  $("#lib-sched").hidden = !(["all", "new"].includes(lib.status) || nNew > 0);
  $("#lib-sched").textContent = nNew ? `Lên lịch (${nNew})...` : "Lên lịch...";
  refreshSchedButtons();
}

/* ---------- Cửa sổ Lên lịch (chỉ hiện khi bấm "Lên lịch...") ---------- */
let schedRunning = false;
function refreshSchedButtons() {
  const off = schedRunning || selectedBy("new").length === 0 || !libPageId();
  $("#sc-go").disabled = off;
  $("#sc-dry").disabled = off;
}
function openSched() {
  const dlg = $("#sched-dlg");
  syncSchedMode();
  updateSchedCount();
  if (!dlg.open) dlg.showModal();
}
$("#lib-sched").addEventListener("click", openSched);
$("#selbar-go").addEventListener("click", openSched);
$("#selbar-none").addEventListener("click", () => $("#lib-selnone").click());
$("#sc-close").addEventListener("click", () => $("#sched-dlg").close());
$("#sched-dlg").addEventListener("click", (e) => { if (e.target === $("#sched-dlg")) $("#sched-dlg").close(); });

$("#lib-grid").addEventListener("change", (e) => {
  const card = e.target.closest(".card");
  if (!card || e.target.type !== "checkbox") return;
  const rel = card.dataset.rel;
  if (e.target.checked) lib.selected.add(rel); else lib.selected.delete(rel);
  card.classList.toggle("sel", e.target.checked);
  updateSchedCount();
});

$("#lib-grid").addEventListener("click", (e) => {
  if (e.target.classList.contains("edit")) openEdit(e.target.closest(".card").dataset.rel);
  if (e.target.classList.contains("vedit")) openVideoEdit(e.target.closest(".card").dataset.rel);
  if (e.target.classList.contains("cnow")) commentNow(e.target.closest(".card").dataset.rel);
  if (e.target.classList.contains("resched")) reschedule(e.target.closest(".card").dataset.rel);
  const card = e.target.closest(".card");
  if (card && e.target.classList.contains("cancelsch")) cancelSched(card.dataset.rel);
  if (card && e.target.classList.contains("retime")) {
    const v = lib.videos.find((x) => x.rel === card.dataset.rel);
    if (v) openRetime(v.rel, v.title, v.scheduled);
  }
});
$("#lib-channel").addEventListener("change", renderLibrary);
$("#lib-status").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-st]");
  if (!b) return;
  lib.status = b.dataset.st;
  renderLibrary();
});
// Các menu dạng thả xuống: đóng khi bấm ra ngoài hoặc chọn một mục
document.addEventListener("click", (e) => {
  $$("details.menu[open]").forEach((m) => {
    if (!m.contains(e.target) || e.target.closest(".menu-pop button")) m.open = false;
  });
});

/* ---------- Chọn đủ video cho 1 tuần / 2 tuần / 1 tháng ---------- */
function selMsg(text, ok) {
  const m = $("#sel-msg");
  m.textContent = text;
  m.className = "msg " + (ok ? "ok" : "bad");
}
function orderedCandidates() {
  const list = channelVideos().filter((v) => !v.scheduled && !isBadReel(v));
  const order = $("#sc-order").value;
  if (order === "newest") list.sort((a, b) => (a.folder < b.folder ? 1 : a.folder > b.folder ? -1 : 0));
  else if (order === "oldest") list.sort((a, b) => (a.folder < b.folder ? -1 : a.folder > b.folder ? 1 : 0));
  else if (order === "random") {
    for (let i = list.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [list[i], list[j]] = [list[j], list[i]]; }
  }
  return list;
}
async function selectForDays(days) {
  const pageId = libPageId();
  if (!pageId) { selMsg("Chưa chọn Fanpage.", false); return; }
  try {
    const r = await api("/api/capacity?" + new URLSearchParams({ page_id: pageId, days: String(days) }));
    const picked = orderedCandidates().slice(0, r.needed);
    lib.selected = new Set(picked.map((v) => v.rel));
    renderLibrary();
    const n = picked.length;
    const pgName = (pg.list.find((x) => x.id === pageId) || {}).name || "";
    const off = r.days_off.length ? `, nghỉ ${r.days_off.map((i) => DAY_SHORT[i]).join(", ")}` : "";
    const rule = `${r.per_day} bài/ngày (khung giờ ${r.slots.join(", ")}${off})`;
    let ok = true;
    let t;
    if (n < r.needed) {
      ok = false;
      t = `Chỉ có ${n} video chưa lên lịch, còn thiếu ${r.needed - n} video so với ${r.needed} video cho ${days} ngày. Đã chọn hết ${n} video.`;
    } else {
      t = `Đã chọn ${n} video, đủ cho ${days} ngày theo Fanpage "${pgName}": ${rule}. Bạn đăng theo kiểu nào, bắt đầu từ ngày nào cũng được (bấm Lên lịch...).`;
    }
    if (r.cap && n > r.cap_remaining) {
      ok = false;
      t += ` Lưu ý: mỗi Fanpage chỉ hẹn tối đa ${r.cap} video/24 giờ (còn ${r.cap_remaining}), nên mỗi đợt app chỉ hẹn được ${r.cap_remaining} video, phần còn lại hẹn tiếp sau.`;
    }
    const skippedBad = channelVideos().filter(isBadReel).length;
    if (skippedBad) t += ` Đã bỏ qua ${skippedBad} video không đạt yêu cầu Reels.`;
    selMsg(t, ok);
  } catch (e) {
    selMsg(e.message, false);
  }
}
$("#sel-menu").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-days]");
  if (b) selectForDays(Number(b.dataset.days));
});
$("#lib-refresh").addEventListener("click", loadLibrary);
$("#lib-selnone").addEventListener("click", () => { lib.selected.clear(); selMsg("", true); renderLibrary(); });
$("#lib-selall").addEventListener("click", () => {
  const kinds = SELALL_KINDS[lib.status] || [];
  filteredVideos().filter((v) => kinds.includes(selKind(v))).forEach((v) => lib.selected.add(v.rel));
  renderLibrary();
});
// "Chọn đủ cho..." không mở được ở tab không có video chưa lên lịch
$("#sel-menu summary").addEventListener("click", (e) => {
  if (!["all", "new"].includes(lib.status)) e.preventDefault();
});

/* ---------- Huỷ lịch, đổi giờ bài đã hẹn ---------- */
// Chỉ bài đã hẹn mà chưa đăng và không lỗi (bài lỗi dùng "Hẹn lại")
function canManage(v) {
  return !!v.scheduled && v.scheduled !== "?" && !["published", "error", "missing"].includes(v.publish_status);
}
function reloadSchedViews() {
  return app.tab === "calendar" ? loadCalendar() : loadLibrary();
}
async function cancelSched(rel) {
  if (!confirm("Huỷ lịch đăng bài này?\n\nApp sẽ xóa bài hẹn trên Facebook, rồi video quay về \"Chưa lên lịch\" để bạn hẹn lại lúc khác.")) return;
  try {
    const r = await api("/api/sched/cancel", "POST", { rel });
    toast(r.message, 5000);
    reloadSchedViews();
  } catch (e) {
    if (!e.data || !e.data.refused) { toast(e.message, 7000); return; }
    // Facebook không cho xóa qua API: có thể người dùng đã tự huỷ trong Meta Business Suite
    if (confirm(e.message + "\n\nNếu bạn đã tự huỷ bài này trong Meta Business Suite (Nội dung đã lên lịch), bấm OK để app chỉ gỡ lịch trong app.\n" +
      "Nếu chưa, bấm Huỷ rồi huỷ bài trên Facebook trước, nếu không bài vẫn được đăng.")) {
      try {
        const r = await api("/api/sched/cancel", "POST", { rel, local_only: true });
        toast(r.message, 5000);
        reloadSchedViews();
      } catch (e2) { toast(e2.message, 7000); }
    }
  }
}
/* ---------- Huỷ lịch / hẹn lại hàng loạt ---------- */
let bulkRunning = false;
async function cancelMany(rels) {
  if (bulkRunning || !rels.length) return;
  const n = rels.length;
  let costNote = "";
  try {
    const u = await api("/api/fb/usage");
    renderFbu(u);
    if (u.paused_minutes) {
      alert(`Facebook đang giới hạn lượt gọi API nên app tạm dừng mọi lệnh gọi Facebook khoảng ${u.paused_minutes} phút.\n\nChưa huỷ gì. Thử lại sau khi hết thời gian này.`);
      return;
    }
    // Bài đã quá giờ hẹn tốn thêm 1 lượt: app hỏi Facebook xem đã đăng chưa rồi mới xoá
    const byRel = new Map(lib.videos.map((v) => [v.rel, v]));
    const now = Date.now();
    const due = rels.filter((r) => { const v = byRel.get(r); const t = v && v.scheduled && v.scheduled !== "?" ? Date.parse(v.scheduled) : NaN; return !isNaN(t) && t <= now; }).length;
    const cost = n * u.costs.cancel + due * u.costs.check;
    const doable = Math.max(0, Math.floor(u.remaining * n / Math.max(cost, 1)));
    costNote = `\n\nMỗi bài tốn khoảng ${u.costs.cancel} lượt gọi Facebook` + (due ? ` (${due} bài đã quá giờ hẹn tốn thêm ${u.costs.check} lượt để hỏi trạng thái trước)` : "") +
      `. Giờ này app còn ${u.remaining}/${u.budget} lượt` +
      (cost > u.remaining
        ? `, KHÔNG đủ cho ${n} bài: app sẽ huỷ khoảng ${doable} bài rồi tự dừng để không chạm giới hạn của Facebook. ${n - doable} bài còn lại vẫn giữ nguyên (chờ đăng), chọn lại và huỷ tiếp sau khoảng ${u.next_free_minutes || 60} phút.`
        : ".");
  } catch (e) { /* không đọc được mức dùng: vẫn cho huỷ, server tự kiểm tra */ }
  if (!confirm(`Huỷ lịch ${n} bài đã chọn?\n\nApp sẽ xóa các bài hẹn này trên Facebook, rồi các video quay về "Chưa lên lịch" để bạn hẹn lại lúc khác. Bài nào đã được đăng sẽ được bỏ qua.${costNote}\n\n` +
    "Nếu Facebook từ chối xóa hoặc đang giới hạn lượt gọi, bài đó giữ nguyên trong app (vẫn nằm trong Chờ đăng) để hai bên không bị lệch.")) return;
  bulkRunning = true;
  $("#selbar-cancel").disabled = true;
  const pageId = app.page;
  try {
    const r = await api("/api/sched/cancel-many", "POST", { page_id: pageId, rels });
    toast(`Đang huỷ lịch ${n} bài...`, 600000);
    const j = await waitJob(r.job, (s) => { if (s.progress.total) toast(`Đang huỷ lịch ${s.progress.done}/${s.progress.total}...`, 600000); });
    toast(j.result, 15000);
    const data = j.data || {};
    const refused = data.refused || [];
    const kept = new Set([...refused, ...(data.failed || [])]);
    if (data.rate_limited) rels.slice(rels.length - (data.left || 0)).forEach((x) => kept.add(x));   // bài chưa kịp xử lý vẫn đang chọn
    if (data.gone_stop && data.gone_left) rels.slice(rels.length - data.gone_left).forEach((x) => kept.add(x));
    rels.filter((x) => !kept.has(x)).forEach((x) => lib.selected.delete(x));   // bài đã xử lý xong thì bỏ chọn
    bulkRunning = false;
    $("#selbar-cancel").disabled = false;
    if (pageId === app.page) await reloadSchedViews();
    // Bài không huỷ được VẪN còn trên Facebook và sẽ được đăng: nói rõ, không để lướt qua
    const notes = [];
    if (data.rate_limited) {
      const mins = data.rate_limited_minutes || data.rate_limited * 60;
      const head = data.app_limited
        ? "App tự DỪNG vì đã dùng hết số lượt gọi Facebook cho phép trong giờ này (để Facebook không khóa cả app)."
        : "Facebook đang giới hạn số lượt gọi API nên app đã DỪNG ngay để không làm tình hình tệ hơn.";
      notes.push(`${head}\n\nCòn ${data.left} bài CHƯA huỷ: chúng vẫn nằm trong tab Chờ đăng và VẪN còn trên Facebook (sẽ được đăng đúng giờ nếu bạn không huỷ).\n` +
        `Đợi khoảng ${mins} phút rồi chọn lại các bài đó và bấm Huỷ lịch. Hoặc huỷ chúng trực tiếp trong Meta Business Suite (Nội dung đã lên lịch).`);
    }
    if (data.gone_stop) {
      notes.push(`App DỪNG vì ${data.gone_stop} bài liên tiếp được Facebook báo "không còn bài". Bài bị xóa thật hiếm khi dồn thành chuỗi như vậy, ` +
        "nên có thể Facebook đang trả lỗi chứ bài chưa mất.\n\n" +
        `Hãy mở Meta Business Suite (Nội dung đã lên lịch) xem ${data.gone_stop} bài vừa rồi còn không: bài nào còn thì VẪN được đăng đúng giờ. ` +
        "Nhật ký của đợt huỷ có câu gốc Facebook trả, bản sao lịch của từng bài nằm ở scheduled.old.json trong thư mục video." +
        (data.gone_left ? `\n\n${data.gone_left} bài chưa xử lý vẫn giữ nguyên trong Chờ đăng. Nếu bạn chắc chúng đã bị xóa trên Facebook thì bấm Kiểm tra trạng thái, rồi chọn chúng và bấm Hẹn lại.` : ""));
    }
    if (refused.length) {
      notes.push(`Facebook không cho xóa ${refused.length} bài qua API nên chúng VẪN còn trên Facebook và sẽ được đăng đúng giờ.\n\n` +
        'Hãy huỷ chúng trong Meta Business Suite (Nội dung đã lên lịch), rồi bấm Kiểm tra trạng thái: bài đã xóa sẽ thành "Không thấy trên Facebook", chọn chúng rồi bấm Hẹn lại để đưa về Chưa lên lịch.');
    }
    if (notes.length) alert(notes.join("\n\n———\n\n"));
  } catch (e) {
    toast(e.message, 7000);
  } finally {
    bulkRunning = false;
    $("#selbar-cancel").disabled = false;
  }
}
async function rebookMany(rels) {
  if (bulkRunning || !rels.length) return;
  if (!confirm(`Hẹn lại ${rels.length} video đã chọn?\n\nApp chỉ gỡ lịch cũ trong app để bạn hẹn lại, KHÔNG xóa gì trên Facebook. ` +
    "Hãy chắc chắn các bài này không còn nằm trong Meta Business Suite (mục Nội dung đã lên lịch) để tránh đăng trùng.")) return;
  bulkRunning = true;
  try {
    const r = await api("/api/reschedule-many", "POST", { page_id: app.page, rels });
    rels.forEach((x) => lib.selected.delete(x));
    toast(`Đã gỡ lịch cũ của ${r.done} video, chúng đã về "Chưa lên lịch".` + (r.failed.length ? ` ${r.failed.length} video không gỡ được: ${r.failed[0].error}` : ""), 8000);
    await loadLibrary();
  } catch (e) {
    toast(e.message, 7000);
  } finally {
    bulkRunning = false;
  }
}
$("#selbar-cancel").addEventListener("click", () => cancelMany(selectedBy("cancel")));
$("#selbar-rebook").addEventListener("click", () => rebookMany(selectedBy("rebook")));

// "YYYY-MM-DDTHH:MM" của một thời điểm theo múi giờ của Page
function inputInTz(iso, tz) {
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const p = {};
  try {
    new Intl.DateTimeFormat("en-CA", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
      .formatToParts(d).forEach((x) => { p[x.type] = x.value; });
  } catch (e) { return ""; }
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}
const rt = { rel: "", busy: false };
function openRetime(rel, title, whenIso) {
  rt.rel = rel;
  const tz = pageTz();
  $("#rt-info").textContent = `${title || ""}. Giờ hiện tại: ${fmtShort(whenIso)}.`;
  $("#rt-tz").textContent = `(múi giờ ${tz})`;
  $("#rt-when").value = inputInTz(whenIso, tz);
  $("#rt-msg").textContent = "";
  $("#rt-log").hidden = true;
  $("#rt-save").disabled = false;
  $("#rt-dlg").showModal();
}
$("#rt-close").addEventListener("click", () => { if (!rt.busy) $("#rt-dlg").close(); });
$("#rt-dlg").addEventListener("cancel", (e) => { if (rt.busy) e.preventDefault(); });
function rtMsg(t, ok) { const m = $("#rt-msg"); m.textContent = t; m.className = "msg " + (ok ? "ok" : "bad"); }
$("#rt-save").addEventListener("click", async () => {
  const when = $("#rt-when").value.replace("T", " ");
  if (!when) { rtMsg("Chọn giờ mới.", false); return; }
  const btn = $("#rt-save");
  btn.disabled = true;
  rtMsg("Đang gửi cho Facebook...", true);
  try {
    const r = await api("/api/sched/retime", "POST", { rel: rt.rel, when });
    rtMsg(r.message, true);
    reloadSchedViews();
    setTimeout(() => { if (!rt.busy) $("#rt-dlg").close(); }, 1200);
  } catch (e) {
    if (e.data && e.data.refused) {
      if (confirm(e.message + "\n\nHuỷ bài cũ trên Facebook rồi tải lại video và hẹn lại vào giờ mới?\nViệc này mất vài phút và tính thêm một lượt vào giới hạn đăng 24 giờ của Page.")) {
        await rebookRetime(when);
        return;
      }
      rtMsg("Chưa đổi gì.", false);
    } else {
      rtMsg(e.message, false);
    }
    btn.disabled = false;
  }
});
async function rebookRetime(when) {
  rt.busy = true;
  schedRunning = true;
  try {
    const r = await api("/api/sched/retime", "POST", { rel: rt.rel, when, rebook: true });
    rtMsg(r.message, true);
    follow(r.job, $("#rt-log"), null, (j) => {
      rt.busy = false;
      schedRunning = false;
      refreshSchedButtons();
      $("#rt-save").disabled = false;
      rtMsg(j.status === "done" ? "Đã hẹn lại với giờ mới." : "Hẹn lại chưa xong: xem nhật ký bên dưới. Video đã về \"Chưa lên lịch\", bạn có thể hẹn lại ở Thư viện.", j.status === "done");
      reloadSchedViews();
    });
  } catch (e) {
    rt.busy = false;
    schedRunning = false;
    $("#rt-save").disabled = false;
    rtMsg(e.message, false);
  }
}

/* ---------- Trạng thái đăng, hẹn lại ---------- */
async function reschedule(rel) {
  if (!confirm("Hẹn lại video này?\n\nApp chỉ gỡ lịch cũ trong app để bạn hẹn lại, KHÔNG xóa gì trên Facebook. " +
    "Hãy chắc chắn bài không còn nằm trong Meta Business Suite (mục Nội dung đã lên lịch) để tránh đăng trùng.")) return;
  try {
    await api("/api/reschedule", "POST", { rel });
    toast("Đã gỡ lịch cũ. Chọn lại video này để hẹn giờ.");
    loadLibrary();
  } catch (e) {
    toast(e.message);
  }
}

async function waitJob(id, onTick) {
  for (;;) {
    const j = await api(`/api/jobs/${id}`);
    if (onTick) onTick(j);
    if (j.status !== "running") { fbuSoon(); return j; }
    await new Promise((r) => setTimeout(r, 800));
  }
}
$("#lib-reels").addEventListener("click", async (e) => {
  const btn = $("#lib-reels");
  btn.disabled = true;
  const pageId = app.page;
  try {
    const r = await api("/api/reelcheck", "POST", { page_id: pageId, force: e.shiftKey });
    toast("Đang kiểm tra video...", 120000);
    const j = await waitJob(r.job, (s) => { if (s.progress.total) toast(`Đang kiểm tra video ${s.progress.done}/${s.progress.total}...`, 120000); });
    toast(j.status === "done" ? j.result : "Kiểm tra chưa xong: " + j.result, 8000);
    if (pageId === app.page) loadLibrary();
  } catch (err) {
    toast(err.message, 7000);
  } finally {
    btn.disabled = !lib.reelcheck.available;
  }
});
$("#lib-check").addEventListener("click", async () => {
  const btn = $("#lib-check");
  btn.disabled = true;
  const pageId = app.page;
  toast("Đang hỏi Facebook...", 600000);
  try {
    const r = await api("/api/status/check", "POST", { page_id: pageId });
    if (!r.job) { toast(r.result, 7000); return; }
    const j = await waitJob(r.job, (s) => { if (s.progress.total) toast(`Đang kiểm tra trạng thái ${s.progress.done}/${s.progress.total}...`, 600000); });
    toast(j.status === "error" ? "Kiểm tra chưa xong: " + j.result : j.result, 15000);
    if (pageId === app.page) await loadLibrary();
  } catch (e) {
    toast(e.message, 7000);
  } finally {
    btn.disabled = false;
  }
});

/* ---------- Link affiliate (CSV) ---------- */
function csvCell(v) {
  const s = String(v == null ? "" : v);
  return /[",\n;]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

$("#aff-tpl").addEventListener("click", () => {
  const list = filteredVideos().filter((v) => !v.scheduled);
  if (!list.length) { toast("Không có video chưa lên lịch trong bộ lọc hiện tại."); return; }
  const lines = ["video,title,link"].concat(
    list.map((v) => [v.yt_id || v.folder, (v.title || "").slice(0, 80), ""].map(csvCell).join(","))
  );
  const blob = new Blob(["\ufeff" + lines.join("\r\n") + "\r\n"], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "affiliate_links.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  toast(`Đã tải CSV mẫu (${list.length} video). Điền cột link rồi bấm "Nhập CSV link affiliate".`, 6000);
});

$("#aff-import").addEventListener("click", () => $("#aff-file").click());
$("#aff-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  try {
    const text = await file.text();
    const r = await api("/api/affiliate-import", "POST", { csv: text });
    const box = $("#aff-report");
    const probs = (r.problems || []).slice(0, 20);
    box.hidden = false;
    box.innerHTML = `
      <b class="${r.updated ? "ok" : "bad"}">Đã cập nhật link cho ${r.updated} video.</b>
      ${r.skipped_empty ? `<span class="hint"> ${r.skipped_empty} dòng bỏ qua vì ô link trống.</span>` : ""}
      ${probs.length ? `<ul>${probs.map((p) => `<li>Dòng ${p.line}${p.key ? " (" + esc(p.key) + ")" : ""}: ${esc(p.reason)}</li>`).join("")}</ul>` : ""}
      ${(r.problems || []).length > probs.length ? `<p class="hint">... và ${r.problems.length - probs.length} dòng khác có vấn đề.</p>` : ""}`;
    toast(`Đã cập nhật link cho ${r.updated} video.`);
    loadLibrary();
  } catch (err) {
    toast(err.message);
  }
});

/* ---------- Sửa nội dung ---------- */
let editRel = null;
let editComment0 = "";
let editLink0 = "";
async function openEdit(rel) {
  try {
    const t = await api("/api/caption?rel=" + encodeURIComponent(rel));
    if (typeof t.caption !== "string") {
      toast("Server đang chạy bản cũ. Nhấn Ctrl+C rồi chạy lại ./run.sh.");
      return;
    }
    editRel = rel;
    editComment0 = t.comment || "";
    editLink0 = t.affiliate || "";
    $("#ed-comment").value = editComment0;
    $("#ed-link").value = editLink0;
    $("#ed-caption").value = t.caption;
    $("#ed-reset").hidden = !t.custom;
    updateEditCount();
    $("#edit-dlg").showModal();
  } catch (e) {
    toast(e.message);
  }
}
function updateEditCount() {
  $("#ed-count").textContent = `${$("#ed-caption").value.length}/2000 ký tự`;
}
$("#ed-caption").addEventListener("input", updateEditCount);

async function saveCaption(caption, msg, comment, link) {
  try {
    const body = { rel: editRel, caption };
    if (comment !== undefined && comment !== editComment0) body.comment = comment;  // chỉ gửi khi có sửa
    if (link !== undefined && link.trim() !== editLink0) body.affiliate = link.trim();
    await api("/api/caption", "PUT", body);
    $("#edit-dlg").close();
    toast(msg);
    loadLibrary();
  } catch (e) {
    toast(e.message);
  }
}
$("#ed-save").addEventListener("click", () =>
  saveCaption($("#ed-caption").value, "Đã lưu nội dung.", $("#ed-comment").value, $("#ed-link").value));
$("#ed-reset").addEventListener("click", () => saveCaption("", "Đã khôi phục nội dung mặc định."));

/* ---------- Chỉnh sửa video: phiên âm, phụ đề, giọng đọc, xuất 9:16 ---------- */
const ve = { rel: "", st: null, cues: [], busy: false, view: "orig" };
const fmtSec = (n) => (Math.round(n * 10) / 10).toString();

function veSettings() {
  return {
    framing: $("#ve-framing").value, subs: $("#ve-subs").checked, position: $("#ve-position").value, size: $("#ve-size").value,
    color: $("#ve-color").value, box: $("#ve-box").checked, loudnorm: $("#ve-loud").checked,
    orig_volume: Number($("#ve-ov").value), voice_volume: 100,
  };
}
function veBusy(on, msg) {
  ve.busy = on;
  ["#ve-trans", "#ve-render", "#ve-discard", "#ve-approve", "#ve-tr-auto", "#ve-tr-paste", "#ve-tr-undo", "#ve-tr-apply", "#ve-savecues", "#ve-addcue", "#ve-voicefile", "#ve-voicedel"].forEach((s) => { $(s).disabled = on || (ve.st && ve.st.scheduled); });
  if (!on) $("#ve-bar").hidden = true;
  if (msg !== undefined) $("#ve-msg").textContent = msg;
  if (ve.st && ve.st.translate) veTrUi();
}
function veSetView(v) {
  ve.view = v;
  const vid = $("#ve-video"), st = ve.st;
  const t = vid.currentTime || 0;
  vid.src = (v === "draft" && st.draft.exists ? mediaUrl(ve.rel) + "?draft=1&e=" + st.draft.mtime : mediaUrl(ve.rel) + "?e=" + st.source.size) + "#t=0.1";   // #t: để trình duyệt vẽ khung hình đầu
  if (t > 0.2) vid.addEventListener("loadedmetadata", () => { try { vid.currentTime = t; } catch (e) { /* bỏ qua */ } }, { once: true });
  document.querySelector(`input[name=ve-view][value=${v}]`).checked = true;
  veCap();
}
function veCap() {
  const vid = $("#ve-video"), cap = $("#ve-cap");
  const c = ve.view === "orig" && $("#ve-subs").checked ? ve.cues.find((x) => vid.currentTime >= x.start && vid.currentTime < x.end) : null;
  cap.hidden = !c;
  if (c) cap.textContent = c.text;
}
function veRenderCues() {
  $("#ve-cuecount").textContent = ve.cues.length ? `(${ve.cues.length} dòng)` : "(chưa có)";
  $("#ve-cues").innerHTML = ve.cues.length ? ve.cues.map((c, i) => `
    <div class="ve-cue" data-i="${i}">
      <button class="link ve-play" type="button" title="Nghe lại đoạn này">▶</button>
      <input class="ve-s" type="number" min="0" step="0.1" value="${fmtSec(c.start)}" aria-label="Bắt đầu (giây)">
      <input class="ve-e" type="number" min="0" step="0.1" value="${fmtSec(c.end)}" aria-label="Kết thúc (giây)">
      <textarea class="ve-t" rows="2" maxlength="200" aria-label="Nội dung">${esc(c.text)}</textarea>
      <span class="ve-acts"><button class="link ve-copy" type="button" title="Sao chép câu gốc để dịch ở nơi khác">Sao chép</button><button class="link ve-del" type="button" title="Xóa dòng này">Xóa</button></span>
      ${c.src ? `<div class="ve-src"><span>Gốc: ${esc(c.src)}</span></div>` : ""}
    </div>`).join("") : '<p class="hint">Chưa có phụ đề. Bấm "Phiên âm" ở bước 1, hoặc tự thêm từng dòng.</p>';
  if (ve.st && ve.st.translate) veTrUi();
}
function veTrUi() {
  const st = ve.st, any = ve.cues.length > 0, hasSrc = ve.cues.some((c) => c.src);
  $("#ve-tr-auto").disabled = !any || ve.busy || !!st.scheduled; $("#ve-tr-copy").disabled = !any; $("#ve-tr-paste").disabled = !any || !!st.scheduled;
  $("#ve-tr-undo").hidden = !hasSrc;
  const tr = st.translate;
  $("#ve-tr-hint").textContent = !any ? "" : hasSrc
    ? `Đã dịch${st.translator ? " bằng " + st.translator : " (tay hoặc AI)"}. Dưới mỗi câu có câu gốc để đối chiếu. Hãy đọc lại: AI có thể dịch sai tên riêng hay thuật ngữ.`
    : tr.ok ? `Dịch tự động bằng ${tr.label} (${tr.model}), hoặc dịch tay: sao chép bản gốc đi dịch rồi dán lại.`
    : `Dịch tự động chưa dùng được: ${tr.problem} Vẫn dịch tay được: sao chép bản gốc, dịch ở nơi khác rồi bấm "Dán bản dịch…".`;
}
// "1. câu" / "1) câu" / "[1] câu" / "1: câu" / "1 - câu"
const VE_NUM = /^\s*[\[(]?(\d{1,4})(?:[\]).:\-]\s+|\]\s*)(.*)$/;   // cần khoảng trắng sau dấu, để "2.5 triệu" không bị coi là câu số 2
function veParseTranslation(text, n) {
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (!lines.length) throw new Error("Chưa dán gì cả.");
  const first = VE_NUM.exec(lines[0]);
  let items;
  if (first && Number(first[1]) === 1) {   // có đánh số: câu nhiều dòng được nối vào câu trước
    items = [];
    for (const l of lines) {
      const m = VE_NUM.exec(l);
      if (m && Number(m[1]) === items.length + 1) items.push(m[2].trim());
      else items[items.length - 1] += "\n" + l;
    }
  } else {
    items = lines;
  }
  if (items.length !== n) throw new Error(`Bản dịch có ${items.length} câu nhưng phụ đề có ${n} dòng. Mỗi dòng phụ đề cần đúng một câu dịch (câu nào trống thì ghi lại câu gốc).`);
  if (items.some((x) => !x)) throw new Error("Có câu dịch bị trống.");
  return items;
}
async function veCopy(text, okMsg) {
  try { await navigator.clipboard.writeText(text); }
  catch (e) {
    const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); } finally { ta.remove(); }
  }
  toast(okMsg);
}
const VE_VI = /[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]/i;
function veReadCues() {
  const notVi = ve.st && ve.st.language && ve.st.language !== "vi";   // phiên âm từ ngôn ngữ khác: gõ tiếng Việt đè lên = bạn đang dịch
  return [...document.querySelectorAll("#ve-cues .ve-cue")].map((r) => {
    const i = Number(r.dataset.i), prev = ve.cues[i] || {}, text = r.querySelector(".ve-t").value;
    const c = { start: Number(r.querySelector(".ve-s").value), end: Number(r.querySelector(".ve-e").value), text };
    if (prev.src) c.src = prev.src;
    else if (notVi && prev.text && VE_VI.test(text) && !VE_VI.test(prev.text)) c.src = prev.text;   // dịch tay: giữ câu gốc để đối chiếu (sửa lỗi chính tả tiếng Anh thì KHÔNG tính là dịch)
    return c;
  });
}
function veRender() {
  const st = ve.st, t = st.tools;
  const problems = [];
  if (!t.ffmpeg.ok || !t.ffmpeg.libass) problems.push(t.ffmpeg.problem);
  if (!t.whisper.ok) problems.push(t.whisper.problem + " (vẫn tự gõ phụ đề và xuất video được.)");
  $("#ve-problem").hidden = !problems.length;
  $("#ve-problem").textContent = problems.join(" ");
  $("#ve-locked").hidden = !st.scheduled;
  const s = st.source;
  $("#ve-vinfo").textContent = s.width ? `Gốc: ${s.width}x${s.height}, ${Math.round(s.duration)} giây${s.has_audio ? "" : ", không có âm thanh"}. Xuất ra 1080x1920 (9:16).` : "";
  $("#ve-lang").innerHTML = Object.entries(st.langs).map(([k, n]) => `<option value="${k}"${k === (st.language || "vi") ? " selected" : ""}>${esc(n)}</option>`).join("");
  $("#ve-src-wrap").hidden = !st.voice.name;
  veRenderCues();
  veTrUi();
  const v = st.voice;
  $("#ve-voicedel").hidden = !v.name;
  $("#ve-voiceinfo").textContent = v.name ? `Đang dùng: ${v.name} (${v.duration} giây, ${v.size_mb} MB).` + (s.duration && v.duration > s.duration + 0.5 ? " Giọng dài hơn video nên sẽ bị cắt cho vừa." : "") : "Chưa có giọng đọc.";
  $("#ve-ov-wrap").hidden = !v.name;
  const set = st.settings;
  $("#ve-framing").value = set.framing; $("#ve-position").value = set.position; $("#ve-size").value = set.size; $("#ve-color").value = set.color;
  $("#ve-subs").checked = set.subs; $("#ve-box").checked = set.box; $("#ve-loud").checked = set.loudnorm;
  $("#ve-ov").value = set.orig_volume; $("#ve-ov-n").textContent = set.orig_volume + "%";
  $("#ve-view-ed").disabled = !st.draft.exists;
  $("#ve-discard").hidden = !st.draft.exists;
  $("#ve-approve").hidden = !st.draft.exists;
  veBusy(false);
  const ed = st.draft;
  $("#ve-msg").textContent = ed.exists
    ? `Có bản nháp (${ed.size_mb} MB), chưa duyệt: hẹn giờ vẫn dùng video hiện tại.` + (ed.stale ? " Phụ đề đã đổi sau lần xuất, nên xuất lại." : " Xem thử rồi bấm Duyệt để thay video gốc.")
    : st.approved ? "Video này đã được chỉnh sửa và duyệt. Xuất lần nữa sẽ chồng thêm lên bản hiện tại (phụ đề cũ đã in cố định)." : "Chưa có bản nháp: hẹn giờ đăng đang dùng video gốc.";
}
async function veLoad(keepView) {
  ve.st = await api("/api/edit/status?rel=" + encodeURIComponent(ve.rel));
  ve.cues = ve.st.cues;
  veRender();
  veSetView(keepView && (keepView !== "draft" || ve.st.draft.exists) ? keepView : ve.st.draft.exists ? "draft" : "orig");
}
async function openVideoEdit(rel) {
  ve.rel = rel;
  const v = lib.videos.find((x) => x.rel === rel);
  $("#ve-name").textContent = v ? v.title : rel;
  try {
    await veLoad();
    $("#ve-dlg").showModal();
  } catch (e) {
    toast(e.message);
  }
}
async function veRunJob(path, body, label) {
  veBusy(true, label);
  $("#ve-bar").hidden = false; $("#ve-bar").value = 0;
  try {
    const r = await api(path, "POST", body);
    const j = await waitJob(r.job, (s) => { if (s.progress.total) $("#ve-bar").value = Math.round(100 * s.progress.done / s.progress.total); });
    if (j.status === "error") throw new Error(j.result);
    toast(j.result, 6000);
    return j;
  } finally {
    veBusy(false);
  }
}
async function veSaveCues() {
  const r = await api("/api/edit/subs", "POST", { rel: ve.rel, cues: veReadCues() });
  ve.cues = r.cues; ve.st.cues = r.cues;
  veRenderCues();
  return r.cues;
}
$("#ve-close").addEventListener("click", () => $("#ve-dlg").close());
$("#ve-dlg").addEventListener("close", () => { $("#ve-video").pause(); loadLibrary(); });
$("#ve-dlg").addEventListener("click", (e) => { if (e.target === $("#ve-dlg") && !ve.busy) $("#ve-dlg").close(); });
document.querySelectorAll("input[name=ve-view]").forEach((r) => r.addEventListener("change", (e) => veSetView(e.target.value)));
$("#ve-video").addEventListener("timeupdate", veCap);
$("#ve-subs").addEventListener("change", veCap);
$("#ve-ov").addEventListener("input", () => { $("#ve-ov-n").textContent = $("#ve-ov").value + "%"; });
$("#ve-cues").addEventListener("click", (e) => {
  const row = e.target.closest(".ve-cue");
  if (!row) return;
  const i = Number(row.dataset.i);
  if (e.target.classList.contains("ve-del")) { ve.cues = veReadCues(); ve.cues.splice(i, 1); veRenderCues(); }
  if (e.target.classList.contains("ve-play")) {
    veSetView("orig");
    const vid = $("#ve-video"), start = Number(row.querySelector(".ve-s").value) || 0;
    vid.addEventListener("loadedmetadata", () => { vid.currentTime = start; vid.play(); }, { once: true });
    if (vid.readyState >= 1) { vid.currentTime = start; vid.play(); }
  }
});
$("#ve-tr-copy").addEventListener("click", () => {
  const cues = veReadCues();
  veCopy(cues.map((c, i) => `${i + 1}. ${(c.src || c.text).replace(/\n/g, " ")}`).join("\n"), `Đã sao chép ${cues.length} câu gốc. Dịch xong, bấm "Dán bản dịch…".`);
});
$("#ve-tr-paste").addEventListener("click", () => { $("#ve-tr-box").hidden = false; $("#ve-tr-pmsg").textContent = ""; $("#ve-tr-text").focus(); });
$("#ve-tr-cancel").addEventListener("click", () => { $("#ve-tr-box").hidden = true; });
$("#ve-tr-apply").addEventListener("click", async () => {
  const cues = veReadCues();
  let items;
  try { items = veParseTranslation($("#ve-tr-text").value, cues.length); }
  catch (e) { $("#ve-tr-pmsg").textContent = e.message; $("#ve-tr-pmsg").className = "msg bad"; return; }
  ve.cues = cues.map((c, i) => ({ start: c.start, end: c.end, text: items[i], src: c.src || c.text }));
  veRenderCues();   // veSaveCues đọc từ các ô nhập, nên phải vẽ lại trước khi lưu
  try { await veSaveCues(); } catch (e) { toast(e.message); return; }
  $("#ve-tr-text").value = ""; $("#ve-tr-box").hidden = true;
  veTrUi();
  toast(`Đã áp dụng ${items.length} câu dịch. Đọc lại rồi xuất video.`);
});
$("#ve-tr-undo").addEventListener("click", async () => {
  if (!confirm("Trả toàn bộ phụ đề về bản gốc? Các câu dịch hiện tại sẽ mất.")) return;
  ve.cues = veReadCues().map((c) => ({ start: c.start, end: c.end, text: c.src || c.text }));
  veRenderCues();
  try { await veSaveCues(); veTrUi(); } catch (e) { toast(e.message); }
});
$("#ve-tr-auto").addEventListener("click", async () => {
  const tr = ve.st.translate;
  if (!tr.ok) { toast(tr.problem + " Vào Cài đặt chung > Dịch phụ đề, hoặc dịch tay.", 8000); return; }
  if (ve.cues.some((c) => c.src) && !confirm("Dịch lại sẽ thay các câu đã dịch (kể cả phần bạn đã sửa). Tiếp tục?")) return;
  try {
    await veSaveCues();
    await veRunJob("/api/edit/translate", { rel: ve.rel, to: "vi" }, "Đang dịch phụ đề...");
    await veLoad(ve.view);
  } catch (e) { $("#ve-msg").textContent = e.message; toast(e.message, 8000); }
});
$("#ve-cues").addEventListener("click", (e) => {
  if (!e.target.classList.contains("ve-copy")) return;
  const c = veReadCues()[Number(e.target.closest(".ve-cue").dataset.i)];
  if (c) veCopy(c.src || c.text, "Đã sao chép câu gốc.");
});
$("#ve-addcue").addEventListener("click", () => {
  ve.cues = veReadCues();
  const last = ve.cues[ve.cues.length - 1];
  const start = last ? last.end : Math.floor($("#ve-video").currentTime * 10) / 10;
  ve.cues.push({ start, end: start + 2, text: "" });
  veRenderCues();
  const ta = document.querySelectorAll("#ve-cues .ve-t"); ta[ta.length - 1].focus();
});
$("#ve-savecues").addEventListener("click", async () => {
  try { const c = await veSaveCues(); toast(`Đã lưu ${c.length} dòng phụ đề.`); } catch (e) { toast(e.message); }
});
$("#ve-trans").addEventListener("click", async () => {
  if (ve.cues.length && !confirm("Phiên âm lại sẽ thay toàn bộ phụ đề hiện có (kể cả phần bạn đã sửa). Tiếp tục?")) return;
  try {
    await veRunJob("/api/edit/transcribe", { rel: ve.rel, lang: $("#ve-lang").value, source: $("#ve-src").value }, "Đang phiên âm...");
    await veLoad(ve.view);
  } catch (e) { $("#ve-msg").textContent = e.message; toast(e.message, 8000); }
});
$("#ve-voicefile").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  e.target.value = "";
  if (!f) return;
  veBusy(true, "Đang tải giọng đọc lên...");
  try {
    const r = await fetch("/api/edit/voice?" + new URLSearchParams({ rel: ve.rel, name: f.name }), { method: "POST", headers: { "X-Upload": "1", "Content-Type": "application/octet-stream" }, body: f });
    let d = {}; try { d = await r.json(); } catch (x) { /* không phải JSON */ }
    if (!r.ok) throw new Error(d.error || "Lỗi " + r.status);
    await veLoad(ve.view);
    toast("Đã thêm giọng đọc.");
  } catch (err) { toast(err.message, 7000); veBusy(false, err.message); }
});
$("#ve-voicedel").addEventListener("click", async () => {
  if (!confirm("Gỡ giọng đọc khỏi video này?")) return;
  try { await api("/api/edit/voice", "DELETE", { rel: ve.rel }); await veLoad(ve.view); } catch (e) { toast(e.message); }
});
$("#ve-render").addEventListener("click", async () => {
  try {
    if ($("#ve-subs").checked && document.querySelector("#ve-cues .ve-cue")) await veSaveCues();
    await veRunJob("/api/edit/render", { rel: ve.rel, settings: veSettings() }, "Đang xuất video...");
    await veLoad("draft");
  } catch (e) { $("#ve-msg").textContent = e.message; toast(e.message, 8000); }
});
$("#ve-discard").addEventListener("click", async () => {
  if (!confirm("Bỏ bản nháp? Video hiện tại không đổi; phụ đề và giọng đọc vẫn được giữ để xuất lại.")) return;
  try { await api("/api/edit/discard", "POST", { rel: ve.rel }); await veLoad("orig"); } catch (e) { toast(e.message); }
});
$("#ve-approve").addEventListener("click", async () => {
  if (!confirm("DUYỆT bản nháp?\n\nBản chỉnh sửa sẽ THAY THẾ video gốc. Video gốc bị XOÁ vĩnh viễn, không khôi phục được.\nPhụ đề và giọng đọc đã dùng cũng được dọn đi.")) return;
  veBusy(true, "Đang thay video gốc...");
  try {
    const r = await api("/api/edit/approve", "POST", { rel: ve.rel, confirm: true });
    toast(r.message, 6000);
    await veLoad("orig");
  } catch (e) { veBusy(false, e.message); toast(e.message, 8000); }
});

/* ---------- Lên lịch ---------- */
// Giờ mặc định: kiểu cố định = 19:00 ngày mai; kiểu tự xếp = ngay bây giờ (app tự chọn khung giờ trống gần nhất)
function initSchedForm() {
  const auto = $("#sc-mode") && $("#sc-mode").value === "auto";
  const tz = pageTz();
  const inTz = (ms) => {
    try { return new Date(ms).toLocaleString("sv-SE", { timeZone: tz }); } catch (e) { return new Date(ms).toLocaleString("sv-SE"); }
  };
  if (auto) {   // ngay bây giờ (theo múi giờ của Page)
    $("#sc-start").value = inTz(Date.now()).slice(0, 16).replace(" ", "T");
  } else {      // 19:00 ngày mai (theo múi giờ của Page)
    $("#sc-start").value = inTz(Date.now() + 86400000).slice(0, 10) + "T19:00";
  }
  scStartTouched = false;
}
let scStartTouched = false;
$("#sc-start").addEventListener("input", () => { scStartTouched = true; });

// Đưa khung "Lên lịch đăng" về trạng thái ban đầu (giữ lại khoảng cách giờ đã chọn)
function resetSchedPanel() {
  initSchedForm();
  $("#sc-confirm").checked = false;
  $("#sc-log").hidden = true;
  $("#sc-log").textContent = "";
  $("#sc-bar").hidden = true;
  $("#sc-bar").value = 0;
  $("#sc-cancel").hidden = true;
  refreshSchedButtons();
}

function schedResult(text, ok) {
  const m = $("#sc-result");
  m.textContent = text;
  m.className = "msg " + (ok ? "ok" : "bad");
}

async function loadFbStatus() {
  try {
    const s = await api("/api/settings");
    const p = curPage();
    $("#sc-tz").value = pageTz();
    $("#fb-status").textContent = p
      ? `Lên lịch đăng cho Fanpage "${p.name}"${p.has_token ? "" : " (chưa có token, vào Kết nối Fanpage để lấy lại)"}. Mỗi video chỉ gắn với một Fanpage.`
      : "";
    if (!scIntervalSet) { $("#sc-interval").value = s.values.SCHEDULE_INTERVAL_HOURS; scIntervalSet = true; }
    if (!scStartTouched) initSchedForm();   // giờ mặc định phải tính theo múi giờ của Page
    syncSchedMode();
  } catch (e) { /* bỏ qua */ }
}
let scIntervalSet = false;

// Kiểu hẹn: "Cách nhau cố định" dùng khoảng giờ; "Tự xếp" dùng khung giờ trong quy tắc của Page
function syncSchedMode() {
  const cur = pg.list.find((x) => x.id === app.page);
  const bn = $("#sc-block-note");
  bn.hidden = !(cur && cur.blocked_until);
  if (!bn.hidden) bn.textContent = `Facebook đang giới hạn tần suất đăng của Page này đến khoảng ${fmtShort(cur.blocked_until, pageTz(cur))}. Chưa nên hẹn thêm lúc này (vẫn xem trước được).`;
  const auto = $("#sc-mode").value === "auto";
  $("#sc-interval-wrap").hidden = auto;
  $("#sc-start-label").textContent = auto ? "Bắt đầu xếp từ" : "Giờ đăng video đầu tiên";
  const hint = $("#sc-auto-hint");
  hint.hidden = !auto;
  $("#sc-partial-wrap").hidden = !auto;
  if (!auto) return;
  const p = pg.list.find((x) => x.id === app.page);
  const r = p && p.schedule;
  if (!r || !r.slots.length) {
    hint.className = "hint bad";
    hint.textContent = "Page này chưa có khung giờ đăng. Đóng cửa sổ này, vào tab Cài đặt Page > Quy tắc đăng để thêm khung giờ.";
    return;
  }
  const off = (r.days_off || []).map((i) => DAY_SHORT[i]).join(", ");
  hint.className = "hint";
  hint.textContent = `Khung giờ của Page: ${r.slots.join(", ")}; tối đa ${r.max_per_day} bài/ngày${off ? `; nghỉ ${off}` : ""}. App tự bỏ qua khung giờ đã có bài, giờ đã qua và quá 29 ngày. Giờ tính theo múi giờ của Page.`;
}
$("#sc-mode").addEventListener("change", () => {
  rememberPage("sc-mode", $("#sc-mode").value);
  if (!scStartTouched) initSchedForm();   // chưa tự sửa giờ thì đổi sang giờ mặc định của kiểu mới
  syncSchedMode();
});
$("#sc-order").addEventListener("change", () => rememberPage("sc-order", $("#sc-order").value));
{
  const m = recalledPage("sc-mode"), o = recalledPage("sc-order");
  if (["interval", "auto"].includes(m)) $("#sc-mode").value = m;
  if (["oldest", "newest", "random", "selected"].includes(o)) $("#sc-order").value = o;
}

let scJob = null;
async function startSchedule(dry) {
  const newRels = selectedBy("new");
  if (!newRels.length) { schedResult("Chưa chọn video chưa lên lịch nào. Đóng cửa sổ này và tích chọn video trước.", false); return; }
  const start = $("#sc-start").value.replace("T", " ");
  if (!start) { schedResult("Chọn giờ bắt đầu.", false); return; }
  schedRunning = true;
  refreshSchedButtons();
  try {
    const r = await api("/api/schedule", "POST", {
      page_id: app.page,
      rels: newRels,
      start,
      interval_hours: $("#sc-interval").value,
      mode: $("#sc-mode").value,
      order: $("#sc-order").value,
      partial: $("#sc-mode").value === "auto" && $("#sc-partial").checked,
      dry_run: dry,
      confirm: $("#sc-confirm").checked,
    });
    scJob = r.job;
    schedResult("", true);
    $("#sc-cancel").hidden = false;
    follow(r.job, $("#sc-log"), $("#sc-bar"), (j) => {
      schedRunning = false;
      refreshSchedButtons();
      $("#sc-cancel").hidden = true;
      const warns = $("#sc-log").textContent.split("\n").map((l) => (l.match(/CẢNH BÁO:\s*(.*)$/) || [])[1]).filter(Boolean);
      if (dry) {
        if (j.status === "cancelled") schedResult("Đã dừng xem trước.", false);
        else if (j.status !== "done") schedResult(`Lỗi: ${j.result || "xem nhật ký phía trên"}`, false);
        else if (warns.length) schedResult(`Xem trước xong, có ${warns.length} cảnh báo: ${warns.join(" · ")}`, false);
        else schedResult("Xem trước xong, không có cảnh báo. Tick xác nhận rồi bấm Lên lịch đăng để đăng thật.", true);
        return;
      }
      loadLibrary();  // cập nhật nhãn "Hẹn ..." và tự bỏ chọn các video đã hẹn
      if (j.status === "done") {
        const msg = `${j.result} Đã reset khung lên lịch.` + (warns.length ? ` Có ${warns.length} cảnh báo: ${warns.join(" · ")}` : "");
        resetSchedPanel();
        schedResult(msg, true);
        toast(j.result, 7000);
      } else {
        // lỗi hoặc đã dừng: giữ nhật ký để đọc, các video hẹn thành công trước đó vẫn được lưu
        const msg = j.status === "cancelled" ? `Đã dừng. ${j.result || ""}` : `Lỗi: ${j.result || "xem nhật ký phía trên"}`;
        schedResult(msg, false);
        toast(msg, 7000);
      }
    });
  } catch (e) {
    schedRunning = false;
    refreshSchedButtons();
    schedResult(e.message, false);   // cửa sổ đang mở che mất thông báo nổi, nên báo lỗi ngay trong cửa sổ
  }
}
$("#sc-dry").addEventListener("click", () => startSchedule(true));
$("#sc-go").addEventListener("click", () => startSchedule(false));
$("#sc-cancel").addEventListener("click", () => {
  if (scJob) api(`/api/jobs/${scJob}/cancel`, "POST").then(() => toast("Đang dừng sau video hiện tại..."));
});

/* ---------- Cài đặt, Comment, Token ---------- */
// [khóa, nhãn, kiểu, nhóm]  nhóm: set = Chung, tok = Token FB, cm = Comment (chung cho mọi Page)
const FIELDS = [
  ["OUTPUT_DIR", "Thư mục lưu video", "text", "set"],
  ["DOWNLOAD_MAX_HEIGHT", "Chất lượng tối đa (px)", "number", "set"],
  ["YTDLP_COOKIES_BROWSER", "Trình duyệt lấy cookie nếu YouTube đòi xác minh (chrome, safari, firefox)", "text", "set"],
  ["SCHEDULE_INTERVAL_HOURS", "Khoảng cách mặc định giữa các bài (giờ)", "number", "set"],
  ["FB_API_VERSION", "Phiên bản Facebook Graph API (v21.0 hết hạn 21/01/2027; v25.0 dùng được đến 07/2028)", "text", "set"],
  ["YTDLP_AUTO_UPDATE", "Tự kiểm tra và cập nhật yt-dlp mỗi ngày (YouTube hay đổi, bản cũ dễ gây lỗi tải)", "onoff", "set"],
  ["FB_CALLS_PER_HOUR", "Số lượt gọi Facebook tối đa mỗi giờ cho cả app (Facebook cho khoảng 200/giờ rồi khóa cả app; 150 là mức an toàn; hết thì app tự dừng chờ, xem chip \"Facebook\" ở đầu trang)", "number", "set"],
  ["REELS_CHECK", "Kiểm tra video đạt yêu cầu Reels trước khi hẹn giờ (video không đạt sẽ bị bỏ qua)", "onoff", "set"],
  ["NOTIFY_MAC", "Thông báo macOS", "onoff", "nt"],
  ["TELEGRAM_BOT_TOKEN", "Token bot Telegram (tạo bằng @BotFather)", "secret", "nt"],
  ["TELEGRAM_CHAT_ID", "Chat ID Telegram nhận tin", "text", "nt"],
  ["LOW_STOCK_DAYS", "Báo \"sắp hết video\" khi Page chỉ còn đủ bài cho dưới bao nhiêu ngày", "number", "nt"],
  ["TRANSLATE_PROVIDER", "Nhà cung cấp", "select", "tr", [["anthropic", "Anthropic (Claude)"], ["openai", "Tương thích OpenAI (OpenAI, Gemini, OpenRouter, Groq, Ollama...)"]]],
  ["TRANSLATE_API_KEY", "Khóa API (để trống nếu chạy model trên máy)", "secret", "tr"],
  ["TRANSLATE_MODEL", "Model", "text", "tr", null, "Để trống = mặc định của hãng (claude-haiku-5-5 / gpt-4o-mini)"],
  ["TRANSLATE_BASE_URL", "Địa chỉ API (tuỳ chọn)", "text", "tr", null, "Để trống = địa chỉ chính thức của hãng"],
  ["FB_APP_ID", "Facebook App ID", "text", "tok"],
  ["FB_APP_SECRET", "Facebook App Secret", "secret", "tok"],
  ["FB_USER_TOKEN", "User token (dán từ Graph API Explorer, hết hạn sau khoảng 1 giờ)", "secret", "tok"],
  ["PUBLISH_LIMIT_24H", "Mặc định: tối đa bao nhiêu video hẹn giờ cho mỗi Fanpage trong 24 giờ (0 = không giới hạn; Facebook tính khoảng 30 bài đăng qua API mỗi 24 giờ, vượt dễ bị chặn tạm thời)", "number", "cm"],
  ["SCHEDULE_DELAY_SECONDS", "Mặc định: nghỉ giữa hai video khi hẹn giờ (giây)", "number", "cm"],
  ["COMMENT_DELAY_MINUTES", "Mặc định: chờ bao nhiêu phút sau giờ đăng thì comment", "number", "cm"],
  ["COMMENT_GAP_SECONDS", "Mặc định: nghỉ giữa hai comment liên tiếp (giây)", "number", "cm"],
];

function fieldHtml([key, label, type, , opts, ph], s) {
  if (type === "select") {
    const cur = s.values[key] || opts[0][0];
    return `<label>${esc(label)}
      <select data-key="${key}">${opts.map(([v, n]) => `<option value="${esc(v)}"${v === cur ? " selected" : ""}>${esc(n)}</option>`).join("")}</select></label>`;
  }
  if (type === "onoff") {
    const on = !["0", "false", "off", "no"].includes(String(s.values[key] || "1").toLowerCase());
    return `<label>${esc(label)}
      <select data-key="${key}"><option value="1"${on ? " selected" : ""}>Bật</option><option value="0"${on ? "" : " selected"}>Tắt</option></select></label>`;
  }
  if (type === "secret") {
    const has = s.secrets[key];
    return `<label>${esc(label)}
      <input data-key="${key}" type="password" autocomplete="off" placeholder="${has ? "Đã lưu (để trống nếu không đổi)" : "Chưa có"}"></label>`;
  }
  return `<label>${esc(label)}
    <input data-key="${key}" type="${type}" value="${esc(s.values[key] || "")}"${ph ? ` placeholder="${esc(ph)}"` : ""}></label>`;
}

async function loadSettings() {
  try {
    const s = await api("/api/settings");
    ["set", "tok", "cm", "nt", "tr"].forEach((g) => {
      $(`#${g}-form`).innerHTML = FIELDS.filter((f) => f[3] === g).map((f) => fieldHtml(f, s)).join("");
    });
  } catch (e) {
    toast(e.message);
  }
  loadYt();
}

/* ---------- yt-dlp: phiên bản và cập nhật ---------- */
async function loadYt() {
  try {
    const y = await api("/api/ytdlp");
    const parts = [`Đang dùng bản ${y.loaded || "?"}`];
    if (y.age_days != null && y.age_days >= 0) parts.push(`phát hành ${y.age_days} ngày trước`);
    if (y.latest) parts.push(`bản mới nhất đã biết: ${y.latest}`);
    let text = parts.join(", ") + ".";
    if (y.pending_restart) {
      text += ` Đã cài bản ${y.installed} nhưng app chưa dùng, cần khởi động lại.`;
      if (!y.service) text += " Bấm Ctrl+C rồi chạy lại ./run.sh.";
    }
    $("#yt-info").textContent = text;
    $("#yt-info").classList.toggle("bad", !!(y.age_days != null && y.age_days > 45 && !y.pending_restart));
    $("#yt-restart").hidden = !(y.service && y.pending_restart);
  } catch (e) { /* bỏ qua */ }
}
let ytRunning = false;
$("#yt-update").addEventListener("click", async () => {
  if (ytRunning) return;
  ytRunning = true;
  $("#yt-update").disabled = true;
  setMsg("yt", "Đang kiểm tra...", true);
  try {
    const r = await api("/api/ytdlp/update", "POST");
    follow(r.job, $("#yt-log"), null, (j) => {
      setMsg("yt", j.result || "Mất kết nối với app, thử lại sau.", j.status === "done");
      ytRunning = false;
      $("#yt-update").disabled = false;
      loadYt();
    });
  } catch (e) {
    setMsg("yt", e.message, false);
    ytRunning = false;
    $("#yt-update").disabled = false;
  }
});
$("#yt-restart").addEventListener("click", async () => {
  try {
    await api("/api/restart", "POST");
    setMsg("yt", "Đang khởi động lại, trang sẽ tự kết nối lại sau ít giây...", true);
    $("#yt-restart").disabled = true;
    const wait = async () => {
      try { await api("/api/ytdlp"); location.reload(); } catch (e) { setTimeout(wait, 2000); }
    };
    setTimeout(wait, 4000);
  } catch (e) { setMsg("yt", e.message, false); }
});

/* ---------- Kho comment (của Fanpage đang làm việc) ---------- */
async function loadPool() {
  if (!app.page) return;
  const id = app.page;
  try {
    const r = await api(`/api/pages/${encodeURIComponent(id)}/comment-pool`);
    if (id !== app.page) return;
    renderPool(r.items.length ? r.items : [""]);
  } catch (e) {
    toast(e.message);
  }
}

function renderPool(items) {
  $("#pl-pool").innerHTML = items.map((t, i) => `
    <div class="pool-item">
      <span class="lbl">Comment ${i + 1}</span>
      <textarea rows="3" maxlength="2000" placeholder="Ví dụ: Mua tại đây 👉 {link}">${esc(t)}</textarea>
      <button class="ghost pool-del" type="button" title="Xóa comment này">Xóa</button>
    </div>`).join("");
  updatePoolCount();
}
function poolValues() {
  return $$("#pl-pool textarea").map((t) => t.value);
}
function updatePoolCount() {
  const n = poolValues().filter((v) => v.trim()).length;
  $("#pl-count").textContent = n ? `${n} comment, chọn ngẫu nhiên khi đăng` : "Chưa có comment nào";
}
$("#pl-add").addEventListener("click", () => {
  renderPool([...poolValues(), ""]);
  const all = $$("#pl-pool textarea");
  all[all.length - 1].focus();
});
$("#pl-pool").addEventListener("click", (e) => {
  const btn = e.target.closest(".pool-del");
  if (!btn) return;
  const idx = $$("#pl-pool .pool-del").indexOf(btn);
  const vals = poolValues();
  vals.splice(idx, 1);
  renderPool(vals.length ? vals : [""]);
});
$("#pl-pool").addEventListener("input", updatePoolCount);
$("#pl-save").addEventListener("click", async () => {
  try {
    const r = await api(`/api/pages/${encodeURIComponent(app.page)}/comment-pool`, "PUT", { items: poolValues() });
    setMsg("pl", `Đã lưu. Kho của Fanpage này có ${r.items.length} comment.`, true);
    await loadPages();
  } catch (e) { setMsg("pl", e.message, false); }
});

function setMsg(group, text, ok) {
  const m = $(`#${group}-msg`);
  m.textContent = text;
  m.className = "msg " + (ok ? "ok" : "bad");
}

// Chỉ lưu các ô thuộc đúng nhóm đang mở, không đụng đến nhóm khác
async function saveGroup(group) {
  const values = {};
  $$(`#${group}-form input, #${group}-form select`).forEach((i) => { values[i.dataset.key] = i.value; });
  await api("/api/settings", "POST", { values });
}

$("#set-save").addEventListener("click", async () => {
  try {
    await saveGroup("set");
    setMsg("set", "Đã lưu cài đặt.", true);
    loadSettings();
  } catch (e) { setMsg("set", e.message, false); }
});

$("#tr-save").addEventListener("click", async () => {
  try {
    await saveGroup("tr");
    setMsg("tr", "Đã lưu.", true);
    loadSettings();
  } catch (e) { setMsg("tr", e.message, false); }
});
$("#tr-test").addEventListener("click", async () => {
  setMsg("tr", "Đang dịch thử...", true);
  try {
    await saveGroup("tr");   // thử đúng những gì đang nhập, không cần bấm Lưu trước
    const r = await api("/api/translate/test", "POST");
    setMsg("tr", `Dùng được. ${r.label} (${r.model}) dịch "Hello, how are you today?" thành: ${r.sample}`, true);
    loadSettings();
  } catch (e) { setMsg("tr", e.message, false); }
});
$("#nt-save").addEventListener("click", async () => {
  try {
    await saveGroup("nt");
    setMsg("nt", "Đã lưu.", true);
    loadSettings();
  } catch (e) { setMsg("nt", e.message, false); }
});
$("#nt-test").addEventListener("click", async () => {
  setMsg("nt", "Đang gửi thử...", true);
  try {
    await saveGroup("nt");  // gửi thử bằng đúng những gì đang nhập, không cần bấm Lưu trước
    const r = await api("/api/notify/test", "POST");
    const parts = Object.entries(r.results).map(([k, v]) => `${k}: ${v}`).join(" · ");
    setMsg("nt", (r.ok ? "Đã gửi. " : "Có kênh gửi lỗi. ") + parts, r.ok);
  } catch (e) { setMsg("nt", e.message, false); }
});
$("#nt-chat").addEventListener("click", async () => {
  setMsg("nt", "Đang tìm chat ID...", true);
  try {
    await saveGroup("nt");  // lưu token vừa nhập trước khi hỏi Telegram
    const r = await api("/api/notify/telegram-chat", "POST");
    setMsg("nt", `Đã lấy chat ID ${r.chat_id}${r.name ? " (" + r.name + ")" : ""} và lưu.`, true);
    loadSettings();
  } catch (e) { setMsg("nt", e.message, false); }
});
$("#cm-save").addEventListener("click", async () => {
  try {
    await saveGroup("cm");
    setMsg("cm", "Đã lưu.", true);
    loadSettings();
  } catch (e) { setMsg("cm", e.message, false); }
});

$("#tok-save").addEventListener("click", async () => {
  try {
    await saveGroup("tok");
    setMsg("tok", "Đã lưu.", true);
    loadSettings();
  } catch (e) { setMsg("tok", e.message, false); }
});
$("#tok-check").addEventListener("click", async () => {
  setMsg("tok", "Đang kiểm tra User token...", true);
  try {
    const r = await api("/api/token/check");
    setMsg("tok", r.message, r.ok);
  } catch (e) { setMsg("tok", e.message, false); }
});

/* ---------- Kết nối Fanpage (chung) và Cài đặt Page (riêng từng Page) ---------- */
function pageBadges(p) {
  return `
        <span class="badge ${p.has_token ? "ok" : "warn"}">${p.has_token ? "Đã có token" : "Chưa có token"}</span>
        <span class="badge">${p.scheduled} video đã hẹn</span>
        <span class="badge ok">${p.published || 0} đã đăng</span>
        <span class="badge">${p.pending_comment} chờ comment</span>
        <span class="badge">${p.comment_count} comment trong kho</span>
        ${p.blocked_until ? `<span class="badge warn" title="${esc(p.blocked_reason)}">Facebook đang giới hạn tần suất đến ${esc(fmtShort(p.blocked_until, pageTz(p)))}</span> <button class="link pg-unblock" type="button">Bỏ cảnh báo</button>` : ""}`;
}

function renderFanpage() {
  $("#pg-empty").hidden = pg.list.length > 0;
  $("#pg-list").innerHTML = pg.list.map((p) => `
    <article class="page-card" data-id="${esc(p.id)}">
      <div class="top"><strong>${esc(p.name)}</strong> <span class="sub">Fanpage ID ${esc(p.id)}</span></div>
      <div class="badges">${pageBadges(p)}</div>
      <div class="actions">
        <button class="primary pg-open" type="button">Mở Page</button>
        <button class="ghost pg-check" type="button">Kiểm tra token</button>
        <button class="ghost pg-del" type="button">Xóa khỏi app</button>
      </div>
      <p class="msg pg-card-msg"></p>
    </article>`).join("");
}

const TZ_CHOICES = ["Asia/Ho_Chi_Minh", "Asia/Tokyo", "Asia/Bangkok", "Asia/Seoul", "Asia/Singapore", "UTC"];
function renderPageSettings() {
  const p = curPage();
  const root = $("#ps-root");
  if (!p) { root.innerHTML = ""; return; }
  const own = p.settings || {}, eff = p.effective || {};
  const num = (cls, key, label) => `
          <label>${label} <small>(đang áp dụng: ${esc(eff[key])})</small>
            <input class="${cls}" type="number" min="0" value="${own[key] == null ? "" : esc(own[key])}" placeholder="Mặc định chung">
          </label>`;
  root.innerHTML = `
    <article class="page-card" data-id="${esc(p.id)}">
      <h2>Cài đặt Fanpage "${esc(p.name)}"</h2>
      <div class="top">
        <input class="pname" value="${esc(p.name)}" maxlength="80" aria-label="Tên Page" title="Xóa trống rồi bấm Lưu tên để quay về tên mặc định">
        <button class="ghost pg-rename" type="button">Lưu tên</button>
      </div>
      <span class="sub">Fanpage ID ${esc(p.id)}. Tên mặc định: "Tên Fanpage - ID"; xóa trống rồi bấm Lưu tên để quay về mặc định.</span>
      <div class="badges">${pageBadges(p)}</div>
      <div class="row2">
        <label class="check"><input class="pg-auto" type="checkbox" ${p.auto_comment ? "checked" : ""}> <span>Tự động comment sau khi bài đăng</span></label>
      </div>
      <fieldset class="rules">
        <legend>Quy tắc đăng (dùng cho kiểu hẹn "Tự xếp")</legend>
        <div class="rrow">
          <label>Khung giờ trong ngày (cách nhau bằng dấu phẩy)
            <input class="pg-slots" type="text" value="${esc((p.schedule.slots || []).join(", "))}" placeholder="12:00, 19:00, 21:00">
          </label>
          <label>Tối đa bài / ngày
            <input class="pg-max" type="number" min="1" max="24" value="${esc(p.schedule.max_per_day)}">
          </label>
        </div>
        <div class="days">Ngày nghỉ: ${DAY_SHORT.map((n, i) => `<label><input type="checkbox" class="pg-off" value="${i}"${(p.schedule.days_off || []).includes(i) ? " checked" : ""}> ${n}</label>`).join("")}</div>
        <div class="actions"><button class="ghost pg-rules-save" type="button">Lưu quy tắc</button></div>
      </fieldset>
      <fieldset class="rules">
        <legend>Múi giờ và giới hạn riêng của Page</legend>
        <div class="rrow">
          <label>Múi giờ (khung giờ đăng và lịch của Page tính theo múi giờ này)
            <input class="ps-tz" type="text" list="tz-list" value="${esc(own.tz || "")}" placeholder="Asia/Ho_Chi_Minh (mặc định)">
            <datalist id="tz-list">${TZ_CHOICES.map((z) => `<option value="${z}">`).join("")}</datalist>
          </label>
          ${num("ps-publish_limit_24h", "publish_limit_24h", "Tối đa video hẹn giờ trong 24 giờ (0 = không giới hạn)")}
        </div>
        <div class="rrow">
          ${num("ps-delay_seconds", "delay_seconds", "Nghỉ giữa hai video khi hẹn giờ (giây)")}
          ${num("ps-comment_delay_minutes", "comment_delay_minutes", "Chờ bao nhiêu phút sau giờ đăng thì comment")}
          ${num("ps-comment_gap_seconds", "comment_gap_seconds", "Nghỉ giữa hai comment liên tiếp (giây)")}
        </div>
        <div class="actions"><button class="ghost pg-set-save" type="button">Lưu múi giờ và giới hạn</button></div>
      </fieldset>
      <div class="actions">
        <button class="ghost pg-check" type="button">Kiểm tra token</button>
      </div>
      <p class="msg pg-card-msg"></p>
    </article>`;
}

function cardMsg(card, text, ok) {
  const m = card && $(".pg-card-msg", card);
  if (!m) return;
  m.textContent = text;
  m.className = "msg pg-card-msg " + (ok ? "ok" : "bad");
}

// Tải lại danh sách Page và vẽ lại mọi nơi đang hiển thị thông tin Page
async function reloadCards() {
  await loadPages();
  renderFanpage();
  if (app.page) { renderPageSettings(); renderCtx(); renderDlHeader(); }
}

async function onPageCardClick(e) {
  const card = e.target.closest(".page-card");
  if (!card) return;
  const id = card.dataset.id;
  const enc = encodeURIComponent(id);
  try {
    if (e.target.classList.contains("pg-open")) {
      showPageTab(id, "library");
    } else if (e.target.classList.contains("pg-rename")) {
      await api(`/api/pages/${enc}`, "PUT", { name: $(".pname", card).value });
      toast("Đã lưu tên.");
      await reloadCards();
    } else if (e.target.classList.contains("pg-rules-save")) {
      const r = await api(`/api/pages/${enc}`, "PUT", {
        schedule: {
          slots: $(".pg-slots", card).value,
          max_per_day: $(".pg-max", card).value,
          days_off: $$(".pg-off:checked", card).map((c) => Number(c.value)),
        },
      });
      const p = pg.list.find((x) => x.id === id);
      if (p) p.schedule = r.page.schedule;
      $(".pg-slots", card).value = r.page.schedule.slots.join(", ");
      renderCtx();
      cardMsg(card, r.page.schedule.slots.length ? "Đã lưu quy tắc đăng." : "Đã lưu. Page chưa có khung giờ nên chưa dùng được kiểu \"Tự xếp\".", true);
    } else if (e.target.classList.contains("pg-set-save")) {
      const val = (cls) => $(cls, card).value;
      await api(`/api/pages/${enc}`, "PUT", {
        settings: {
          tz: val(".ps-tz"),
          publish_limit_24h: val(".ps-publish_limit_24h"),
          delay_seconds: val(".ps-delay_seconds"),
          comment_delay_minutes: val(".ps-comment_delay_minutes"),
          comment_gap_seconds: val(".ps-comment_gap_seconds"),
        },
      });
      await reloadCards();
      scStartTouched = false;
      cardMsg($("#ps-root .page-card"), "Đã lưu múi giờ và giới hạn của Page.", true);
    } else if (e.target.classList.contains("pg-unblock")) {
      if (!confirm("Bỏ cảnh báo giới hạn tần suất cho Page này?\n\nChỉ bỏ khi bạn chắc chắn Facebook đã hết chặn. Hẹn giờ hoặc comment khi vẫn đang bị chặn có thể làm thời gian chặn kéo dài hơn.")) return;
      await api(`/api/pages/${enc}/block`, "DELETE");
      toast("Đã bỏ cảnh báo.");
      await reloadCards();
    } else if (e.target.classList.contains("pg-check")) {
      cardMsg(card, "Đang kiểm tra...", true);
      const r = await api(`/api/pages/${enc}/check`);
      cardMsg(card, r.message, r.ok);
    } else if (e.target.classList.contains("pg-del")) {
      const p = pg.list.find((x) => x.id === id);
      const warn = p && p.scheduled ? `\n\nPage này đang có ${p.scheduled} video đã hẹn. Chúng vẫn được đăng trên Facebook, nhưng app sẽ không comment được nữa.` : "";
      if (!confirm(`Xóa "${p ? p.name : id}" khỏi app? Không xóa gì trên Facebook. Các thư mục của Page này sẽ thành "chưa gán Page".${warn}`)) return;
      await api(`/api/pages/${enc}`, "DELETE");
      toast("Đã xóa khỏi app.");
      await reloadCards();
    }
  } catch (err) {
    cardMsg(card, err.message, false);
  }
}
async function onPageCardChange(e) {
  if (!e.target.classList.contains("pg-auto")) return;
  const card = e.target.closest(".page-card");
  try {
    await api(`/api/pages/${encodeURIComponent(card.dataset.id)}`, "PUT", { auto_comment: e.target.checked });
    toast(e.target.checked ? "Đã bật tự động comment cho Page này." : "Đã tắt tự động comment cho Page này.");
    const p = pg.list.find((x) => x.id === card.dataset.id);
    if (p) p.auto_comment = e.target.checked;
  } catch (err) {
    e.target.checked = !e.target.checked;
    cardMsg(card, err.message, false);
  }
}
["#pg-list", "#ps-root"].forEach((sel) => {
  $(sel).addEventListener("click", onPageCardClick);
  $(sel).addEventListener("change", onPageCardChange);
});

function pgMsg(text, ok) {
  const m = $("#pg-msg");
  m.textContent = text;
  m.className = "msg " + (ok ? "ok" : "bad");
}

$("#pg-discover").addEventListener("click", async () => {
  pgMsg("Đang lấy danh sách Page từ Facebook...", true);
  $("#pg-cands").innerHTML = "";
  $("#pg-add-row").hidden = true;
  try {
    const r = await api("/api/pages/discover", "POST");
    pgMsg(r.message, r.ok);
    if (r.ok) {
      $("#pg-cands").innerHTML = r.candidates.length
        ? r.candidates.map((c) => `<label><input type="checkbox" value="${esc(c.id)}" checked> <span>${esc(c.name)} <small>(ID ${esc(c.id)})</small></span></label>`).join("")
        : '<p class="hint">Không có Page mới nào để thêm.</p>';
      $("#pg-add-row").hidden = !r.candidates.length;
    }
    await reloadCards();
  } catch (e) {
    pgMsg(e.message, false);
  }
});

$("#pg-add").addEventListener("click", async () => {
  const ids = $$("#pg-cands input:checked").map((i) => i.value);
  if (!ids.length) { pgMsg("Chưa tick Page nào.", false); return; }
  try {
    const r = await api("/api/pages/add", "POST", { ids });
    pgMsg(`Đã thêm ${r.added.length} Page.`, true);
    $("#pg-cands").innerHTML = "";
    $("#pg-add-row").hidden = true;
    await reloadCards();
  } catch (e) {
    pgMsg(e.message, false);
  }
});

/* ---------- Lịch tuần (chỉ xem) ---------- */
const cal = { start: "" };
function addDays(ymd, n) {
  const [y, m, d] = ymd.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}
function dm(ymd) { const [, m, d] = ymd.split("-"); return `${d}/${m}`; }

async function loadCalendar() {
  await loadPages();
  renderCtx();
  const pageId = app.page;
  const q = new URLSearchParams({ days: "7", page_id: pageId });
  if (cal.start) q.set("start", cal.start);
  const grid = $("#cal-grid");
  try {
    const r = await api("/api/calendar?" + q);
    if (pageId !== app.page) return;
    cal.start = r.start;
    const page = curPage();
    const off = (page && page.schedule && page.schedule.days_off) || [];
    $("#cal-range").textContent = `${dm(r.start)} – ${dm(addDays(r.start, 6))} · ${r.items.length} bài · múi giờ ${r.tz}`;
    grid.innerHTML = Array.from({ length: 7 }, (_, i) => {
      const day = addDays(r.start, i);
      const items = r.items.filter((it) => it.date === day);
      const cls = ["cal-day", off.includes(i) ? "off" : "", day === r.today ? "today" : ""].join(" ").trim();
      const body = items.length ? items.map((it) => {
        const c = it.publish_status === "published" ? "ok" : ["error", "missing"].includes(it.publish_status) ? "bad" : it.overdue ? "warn" : "";
        const link = safeLink(it.permalink);
        const title = link ? `<a href="${esc(link)}" target="_blank" rel="noopener noreferrer">${esc(it.title)}</a>` : esc(it.title);
        const note = it.publish_status === "published" ? "Đã đăng" : c === "bad" ? "Lỗi đăng" : it.overdue ? "Quá giờ chưa đăng" : "Đã hẹn";
        const acts = canManage({ scheduled: it.when, publish_status: it.publish_status })
          ? `<span class="cal-acts"><button class="link retime" type="button">Đổi giờ</button> <button class="link cancelsch" type="button">Huỷ lịch</button></span>` : "";
        return `<div class="cal-item ${c}" title="${esc(it.title)}" data-rel="${esc(it.rel)}" data-when="${esc(it.when)}"><b>${esc(it.time)}</b> ${title}<small>${esc(note)}</small>${acts}</div>`;
      }).join("") : '<span class="cal-none">Trống</span>';
      return `<div class="${cls}"><h3>${DAY_SHORT[i]} <small>${dm(day)}${off.includes(i) ? " · nghỉ" : ""}${items.length ? ` · ${items.length} bài` : ""}</small></h3>${body}</div>`;
    }).join("");
  } catch (e) {
    grid.innerHTML = `<p class="msg bad">${esc(e.message)}</p>`;
  }
}
$("#cal-grid").addEventListener("click", (e) => {
  const item = e.target.closest(".cal-item");
  if (!item) return;
  if (e.target.classList.contains("cancelsch")) cancelSched(item.dataset.rel);
  if (e.target.classList.contains("retime")) openRetime(item.dataset.rel, item.getAttribute("title"), item.dataset.when);
});
$("#cal-prev").addEventListener("click", () => { if (cal.start) cal.start = addDays(cal.start, -7); loadCalendar(); });
$("#cal-next").addEventListener("click", () => { if (cal.start) cal.start = addDays(cal.start, 7); loadCalendar(); });
$("#cal-today").addEventListener("click", () => { cal.start = ""; loadCalendar(); });

/* ---------- Nhật ký ---------- */
let jobsTimer = null;
async function loadJobs() {
  clearTimeout(jobsTimer);
  try {
    const all = await api("/api/jobs");
    const jobs = app.page ? all.filter((j) => j.page_id === app.page) : all;   // trong Page chỉ thấy tác vụ của Page đó
    $("#jobs-list").innerHTML = jobs.length
      ? jobs.map((j) => `
        <div class="job" data-id="${j.id}">
          <span class="t">${esc(j.title)}</span>
          <span class="s">${esc(j.created)}</span>
          <span class="s ${j.status}">${esc(STATUS_LABEL[j.status] || j.status)}${j.progress.total ? ` ${j.progress.done}/${j.progress.total}` : ""}</span>
        </div>`).join("")
      : `<p class="hint">${app.page ? "Fanpage này chưa có tác vụ nào." : "Chưa có tác vụ nào."}</p>`;
  } catch (e) { /* bỏ qua */ }
  if ($("#tab-jobs").classList.contains("active")) jobsTimer = setTimeout(loadJobs, 3000);
}
$("#jobs-list").addEventListener("click", (e) => {
  const row = e.target.closest(".job");
  if (row) follow(row.dataset.id, $("#jobs-log"), null, null);
});

/* ---------- Thống kê bài đăng (chỉ đọc dữ liệu trong app, không gọi Facebook) ---------- */
const COMMENT_LABEL = { done: "Đã comment", pending: "Chờ comment", retry: "Sẽ thử lại", error: "Comment lỗi", expired: "Quá hạn comment", skipped: "Bỏ qua", none: "Không có comment" };
function stBars(rows, kind) {
  const max = Math.max(1, ...rows.map((r) => Math.max(r.n, r.target)));
  return rows.map((r) => {
    const miss = kind === "back" && !r.off && r.n < r.target && r.date !== stState.today;
    const cls = r.n >= r.target && r.n > 0 ? "ok" : miss ? "warn" : "";
    const label = `${DAY_SHORT[r.weekday]} ${dm(r.date)}${r.date === stState.today ? " · nay" : ""}`;
    const text = r.off ? (r.n ? `${r.n} (ngày nghỉ)` : "nghỉ") : r.target ? `${r.n}/${r.target}` : String(r.n);
    return `<div class="st-row${r.off ? " off" : ""}"><span class="st-day">${esc(label)}</span><span class="st-bar" aria-hidden="true"><i class="${cls}" style="width:${Math.round(100 * r.n / max)}%"></i></span><b class="st-n">${esc(text)}</b></div>`;
  }).join("");
}
const stState = { today: "" };
function renderStats(d) {
  stState.today = d.today;
  const c = d.counts, p = d.published, q = d.queue, b = d.budget, cm = d.comments, cn = d.cancelled;
  const card = (n, label, sub = "", cls = "") => `<div class="st-card ${cls}"><b>${esc(n)}</b><span>${esc(label)}</span>${sub ? `<small>${esc(sub)}</small>` : ""}</div>`;
  const pr = d.problems, bad = pr.error + pr.missing + pr.unconfirmed;
  const notes = [];
  if (!d.per_day) notes.push("Page này chưa có khung giờ đăng (thêm ở Cài đặt Page > Quy tắc đăng) nên chưa so được với mục tiêu mỗi ngày.");
  if (bad) {
    const parts = [pr.error && `${pr.error} bài lỗi`, pr.missing && `${pr.missing} bài không thấy trên Facebook`, pr.unconfirmed && `${pr.unconfirmed} bài đã tới giờ mà chưa xác nhận đã đăng`].filter(Boolean);
    notes.push(`Có ${parts.join(", ")}. Nên bấm "Kiểm tra trạng thái" ở Thư viện và xử lý trước khi hẹn thêm, vì tỷ lệ đăng thành công bên dưới tính cả các bài này.`);
  }
  const until = q.until ? `${q.until.slice(8, 10)}/${q.until.slice(5, 7)}` : "";
  const runway = q.runway_days == null ? "Chưa tính được số ngày còn bài (Page chưa có khung giờ đăng)." :
    `Page còn đủ bài cho khoảng ${q.runway_days} ngày: ${until ? `lịch đã hẹn đến ${until}` : "chưa hẹn bài nào"}, kho ${q.new} video chưa lên lịch đủ ${q.stock_days} ngày${q.unusable ? ` (${q.unusable} video không đạt Reels không tính)` : ""}.`;
  const lim = [];
  if (b.cap) lim.push(`giới hạn ${b.cap} video/24 giờ: còn ${b.cap_left}/${b.cap}`);
  lim.push(b.fb_paused_minutes ? `Facebook đang giới hạn, app tạm dừng ${b.fb_paused_minutes} phút` : `lượt gọi Facebook: ${b.fb_used}/${b.fb_budget} đã dùng trong giờ này, mỗi video tốn ${b.per_video} lượt`);
  const can = b.can_schedule_now > 0
    ? `Hiện hẹn được thêm tối đa <b>${b.can_schedule_now}</b> video (${esc(lim.join("; "))}).`
    : `Hiện <b>chưa hẹn thêm được</b> (${esc(lim.join("; "))})${!b.fb_paused_minutes && b.next_free_minutes ? `. Có thể hẹn tiếp sau khoảng ${b.next_free_minutes} phút` : ""}.`;
  const reasons = cn.reasons.length ? ` (${cn.reasons.map((r) => `${esc(r.label)}: ${r.n}`).join("; ")})` : "";
  const cmText = !cm.enabled && !cm.wanted ? "Page này đang tắt tự động comment." :
    cm.wanted ? `Đã comment <b>${cm.done}/${cm.wanted}</b> bài đã đăng${cm.rate == null ? "" : ` (${cm.rate}%)`}. Đang chờ ${cm.waiting}, lỗi ${cm.failed}, quá hạn ${cm.expired}.${cm.skipped ? ` Bỏ qua ${cm.skipped} (bài lỗi hoặc không thấy).` : ""}` :
    "Chưa có bài đã đăng nào cần comment.";
  const chRows = d.channels.map((x) => `<tr><td>${esc(x.name)}</td><td>${x.total}</td><td>${x.new}</td><td>${x.pending}</td><td>${x.published}</td><td${x.problem ? ' class="bad"' : ""}>${x.problem}</td></tr>`).join("");
  const recent = d.recent.length ? d.recent.map((r) => {
    const link = safeLink(r.permalink);
    const title = link ? `<a href="${esc(link)}" target="_blank" rel="noopener noreferrer">${esc(r.title)}</a>` : esc(r.title);
    return `<li><b>${esc(fmtShort(r.when, d.tz))}</b> ${title} <small>${esc(COMMENT_LABEL[r.comment_status] || r.comment_status)}</small></li>`;
  }).join("") : '<li class="muted">Chưa có bài nào được xác nhận đã đăng.</li>';
  $("#st-root").innerHTML = `
    <div class="st-cards">
      ${card(p.total, "Đã đăng", `${p.last7} bài trong 7 ngày qua (${String(p.avg_per_day7).replace(".", ",")}/ngày), ${p.last30} bài trong 30 ngày`)}
      ${card(p.success_rate == null ? "-" : p.success_rate + "%", "Đăng thành công", p.judged ? `${p.total}/${p.judged} bài đã tới giờ` : "Chưa có bài nào tới giờ", p.success_rate != null && p.success_rate < 80 ? "bad" : "")}
      ${card(c.pending, "Chờ đăng", q.next7 ? `${q.next7} bài trong 7 ngày tới` : "")}
      ${card(c.new, "Chưa lên lịch", q.unusable ? `${q.unusable} không đạt Reels` : "")}
      ${card(c.problem, "Lỗi / quá giờ", "", c.problem ? "bad" : "")}
    </div>
    <div class="panel st-plan">
      <h3>Trước khi hẹn thêm</h3>
      <p class="${q.level === "low" ? "bad" : ""}">${esc(runway)}</p>
      <p>${can}</p>
      ${notes.map((n) => `<p class="bad">${esc(n)}</p>`).join("")}
    </div>
    <div class="st-two">
      <div class="panel"><h3>Đã đăng ${d.back.length} ngày qua</h3><p class="hint">Số bài đã đăng / số bài mục tiêu mỗi ngày theo quy tắc của Page. Vàng: ngày đã qua mà chưa đủ.</p>${stBars(d.back, "back")}</div>
      <div class="panel"><h3>Sắp đăng ${d.ahead.length} ngày tới</h3><p class="hint">Số bài đã hẹn / số bài mục tiêu mỗi ngày. Ngày trống là chỗ còn nhận thêm bài.</p>${stBars(d.ahead, "ahead")}</div>
    </div>
    <div class="st-two">
      <div class="panel"><h3>Comment affiliate</h3><p>${cmText}</p></div>
      <div class="panel"><h3>Huỷ lịch ${cn.days} ngày qua</h3><p>${cn.recent ? `<b>${cn.recent}</b> bài${reasons}.` : "Không có bài nào bị huỷ hoặc gỡ lịch."}</p></div>
    </div>
    <div class="panel"><h3>Theo thư mục kênh</h3>
      <table class="st-table"><thead><tr><th>Kênh</th><th>Video</th><th>Chưa lên lịch</th><th>Chờ đăng</th><th>Đã đăng</th><th>Lỗi</th></tr></thead><tbody>${chRows || '<tr><td colspan="6" class="muted">Chưa có video.</td></tr>'}</tbody></table>
    </div>
    <div class="panel"><h3>Đã đăng gần đây</h3><ul class="st-recent">${recent}</ul></div>`;
}
async function loadStats() {
  await loadPages();
  renderCtx();
  const pageId = app.page;
  const root = $("#st-root");
  if (!root.children.length) root.innerHTML = '<p class="hint">Đang tính...</p>';
  try {
    const d = await api("/api/stats?" + new URLSearchParams({ page_id: pageId }));
    if (pageId !== app.page || app.tab !== "stats") return;
    renderStats(d);
    $("#st-info").textContent = `Cập nhật ${new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" })} · múi giờ ${d.tz}`;
  } catch (e) {
    root.innerHTML = `<p class="msg bad">${esc(e.message)}</p>`;
  }
}
$("#st-refresh").addEventListener("click", loadStats);

/* ---------- Tổng quan ---------- */
const ov = { pages: [], unassigned: [] };
async function loadOverview() {
  try {
    const [d] = await Promise.all([api("/api/overview"), loadPages()]);
    ov.pages = d.pages;
    ov.unassigned = d.unassigned;
    renderOverview();
  } catch (e) {
    toast(e.message);
  }
}

function ovNext(p) {
  return p.next_post ? `Bài kế tiếp: ${fmtShort(p.next_post, pageTz(p))}` : "Chưa có bài nào đang chờ đăng";
}
function stockLine(p) {
  const s = p.stock;
  if (!s || s.level === "unknown") return "Chưa có khung giờ đăng nên chưa tính được kho video (thêm ở tab Cài đặt Page).";
  const until = s.queue_until ? `Lịch đã hẹn đến ${s.queue_until.slice(8, 10)}/${s.queue_until.slice(5, 7)}` : "Chưa hẹn bài nào";
  const bad = s.unusable ? ` (${s.unusable} video không đạt Reels không tính)` : "";
  return `Kho: ${s.new} video chưa lên lịch${bad}, đủ khoảng ${s.stock_days} ngày (${s.per_day} bài/ngày). ${until}. Tổng cộng Page còn đủ bài cho khoảng ${s.runway_days} ngày.`;
}
function stockBadge(p) {
  const s = p.stock;
  if (!s) return "";
  if (s.level === "low") return `<span class="badge bad" title="Còn đủ bài cho dưới ${s.low_days} ngày">Sắp hết video</span>`;
  if (s.level === "warn") return '<span class="badge warn" title="Kho video còn ít, nên tải thêm">Kho còn ít</span>';
  return "";
}
function renderOverview() {
  const al = $("#ov-alert");
  const lows = ov.pages.filter((p) => p.stock && p.stock.level === "low" && p.videos > 0);
  al.hidden = !lows.length;
  if (lows.length) {
    al.innerHTML = `<h3>Sắp hết video</h3><p class="hint bad">${lows.map((p) => `<b>${esc(p.name)}</b> (còn đủ khoảng ${p.stock.runway_days} ngày)`).join(", ")}. Bấm "Tải video" ở Page tương ứng để tải thêm.</p>`;
  }
  const un = $("#ov-unassigned");
  un.hidden = !ov.unassigned.length;
  if (ov.unassigned.length) {
    const opts = pg.list.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("");
    un.innerHTML = `
      <h3>Thư mục chưa thuộc Fanpage nào</h3>
      <p class="hint">Mỗi thư mục chỉ thuộc đúng một Fanpage. Chọn Fanpage rồi bấm Gán. Thư mục chưa gán không hiện trong Thư viện của Page nào.</p>
      ${ov.unassigned.map((i) => {
        const names = (i.pages || []).map((id) => (pg.list.find((p) => p.id === id) || {}).name || id);
        const multi = names.length > 1;
        return `<div class="ov-un" data-name="${esc(i.name)}">
          <span><b>${esc(i.name)}</b> · ${i.videos} video${i.scheduled ? `, ${i.scheduled} đã hẹn` : ""}${multi ? `<br><small class="bad">Có video đã hẹn cho nhiều Page (${esc(names.join(", "))}). Hãy hẹn lại hoặc chờ đăng xong để gán.</small>` : ""}</span>
          <select aria-label="Fanpage cho thư mục ${esc(i.name)}"${multi ? " disabled" : ""}>${opts}</select>
          <button class="ghost ov-assign" type="button"${multi ? " disabled" : ""}>Gán</button>
        </div>`;
      }).join("")}
      <p class="msg" id="ov-msg"></p>`;
  }
  $("#ov-empty").hidden = ov.pages.length > 0;
  $("#ov-grid").innerHTML = ov.pages.map((p) => {
    const c = p.counts, t = p.today;
    const stat = (n, label, cls = "") => `<div class="${cls}"><b>${n}</b><small>${label}</small></div>`;
    return `
    <article class="ov-card" data-id="${esc(p.id)}">
      <div class="ov-head">
        <h3>${esc(p.name)}</h3>
        <div class="badges">
          <span class="badge ${p.has_token ? "ok" : "warn"}">${p.has_token ? "Đã có token" : "Chưa có token"}</span>
          ${p.auto_comment ? '<span class="badge ok">Tự động comment</span>' : ""}
          ${stockBadge(p)}
          ${p.blocked_until ? `<span class="badge warn" title="${esc(p.blocked_reason)}">Facebook giới hạn đến ${esc(fmtShort(p.blocked_until, pageTz(p)))}</span>` : ""}
        </div>
      </div>
      <div class="ov-stats">
        ${stat(`${t.scheduled}${t.per_day ? "/" + t.per_day : ""}`, "Bài hôm nay")}
        ${stat(c.pending, "Chờ đăng")}
        ${stat(c.new, "Chưa lên lịch")}
        ${stat(c.published, "Đã đăng")}
        ${stat(c.problem, "Lỗi / quá giờ", c.problem ? "bad" : "")}
      </div>
      <p class="sub${p.stock && p.stock.level === "low" ? " bad" : ""}">${esc(stockLine(p))}</p>
      <p class="sub">${esc(ovNext(p))}. Đã hẹn ${p.used_24h}${p.cap ? "/" + p.cap : ""} video trong 24 giờ qua. ${p.folders} thư mục, ${p.videos} video. Múi giờ ${esc(pageTz(p))}.</p>
      <div class="actions">
        <button class="primary ov-open" type="button">Mở Page</button>
        <button class="ghost ov-dl" type="button">Tải video</button>
        <button class="ghost ov-cal" type="button">Lịch</button>
      </div>
    </article>`;
  }).join("");
}
$("#ov-grid").addEventListener("click", (e) => {
  const card = e.target.closest(".ov-card");
  if (!card) return;
  const t = e.target.classList;
  if (t.contains("ov-open")) showPageTab(card.dataset.id, "library");
  else if (t.contains("ov-dl")) showPageTab(card.dataset.id, "download");
  else if (t.contains("ov-cal")) showPageTab(card.dataset.id, "calendar");
});
$("#ov-unassigned").addEventListener("click", async (e) => {
  const btn = e.target.closest(".ov-assign");
  if (!btn) return;
  const row = btn.closest(".ov-un");
  const m = $("#ov-msg");
  try {
    await api("/api/channels/assign", "POST", { name: row.dataset.name, page_id: $("select", row).value });
    toast(`Đã gán thư mục "${row.dataset.name}".`);
    loadOverview();
  } catch (err) {
    m.textContent = err.message;
    m.className = "msg bad";
  }
});

/* ---------- Khởi động ---------- */
initSchedForm();
async function route() {
  const [t, a, b] = (location.hash.replace("#", "") || "overview").split("/");
  if (t === "p" && a) await showPageTab(decodeURIComponent(a), b);
  else await showView(t, a);
}
loadPages().then(route);
window.addEventListener("hashchange", route);   // địa chỉ sửa tay hoặc dán vào (các lần chuyển trang của app dùng replaceState nên không gọi lại)
