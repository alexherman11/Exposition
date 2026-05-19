/* Schedule timeline — proportional time spacing, animated card mutations, live
 * "Now" indicator, and a detail panel that opens when you tap a card. §3.1. */

import { state, toast } from "./app.js";

let activeLayer = "planned";
let nowTimer = null;

export function initSchedule(_state) {
  document.querySelectorAll(".schedule-tabs button").forEach(b => {
    b.addEventListener("click", () => {
      document.querySelectorAll(".schedule-tabs button").forEach(x => x.classList.remove("active"));
      b.classList.add("active");
      activeLayer = b.dataset.layer;
      refreshSchedule();
    });
  });
  refreshSchedule();
  // Tick the "Now" bar every 60s
  clearInterval(nowTimer);
  nowTimer = setInterval(() => placeNowBar(), 60_000);
}

const TRACK_KEYS = {
  "AI & Big Data": "ai",
  "IoT Tech": "iot",
  "Edge Computing": "edge",
  "Cyber Security": "cyber",
  "Data Centre": "data",
  "Digital Transformation": "data",
  "Intelligent Automation": "ai",
  "Physical AI": "ai",
  "AI Developer": "ai",
};

function toMin(s) { const [h,m] = s.split(":").map(Number); return h*60+m; }

function todayISO() {
  // The event is May 18-19 2026. For demo purposes if today isn't one of those,
  // we still want the "Now" bar to show at the user's wall-clock time — but
  // place it on the matching event day so it lands inside the timeline. We
  // pick the closer of the two days.
  const today = new Date().toISOString().slice(0, 10);
  if (today === "2026-05-18" || today === "2026-05-19") return today;
  // Outside the event: pick whichever event day matches the day-of-week of now
  // (or just default to Day 2 if past). Returning null hides the bar.
  return null;
}

export function refreshSchedule() {
  const root = document.getElementById("timeline");
  const items = state.plan.filter(p => p.layer === activeLayer);

  if (!items.length) {
    root.innerHTML = `<div class="card empty">${activeLayer === "planned" ? "No sessions planned yet — try “Plan my day for LoRa IoT”" : `Nothing ${activeLayer} yet.`}</div>`;
    return;
  }

  // sort by day,start
  items.sort((a, b) => {
    const e1 = a.entity || {}, e2 = b.entity || {};
    return (e1.day || "").localeCompare(e2.day || "") || (e1.start || "").localeCompare(e2.start || "");
  });

  const html = [];
  let prevDay = null, prevEnd = null;

  for (const p of items) {
    const e = p.entity;
    if (!e || e.type !== "session") continue;

    if (e.day !== prevDay) {
      html.push(`<div class="day-divider" data-day="${e.day}">${formatDay(e.day)}</div>`);
      prevDay = e.day;
      prevEnd = null;
    } else if (prevEnd) {
      const gap = toMin(e.start) - toMin(prevEnd);
      if (gap > 5) {
        html.push(`<div class="timeslot gap" data-gap-day="${e.day}" data-gap-start="${prevEnd}" data-gap-end="${e.start}">
          <div class="time"></div>
          <div class="gap-note">${gap} min — ${gap >= 25 ? "fillable" : "tight turnaround"}</div>
        </div>`);
      }
    }

    const trackClass = TRACK_KEYS[e.track] || "ai";
    const score = matchScore(e);
    html.push(`
      <div class="timeslot" data-day="${e.day}" data-start="${e.start}" data-end="${e.end}">
        <div class="time">${e.start}<br><span class="end-time">${e.end}</span></div>
        <div class="card add-anim" data-id="${e.id}" data-track-${trackClass}>
          <div class="row-1">
            <div class="title">${escape(e.title)}</div>
            <div class="match">${score}%</div>
          </div>
          <div class="meta">${e.room ? escape(e.room) + " · " : ""}${escape(e.track)}</div>
          <div class="row-bottom">
            <div class="tags">${(e.tags||[]).slice(0,3).map(t => `<span class="tag">${escape(t)}</span>`).join("")}</div>
            <div class="map-link">📍 Map</div>
          </div>
        </div>
      </div>
    `);
    prevEnd = e.end;
  }

  root.innerHTML = html.join("");

  // Wire up card click → detail panel; map-link click → switch to map
  root.querySelectorAll(".card").forEach(card => {
    if (card.classList.contains("empty")) return;
    const id = card.dataset.id;
    const sess = state.sessions.find(s => s.id === id);
    if (!sess) return;
    card.addEventListener("click", (e) => {
      // Map-link sub-click is handled separately
      if (e.target.closest(".map-link")) return;
      openDetail(sess);
    });
    card.querySelector(".map-link")?.addEventListener("click", (e) => {
      e.stopPropagation();
      openOnMap(sess);
    });
  });

  placeNowBar();
}

function formatDay(iso) {
  // e.g. "2026-05-18" -> "Monday · May 18"
  try {
    const d = new Date(iso + "T00:00:00");
    const weekday = d.toLocaleDateString("en-US", { weekday: "long" });
    const monthDay = d.toLocaleDateString("en-US", { month: "long", day: "numeric" });
    return `${weekday} · ${monthDay}`;
  } catch (_) {
    return iso;
  }
}

function placeNowBar() {
  const root = document.getElementById("timeline");
  if (!root) return;
  // Remove old bar
  root.querySelector(".now-bar")?.remove();

  const day = todayISO();
  if (!day) return;
  const now = new Date();
  const nowMin = now.getHours() * 60 + now.getMinutes();

  // Find the timeslot rows for this day, sorted by start
  const rows = [...root.querySelectorAll(`.timeslot[data-day="${day}"]`)];
  if (!rows.length) return;
  rows.sort((a, b) => a.dataset.start.localeCompare(b.dataset.start));

  // Figure out where to insert the bar. We position vertically by interpolating
  // between the previous row's bottom and the next row's top in actual pixel
  // space, weighted by time.
  let insertBefore = null;
  let insertAfter = null;
  for (const r of rows) {
    const s = toMin(r.dataset.start);
    if (nowMin < s) { insertBefore = r; break; }
    insertAfter = r;
  }

  const bar = document.createElement("div");
  bar.className = "now-bar";
  const label = now.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  bar.innerHTML = `<div class="now-bar-pill">Now · ${label}</div><div class="now-bar-line"></div>`;
  // Position the bar between the two rows; if "now" is between sessions,
  // interpolate vertically between them.
  if (insertAfter && insertBefore) {
    const afterEnd = toMin(insertAfter.dataset.end);
    const beforeStart = toMin(insertBefore.dataset.start);
    const span = Math.max(1, beforeStart - afterEnd);
    const frac = Math.min(1, Math.max(0, (nowMin - afterEnd) / span));
    insertAfter.insertAdjacentElement("afterend", bar);
    bar.style.marginTop = `${Math.round(8 + 24 * frac)}px`;
  } else if (insertBefore) {
    // "Now" is before the first session of the day — place at the top
    rows[0].insertAdjacentElement("beforebegin", bar);
  } else if (insertAfter) {
    // "Now" is after the last session — place at the bottom
    insertAfter.insertAdjacentElement("afterend", bar);
  }
}

async function openDetail(sess) {
  const detail = document.getElementById("schedule-detail");
  if (!detail) return;
  detail.hidden = false;
  const speakers = (sess.speaker_ids || [])
    .map(sid => state.speakers?.find(sp => sp.id === sid))
    .filter(Boolean);
  const score = matchScore(sess);
  const dayLabel = formatDay(sess.day);
  detail.innerHTML = `
    <div class="detail-head">
      <div>
        <div class="detail-day">${dayLabel} · ${sess.start}–${sess.end}</div>
        <h3>${escape(sess.title)}</h3>
        <div class="sub">${escape(sess.room || "")} ${sess.room ? "· " : ""}${escape(sess.track)} · ${score}% match</div>
      </div>
      <button class="x" aria-label="Close">✕</button>
    </div>
    ${sess.abstract ? `<div class="desc">${escape(sess.abstract)}</div>` : ""}
    ${(sess.tags && sess.tags.length) ? `<div class="tags">${sess.tags.map(t => `<span class="tag">${escape(t)}</span>`).join("")}</div>` : ""}
    ${speakers.length ? `
      <div class="speakers">
        <div class="section-label">${speakers.length === 1 ? "Speaker" : `${speakers.length} Speakers`}</div>
        <div class="speaker-list">
          ${speakers.map(sp => `
            <div class="speaker">
              <div class="speaker-avatar">${initialOf(sp.name)}</div>
              <div class="speaker-meta">
                <div class="speaker-name">${escape(sp.name)}</div>
                <div class="speaker-sub">${escape(sp.title || "")}${sp.title && sp.company ? " · " : ""}${escape(sp.company || "")}</div>
              </div>
            </div>
          `).join("")}
        </div>
      </div>
    ` : ""}
    <div class="actions">
      <button class="ann" data-act="map">📍 Find on map</button>
      <button class="ann" data-act="save">☆ Save for later</button>
      <button class="ann" data-act="attended">✓ Mark attended</button>
    </div>
  `;
  detail.querySelector(".x")?.addEventListener("click", () => { detail.hidden = true; });
  detail.querySelectorAll("button.ann").forEach(btn => {
    btn.addEventListener("click", () => {
      const act = btn.dataset.act;
      if (act === "map") {
        openOnMap(sess);
        return;
      }
      const tool = act === "save" ? "save_for_later" : "mark_visited";
      fetch(state.apiBase + "/api/tool/" + tool, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ user_id: state.userId, entity_id: sess.id }),
      }).then(r => r.json()).then(() => {
        toast(act === "save" ? "Saved for later" : "Marked attended");
        // Refresh plan and detail
        fetch(state.apiBase + "/api/plan/" + state.userId).then(r => r.json()).then(plan => {
          state.plan = plan; refreshSchedule();
        });
      });
    });
  });
  detail.scrollTop = 0;
}

function initialOf(name) {
  const parts = String(name || "").trim().split(/\s+/);
  return ((parts[0]?.[0] || "?") + (parts[1]?.[0] || "")).toUpperCase().slice(0, 2);
}

async function openOnMap(sess) {
  const speakerCompanies = (sess.speaker_ids || [])
    .map(sid => state.speakers?.find(sp => sp.id === sid)?.company)
    .filter(Boolean);
  let booth = null;
  for (const co of speakerCompanies) {
    const lc = co.toLowerCase();
    const ex = state.exhibitors.find(e => e.company.toLowerCase() === lc);
    if (ex) { booth = ex.booth_number; break; }
  }
  document.querySelector('.view-switch button[data-view="map"]')?.click();
  if (booth) {
    const mapMod = await import("./map.js");
    mapMod.applyHighlights([booth]);
  } else {
    toast("This session's speaker company isn't on the floor plan.");
  }
}

function matchScore(e) {
  const text = `${e.title} ${(e.tags||[]).join(" ")}`.toLowerCase();
  const interests = ["lora","iot","edge","cooling","gemini","agent","llm","quantum"];
  const hits = interests.filter(i => text.includes(i)).length;
  return Math.min(99, 60 + hits * 12);
}

function escape(s) {
  return String(s || "").replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;" }[c]));
}
