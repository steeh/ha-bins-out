/* Bins Out card for Home Assistant: vanilla ES module, no dependencies. */

const DEFAULT_ENTITY = "sensor.bins_out_next_collection";
// Not "collected": switching put-out off after collection time would mark the bin forgotten.
const TOGGLE_STATUSES = new Set(["tomorrow", "today", "out", "forgotten"]);
const HOLD_MS = 500;
const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/* ---------- helpers ---------- */

function parseLocalDate(str) {
  if (!str || typeof str !== "string") return null;
  const [y, m, d] = str.split("-").map(Number);
  if (!y || !m || !d) return null;
  return new Date(y, m - 1, d);
}

function isoLocal(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function fmtDate(date) {
  return `${DAY_NAMES[date.getDay()]} ${date.getDate()} ${MONTH_NAMES[date.getMonth()]}`;
}

function inDays(n) {
  if (n === null || n === undefined) return "";
  if (n === 0) return "today";
  if (n === 1) return "in 1 day";
  return `in ${n} days`;
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function safeColour(hex) {
  return /^#[0-9a-f]{3,8}$/i.test(hex || "") ? hex : "#888888";
}

function luminance(hex) {
  let h = safeColour(hex).slice(1);
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255;
}

// Light fills (white, yellow) need a dark outline on light themes.
function isLightColour(hex) {
  return luminance(hex) > 0.7;
}

// Dark fills (black, brown, purple, dark blue) need a theme-coloured outline on dark themes.
function isDarkColour(hex) {
  return luminance(hex) < 0.3;
}

// CSS class for a bin's tone, used by the SVG and the calendar/legend dots.
function toneClass(hex) {
  if (isLightColour(hex)) return "light";
  if (isDarkColour(hex)) return "dark";
  return "";
}

function statusLabel(bin) {
  switch (bin.status) {
    case "upcoming": return inDays(bin.days_until) || "Upcoming";
    case "tomorrow": return "Tonight";
    case "today": return "Put out NOW";
    case "out": return "Out ✓";
    case "collected": return "Collected, bring it in";
    case "forgotten": return "Missed!";
    default: return "No collections";
  }
}

function binSvg(bin) {
  const fill = bin.status === "none" ? "#9e9e9e" : safeColour(bin.colour_hex);
  const light = isLightColour(fill);
  const dark = isDarkColour(fill);
  const stroke = light ? "#333" : "rgba(0,0,0,0.35)";
  const lid = light ? "#d0d0d0" : "rgba(0,0,0,0.25)";
  return `
  <svg viewBox="0 0 64 80" class="bin-svg ${dark ? "darkfill" : ""}" aria-hidden="true">
    <rect class="ol" x="6" y="10" width="52" height="9" rx="3" fill="${fill}" stroke="${stroke}" stroke-width="1.5"/>
    <rect x="6" y="10" width="52" height="4" rx="2" fill="${lid}"/>
    <rect class="ol" x="24" y="5" width="16" height="6" rx="2" fill="${fill}" stroke="${stroke}" stroke-width="1.5"/>
    <path class="ol" d="M10 19 H54 L50 70 H14 Z" fill="${fill}" stroke="${stroke}" stroke-width="1.5" stroke-linejoin="round"/>
    <path d="M20 26 L22 62 M32 26 V62 M44 26 L42 62" stroke="rgba(0,0,0,0.18)" stroke-width="2.5" stroke-linecap="round"/>
    <circle cx="18" cy="72" r="6" fill="#333" stroke="#111" stroke-width="1"/>
    <circle cx="18" cy="72" r="2.2" fill="#888"/>
    <circle cx="46" cy="72" r="6" fill="#333" stroke="#111" stroke-width="1"/>
    <circle cx="46" cy="72" r="2.2" fill="#888"/>
  </svg>`;
}

function badgeFor(status) {
  switch (status) {
    case "out":
    case "collected":
      return `<span class="badge ok" aria-hidden="true">✓</span>`;
    case "forgotten":
      return `<span class="badge err" aria-hidden="true">!</span>`;
    case "today":
    case "tomorrow":
      return `<span class="badge warn" aria-hidden="true">●</span>`;
    default:
      return "";
  }
}

/* ---------- styles ---------- */

const STYLE = `
:host { display: block; }
ha-card { padding: 16px; overflow: hidden; }
.header { display:flex; align-items:baseline; justify-content:space-between; gap:8px; margin-bottom:12px; }
.title { font-size: 1.25rem; font-weight: 500; color: var(--primary-text-color); }
.summary { font-size: .85rem; color: var(--secondary-text-color); }

.banner {
  display:flex; gap:10px; align-items:flex-start;
  padding:10px 12px; margin-bottom:12px; border-radius:10px;
  font-size:.9rem; line-height:1.35; color: var(--primary-text-color);
  background: color-mix(in srgb, var(--warning-color, #ffa600) 16%, transparent);
  border-left: 4px solid var(--warning-color, #ffa600);
}
.banner.err {
  background: color-mix(in srgb, var(--error-color, #db4437) 16%, transparent);
  border-left-color: var(--error-color, #db4437);
}
.banner .icon { font-size: 1.1rem; line-height: 1.2; }

.bins { display:grid; gap:12px; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); }
.bins.row { grid-auto-flow: column; grid-auto-columns: minmax(110px, 1fr); grid-template-columns: none; overflow-x:auto; }
.bins.list { grid-template-columns: 1fr; }

.bin {
  --ring: transparent;
  position:relative; display:flex; flex-direction:column; align-items:center; text-align:center;
  gap:4px; padding:12px 8px 10px; border-radius:14px; cursor:pointer;
  background: color-mix(in srgb, var(--primary-text-color) 4%, transparent);
  border: 2px solid var(--ring);
  transition: transform .15s ease, box-shadow .2s ease, background .2s ease;
  user-select:none; -webkit-user-select:none; -webkit-tap-highlight-color: transparent;
  outline: none;
}
.bin:hover { background: color-mix(in srgb, var(--primary-text-color) 8%, transparent); }
.bin:active { transform: scale(.97); }
.bin:focus-visible { box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary-color, #03a9f4) 60%, transparent); }
.bin.disabled { cursor: default; }

.bins.list .bin { flex-direction:row; text-align:left; gap:14px; padding:10px 12px; }
.bins.list .bin .text { flex:1; align-items:flex-start; }
.bins.list .bin-art { width:52px; }

.bin-art { position:relative; width:72px; transition: filter .3s ease, opacity .3s ease; }
.bin-svg { width:100%; height:auto; display:block; filter: drop-shadow(0 2px 3px rgba(0,0,0,.25)); }
.bin-svg.darkfill .ol { stroke: color-mix(in srgb, var(--primary-text-color, #000) 55%, transparent); stroke-width: 2; }
.text { display:flex; flex-direction:column; align-items:center; gap:2px; min-width:0; }
.name { font-weight:600; color: var(--primary-text-color); font-size: .98rem; }
.label { font-size:.85rem; font-weight:600; color: var(--secondary-text-color); }
.when { font-size:.78rem; color: var(--secondary-text-color); }

.badge {
  position:absolute; top:-4px; right:-6px; width:22px; height:22px; border-radius:50%;
  display:flex; align-items:center; justify-content:center; font-size:13px; font-weight:700; color:#fff;
  box-shadow: 0 1px 3px rgba(0,0,0,.35);
}
.badge.ok { background: var(--success-color, #43a047); }
.badge.err { background: var(--error-color, #db4437); }
.badge.warn { background: var(--warning-color, #ffa600); font-size: 9px; }

/* statuses */
/* Not due soon: keep the true colour, just slightly lighter; plain border and quieter label. */
.s-upcoming .bin-art { opacity:.7; }
.s-upcoming .label { font-size:.8rem; font-weight:500; }
.s-none .bin-art { opacity:.35; filter: grayscale(1); }
.s-tomorrow { --ring: var(--warning-color, #ffa600); }
.s-tomorrow .label, .s-today .label { color: var(--warning-color, #ffa600); }
.s-tomorrow.due { animation: glow 2.4s ease-in-out infinite; }
.s-today { --ring: var(--warning-color, #ffa600); animation: glowStrong 1.2s ease-in-out infinite; }
.s-out .label, .s-collected .label { color: var(--success-color, #43a047); }
.s-collected { --ring: color-mix(in srgb, var(--success-color, #43a047) 60%, transparent); }
.s-forgotten { --ring: var(--error-color, #db4437); background: color-mix(in srgb, var(--error-color, #db4437) 10%, transparent); }
.s-forgotten .label { color: var(--error-color, #db4437); }

@keyframes glow {
  0%,100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--warning-color, #ffa600) 0%, transparent); }
  50% { box-shadow: 0 0 14px 2px color-mix(in srgb, var(--warning-color, #ffa600) 45%, transparent); }
}
@keyframes glowStrong {
  0%,100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--warning-color, #ffa600) 20%, transparent); }
  50% { box-shadow: 0 0 20px 5px color-mix(in srgb, var(--warning-color, #ffa600) 70%, transparent); }
}
@media (prefers-reduced-motion: reduce) {
  .bin, .bin-art { transition: none; }
  .s-tomorrow.due, .s-today { animation: none; }
}

/* calendar */
.cal { margin-top:16px; padding-top:12px; border-top:1px solid var(--divider-color, rgba(127,127,127,.25)); }
.cal-strip { display:grid; grid-template-columns: repeat(7, 1fr); gap:4px; }
.day {
  position:relative; display:flex; flex-direction:column; align-items:center; gap:3px;
  padding:5px 0 6px; border-radius:8px; min-height:44px;
  color: var(--secondary-text-color); font-size:.72rem;
}
.day .dn { font-size:.62rem; text-transform:uppercase; letter-spacing:.04em; opacity:.8; }
.day .dd { font-size:.85rem; font-weight:600; color: var(--primary-text-color); }
.day.today { background: color-mix(in srgb, var(--primary-color, #03a9f4) 18%, transparent); }
.day.today .dd { color: var(--primary-color, #03a9f4); }
.day.has { background: color-mix(in srgb, var(--primary-text-color) 5%, transparent); }
.day.today.has { background: color-mix(in srgb, var(--primary-color, #03a9f4) 18%, transparent); }
.dots { display:flex; gap:3px; flex-wrap:wrap; justify-content:center; min-height:8px; }
.dot { width:8px; height:8px; border-radius:50%; flex:none; box-shadow: inset 0 0 0 1px rgba(0,0,0,.35); }
.dot.light { box-shadow: inset 0 0 0 1.5px #333; }
.dot.dark { box-shadow: 0 0 0 1.5px color-mix(in srgb, var(--primary-text-color, #000) 55%, transparent); }
.moved { position:absolute; top:3px; right:4px; width:6px; height:6px; border-radius:50%; background: var(--warning-color, #ffa600); }
.legend { display:flex; flex-wrap:wrap; gap:6px 14px; margin-top:10px; font-size:.75rem; color: var(--secondary-text-color); }
.legend span { display:inline-flex; align-items:center; gap:5px; }

.empty { padding:8px 0; color: var(--secondary-text-color); }
.warning { padding:16px; color: var(--error-color, #db4437); }
`;

/* ---------- card ---------- */

class BinsOutCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._lastKey = null;
    this._bins = [];
  }

  static getStubConfig() {
    return { entity: DEFAULT_ENTITY };
  }

  static getConfigElement() {
    return document.createElement("bins-out-card-editor");
  }

  setConfig(config) {
    if (!config || typeof config !== "object") throw new Error("Invalid configuration");
    const days = config.days === undefined ? 14 : Number(config.days);
    if (!Number.isFinite(days) || days < 7 || days > 35) throw new Error("days must be between 7 and 35");
    const layout = config.layout || "auto";
    if (!["auto", "row", "list"].includes(layout)) throw new Error('layout must be "auto", "row" or "list"');
    if (config.entity !== undefined && typeof config.entity !== "string") throw new Error("entity must be a string");
    this._config = {
      entity: config.entity || DEFAULT_ENTITY,
      title: config.title === undefined ? "Bins" : String(config.title),
      show_calendar: config.show_calendar !== false,
      days: Math.round(days),
      layout,
    };
    this._lastKey = null;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return this._config && this._config.show_calendar ? 5 : 3;
  }

  _render() {
    if (!this._config || !this._hass) return;
    const stateObj = this._hass.states[this._config.entity];
    // Re-render only when the entity changes, or once a day (so "today" moves on).
    const key = stateObj
      ? `${stateObj.last_updated}|${isoLocal(new Date())}`
      : "missing";
    if (key === this._lastKey) return;
    this._lastKey = key;

    if (!stateObj) {
      this.shadowRoot.innerHTML = `<style>${STYLE}</style>
        <ha-card><div class="warning">Bins Out entity not found: <code>${esc(this._config.entity)}</code></div></ha-card>`;
      return;
    }

    const a = stateObj.attributes || {};
    const bins = Array.isArray(a.bins) ? a.bins : [];
    this._bins = bins;
    const cfg = this._config;

    let banner = "";
    if (a.forgotten_message) banner = `<div class="banner err" role="alert"><span class="icon">⚠️</span><span>${esc(a.forgotten_message)}</span></div>`;
    else if (a.morning_message) banner = `<div class="banner" role="status"><span class="icon">🌅</span><span>${esc(a.morning_message)}</span></div>`;
    else if (a.tonight_message) banner = `<div class="banner" role="status"><span class="icon">🌙</span><span>${esc(a.tonight_message)}</span></div>`;

    const days = Number(stateObj.state);
    const nextBins = Array.isArray(a.next_bins) ? a.next_bins : [];
    const summary = nextBins.length && Number.isFinite(days)
      ? `${esc(nextBins.join(" & "))} ${esc(inDays(days))}`
      : "";

    const header = cfg.title
      ? `<div class="header"><div class="title">${esc(cfg.title)}</div><div class="summary">${summary}</div></div>`
      : "";

    const layoutClass = cfg.layout === "auto" ? "" : cfg.layout;
    const binsHtml = bins.length
      ? `<div class="bins ${layoutClass}">${bins.map((b, i) => this._binHtml(b, i)).join("")}</div>`
      : `<div class="empty">No bins configured yet.</div>`;

    const cal = cfg.show_calendar && bins.length ? this._calendarHtml(bins, cfg.days) : "";

    this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card>${header}${banner}${binsHtml}${cal}</ha-card>`;
    this._attachHandlers();
  }

  _binHtml(bin, idx) {
    const status = bin.status || "none";
    const next = parseLocalDate(bin.next_collection);
    const when = next ? `${fmtDate(next)} · ${inDays(bin.days_until)}` : "";
    const ents = bin.entities || {};
    const canToggle = TOGGLE_STATUSES.has(status) && !!ents.put_out;
    const canInfo = !!ents.status;
    const disabled = !canToggle && !canInfo;
    const label = statusLabel(bin);
    const aria = `${bin.name}: ${label}${when ? ", " + when : ""}${canToggle ? ". Tap to toggle put out." : ""}`;
    return `
      <div class="bin s-${esc(status)} ${bin.due ? "due" : ""} ${disabled ? "disabled" : ""}"
           data-idx="${idx}" role="button" tabindex="${disabled ? -1 : 0}"
           aria-label="${esc(aria)}" ${disabled ? 'aria-disabled="true"' : ""}>
        <div class="bin-art">${binSvg(bin)}${badgeFor(status)}</div>
        <div class="text">
          <div class="name">${esc(bin.name)}</div>
          <div class="label">${esc(label)}</div>
          ${when ? `<div class="when">${esc(when)}</div>` : ""}
        </div>
      </div>`;
  }

  _calendarHtml(bins, numDays) {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const byDate = new Map();
    for (const bin of bins) {
      const movedFrom = {};
      for (const [orig, dest] of Object.entries(bin.moved || {})) movedFrom[dest] = orig;
      for (const d of bin.upcoming || []) {
        if (!byDate.has(d)) byDate.set(d, []);
        byDate.get(d).push({ bin, movedFrom: movedFrom[d] || null });
      }
    }
    const cells = [];
    for (let i = 0; i < numDays; i++) {
      const date = new Date(today.getFullYear(), today.getMonth(), today.getDate() + i);
      const iso = isoLocal(date);
      const entries = byDate.get(iso) || [];
      const moved = entries.filter((e) => e.movedFrom);
      const titleParts = entries.map((e) => {
        let t = e.bin.name;
        if (e.movedFrom) {
          const o = parseLocalDate(e.movedFrom);
          t += ` (moved from ${o ? fmtDate(o) : e.movedFrom})`;
        }
        return t;
      });
      const title = `${fmtDate(date)}${titleParts.length ? ": " + titleParts.join(", ") : ""}`;
      cells.push(`
        <div class="day ${i === 0 ? "today" : ""} ${entries.length ? "has" : ""}" title="${esc(title)}">
          ${moved.length ? `<span class="moved"></span>` : ""}
          <span class="dn">${DAY_NAMES[date.getDay()]}</span>
          <span class="dd">${date.getDate()}</span>
          <span class="dots">${entries.map((e) => {
            const c = safeColour(e.bin.colour_hex);
            return `<span class="dot ${toneClass(c)}" style="background:${c}"></span>`;
          }).join("")}</span>
        </div>`);
    }
    const anyMoved = bins.some((b) => b.moved && Object.keys(b.moved).length);
    const legend = bins.map((b) => {
      const c = safeColour(b.colour_hex);
      return `<span><span class="dot ${toneClass(c)}" style="background:${c}"></span>${esc(b.name)}</span>`;
    }).join("") + (anyMoved ? `<span><span class="moved" style="position:static"></span>Moved date</span>` : "");
    return `<div class="cal"><div class="cal-strip">${cells.join("")}</div><div class="legend">${legend}</div></div>`;
  }

  _attachHandlers() {
    this.shadowRoot.querySelectorAll(".bin").forEach((el) => {
      const bin = this._bins[Number(el.dataset.idx)];
      if (!bin) return;
      let timer = null;
      let held = false;
      const clear = () => { if (timer) { clearTimeout(timer); timer = null; } };
      el.addEventListener("pointerdown", (ev) => {
        if (ev.button !== undefined && ev.button !== 0) return;
        held = false;
        clear();
        timer = setTimeout(() => { held = true; timer = null; this._moreInfo(bin); }, HOLD_MS);
      });
      el.addEventListener("pointerup", clear);
      el.addEventListener("pointerleave", clear);
      el.addEventListener("pointercancel", clear);
      el.addEventListener("contextmenu", (ev) => ev.preventDefault());
      el.addEventListener("click", (ev) => {
        ev.preventDefault();
        if (held) { held = false; return; }
        this._tap(bin);
      });
      el.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); this._tap(bin); }
      });
    });
  }

  _tap(bin) {
    const ents = bin.entities || {};
    if (TOGGLE_STATUSES.has(bin.status) && ents.put_out) {
      this._hass.callService("switch", "toggle", { entity_id: ents.put_out });
    } else {
      this._moreInfo(bin);
    }
  }

  _moreInfo(bin) {
    const id = bin.entities && bin.entities.status;
    if (!id) return;
    this.dispatchEvent(new CustomEvent("hass-more-info", {
      detail: { entityId: id }, bubbles: true, composed: true,
    }));
  }
}

/* ---------- editor ---------- */

class BinsOutCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
  }

  _render() {
    const c = this._config || {};
    const title = c.title === undefined ? "Bins" : c.title;
    const days = c.days === undefined ? 14 : c.days;
    const layout = c.layout || "auto";
    this.shadowRoot.innerHTML = `
      <style>
        .form { display:grid; gap:14px; padding:4px 0; }
        label { display:flex; flex-direction:column; gap:4px; font-size:.9rem; color: var(--primary-text-color); }
        label.row { flex-direction:row; align-items:center; gap:10px; }
        input[type=text], input[type=number], select {
          padding:8px 10px; border-radius:6px; font: inherit;
          border:1px solid var(--divider-color, #ccc);
          background: var(--card-background-color, #fff); color: var(--primary-text-color);
        }
        .hint { font-size:.75rem; color: var(--secondary-text-color); }
      </style>
      <div class="form">
        <label>Entity
          <input type="text" id="entity" value="${esc(c.entity || DEFAULT_ENTITY)}">
        </label>
        <label>Title
          <input type="text" id="title" value="${esc(title)}">
          <span class="hint">Leave empty to hide the header.</span>
        </label>
        <label class="row"><input type="checkbox" id="show_calendar" ${c.show_calendar === false ? "" : "checked"}> Show calendar</label>
        <label>Calendar days (7–35)
          <input type="number" id="days" min="7" max="35" value="${esc(days)}">
        </label>
        <label>Layout
          <select id="layout">
            ${["auto", "row", "list"].map((l) => `<option value="${l}" ${l === layout ? "selected" : ""}>${l}</option>`).join("")}
          </select>
        </label>
      </div>`;
    const root = this.shadowRoot;
    root.getElementById("entity").addEventListener("change", (e) => this._set("entity", e.target.value.trim()));
    root.getElementById("title").addEventListener("change", (e) => this._set("title", e.target.value));
    root.getElementById("show_calendar").addEventListener("change", (e) => this._set("show_calendar", e.target.checked));
    root.getElementById("days").addEventListener("change", (e) => {
      const v = Math.min(35, Math.max(7, Number(e.target.value) || 14));
      e.target.value = v;
      this._set("days", v);
    });
    root.getElementById("layout").addEventListener("change", (e) => this._set("layout", e.target.value));
  }

  _set(key, value) {
    this._config = { ...this._config, [key]: value };
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config: this._config }, bubbles: true, composed: true,
    }));
  }
}

/* ---------- registration ---------- */

// HA 2026.10 can swap window.customElements for a new registry while it boots. If this module ran
// before the swap, our definitions would be stranded in the old registry ("Configuration error").
// So register in whatever registry is current, and again whenever it changes. Each registry gets a
// fresh subclass, because one constructor can't be defined in two registries.
function register() {
  const reg = window.customElements;
  if (!reg) return;
  if (!reg.get("bins-out-card")) reg.define("bins-out-card", class extends BinsOutCard {});
  if (!reg.get("bins-out-card-editor")) reg.define("bins-out-card-editor", class extends BinsOutCardEditor {});
  window.customCards = window.customCards || [];
  if (!window.customCards.some((c) => c.type === "bins-out-card")) {
    window.customCards.push({
      type: "bins-out-card",
      name: "Bins Out",
      description: "Shows when each bin needs to go out.",
      preview: true,
    });
  }
}

// Cheap and idempotent: only defines what's missing in the current registry, so it also covers
// the registry object being swapped (old definitions don't carry over).
function checkRegistry() {
  register();
}

checkRegistry();
const registryTimer = setInterval(checkRegistry, 250);
setTimeout(() => clearInterval(registryTimer), 30000);
window.addEventListener("load", checkRegistry);
// Exposed for demo.html's "Simulate registry swap" test.
window.__binsOutCheckRegistry = checkRegistry;
