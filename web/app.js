"use strict";

/* ===================== helpers ===================== */
const $ = (sel, root = document) => root.querySelector(sel);
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage may be blocked */ } },
};
/** sessionStorage: what the app was showing, so a reload or a return from another app lands in the same place. */
const session = {
  get(k, d) { try { const v = sessionStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } },
  set(k, v) { try { sessionStorage.setItem(k, v); } catch (e) { /* storage may be blocked */ } },
  del(k) { try { sessionStorage.removeItem(k); } catch (e) { /* storage may be blocked */ } },
};
const UA = navigator.userAgent;
const isIOS = /iPad|iPhone|iPod/.test(UA) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const isAndroid = /Android/.test(UA);
const isStandalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
document.documentElement.classList.add(isIOS ? "ios" : isAndroid ? "android" : "desktop");
if (isStandalone) document.documentElement.classList.add("standalone");
const buzz = (pattern = 8) => { try { if (navigator.vibrate) navigator.vibrate(pattern); } catch (e) { /* not supported */ } };
const localDay = (d = new Date()) => d.toLocaleDateString("en-CA");
const fadeIn = (el) => { if (el && el.animate) el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 160, easing: "ease-out" }); };

let S = null;            // latest state from the server
let tab = session.get("sootable-tab", "home");
let range = [30, 365, 1000].includes(Number(store.get("sootable-range"))) ? Number(store.get("sootable-range")) : 30;   // chart range in days
let trendCache = {};     // range -> {days, text}
let historyData = null;
let alertsData = null;
let dev = store.get("sootable-dev") === "1" || /[?&]dev=1|#dev/.test(location.href);
let lastShown = null;    // the value the home scale last animated to
let versionTaps = 0;
let scrollPos = {};      // remembered scroll position per tab
try { scrollPos = JSON.parse(session.get("sootable-scroll", "{}")) || {}; } catch (e) { scrollPos = {}; }
let restoring = true;    // the first screen after a reload goes back to where it was scrolled
let measuring = false;   // a reading is in progress, so background updates stay out of the way

let online = true;
function setOnline(ok) {
  if (ok === online) return;
  online = ok;
  const bar = $("#banner");
  if (bar) bar.hidden = ok;
  if (ok && S) pollState();   // back online: catch up on whatever changed
}

async function api(path, method = "GET", body) {
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    setOnline(false);          // the server itself could not be reached
    throw e;
  }
  setOnline(true);
  if (!res.ok) throw new Error((await res.text()) || res.statusText);
  return res.json();
}

const ICON = {
  home: '<path d="M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
  trend: '<path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/>',
  bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
  bellOff: '<path d="M18 8a6 6 0 0 0-9.3-5M6 8c0 7-3 9-3 9h13M13.7 21a2 2 0 0 1-3.4 0M3 3l18 18"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  bt: '<path d="M7 7l10 10-5 5V2l5 5L7 17"/>',
  chev: '<path d="M6 9l6 6 6-6"/>',
  back: '<path d="M15 5l-7 7 7 7"/>',
  measure: '<circle cx="12" cy="12" r="3.2"/><path d="M12 2.5v4M12 17.5v4M2.5 12h4M17.5 12h4"/>',
  sunrise: '<path d="M3 19h18M6.5 15a5.5 5.5 0 0 1 11 0M12 4v4M4.6 8.6l2 2M19.4 8.6l-2 2M9 6l3-3 3 3"/>',
  sunset: '<path d="M3 19h18M6.5 15a5.5 5.5 0 0 1 11 0M12 4v4M4.6 8.6l2 2M19.4 8.6l-2 2M9 5l3 3 3-3"/>',
  moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
};
const svgIcon = (name) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[name]}</svg>`;
const ARROW = { up: "&#8599;", down: "&#8600;", flat: "&#8594;" };

/* ---- vehicle line art: four kinds, drawn at 120 x 60 ---- */
const KINDS = ["car", "suv", "truck", "auto"];
const KIND_NAME = { car: "Car", suv: "SUV or MUV", truck: "Truck or bus", auto: "Auto" };
const KIND_HINT = { car: "Sedan, hatchback", suv: "Innova, Scorpio", truck: "Goods, bus", auto: "Three-wheeler" };
const KIND_DEFAULT = { car: "My car", suv: "My SUV", truck: "My truck", auto: "My auto" };
const KIND_IDEAS = { car: ["My car", "Family car", "Office car"], suv: ["My SUV", "Dad's SUV", "Family SUV"], truck: ["Tipper", "Delivery truck", "Bus 1"], auto: ["My auto", "Rickshaw"] };
const wheel = (cx, cy, r = 9) => `<circle cx="${cx}" cy="${cy}" r="${r}" style="fill:var(--wheel,#333)"/><circle cx="${cx}" cy="${cy}" r="2.4" fill="currentColor" stroke="none"/>`;
const ART = {
  car: `<path d="M8 47V38q0-5 5-6.500l19-5 14-13q2-2 6-2h26q4 0 6 3l10 14 13 3q5 1 5 6.500V47"/><path d="M50 26l8-12h21l9 12z"/>${wheel(32, 47)}${wheel(90, 47)}`,
  suv: `<path d="M8 47V24q0-6 6-8l14-4h58q5 0 8 4l8 13 8 3q6 1 6 7v8"/><path d="M26 28V17h22v11zM52 28V17h30l8 11z"/>${wheel(30, 47)}${wheel(92, 47)}`,
  truck: `<rect x="6" y="9" width="64" height="38" rx="3"/><path d="M70 47V22h18l12 13 12 4v8"/><path d="M76 22v11h18"/>${wheel(24, 49)}${wheel(50, 49)}${wheel(98, 49)}`,
  auto: `<path d="M10 47V20q0-9 12-9h46q12 0 17 12l6 14 16 4q5 1 5 7v3"/><path d="M26 22h40l8 14H26z"/>${wheel(28, 49)}${wheel(94, 49)}`,
};
const art = (kind, cls = "") => `<svg class="${cls}" viewBox="0 0 120 60" fill="none" stroke="currentColor" stroke-width="3.4" stroke-linejoin="round" stroke-linecap="round" aria-hidden="true">${ART[kind] || ART.car}</svg>`;

/* ===================== wording ===================== */
const BAND_WORD = { OK: "Good", WATCH: "Close to limit", OVER: "Over limit" };
function band(k, limit) {
  if (k === null || k === undefined) return null;
  const r = Math.round(k * 100) / 100;
  if (r > limit) return "OVER";
  return r >= Math.round(limit * 0.8 * 100) / 100 ? "WATCH" : "OK";
}
const bandColor = (b) => (b === "OVER" ? "#ff6b5e" : b === "WATCH" ? "#ff8a3d" : "#6fd6a1");
const ALERT_TITLE = { WATCH: "Close to the limit", OVER: "Over the legal limit", RISE: "Smoke level rising quickly" };
const ALERT_STATE = { WATCH: ["WATCH", "Close to limit"], RISE: ["WATCH", "Rising"], OVER: ["OVER", "Over limit"] };

function verdictText(s) {
  const limit = s.vehicle.limit_k;
  if (s.status === null) {
    const need = Math.max(0, 3 - s.daily_count);
    return need ? `${need} more daily reading${need > 1 ? "s" : ""} needed for a trend.` : "Each day's reading updates the trend.";
  }
  if (s.status === "OK") return `${Math.round((1 - s.smoothed / limit) * 100)}% below the legal limit.`;
  if (s.status === "WATCH") return `${Math.round((s.smoothed / limit) * 100)}% of the legal limit. A service check is advisable.`;
  return "Above the legal limit. Have the injectors and air filter checked, then get a PUC test.";
}

function trendSentence(s) {
  const avgs = s.chart.map((p, i) => [i, p.avg]).filter((x) => x[1] !== null);
  if (avgs.length < 2 || avgs[avgs.length - 1][0] - avgs[0][0] < 7) return null;
  const d = avgs[avgs.length - 1][1] - avgs[0][1];
  const span = avgs[avgs.length - 1][0] - avgs[0][0] + 1;
  if (Math.abs(d) < 0.05) return { icon: "flat", text: `Steady over ${span} days` };
  return d > 0 ? { icon: "up", text: `Up ${d.toFixed(2)} over ${span} days` } : { icon: "down", text: `Down ${Math.abs(d).toFixed(2)} over ${span} days` };
}

const parseLocal = (iso) => new Date(iso);
function fmtWhen(iso) {
  const d = parseLocal(iso), now = new Date();
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const days = Math.round((new Date(now.toDateString()) - new Date(d.toDateString())) / 86400000);
  if (days === 0) return `today, ${time}`;
  if (days === 1) return `yesterday, ${time}`;
  return `${d.toLocaleDateString([], { day: "numeric", month: "short" })}, ${time}`;
}
const fmtDay = (day, opts) => new Date(day + "T00:00:00").toLocaleDateString([], opts);
const fmtSpan = (days) => (days < 14 ? `${days} days` : days < 60 ? `${Math.round(days / 7)} weeks` : `${Math.round(days / 30)} months`);
const manyVehicles = () => S && S.vehicles && S.vehicles.length > 1;

/* ===================== toasts ===================== */
function toast(message, { title = "", tone = "", action = null, ms = 6000 } = {}) {
  for (const old of $("#toasts").children) if (old.textContent.includes(message)) return;   // never stack the same message
  const t = document.createElement("div");
  t.className = `toast ${tone}`;
  t.setAttribute("role", "status");
  t.innerHTML = `<div class="grow">${title ? `<b>${esc(title)}</b><br>` : ""}<span>${esc(message)}</span></div>${action ? `<button>${esc(action.label)}</button>` : ""}`;
  if (action) t.querySelector("button").onclick = () => { action.run(); t.remove(); };
  $("#toasts").append(t);
  setTimeout(() => t.remove(), ms);
}

function notifyNew(alerts) {
  if (!alerts || !alerts.length || store.get("sootable-notify", "1") !== "1") return;
  buzz([14, 50, 14]);
  for (const a of alerts) {
    const title = (manyVehicles() && a.vehicle ? `${a.vehicle}: ` : "") + (ALERT_TITLE[a.type] || "SootAble");
    const open = () => { if (a.vehicle_id && a.vehicle_id !== S.vehicle.id) selectVehicle(a.vehicle_id, "alerts"); else go("alerts"); };
    toast(a.message, { title, tone: a.type, action: { label: "View", run: open }, ms: 9000 });
    try { if ("Notification" in window && Notification.permission === "granted") new Notification(`SootAble: ${title}`, { body: a.message }); } catch (e) { /* optional */ }
  }
}

/* ===================== bottom sheet (inside the app) ===================== */
const layer = $("#sheet"), panel = $(".sheet-panel", layer);
let lastFocus = null;
const sheetOpen = () => !layer.hidden;

function openSheet(html) {
  const first = layer.hidden;
  if (first) lastFocus = document.activeElement;
  layer.classList.remove("closing");
  layer.hidden = false;
  panel.innerHTML = `<div class="grab-area"><div class="grab"></div></div>${html}`;
  panel.style.transform = "";
  panel.scrollTop = 0;
  if (first) panel.focus({ preventScroll: true });
  enableDrag();
}

function closeSheet() {
  if (layer.hidden || layer.classList.contains("closing")) return;
  const done = () => { layer.hidden = true; layer.classList.remove("closing"); panel.style.transform = ""; if (lastFocus && lastFocus.focus) lastFocus.focus({ preventScroll: true }); };
  layer.classList.add("closing");
  setTimeout(done, reduceMotion ? 10 : 170);
}

function enableDrag() {
  const grab = $(".grab-area", panel);
  let y0 = null, dy = 0;
  grab.onpointerdown = (e) => { y0 = e.clientY; dy = 0; grab.setPointerCapture(e.pointerId); panel.style.animation = "none"; panel.style.transition = "none"; };
  grab.onpointermove = (e) => { if (y0 === null) return; dy = Math.max(0, e.clientY - y0); panel.style.transform = `translateY(${dy}px)`; };
  const end = () => {
    if (y0 === null) return;
    y0 = null;
    panel.style.transition = "transform 0.2s ease";
    if (dy > 110) { buzz(6); panel.style.transform = "translateY(100%)"; setTimeout(() => { layer.hidden = true; panel.style.transform = ""; panel.style.animation = ""; panel.style.transition = ""; if (lastFocus && lastFocus.focus) lastFocus.focus({ preventScroll: true }); }, 200); }
    else { panel.style.transform = ""; setTimeout(() => { panel.style.animation = ""; panel.style.transition = ""; }, 210); }
  };
  grab.onpointerup = end;
  grab.onpointercancel = end;
}

layer.addEventListener("click", (e) => {
  if (e.target === layer) { closeSheet(); return; }
  const a = e.target.closest("[data-sheet]");
  if (a) { sheetAction(a.dataset.sheet); return; }
  const sm = e.target.closest("[data-sample]");
  if (sm) { closeSheet(); ob.pairOnly ? useDemoForVehicle(sm.dataset.sample) : finishOnboarding(sm.dataset.sample); return; }
  const vh = e.target.closest("[data-vehicle]");
  if (vh) { selectVehicle(Number(vh.dataset.vehicle)); return; }
  const nk = e.target.closest("[data-newkind]");
  if (nk) { newKind = nk.dataset.newkind; panel.querySelectorAll("[data-newkind]").forEach((k) => k.classList.toggle("sel", k === nk)); return; }
  const ck = e.target.closest("[data-setkind]");
  if (ck) setKind(ck.dataset.setkind);
});
document.addEventListener("keydown", (e) => {
  if (!sheetOpen()) return;
  if (e.key === "Escape") { closeSheet(); return; }
  if (e.key === "Tab") {
    const f = [...panel.querySelectorAll('button, a[href], input, select, summary, [tabindex="0"]')].filter((x) => !x.disabled && x.offsetParent !== null);
    if (!f.length) { e.preventDefault(); return; }
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && (document.activeElement === first || document.activeElement === panel)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
});

function confirmSheet(title, text, confirmLabel, onConfirm, danger = false) {
  openSheet(`<h2>${esc(title)}</h2><p class="muted">${esc(text)}</p>
    <div class="row" style="margin-top:20px"><button class="btn block" data-sheet="close">Cancel</button>
    <button class="btn block ${danger ? "danger" : "primary"}" data-sheet="confirm">${esc(confirmLabel)}</button></div>`);
  panel._confirm = onConfirm;
}

function sheetAction(name) {
  if (name === "close") closeSheet();
  else if (name === "confirm") { const fn = panel._confirm; closeSheet(); fn && fn(); }
  else if (name === "measure-start") measureRun();
  else if (name === "measure-again") measureOpen();
  else if (name === "sync") { closeSheet(); doSync(); }
  else if (name === "add-vehicle") addVehicleSheet();
  else if (name === "add-vehicle-save") addVehicle();
}

/* ===================== shell and routing ===================== */
function setState(s) {
  S = s;
  trendCache = {};
  historyData = null;
  alertsData = null;
}

function showMain() {
  $("#onboarding").hidden = true;
  $("#main").hidden = false;
  go(tab);
}

/** Show a tab. refresh=true re-renders the current tab in place (keeps the scroll position, no fade). */
function go(name, refresh = false) {
  const view = $("#view");
  if (!refresh && name !== tab) scrollPos[tab] = view.scrollTop;
  const keep = refresh ? view.scrollTop : name === tab && !restoring ? 0 : scrollPos[name] || 0;
  restoring = false;
  tab = name;
  session.set("sootable-tab", name);
  renderTabbar();
  renderAppbar();
  const done = () => { view.scrollTop = keep; if (!refresh) fadeIn(view); };
  if (name === "home") { renderHome(view); done(); }
  else if (name === "history") renderHistory(view).then(done);
  else if (name === "alerts") renderAlerts(view).then(done);
  else if (name === "settings") { renderSettings(view); done(); }
  else if (name === "dev") { renderDev(view); done(); }
}
const refresh = () => go(tab, true);

function renderAppbar() {
  const synced = S.device.paired && S.device.last_sync;
  $("#appbar").innerHTML = `
    <button class="vswitch" data-action="vehicles" aria-label="Vehicle: ${esc(S.vehicle.name)}. Switch vehicle">${art(S.vehicle.kind, "vicon")}<span>${esc(S.vehicle.name)}</span>${svgIcon("chev").replace("<svg", '<svg class="chev"')}</button>
    <button class="meterbtn ${synced ? "" : "off"}" data-go="device" aria-label="${S.device.paired ? "Meter connected" : "No meter paired. Pair a meter"}">${svgIcon("bt")}<i></i></button>`;
}

function renderTabbar() {
  const t = (id, label, icon) => `<button class="tab" data-go="${id}" ${tab === id ? 'aria-current="page"' : ""}>${svgIcon(icon)}<span>${label}</span>${id === "alerts" && S && S.alert_count && !store.get(`sootable-seen-${S.vehicle.id}-${S.alert_count}`) ? '<i class="badge"></i>' : ""}</button>`;
  $("#tabbar").innerHTML = t("home", "Home", "home") + t("history", "History", "trend") + t("alerts", "Alerts", "bell") + t("settings", "Settings", "gear");
}

document.addEventListener("click", (e) => {
  if (e.target.closest("button, .btn, .item, a")) buzz(6);
  const g = e.target.closest("[data-go]");
  if (g) { g.dataset.go === "device" ? (S.device.paired ? openDeviceSheet() : startPairing()) : go(g.dataset.go); }
});

/* ===================== vehicles ===================== */
let newKind = "car";

function kindTiles(attr, selected, small = false) {
  return `<div class="kinds ${small ? "small" : ""}">${KINDS.map((k) => `<button class="kind ${k === selected ? "sel" : ""}" ${attr}="${k}">${art(k, "art")}<div><b>${KIND_NAME[k]}</b><span>${KIND_HINT[k]}</span></div></button>`).join("")}</div>`;
}

function openVehicles() {
  const rows = S.vehicles.map((x) => `<button class="item vrow ${x.id === S.vehicle.id ? "on" : ""}" data-vehicle="${x.id}">
      ${art(x.kind, "vicon")}
      <span class="lbl"><b>${esc(x.name)}</b><br>
        <span class="muted small">${x.reading_count ? `${x.status ? BAND_WORD[x.status] + " &middot; " : ""}${x.smoothed !== null ? x.smoothed.toFixed(2) : "no trend yet"}` : "No readings yet"} &middot; ${x.meter ? esc(x.meter) : "no meter"}</span></span>
      <span class="check">${x.id === S.vehicle.id ? "&#10003;" : ""}</span></button>`).join("");
  openSheet(`<h2>Vehicles</h2><p class="muted small">Each vehicle has its own readings, trend and alerts.</p>
    <div class="list">${rows}</div>
    <button class="btn block primary" style="margin-top:18px" data-sheet="add-vehicle">Add vehicle</button>`);
}

function addVehicleSheet() {
  newKind = "car";
  openSheet(`<h2>Add vehicle</h2>
    <div style="margin-top:14px">${kindTiles("data-newkind", "car", true)}</div>
    <label class="field" for="new-vehicle" style="margin-top:18px">Name</label>
    <input id="new-vehicle" type="text" maxlength="40" placeholder="e.g. Dad's Innova" autocomplete="off">
    <div class="row" style="margin-top:20px"><button class="btn block" data-sheet="close">Cancel</button><button class="btn block primary" data-sheet="add-vehicle-save">Add</button></div>`);
}

async function addVehicle() {
  const name = ($("#new-vehicle") || {}).value || "";
  if (!name.trim()) { $("#new-vehicle").focus(); return; }
  closeSheet();
  setState(await api("/api/vehicles", "POST", { name, kind: newKind }));
  lastShown = null; tab = "home";
  startPairing();   // a new vehicle needs its own meter: connect it now
}

function kindSheet() {
  openSheet(`<h2>Vehicle type</h2><p class="muted small">Only changes the picture. The legal limit is the same for all.</p>
    <div style="margin-top:14px">${kindTiles("data-setkind", S.vehicle.kind)}</div>`);
}
async function setKind(kind) {
  setState(await api("/api/settings", "POST", { name: S.vehicle.name, kind }));
  closeSheet(); refresh();
}

async function selectVehicle(id, openTab = null) {
  closeSheet();
  if (id !== S.vehicle.id) { setState(await api("/api/vehicles/select", "POST", { id })); lastShown = null; }
  if (openTab) tab = openTab;
  showMain();
}

/* ===================== Home ===================== */
/** The scale: a ruler with the legal limit marked on it, like the scale on an opacimeter. */
function drawScale(box, value, limit, animate) {
  const W = 320, L = 4, R = 316, y0 = 40;
  const max = Math.ceil(Math.max(3, limit * 1.3, (value || 0) * 1.08) * 2) / 2;
  const x = (v) => L + (Math.min(v, max) / max) * (R - L);
  const aria = value === null ? "No reading yet" : `Smoke level ${value.toFixed(2)} on a scale from 0 to ${max}. Legal limit ${limit}.`;
  let s = `<svg viewBox="0 0 ${W} 80" role="img" aria-label="${aria}">`;
  s += `<rect x="${L}" y="${y0 - 3}" width="${R - L}" height="6" rx="3" fill="#2e2e2e"/>`;
  s += `<rect x="${x(limit)}" y="${y0 - 3}" width="${R - x(limit)}" height="6" rx="3" fill="#ff6b5e" fill-opacity=".3"/>`;
  if (value !== null) s += `<rect class="fill" x="${L}" y="${y0 - 3}" width="${x(value) - L}" height="6" rx="3" fill="${bandColor(band(value, limit))}"/>`;
  for (let t = 0; t <= max + 1e-9; t += 0.25) {
    const X = x(t), major = Math.abs(t - Math.round(t)) < 1e-9;
    s += `<line x1="${X}" x2="${X}" y1="${y0 + 9}" y2="${y0 + (major ? 19 : 14)}" stroke="#4a4a4a"/>`;
    if (major) s += `<text x="${X}" y="${y0 + 32}" text-anchor="${t === 0 ? "start" : "middle"}">${t}</text>`;
  }
  s += `<line x1="${x(limit)}" x2="${x(limit)}" y1="${y0 - 20}" y2="${y0 + 19}" stroke="#ff6b5e" stroke-width="2.5"/>`;
  s += `<text x="${x(limit)}" y="${y0 - 26}" text-anchor="middle" style="fill:#ff6b5e;font-weight:500">LIMIT ${limit}</text>`;
  if (value !== null) s += `<g class="marker" style="transform:translateX(${x(value)}px)"><path d="M0 ${y0 - 6} L-7 ${y0 - 18} L7 ${y0 - 18} Z" fill="#f2f2f2"/></g>`;
  box.innerHTML = s + "</svg>";
  if (animate && value !== null) {
    const m = $(".marker", box), f = $(".fill", box);
    m.style.transform = `translateX(${x(0)}px)`; f.style.width = "0px";
    void box.offsetWidth;
    requestAnimationFrame(() => { m.style.transform = `translateX(${x(value)}px)`; f.style.width = `${x(value) - L}px`; });
  }
}

function sparkline(values, color) {
  const pts = values.map((v, i) => [i, v]).filter((p) => p[1] !== null);
  if (pts.length < 2) return "";
  const lo = Math.min(...pts.map((p) => p[1])), hi = Math.max(...pts.map((p) => p[1])), span = Math.max(hi - lo, 0.25);
  const n = values.length - 1;
  const d = pts.map(([i, v]) => `${((i / n) * 100).toFixed(1)},${(26 - ((v - lo) / span) * 24).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 100 28" preserveAspectRatio="none" aria-hidden="true"><polyline points="${d}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg>`;
}

function emptyHome() {
  if (!S.device.paired) {
    return `<section class="empty">${art(S.vehicle.kind, "art")}
      <h2>No meter connected to ${esc(S.vehicle.name)}</h2>
      <p class="muted">Each vehicle has its own meter. Connect one to start taking readings.</p>
      <button class="btn block primary" data-action="pair-meter">Connect meter</button></section>`;
  }
  return `<section class="empty">${art(S.vehicle.kind, "art")}
      <h2>No readings for ${esc(S.vehicle.name)}</h2>
      <p class="muted">The meter records one reading a day. They appear here when the app syncs with it.</p>
      <button class="btn block primary" data-action="sync">Sync now</button></section>`;
}

function renderHome(view) {
  const s = S, limit = s.vehicle.limit_k;
  if (!s.reading_count) { view.innerHTML = emptyHome(); lastShown = null; return; }
  const ts = trendSentence(s), status = s.status || "NONE";
  const vals = s.chart.map((p) => p.k).filter((k) => k !== null);
  const last7 = s.chart.slice(-7);
  const done7 = last7.filter((d) => d.k !== null).length;
  const since = s.baseline && s.smoothed !== null ? ((s.smoothed - s.baseline) / s.baseline) * 100 : null;
  const notices = [];
  if (!s.device.paired) notices.push(["red", `No meter is connected to ${s.vehicle.name}, so new readings won't arrive. Connect one in Settings.`]);
  if (s.note) notices.push(["", s.note]);
  if (s.clean_reminder) notices.push(["", "Wipe the sensor window clean. You can log it in Settings."]);
  if (s.low_battery) notices.push(["", "The meter's battery is low."]);
  if (s.fault) notices.push(["red", "Meter hardware warning: the fan did not start properly."]);
  const f = s.forecast;

  view.innerHTML = `
    <section class="card hero">
      <div class="rowline"><span class="label">Smoke level${s.scenario ? " &middot; demo data" : ""}</span><span class="pill ${status}">${s.status ? BAND_WORD[s.status] : "No trend yet"}</span></div>
      <div class="numeral"><b id="num">${s.smoothed === null ? "--" : s.smoothed.toFixed(2)}</b><small>m<sup>-1</sup></small></div>
      <p class="status-line">${esc(verdictText(s))}</p>
      <div class="scale" id="scale"></div>
      <div class="rowline" style="margin-top:8px"><span class="meta-line" style="margin:0">${ts ? `<span aria-hidden="true">${ARROW[ts.icon]}</span> ${esc(ts.text)}` : "&nbsp;"}</span><button class="linkbtn" data-action="info">What is this?</button></div>
    </section>
    <section class="tiles">
      <div class="tile"><div><span class="label">Today</span><div class="v">${s.today_done ? "Recorded" : "Waiting"}</div></div>
        <div><div class="dots7" aria-hidden="true">${last7.map((d) => `<i class="${d.k !== null ? "on" : ""}"></i>`).join("")}</div><div class="s">${done7} of 7 days. Last ${esc(fmtWhen(s.last_reading))}</div></div></div>
      <div class="tile"><div><span class="label">7-day average</span><div class="v">${s.smoothed === null ? "--" : s.smoothed.toFixed(2)}</div></div>${sparkline(s.chart.slice(-14).map((p) => p.avg), "#f5a524")}</div>
      <div class="tile"><div><span class="label">Highest, 30 days</span><div class="v">${vals.length ? Math.max(...vals).toFixed(2) : "--"}</div></div><div class="s">${vals.length} readings</div></div>
      <div class="tile"><div><span class="label">Since baseline</span><div class="v">${since === null ? "--" : (since >= 0 ? "+" : "") + Math.round(since) + "%"}</div></div><div class="s">${s.baseline === null ? "Needs 14 days" : `Baseline ${s.baseline.toFixed(2)}`}</div></div>
    </section>
    ${f ? `<section class="card insight"><span class="label">Outlook</span><div style="margin-top:8px"><b>Projected to reach the limit around ${esc(fmtDay(f.date, { day: "numeric", month: "long" }))}</b>
        <p class="muted">In about ${esc(fmtSpan(f.days))} at the current pace. Straight-line projection from the last 60 days of readings.</p></div></section>` : ""}
    ${notices.map(([c, t]) => `<div class="notice ${c}"><p>${esc(t)}</p></div>`).join("")}
    <section class="card chart-card">
      <div class="rowline"><span class="label">Trend</span>
        <div class="tabs" role="group" aria-label="Chart range">${[[30, "30D"], [365, "1Y"], [1000, "All"]].map(([d, l]) => `<button data-range="${d}" aria-pressed="${range === d}">${l}</button>`).join("")}</div></div>
      <div class="chart-well" id="chart-wrap"></div>
      <p class="muted small" id="chart-text" style="margin-top:10px"></p>
    </section>`;
  drawScale($("#scale"), s.smoothed, limit, !reduceMotion && lastShown !== s.smoothed);
  lastShown = s.smoothed;
  loadChart();
}

async function loadChart() {
  let data;
  if (range === 30) data = { days: S.chart, text: S.chart_text };
  else {
    if (!trendCache[range]) trendCache[range] = await api(`/api/trend?days=${range}`);
    data = trendCache[range];
  }
  if (tab !== "home" || !$("#chart-wrap")) return;
  $("#chart-text").textContent = data.text;
  drawChart($("#chart-wrap"), data.days, S.vehicle.limit_k);
}

function drawChart(wrap, data, limit) {
  const W = 600, H = 240, L = 34, R = 8, T = 18, B = 26, n = data.length;
  const all = data.flatMap((d) => [d.k, d.avg]).filter((v) => v !== null);
  // the axis starts just below the data (not at 0) so a slow change is visible; the labels show the scale
  const lo = all.length ? Math.max(0, Math.floor((Math.min(...all, limit * 0.8) - 0.4) * 2) / 2) : 0;
  const top = Math.max(limit * 1.2, ...all) * 1.04;
  const x = (i) => L + (n > 1 ? (i * (W - L - R)) / (n - 1) : 0);
  const y = (v) => H - B - ((v - lo) / (top - lo)) * (H - B - T);
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-labelledby="chart-text">`;
  // the range that is within the limit, shaded like a target range
  svg += `<rect x="${L}" y="${y(limit)}" width="${W - L - R}" height="${H - B - y(limit)}" fill="#6fd6a1" fill-opacity=".07"/>`;
  const step = top - lo > 3 ? 1 : 0.5;
  for (let t = Math.ceil(lo / step) * step; t <= top; t += step) svg += `<line x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}" stroke="#fff" stroke-opacity=".07"/><text x="${L - 8}" y="${y(t) + 3.5}" text-anchor="end">${Number.isInteger(t) ? t : t.toFixed(1)}</text>`;
  for (let j = 0; j < 5 && n > 1; j++) {
    const i = Math.round((j * (n - 1)) / 4);
    const label = n > 60 ? fmtDay(data[i].day, { month: "short", year: "2-digit" }) : fmtDay(data[i].day, { day: "numeric", month: "short" });
    svg += `<text x="${x(i)}" y="${H - 6}" text-anchor="${j === 0 ? "start" : j === 4 ? "end" : "middle"}">${esc(label)}</text>`;
  }
  svg += `<line x1="${L}" x2="${W - R}" y1="${y(limit)}" y2="${y(limit)}" stroke="#ff6b5e" stroke-width="1.5" stroke-dasharray="5 4"/>`;
  // put the label on whichever side the data is farther from the limit line, so it never covers the trend
  const avgs = data.map((d) => d.avg).filter((v) => v !== null);
  const dataOnRight = avgs.length > 1 && Math.abs(avgs[avgs.length - 1] - limit) < Math.abs(avgs[0] - limit);
  svg += `<text x="${dataOnRight ? L + 4 : W - R - 4}" y="${y(limit) - 6}" text-anchor="${dataOnRight ? "start" : "end"}" style="fill:#ff6b5e;font-weight:500">LIMIT ${limit}</text>`;
  let line = "", seg = [];
  const flush = () => { if (seg.length > 1) line += "M" + seg.map(([a, b]) => `${a.toFixed(1)} ${b.toFixed(1)}`).join(" L"); seg = []; };
  data.forEach((d, i) => (d.avg === null ? flush() : seg.push([x(i), y(d.avg)])));
  flush();
  if (line) svg += `<path d="${line}" fill="none" stroke="#f5a524" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>`;
  const r = n > 120 ? 1.5 : n > 45 ? 2.6 : 3.6;
  data.forEach((d, i) => { if (d.k !== null) svg += `<circle cx="${x(i).toFixed(1)}" cy="${y(d.k).toFixed(1)}" r="${r}" fill="${bandColor(band(d.k, limit))}"/>`; });
  svg += `<line id="cursor" y1="${T - 6}" y2="${H - B}" stroke="#f2f2f2" stroke-opacity=".5" visibility="hidden"/></svg><div class="tip" id="tip"></div>`;
  wrap.innerHTML = svg;

  const tip = $("#tip", wrap), cursor = $("#cursor", wrap), svgEl = $("svg", wrap);
  let lastIdx = -1;
  const show = (clientX) => {
    const box = svgEl.getBoundingClientRect();
    const px = ((clientX - box.left) / box.width) * W;
    const i = Math.max(0, Math.min(n - 1, Math.round(((px - L) / (W - L - R)) * (n - 1))));
    const d = data[i];
    if (d.k === null && d.avg === null) { tip.classList.remove("show"); cursor.setAttribute("visibility", "hidden"); return; }
    if (i !== lastIdx) { lastIdx = i; buzz(3); }
    cursor.setAttribute("x1", x(i)); cursor.setAttribute("x2", x(i)); cursor.setAttribute("visibility", "visible");
    const b = band(d.k !== null ? d.k : d.avg, limit);
    tip.innerHTML = `<span class="muted">${esc(fmtDay(d.day, { weekday: "short", day: "numeric", month: "short", year: n > 365 ? "numeric" : undefined }))}</span><br>` +
      (d.k !== null ? `<b>${d.k.toFixed(2)}</b> <span class="state ${b}" style="font-size:.8rem">${BAND_WORD[b]}</span>` : '<span class="muted">No reading</span>') +
      (d.avg !== null ? `<br><span class="muted">Trend ${d.avg.toFixed(2)}</span>` : "");
    const pct = (x(i) / W) * 100;
    tip.style.left = `${Math.max(22, Math.min(78, pct))}%`;
    tip.classList.add("show");
  };
  wrap.onpointermove = (e) => show(e.clientX);
  wrap.onpointerdown = (e) => show(e.clientX);
  wrap.onpointerleave = () => { tip.classList.remove("show"); cursor.setAttribute("visibility", "hidden"); lastIdx = -1; };
}

/* ===================== History ===================== */
async function renderHistory(view) {
  view.innerHTML = `<div class="screen-title"><h2>History</h2><p class="muted small">${esc(S.vehicle.name)}</p></div><div id="hist"></div>`;
  if (!historyData) historyData = await api("/api/history");
  const box = $("#hist");
  if (tab !== "history" || !box) return;
  if (!historyData.length) { box.innerHTML = `<div class="empty"><h2>No readings</h2><p class="muted">Daily readings for ${esc(S.vehicle.name)} appear here.</p></div>`; return; }
  const limit = S.vehicle.limit_k;
  let html = "", month = "", open = false;
  for (const d of historyData) {
    const m = fmtDay(d.day, { month: "long", year: "numeric" });
    if (m !== month) { if (open) html += "</div>"; html += `<div class="month"><span class="label">${esc(m)}</span></div><div class="rows">`; month = m; open = true; }
    const b = band(d.k, limit);
    const pct = d.k === null ? 0 : Math.min(100, (d.k / 3.5) * 100);
    html += `<button class="hrow ${b || ""}" data-day="${d.day}">
      <div class="day"><b>${fmtDay(d.day, { day: "numeric" })}</b><span>${esc(fmtDay(d.day, { weekday: "short" }))}</span></div>
      <div>${d.k !== null ? `<span class="val">${d.k.toFixed(2)}</span><div class="bar"><i style="width:${pct.toFixed(0)}%"></i></div>` : `<span class="muted">No usable reading</span>`}
        ${d.reason ? `<div class="reason">${esc(d.reason)}</div>` : ""}</div>
      ${d.k !== null ? `<span class="state ${b}">${BAND_WORD[b]}</span>` : "<span></span>"}</button>`;
  }
  box.innerHTML = html + (open ? "</div>" : "");
}

async function openDay(day) {
  const rows = await api(`/api/day/${day}`);
  const limit = S.vehicle.limit_k;
  const items = rows.map((r) => {
    const b = band(r.k, limit);
    return `<div class="item static"><div class="lbl"><div class="muted small">${esc(parseLocal(r.time).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }))}</div>
        ${r.valid ? `<span style="font:700 1.9rem/1 var(--f-num)">${r.k.toFixed(2)}</span>` : `<b>Not counted</b><div class="reason">${esc(r.reason)} Try measuring again.</div>`}</div>
        ${r.valid ? `<span class="state ${b}">${BAND_WORD[b]}</span>` : ""}</div>`;
  }).join("");
  const tech = rows.map((r) => `<tr><td>${esc(parseLocal(r.time).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }))}</td><td>clean ${r.i0}</td><td>smoky ${r.i}</td><td>${esc(r.flags.join(", ") || "-")}</td></tr>`).join("");
  openSheet(`<h2>${esc(fmtDay(day, { weekday: "long", day: "numeric", month: "long" }))}</h2><p class="muted small">${esc(fmtDay(day, { year: "numeric" }))}</p>
    <div class="list">${items}</div>
    <details><summary>Technical details</summary><table><tr><th>Time</th><th>Clean air</th><th>Exhaust</th><th>Flags</th></tr>${tech}</table></details>
    <button class="btn block" style="margin-top:18px" data-sheet="close">Close</button>`);
}

/* ===================== Alerts ===================== */
async function renderAlerts(view) {
  view.innerHTML = `<div class="screen-title"><h2>Alerts</h2><p class="muted small">${esc(S.vehicle.name)}</p></div><div id="alerts"></div>`;
  if (!alertsData) alertsData = await api("/api/alerts");
  store.set(`sootable-seen-${S.vehicle.id}-${S.alert_count}`, "1");
  renderTabbar();
  const box = $("#alerts");
  if (tab !== "alerts" || !box) return;
  if (!alertsData.length) {
    box.innerHTML = `<div class="empty"><h2>No alerts</h2><p class="muted">Alerts appear when the smoke level changes status.</p></div>`;
    return;
  }
  box.innerHTML = alertsData.map((a) => {
    const [cls, word] = ALERT_STATE[a.type] || ["WATCH", a.type];
    return `<div class="acard"><div class="when"><span>${esc(fmtDay(a.day, { day: "numeric", month: "short", year: "numeric" }))}${a.delivered ? "" : " &middot; repeat"}</span><span class="state ${cls}">${word}</span></div>
      <h3>${esc(ALERT_TITLE[a.type] || a.type)}</h3><p class="muted">${esc(a.message)}</p></div>`;
  }).join("");
}

/* ===================== Settings ===================== */
function renderSettings(view) {
  const s = S, dv = s.device, many = manyVehicles();
  const notify = store.get("sootable-notify", "1") === "1";
  view.innerHTML = `
    <div class="screen-title"><h2>Settings</h2></div>
    <section class="s-block"><div class="group">
      <div class="vhead">${art(s.vehicle.kind, "vicon")}<div><span class="label">Vehicle</span><div class="muted small" style="margin-top:6px">${KIND_NAME[s.vehicle.kind]}</div></div></div>
      <div class="name-row"><label class="field" for="vname">Name</label><input id="vname" type="text" maxlength="40" value="${esc(s.vehicle.name)}" autocomplete="off"></div>
      <button class="item" data-action="kind"><span class="lbl">Type</span><span class="meta">${KIND_NAME[s.vehicle.kind]}</span><span class="chev">&rsaquo;</span></button>
      <button class="item" data-sheet-open="add-vehicle"><span class="lbl">Add another vehicle</span><span class="chev">&rsaquo;</span></button>
      ${many ? `<button class="item" data-action="remove-vehicle"><span class="lbl" style="color:var(--over)">Remove ${esc(s.vehicle.name)}</span></button>` : ""}
    </div></section>
    <section class="s-block"><span class="label">Notifications</span><div class="group">
      <label class="item static"><span class="lbl"><b>Alerts</b><div class="muted small">When the status changes</div></span><span class="toggle"><input type="checkbox" id="notify" ${notify ? "checked" : ""}><i></i></span></label>
    </div></section>
    <section class="s-block"><span class="label">Meter</span><div class="group">
      ${dv.paired ? `
      <div class="item static"><span class="lbl">Meter for ${esc(s.vehicle.name)}</span><span class="meta">${esc(dv.name)}</span></div>
      <div class="item static"><span class="lbl">Firmware</span><span class="meta">${dv.fw}</span></div>
      <div class="item static"><span class="lbl">Sampling chamber</span><span class="meta">${dv.chamber_mm} mm</span></div>
      <div class="item static"><span class="lbl">Last sync</span><span class="meta">${dv.last_sync ? esc(fmtWhen(dv.last_sync)) : "never"}</span></div>
      <div class="item static"><span class="lbl">Battery</span><span class="meta">${s.low_battery ? "Low" : "Good"}</span></div>
      <button class="item" data-action="sync"><span class="lbl"><b>Sync now</b></span><span class="chev">&rsaquo;</span></button>
      <button class="item" data-action="pair-meter"><span class="lbl">Change meter</span><span class="chev">&rsaquo;</span></button>
      <button class="item" data-action="forget-meter"><span class="lbl" style="color:var(--over)">Forget this meter</span></button>`
      : `<div class="item static"><span class="lbl">No meter connected to ${esc(s.vehicle.name)}</span></div>
      <button class="item" data-action="pair-meter"><span class="lbl"><b>Connect a meter</b></span><span class="chev">&rsaquo;</span></button>`}
    </div></section>
    <section class="s-block"><span class="label">Maintenance</span><div class="group">
      <button class="item" data-action="cleaned"><span class="lbl"><b>Sensor window cleaned</b><div class="muted small">Resets the 30-reading reminder</div></span><span class="chev">&rsaquo;</span></button>
      <button class="item" data-action="serviced"><span class="lbl"><b>Engine serviced</b><div class="muted small">Starts a new baseline for ${esc(s.vehicle.name)}</div></span><span class="chev">&rsaquo;</span></button>
    </div></section>
    ${canInstall() ? `<section class="s-block"><span class="label">App</span><div class="group">
      <button class="item" data-action="install"><span class="lbl"><b>Add to Home screen</b><div class="muted small">Opens full screen, like any app</div></span><span class="chev">&rsaquo;</span></button>
    </div></section>` : ""}
    <section class="s-block"><span class="label">Data</span><div class="group">
      <div class="item static"><span class="lbl">Stored on this phone</span><span class="meta">${Math.max(1, Math.round(s.storage_bytes / 1024))} KB</span></div>
      <a class="item" href="/api/export.csv" download><span class="lbl"><b>Export readings</b><div class="muted small">CSV file</div></span><span class="chev">&rsaquo;</span></a>
      <button class="item" data-action="delete"><span class="lbl" style="color:var(--over)"><b>Delete all data</b></span></button>
    </div></section>
    ${dev ? `<section class="s-block"><span class="label">Developer</span><div class="group"><button class="item" data-go="dev"><span class="lbl"><b>Developer tools</b><div class="muted small">Simulator and protocol inspector</div></span><span class="chev">&rsaquo;</span></button><a class="item" href="/hardware" target="_blank" rel="noopener"><span class="lbl"><b>Hardware demo</b><div class="muted small">3D simulator of the meter</div></span><span class="chev">&rsaquo;</span></a></div></section>` : ""}
    <section class="about"><div class="stack">
      <p class="muted small">SootAble does not replace a PUC certificate or an OBD scanner, and works on diesel exhaust only. The legal limit used is 2.45 m<sup>-1</sup> (65 Hartridge units), the CMVR limit. All data stays on this phone.</p>
      <button class="muted small" id="version" style="background:none;border:0;text-align:left;cursor:default;padding:0;min-height:32px">Version 1.0</button></div></section>`;
  $("#vname").onchange = async (e) => { setState(await api("/api/settings", "POST", { name: e.target.value, kind: S.vehicle.kind })); renderAppbar(); toast("Saved.", { tone: "ok", ms: 1500 }); };
  $("#notify").onchange = (e) => { store.set("sootable-notify", e.target.checked ? "1" : "0"); askNotificationPermission(e.target.checked); };
  $("#version").onclick = () => {
    if (++versionTaps >= 5 && !dev) { dev = true; store.set("sootable-dev", "1"); refresh(); toast("Developer tools enabled", { ms: 2500 }); }
  };
}

function askNotificationPermission(on) {
  try { if (on && "Notification" in window && Notification.permission === "default") Notification.requestPermission(); } catch (e) { /* optional */ }
}

/* ===================== device, syncing ===================== */
function openDeviceSheet() {
  const dv = S.device, ok = !!dv.last_sync;
  openSheet(`<h2>${esc(dv.name || "Meter")}</h2>
    <p class="muted">${ok ? `Last synced ${esc(fmtWhen(dv.last_sync))}. ` : ""}Firmware ${dv.fw}, sampling chamber ${dv.chamber_mm} mm.</p>
    <div class="row" style="margin-top:20px"><button class="btn block" data-sheet="close">Close</button><button class="btn block primary" data-sheet="sync">Sync now</button></div>`);
}

async function doSync() {
  if (!S.meters_paired) { startPairing(); return; }   // no vehicle has a meter yet
  try {
    const s = await api("/api/sync", "POST");
    setState(s); refresh(); notifyNew(s.new_alerts);
    toast(s.complete === false ? "Sync did not finish. Try again." : "Up to date.", { tone: s.complete === false ? "error" : "ok", ms: 2000 });
  } catch (e) { toast(online ? "Could not reach the meter." : "Can't reach SootAble.", { tone: "error" }); }
}

function measureOpen() {
  if (!S.device.paired) { toast(`Connect a meter to ${S.vehicle.name} first.`, { ms: 2500 }); startPairing(); return; }
  openSheet(`<h2>Take a reading</h2><p class="muted small">${esc(S.vehicle.name)} &middot; ${esc(S.device.name)}</p>
    <p class="muted" style="margin-top:10px">Run the engine until warm. Push the sampling tube about 10 cm into the tailpipe and keep the engine idling until the reading finishes. It takes about a minute.</p>
    <div class="row" style="margin-top:20px"><button class="btn block" data-sheet="close">Cancel</button><button class="btn block primary" data-sheet="measure-start">Start</button></div>`);
}

async function measureRun() {
  const steps = ["Drawing in exhaust sample", "Flushing with clean air for a reference", "Calculating smoke level"];
  openSheet(`<h2>Measuring</h2><p class="muted">Keep the tube in place.</p>
    <ul class="steps" id="steps">${steps.map((t) => `<li><span class="dotc"></span>${esc(t)}</li>`).join("")}</ul><div class="progress"><i id="prog"></i></div>`);
  const phase = (n) => {
    [...document.querySelectorAll("#steps li")].forEach((li, i) => { li.className = i < n ? "done" : i === n ? "on" : ""; });
    const p = $("#prog"); if (p) p.style.width = `${Math.round(((n + (n < steps.length ? 0.4 : 0)) / steps.length) * 100)}%`;
    buzz(8);
  };
  measuring = true;
  const request = api("/api/measure", "POST", { vehicle_id: S.vehicle.id }).catch((e) => e);
  const pause = reduceMotion ? 400 : 1500;
  for (let i = 0; i < steps.length; i++) { phase(i); await sleep(pause); }
  phase(steps.length);
  const result = await request;
  measuring = false;
  if (result instanceof Error) {
    openSheet(`<h2>${online ? "Could not reach the meter" : "Can't reach SootAble"}</h2><p class="muted">${online ? "Check that it is switched on and in range." : "Check your connection and try again."}</p>
      <div class="row" style="margin-top:20px"><button class="btn block" data-sheet="close">Close</button><button class="btn block primary" data-sheet="measure-again">Try again</button></div>`);
    return;
  }
  setState(result);
  const l = result.latest, limit = result.vehicle.limit_k;
  if (!l || !l.valid) {
    buzz([30, 60, 30]);
    openSheet(`<h2>Reading failed</h2><p class="muted">${esc((l && l.reason) || "Something went wrong.")} It was not added to ${esc(result.vehicle.name)}'s history.</p>
      <div class="row" style="margin-top:20px"><button class="btn block" data-sheet="close">Close</button><button class="btn block primary" data-sheet="measure-again">Measure again</button></div>`);
  } else {
    const b = band(l.k, limit);
    buzz([12, 40, 12]);
    openSheet(`<div class="result"><span class="label">${esc(result.vehicle.name)}</span>
      <div class="big">${l.k.toFixed(2)}</div><span class="pill ${b}">${BAND_WORD[b]}</span>
      <p class="muted" style="margin-top:14px">Limit ${limit}. Saved to ${esc(result.vehicle.name)}'s history.</p></div>
      <button class="btn block primary" style="margin-top:20px" data-sheet="close">Done</button>`);
  }
  refresh();
  notifyNew(result.new_alerts);
}

/* ===================== pull down to sync ===================== */
(function pullToRefresh() {
  const view = $("#view"), box = $("#ptr"), spin = $("i", box);
  let y0 = null, pull = 0;
  view.addEventListener("touchstart", (e) => { y0 = view.scrollTop <= 0 && !sheetOpen() ? e.touches[0].clientY : null; pull = 0; box.style.transition = "none"; }, { passive: true });
  view.addEventListener("touchmove", (e) => {
    if (y0 === null) return;
    const dy = e.touches[0].clientY - y0;
    if (dy <= 0 || view.scrollTop > 0) { pull = 0; box.style.height = "0px"; return; }
    pull = Math.min(dy * 0.5, 70);
    box.style.height = pull + "px";
    spin.style.opacity = Math.min(pull / 44, 1);
    spin.style.transform = `rotate(${pull * 7}deg)`;
  }, { passive: true });
  view.addEventListener("touchend", async () => {
    if (y0 === null) return;
    y0 = null;
    box.style.transition = "height 0.2s ease";
    if (pull >= 56) {
      buzz(12); box.classList.add("spin"); box.style.height = "48px";
      await doSync();
      box.classList.remove("spin");
    }
    box.style.height = "0px"; spin.style.opacity = 0; pull = 0;
  });
})();

/* ===================== actions ===================== */
document.addEventListener("click", async (e) => {
  const r = e.target.closest("[data-range]");
  if (r) { range = Number(r.dataset.range); store.set("sootable-range", String(range)); refresh(); return; }
  const d = e.target.closest("[data-day]");
  if (d) { openDay(d.dataset.day); return; }
  const so = e.target.closest("[data-sheet-open]");
  if (so) { addVehicleSheet(); return; }
  const a = e.target.closest("[data-action]");
  if (!a) return;
  const act = a.dataset.action;
  if (act === "measure") measureOpen();
  else if (act === "sync") doSync();
  else if (act === "vehicles") openVehicles();
  else if (act === "pair-meter") startPairing();
  else if (act === "forget-meter") confirmSheet(`Forget ${S.device.name}?`, `${S.vehicle.name} will have no meter until you connect one. Saved readings stay on this phone.`, "Forget meter", async () => { setState(await api(`/api/meters/${encodeURIComponent(S.device.id)}`, "DELETE")); refresh(); toast("Meter forgotten.", { ms: 2000 }); }, true);
  else if (act === "kind") kindSheet();
  else if (act === "remove-vehicle") confirmSheet(`Remove ${S.vehicle.name}?`, "Its readings and alerts are deleted from this phone. This can't be undone.", "Remove", async () => { setState(await api(`/api/vehicles/${S.vehicle.id}`, "DELETE")); lastShown = null; showMain(); toast("Vehicle removed.", { ms: 2000 }); }, true);
  else if (act === "info") openSheet(`<h2>Smoke level</h2>
      <p class="muted">How much the exhaust smoke blocks light in the meter's sampling chamber, in m<sup>-1</sup>. Lower is cleaner. The big number is the average of the last week of readings.</p>
      <div class="list">
        <div class="item static"><span class="state OK" style="min-width:140px">Good</span><span class="lbl meta" style="text-align:left">Below 1.96</span></div>
        <div class="item static"><span class="state WATCH" style="min-width:140px">Close to limit</span><span class="lbl meta" style="text-align:left">1.96 to 2.45</span></div>
        <div class="item static"><span class="state OVER" style="min-width:140px">Over limit</span><span class="lbl meta" style="text-align:left">Above 2.45, the legal limit</span></div></div>
      <button class="btn block" style="margin-top:18px" data-sheet="close">Close</button>`);
  else if (act === "cleaned") { setState(await api("/api/chamber/cleaned", "POST")); toast("Saved.", { tone: "ok", ms: 1800 }); refresh(); }
  else if (act === "serviced") confirmSheet(`${S.vehicle.name} serviced?`, "A new baseline is measured so the serviced engine is compared with itself, not with its earlier condition.", "Start new baseline", async () => { setState(await api("/api/baseline/reset", "POST")); toast("New baseline started.", { tone: "ok", ms: 2000 }); refresh(); });
  else if (act === "delete") confirmSheet("Delete all data?", "Every vehicle, reading and alert is removed from this phone. This can't be undone. Export first if you want a copy.", "Delete", async () => { setState(await api("/api/data", "DELETE")); lastShown = null; tab = "home"; startOnboarding(); }, true);
  else if (act === "install") installApp();
  else if (act === "dev-run") devRun();
});

/* ===================== first run: a plain screen per question ===================== */
const STEPS = 4;   // welcome, vehicle type, name, meter
const freshOb = (extra = {}) => ({ step: 0, kind: null, name: "", pair: "idle", devices: [], chosen: null, pairOnly: false, vehicleId: null, vehicleName: "", ...extra });
let ob = freshOb();

/** Setup answers survive a reload (or the phone swapping the app out) until setup is finished. */
function saveOnboarding() {
  if (ob.pairOnly) return;
  const { step, kind, name } = ob;
  session.set("sootable-ob", JSON.stringify({ step, kind, name }));
}

function startOnboarding() {
  ob = freshOb();
  try {
    const saved = JSON.parse(session.get("sootable-ob", "null"));
    if (saved && saved.step > 0) ob = freshOb({ step: Math.min(saved.step, 3), kind: saved.kind, name: saved.name || "" });
  } catch (e) { /* start from the beginning */ }
  $("#main").hidden = true;
  $("#onboarding").hidden = false;
  renderOnboarding();
}

/** The same scan, choose and connect screen, opened on its own (no meter paired yet, or pairing a new one). */
function startPairing() {
  ob = freshOb({ step: 3, pairOnly: true, vehicleId: S.vehicle.id, vehicleName: S.vehicle.name });
  closeSheet();
  $("#main").hidden = true;
  $("#onboarding").hidden = false;
  renderOnboarding();
}

function goStep(n) { ob.step = n; renderOnboarding(); }
const obName = () => (ob.name || "").trim() || KIND_DEFAULT[ob.kind || "car"];

async function scanForMeters() {
  ob.pair = "scanning"; renderOnboarding();
  const [res] = await Promise.all([api("/api/scan").catch(() => ({ devices: [] })), sleep(reduceMotion ? 300 : 1800)]);
  ob.devices = res.devices; ob.pair = "list"; renderOnboarding(); buzz(10);
}

async function connectTo(id) {
  ob.chosen = ob.devices.find((d) => d.id === id);
  ob.pair = "connecting"; renderOnboarding();
  try {
    const [s] = await Promise.all([api("/api/pair", "POST", { id, vehicle_id: ob.vehicleId }), sleep(reduceMotion ? 300 : 1200)]);
    setState(s); ob.pair = "done"; buzz([12, 40, 12]);
  } catch (e) {
    ob.pair = "list"; toast("Could not connect. Try again.", { tone: "error" });
  }
  renderOnboarding();
}

const signalBars = (rssi) => Math.max(1, Math.min(4, Math.round((rssi + 95) / 12)));
const barsHTML = (n) => `<div class="bars" aria-label="Signal ${n} of 4">${[1, 2, 3, 4].map((i) => `<i style="${i > n ? "opacity:.25" : ""}"></i>`).join("")}</div>`;

function renderOnboarding() {
  saveOnboarding();
  const root = $("#onboarding"), step = ob.step;
  let body = "", foot = "", bodyCls = "";
  if (step === 0) {
    body = `<div class="welcome"><div class="mark"><img src="/static/logo-mark.png" alt=""></div>
      <h1>SootAble</h1><p class="lead" style="margin-top:6px">Daily smoke readings for diesel vehicles.</p>
      <p class="legal">SootAble does not replace a PUC certificate or an OBD scanner. It works on diesel exhaust only.</p></div>`;
    foot = `<button class="btn primary block" data-ob="next">Continue</button>`;
  } else if (step === 1) {
    body = `<div><h1>Vehicle type</h1><p class="lead" style="margin-top:6px">Diesel vehicles only.</p></div>${kindTiles("data-obkind", ob.kind)}`;
    bodyCls = "top";
  } else if (step === 2) {
    const ideas = KIND_IDEAS[ob.kind || "car"];
    body = `<div><h1>Vehicle name</h1><p class="lead" style="margin-top:6px">Shown at the top of the app.</p></div>
      <input id="ob-name" class="bigfield" type="text" maxlength="40" placeholder="${esc(KIND_DEFAULT[ob.kind || "car"])}" value="${esc(ob.name)}" autocomplete="off">
      <div class="chips">${ideas.map((t) => `<button class="chipbtn ${ob.name === t ? "sel" : ""}" data-obidea="${esc(t)}">${esc(t)}</button>`).join("")}</div>`;
    bodyCls = "top";
    foot = `<button class="btn primary block" data-ob="next">Continue</button>`;
  } else {
    // connect the meter: scan, choose from what was found, connect. The only way past this is a paired meter or demo data.
    // each vehicle has its own meter; pairOnly screens name the vehicle being connected
    const p = ob.pair, found = ob.devices, chosen = ob.chosen, dv = S && S.device;
    const who = ob.pairOnly ? ob.vehicleName : "";
    const title = p === "idle" ? (who ? `Connect ${who}'s meter` : "Connect your meter") : p === "scanning" ? "Searching"
      : p === "list" ? (found.length ? (who ? `Select the meter for ${who}` : "Select your meter") : "No meter found")
      : p === "connecting" ? `Connecting to ${chosen.name}` : "Connected";
    const sub = p === "idle" ? "Turn the meter on. Hold the button for two seconds until the light blinks."
      : p === "scanning" ? "Looking for meters in range."
      : p === "list" ? (found.length ? "Meters in range:" : "Check that it is on and close to the phone, then search again.")
      : p === "connecting" ? "Setting up the connection." : (who ? `${chosen.name} is now ${who}'s meter.` : "The meter is ready to use.");
    const art = p === "scanning" || p === "connecting" ? "busy" : p === "done" ? "done" : "";
    // a meter that is already on another vehicle can still be chosen: connecting it moves it here
    const status = (d) => (d.vehicle_id && d.vehicle_id === ob.vehicleId ? `Already on ${esc(d.vehicle)}`
      : d.vehicle ? `On ${esc(d.vehicle)}. Connecting moves it here.` : "Not in use");
    const devices = p === "list" ? found.map((d) => `<button class="devcard" data-obdev="${esc(d.id)}"><div><b>${esc(d.name)}</b><span class="muted small">${status(d)}</span></div>${barsHTML(signalBars(d.rssi))}</button>`).join("")
      : p === "connecting" ? `<div class="devcard"><div><b>${esc(chosen.name)}</b><span class="muted small">Connecting</span></div>${barsHTML(signalBars(chosen.rssi))}</div>`
      : p === "done" ? `<div class="devcard"><div><b>${esc(dv.name)}</b><span class="muted small">Firmware ${dv.fw} &middot; chamber ${dv.chamber_mm} mm</span></div>${barsHTML(signalBars(chosen.rssi))}</div>` : "";
    body = `<div><div class="pairing-art ${art}">${p === "done" ? '<svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.500L19 7.500"/></svg>' : svgIcon("bt")}</div>
      <h1 style="margin-top:14px">${title}</h1><p class="lead" style="margin-top:6px">${sub}</p></div>${devices ? `<div class="stack">${devices}</div>` : ""}`;
    bodyCls = "top";
    // the same choice every time a vehicle needs a meter: find one over Bluetooth, or use demo data
    const demo = `<button class="btn ghost block" style="margin-top:6px" data-ob="sample">No meter? Use demo data</button>`;
    foot = p === "done" ? `<button class="btn primary block" data-ob="${ob.pairOnly ? "close" : "finish"}">${ob.pairOnly ? "Done" : "Continue"}</button>`
      : p === "idle" ? `<button class="btn primary block" data-ob="pair">Search for meter</button>${demo}`
      : p === "list" ? `<button class="btn ${found.length ? "" : "primary"} block" data-ob="pair">Search again</button>${found.length ? "" : demo}`
      : `<button class="btn block" disabled>${p === "scanning" ? "Searching…" : "Connecting…"}</button>`;
  }
  root.innerHTML = `<div class="ob">
    <div class="ob-top"><button class="ob-back" data-ob="${ob.pairOnly ? "close" : "back"}" ${step === 0 ? "hidden" : ""} aria-label="${ob.pairOnly ? "Close" : "Back"}">${svgIcon("back")}</button>
      ${ob.pairOnly || step === 0 ? '<div style="flex:1"></div>' : `<div class="progress-bar" aria-hidden="true"><i style="width:${Math.round((step / (STEPS - 1)) * 100)}%"></i></div><span style="width:20px"></span>`}</div>
    <div class="ob-body ${bodyCls}">${body}</div><div class="ob-foot">${foot}</div></div>`;
  fadeIn($(".ob-body", root));
}

document.addEventListener("click", async (e) => {
  const kb = e.target.closest("[data-obkind]");
  if (kb) {
    if (ob.step !== 1) return;
    const old = KIND_DEFAULT[ob.kind];
    ob.kind = kb.dataset.obkind; buzz(10);
    if (!ob.name || ob.name === old) ob.name = "";
    document.querySelectorAll("[data-obkind]").forEach((k) => k.classList.toggle("sel", k === kb));
    setTimeout(() => goStep(2), reduceMotion ? 100 : 260);
    return;
  }
  const dvc = e.target.closest("[data-obdev]");
  if (dvc) { await connectTo(dvc.dataset.obdev); return; }
  const idea = e.target.closest("[data-obidea]");
  if (idea) { const inp = $("#ob-name"); inp.value = idea.dataset.obidea; ob.name = inp.value; document.querySelectorAll("[data-obidea]").forEach((c) => c.classList.toggle("sel", c === idea)); return; }
  const b = e.target.closest("[data-ob]");
  if (!b) return;
  const act = b.dataset.ob;
  if (ob.step === 2) ob.name = ($("#ob-name") || {}).value || "";
  if (act === "next") goStep(ob.step + 1);
  else if (act === "back") goStep(Math.max(0, ob.step - 1));
  else if (act === "close") { lastShown = null; showMain(); }
  else if (act === "pair") await scanForMeters();
  else if (act === "finish") await finishOnboarding();
  else if (act === "sample") openSheet(`<h2>Use demo data</h2><p class="muted">The meter is not built yet. This loads example readings${ob.pairOnly ? ` for ${esc(ob.vehicleName)}` : ""} from a demo meter so the app can be explored.${ob.pairOnly && manyVehicles() ? " Your other vehicles are not affected." : ""}</p>
      <div class="stack" style="margin-top:18px">
        <button class="btn block" data-sample="steady_healthy">Healthy engine</button>
        <button class="btn block" data-sample="wearing_out">Engine wearing out</button>
        <button class="btn ghost block" data-sheet="close">Cancel</button></div>`);
});
document.addEventListener("input", (e) => { if (e.target.id === "ob-name") { ob.name = e.target.value; saveOnboarding(); document.querySelectorAll("[data-obidea]").forEach((c) => c.classList.toggle("sel", c.dataset.obidea === ob.name)); } });
document.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.id === "ob-name") { ob.name = e.target.value; goStep(3); } });

/** Demo data for one vehicle in an app that is already set up. Other vehicles are left alone. */
async function useDemoForVehicle(name) {
  try {
    const s = await api("/api/scenario", "POST", { name, vehicle_id: ob.vehicleId, keep: true });
    setState(s); lastShown = null; tab = "home";
    showMain();   // demo history is not news, so no alert toasts (the Alerts tab still shows its badge)
  } catch (e) {
    toast("Every demo meter is already in use. Connect a meter instead.", { tone: "error" });
  }
}

async function finishOnboarding(sample) {
  const name = obName();
  let s = await api("/api/onboarding", "POST", { name, kind: ob.kind || "car" });
  if (sample) s = await api("/api/scenario", "POST", { name: sample });
  session.del("sootable-ob");
  setState(s);
  lastShown = null;
  tab = "home";
  showMain();
}

/* ===================== developer tools (hidden) ===================== */
let inspectorLast = 0;
async function renderDev(view) {
  const names = await api("/api/scenarios");
  const dv = S.device;
  view.innerHTML = `<div class="screen-title"><div class="row between"><h2>Developer</h2><button class="linkbtn" id="dev-off">Hide</button></div>
    <p class="muted small">Not part of the product. These drive the simulated meter and show the raw Bluetooth traffic. The real meter records a reading by itself every day.</p></div>
    <section class="s-block"><div class="stack">
      <label class="field" for="scenario">Scenario</label>
      <select id="scenario">${Object.entries(names).map(([id, l]) => `<option value="${id}" ${S.scenario === id ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>
      <button class="btn block" data-action="dev-run">Run scenario</button>
      <button class="btn block" data-action="measure">Record a reading now</button>
      <label class="field" for="level">Next measurement: <b id="level-v">${Number(dv.sim_k).toFixed(2)}</b></label>
      <input type="range" id="level" min="0.1" max="4" step="0.05" value="${dv.sim_k}">
      <div class="flags" id="flags"></div></div></section>
    <section class="s-block"><span class="label">Protocol inspector</span><div class="inspector" id="inspector" tabindex="0" aria-label="Protocol inspector" style="margin-top:10px"></div></section>
    <section class="s-block"><button class="btn ghost block" data-go="settings">Back to settings</button></section>`;
  $("#dev-off").onclick = () => { dev = false; store.set("sootable-dev", "0"); go("home"); };
  const flags = [[1, "No reference"], [2, "Saturated"], [4, "Low battery"], [8, "Fan fault"]];
  $("#flags").innerHTML = flags.map(([bit, n]) => `<label><input type="checkbox" value="${bit}" ${dv.sim_flags & bit ? "checked" : ""}> ${n}</label>`).join("");
  const push = () => {
    const f = [...document.querySelectorAll("#flags input")].reduce((n, c) => n + (c.checked ? Number(c.value) : 0), 0);
    $("#level-v").textContent = Number($("#level").value).toFixed(2);
    return api("/api/sim/level", "POST", { k: Number($("#level").value), flags: f }).then(setState);
  };
  $("#level").onchange = push;
  $("#level").oninput = () => ($("#level-v").textContent = Number($("#level").value).toFixed(2));
  document.querySelectorAll("#flags input").forEach((c) => (c.onchange = push));
  pollInspector();
}

async function devRun() {
  const s = await api("/api/scenario", "POST", { name: $("#scenario").value });
  setState(s); notifyNew(s.new_alerts); go("dev");
}

async function pollInspector() {
  if (tab !== "dev") return;
  try {
    const { entries, last } = await api(`/api/inspector?since=${inspectorLast}`);
    inspectorLast = last;
    const box = $("#inspector");
    for (const e of entries) {
      const cls = e.dir.startsWith("device") ? "d" : e.dir === "app" ? "a" : "n";
      const bad = /CRC|LOST|missing|invalid|error/.test(e.note) ? " bad" : "";
      const row = document.createElement("div");
      row.className = cls + bad;
      row.textContent = `${e.dir.padEnd(11)} ${e.hex}${e.hex && e.note ? "  " : ""}${e.note}`;
      box.append(row);
    }
    while (box.childElementCount > 400) box.firstChild.remove();
    if (entries.length) box.scrollTop = box.scrollHeight;
  } catch (e) { /* transient */ }
  setTimeout(pollInspector, 1000);
}

/* ===================== desktop frame clock ===================== */
function tickClock() {
  const d = new Date();
  $("#clock").textContent = `${d.getHours() % 12 || 12}:${String(d.getMinutes()).padStart(2, "0")}`;
}
tickClock();
setInterval(tickClock, 20000);

/* ===================== staying current ===================== */
/** Re-read the state and redraw if something changed (a sync, a new day, the data being cleared elsewhere). */
let polling = false;
async function pollState() {
  if (polling || !S || document.hidden || measuring) return;
  polling = true;
  try {
    const s = await api("/api/state");
    const idle = !sheetOpen() && !measuring && !(document.activeElement && /^(INPUT|SELECT)$/.test(document.activeElement.tagName));
    if (JSON.stringify(s) !== JSON.stringify(S) && idle) {
      const wasSetUp = S.onboarded;
      setState(s);
      if (!s.onboarded && wasSetUp) { lastShown = null; startOnboarding(); }
      else if (s.onboarded && !$("#main").hidden) { refresh(); }
    }
  } catch (e) { /* the offline banner already says so */ }
  polling = false;
}

/** Fetch whatever the meters have stored since the last time, without being asked. */
let lastAutoSync = 0;
async function autoSync(force = false) {
  if (!S || !S.onboarded || !S.meters_paired || document.hidden || measuring || !online) return;
  if (!force && Date.now() - lastAutoSync < 10 * 60 * 1000) return;
  lastAutoSync = Date.now();
  try {
    const s = await api("/api/sync", "POST");
    if (sheetOpen() || measuring) { pollState(); return; }   // do not redraw under an open sheet; the next poll will
    setState(s);
    if (!$("#main").hidden) refresh();
    notifyNew(s.new_alerts);
  } catch (e) { /* silent: the pull-down and Sync now buttons report failures */ }
}

(function keepFresh() {
  const tick = () => { pollState(); setTimeout(tick, online ? 30000 : 5000); };
  setTimeout(tick, 30000);
  setInterval(() => autoSync(), 60000);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { saveScroll(); return; }
    pollState(); autoSync();
  });
  addEventListener("online", () => { setOnline(true); pollState(); });
  addEventListener("offline", () => setOnline(false));
})();

function saveScroll() {
  if (!S || $("#main").hidden) return;
  scrollPos[tab] = $("#view").scrollTop;
  session.set("sootable-scroll", JSON.stringify(scrollPos));
}
addEventListener("pagehide", saveScroll);

/* ===================== the system back button and gesture ===================== */
/* One spare history entry is always kept in front of the app. Back lands on the one behind it, we close
   the topmost thing (sheet, setup step, tab), and put the spare back. With nothing left to close, back
   goes on to leave the app as usual. */
history.replaceState({ root: 1 }, "");
history.pushState({ guard: 1 }, "");
addEventListener("popstate", () => {
  const onboarding = !$("#onboarding").hidden;
  if (sheetOpen()) closeSheet();
  else if (onboarding && ob.pair !== "scanning" && ob.pair !== "connecting" && ob.step > 0 && !ob.pairOnly) goStep(ob.step - 1);
  else if (onboarding && ob.pairOnly) { lastShown = null; showMain(); }
  else if (!onboarding && tab !== "home") go("home");
  else { history.back(); return; }
  history.pushState({ guard: 1 }, "");
});

/* ===================== install (Add to Home screen) ===================== */
let installEvent = null;
addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); installEvent = e; if (S && tab === "settings") refresh(); });
addEventListener("appinstalled", () => { installEvent = null; if (S && tab === "settings") refresh(); });
const canInstall = () => !isStandalone && (!!installEvent || isIOS);

async function installApp() {
  if (installEvent) { installEvent.prompt(); try { await installEvent.userChoice; } catch (e) { /* dismissed */ } installEvent = null; refresh(); return; }
  openSheet(`<h2>Add to Home screen</h2>
    <p class="muted">In Safari, tap the Share button, then choose <b>Add to Home Screen</b>. SootAble then opens full screen from its own icon.</p>
    <button class="btn block primary" style="margin-top:20px" data-sheet="close">Got it</button>`);
}

/* ===================== errors ===================== */
addEventListener("unhandledrejection", (e) => {
  e.preventDefault();
  if (online) toast("Something went wrong. Try again.", { tone: "error" });
});

/* ===================== start ===================== */
const hideBoot = () => { const b = $("#boot"); if (b) { b.classList.add("gone"); setTimeout(() => b.remove(), 260); } };

async function init() {
  try {
    setState(await api("/api/state"));
  } catch (e) {
    hideBoot();
    $("#onboarding").hidden = false;
    $("#onboarding").innerHTML = `<div class="ob"><div class="ob-body"><h1>Can't reach SootAble</h1><p class="lead">Trying again&hellip;</p></div></div>`;
    setTimeout(init, 3000);
    return;
  }
  if (location.hash === "#dev") { dev = true; store.set("sootable-dev", "1"); }
  if (tab === "dev" && !dev) tab = "home";
  if (!["home", "history", "alerts", "settings", "dev"].includes(tab)) tab = "home";
  if (!S.onboarded) startOnboarding(); else showMain();
  const hashTab = location.hash.replace("#", "");
  if (S.onboarded && ["history", "alerts", "settings", "dev"].includes(hashTab) && (hashTab !== "dev" || dev)) go(hashTab);
  hideBoot();
  autoSync(true);
}
init();

if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost" || location.hostname === "127.0.0.1")) {
  addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => { /* the app works without it */ }));
}
