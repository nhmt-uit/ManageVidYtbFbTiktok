/*
 * Gom link các bài trên trang cá nhân Rednote (chạy trong Console của Chrome).
 *
 * Cách dùng:
 *  1. Đăng nhập Rednote trong Chrome, mở trang cá nhân cần lấy (chỉ trang của bạn hoặc người cho phép).
 *  2. Bấm F12 (hoặc Cmd+Option+J) -> tab Console. Nếu Chrome chặn dán, gõ: allow pasting  rồi Enter.
 *  3. Dán toàn bộ file này, Enter. Một bảng nhỏ hiện ở góc phải trên cùng trang.
 *  4. Script tự cuộn CHẬM đến cuối trang để tải hết bài (có thể bấm "Dừng" bất cứ lúc nào).
 *  5. Bấm "Chép" để chép link vào clipboard, rồi dán vào tab "Tải video" của ManageVideosTool.
 *
 * Script chỉ đọc các link đang có trên trang, không gửi dữ liệu đi đâu, không đọc cookie/mật khẩu.
 */
(() => {
  const DELAY_MIN = 1800;     // ms nghỉ tối thiểu giữa 2 lần cuộn (cuộn chậm để tránh bị Rednote khóa)
  const DELAY_MAX = 3500;     // ms nghỉ tối đa
  const STEP = 0.7;           // mỗi lần cuộn bao nhiêu phần chiều cao màn hình
  const IDLE_LIMIT = 8;       // số lần cuộn liên tiếp không có bài mới thì coi như đã hết
  const MAX_STEPS = 800;      // chặn an toàn
  const BATCH = 100;          // mỗi nút "Chép" lấy tối đa bấy nhiêu link (app nhận tối đa 1000 link một lần)

  if (window.__rnCollector) { window.__rnCollector.stop(); document.getElementById("rn-collector")?.remove(); }

  const found = new Map();    // id -> link
  const ID = /\/(?:explore|discovery\/item|user\/profile\/[0-9a-f]+)\/([0-9a-f]{24})(?=[/?#]|$)/i;
  let stopped = false, steps = 0;

  const collect = () => {
    let added = 0;
    for (const a of document.querySelectorAll("a[href]")) {
      let u;
      try { u = new URL(a.getAttribute("href"), location.href); } catch { continue; }
      const m = ID.exec(u.pathname);
      if (!m) continue;
      const id = m[1].toLowerCase();
      const token = u.searchParams.get("xsec_token");
      const link = "https://www.xiaohongshu.com/explore/" + id + (token ? "?xsec_token=" + encodeURIComponent(token) + "&xsec_source=pc_user" : "");
      const old = found.get(id);
      if (!old) { found.set(id, link); added++; }
      else if (!old.includes("xsec_token") && token) found.set(id, link);   // ưu tiên link có token
    }
    return added;
  };

  // ---- bảng điều khiển nhỏ ----
  const box = document.createElement("div");
  box.id = "rn-collector";
  box.style.cssText = "position:fixed;top:12px;right:12px;z-index:2147483647;background:#fff;color:#222;border:1px solid #bbb;border-radius:10px;padding:10px 12px;font:13px/1.4 system-ui,sans-serif;box-shadow:0 4px 18px rgba(0,0,0,.25);width:250px";
  box.innerHTML = '<b>Gom link Rednote</b><div id="rn-st" style="margin:6px 0">Đang bắt đầu…</div><div id="rn-bt" style="display:flex;flex-wrap:wrap;gap:6px"></div>';
  document.body.appendChild(box);
  const st = box.querySelector("#rn-st"), bt = box.querySelector("#rn-bt");
  const button = (text, fn) => { const b = document.createElement("button"); b.textContent = text; b.style.cssText = "padding:4px 8px;border:1px solid #888;border-radius:6px;background:#f4f4f4;cursor:pointer"; b.onclick = fn; bt.appendChild(b); return b; };
  const say = (t) => { st.textContent = t; };

  const copy = async (text, label) => {
    try { await navigator.clipboard.writeText(text); say("Đã chép " + label + ". Dán vào ô link trong app."); }
    catch {
      const ta = document.createElement("textarea"); ta.value = text; ta.style.cssText = "position:fixed;left:-9999px"; document.body.appendChild(ta); ta.select();
      const ok = document.execCommand("copy"); ta.remove();
      say(ok ? "Đã chép " + label + ". Dán vào ô link trong app." : "Không chép được, hãy dùng nút Tải file .txt");
    }
  };

  const showResult = () => {
    bt.innerHTML = "";
    const all = [...found.values()];
    say("Xong: " + all.length + " bài. (Gồm cả video và ảnh; app sẽ lọc theo mục 'Nội dung' bạn chọn.)");
    if (!all.length) return;
    for (let i = 0; i < all.length; i += BATCH) {
      const part = all.slice(i, i + BATCH);
      button(all.length > BATCH ? "Chép " + (i + 1) + "–" + (i + part.length) : "Chép " + all.length + " link", () => copy(part.join("\n"), part.length + " link"));
    }
    button("Tải file .txt", () => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([all.join("\n")], { type: "text/plain" }));
      a.download = "rednote_links.txt"; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    });
    button("Đóng", () => box.remove());
  };

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  window.__rnCollector = { stop() { stopped = true; } };
  button("Dừng", () => { stopped = true; say("Đang dừng…"); });

  (async () => {
    collect();
    let idle = 0;
    while (!stopped && steps < MAX_STEPS && idle < IDLE_LIMIT) {
      steps++;
      const before = window.scrollY;
      window.scrollBy(0, Math.max(200, window.innerHeight * STEP));
      await sleep(DELAY_MIN + Math.random() * (DELAY_MAX - DELAY_MIN));
      const added = collect();
      const atBottom = window.scrollY === before || window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4;
      idle = added === 0 && atBottom ? idle + 1 : (added ? 0 : idle);
      say("Đang cuộn… đã thấy " + found.size + " bài");
    }
    collect();
    if (!stopped && idle < IDLE_LIMIT && steps >= MAX_STEPS) say("Đạt giới hạn cuộn, chép kết quả bên dưới.");
    showResult();
  })();
})();
