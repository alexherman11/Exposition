/* Schedule timeline — proportional time spacing, animated card mutations. §3.1. */

import { state } from "./app.js";

let activeLayer = "planned";

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
}

const TRACK_KEYS = {
  "AI & Big Data": "ai",
  "IoT Tech": "iot",
  "Edge Computing": "edge",
  "Cyber Security": "cyber",
  "Data Centre": "data",
  "Digital Transformation": "data",
  "Intelligent Automation": "ai",
};

function toMin(s) { const [h,m] = s.split(":").map(Number); return h*60+m; }

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
      html.push(`<div style="margin: 18px 0 12px; color: var(--text-mute); font-size: 12px; letter-spacing: 0.6px; text-transform: uppercase;">${e.day}</div>`);
      prevDay = e.day;
      prevEnd = null;
    } else if (prevEnd) {
      const gap = toMin(e.start) - toMin(prevEnd);
      if (gap > 5) {
        html.push(`<div class="timeslot gap"><div class="time"></div><div class="gap-note">${gap} min — ${gap >= 25 ? "fillable" : "tight turnaround"}</div></div>`);
      }
    }

    const trackClass = TRACK_KEYS[e.track] || "ai";
    html.push(`
      <div class="timeslot">
        <div class="time">${e.start}<br><span style="font-size:10px; opacity:0.6">${e.end}</span></div>
        <div class="card add-anim" data-id="${e.id}" data-track-${trackClass}>
          <div class="row-1">
            <div class="title">${escape(e.title)}</div>
            <div class="match">${matchScore(e)}%</div>
          </div>
          <div class="meta">${e.room} · ${e.track}</div>
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
}

function matchScore(e) {
  // toy: count interest hits
  const text = `${e.title} ${(e.tags||[]).join(" ")}`.toLowerCase();
  const interests = ["lora","iot","edge","cooling","gemini","agent","llm","quantum"];
  const hits = interests.filter(i => text.includes(i)).length;
  return Math.min(99, 60 + hits * 12);
}

function escape(s) {
  return String(s || "").replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;" }[c]));
}
