/* תפריט נגישות פשוט, בלי ספריות חיצוניות. ההגדרות נשמרות בדפדפן של הגולש. */
(function () {
  var KEY = "yg-a11y";
  var state = { scale: 1, contrast: false, links: false, still: false };
  try { Object.assign(state, JSON.parse(localStorage.getItem(KEY) || "{}")); } catch (e) {}

  var css = ""
    + ".a11y-btn{position:fixed;bottom:12px;left:12px;z-index:50;width:42px;height:42px;opacity:.85;border-radius:50%;border:0;"
    + "background:#0b1f3a;color:#fff;display:grid;place-items:center;cursor:pointer;box-shadow:0 6px 18px -6px rgba(0,0,0,.5)}"
    + ".a11y-btn:focus-visible,.a11y-panel button:focus-visible,.a11y-panel a:focus-visible{outline:3px solid #ffb703;outline-offset:2px}"
    + ".a11y-panel{position:fixed;bottom:62px;left:12px;z-index:50;width:250px;background:#fff;color:#0a2342;border-radius:14px;"
    + "box-shadow:0 12px 30px -8px rgba(0,0,0,.45);padding:14px;font:600 16px/1.4 Assistant,system-ui,Arial,sans-serif;direction:rtl}"
    + ".a11y-panel[hidden]{display:none}"
    + ".a11y-panel h2{font-size:18px;margin:0 0 10px}"
    + ".a11y-panel .row{display:flex;gap:6px;margin-bottom:8px}"
    + ".a11y-panel button{flex:1;font:inherit;padding:9px 8px;border-radius:9px;border:1.5px solid #d3e1ec;background:#f6f9fc;color:#0a2342;cursor:pointer;text-align:right}"
    + ".a11y-panel button[aria-pressed=true]{background:#0a2342;color:#fff;border-color:#0a2342}"
    + ".a11y-panel .tog{display:block;width:100%;margin-bottom:6px}"
    + ".a11y-panel a{display:block;margin-top:6px;color:#0b4f8a}"
    + "html.a11y-contrast body{filter:contrast(1.35)}"
    + "html.a11y-links a{text-decoration:underline !important;outline:2px dashed #ffb703;outline-offset:2px}"
    + "html.a11y-still *,html.a11y-still *::before,html.a11y-still *::after{animation:none !important;transition:none !important}"
    + ".a11y-btn:hover,.a11y-btn:focus-visible{opacity:1}";
  var style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} }
  function apply() {
    var html = document.documentElement;
    document.body.style.zoom = state.scale === 1 ? "" : String(state.scale);
    html.classList.toggle("a11y-contrast", !!state.contrast);
    html.classList.toggle("a11y-links", !!state.links);
    html.classList.toggle("a11y-still", !!state.still);
    if (panel) {
      panel.querySelector("[data-t=contrast]").setAttribute("aria-pressed", !!state.contrast);
      panel.querySelector("[data-t=links]").setAttribute("aria-pressed", !!state.links);
      panel.querySelector("[data-t=still]").setAttribute("aria-pressed", !!state.still);
      panel.querySelector(".size").textContent = "גודל טקסט: " + Math.round(state.scale * 100) + "%";
    }
  }

  var btn = document.createElement("button");
  btn.className = "a11y-btn";
  btn.type = "button";
  btn.setAttribute("aria-label", "תפריט נגישות");
  btn.setAttribute("aria-expanded", "false");
  btn.setAttribute("aria-controls", "a11y-panel");
  btn.innerHTML = '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="16" cy="4" r="1"/><path d="m18 19 1-7-6 1"/><path d="m5 8 3-3 5.5 3-2.36 3.5"/><path d="M4.24 14.5a5 5 0 0 0 6.88 6"/><path d="M13.76 17.5a5 5 0 0 0-6.88-6"/></svg>';

  var panel = document.createElement("div");
  panel.className = "a11y-panel";
  panel.id = "a11y-panel";
  panel.hidden = true;
  panel.setAttribute("role", "region");
  panel.setAttribute("aria-label", "תפריט נגישות");
  panel.innerHTML = ""
    + "<h2>נגישות</h2>"
    + "<p class='size' style='margin:0 0 6px' aria-live='polite'></p>"
    + "<div class='row'><button type='button' data-a='bigger'>הגדלת טקסט +</button>"
    + "<button type='button' data-a='smaller'>הקטנת טקסט −</button></div>"
    + "<button type='button' class='tog' data-t='contrast' aria-pressed='false'>ניגודיות גבוהה</button>"
    + "<button type='button' class='tog' data-t='links' aria-pressed='false'>הדגשת קישורים</button>"
    + "<button type='button' class='tog' data-t='still' aria-pressed='false'>עצירת אנימציות</button>"
    + "<button type='button' class='tog' data-a='reset'>איפוס הגדרות</button>"
    + "<a href='accessibility.html'>הצהרת נגישות</a>";

  document.body.appendChild(btn);
  document.body.appendChild(panel);

  function setOpen(open) {
    panel.hidden = !open;
    btn.setAttribute("aria-expanded", String(open));
    if (open) panel.querySelector("button").focus();
  }
  btn.addEventListener("click", function () { setOpen(panel.hidden); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !panel.hidden) { setOpen(false); btn.focus(); }
  });
  panel.addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (!b) return;
    var a = b.getAttribute("data-a"), t = b.getAttribute("data-t");
    if (a === "bigger") state.scale = Math.min(1.6, Math.round((state.scale + 0.1) * 10) / 10);
    if (a === "smaller") state.scale = Math.max(0.9, Math.round((state.scale - 0.1) * 10) / 10);
    if (a === "reset") state = { scale: 1, contrast: false, links: false, still: false };
    if (t) state[t] = !state[t];
    save(); apply();
  });
  apply();
})();
