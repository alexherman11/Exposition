/* Top-level orchestrator. Holds shared state and routes view switches. */

import { initChat, sendChat } from "./chat.js";
import { initMap, applyHighlights, setYouAreHere } from "./map.js";
import { initSchedule, refreshSchedule } from "./schedule.js";

const API_BASE = window.location.port === "5173" || window.location.port === "8080"
  ? "http://" + window.location.hostname + ":8000"
  : "";

const WS_BASE = (API_BASE || window.location.origin).replace(/^http/, "ws");

export const state = {
  userId: "demo",
  apiBase: API_BASE,
  wsBase: WS_BASE,
  view: "chat",
  highlights: [],
  plan: [],
  booths: [],
  exhibitors: [],
  sessions: [],
  annotations: {},
};

/* ─── view switching ─── */
function setView(name) {
  state.view = name;
  document.querySelectorAll(".view-switch button").forEach(b => b.classList.toggle("active", b.dataset.view === name));
  document.querySelectorAll(".view-pane").forEach(p => p.hidden = (p.dataset.pane !== name && p.dataset.pane !== "chat"));
  document.body.classList.toggle("view-map", name === "map");
  document.body.classList.toggle("view-schedule", name === "schedule");
  // chat is always visible on desktop (side panel)
  document.querySelector('.view-pane[data-pane="map"]').hidden = name !== "map";
  document.querySelector('.view-pane[data-pane="schedule"]').hidden = name !== "schedule";
}

/* ─── boot ─── */
async function boot() {
  // Fetch corpus
  try {
    const [booths, exhibitors, sessions, annSummary] = await Promise.all([
      fetch(API_BASE + "/api/booths").then(r => r.json()),
      fetch(API_BASE + "/api/exhibitors").then(r => r.json()),
      fetch(API_BASE + "/api/sessions").then(r => r.json()),
      fetch(API_BASE + "/api/annotations/summary").then(r => r.json()).catch(() => ({})),
    ]);
    state.booths = booths;
    state.exhibitors = exhibitors;
    state.sessions = sessions;
    state.annotations = annSummary;
  } catch (e) {
    console.error("corpus fetch failed", e);
    toast("Backend not reachable — start it on :8000");
  }

  initMap(state);
  initSchedule(state);
  initChat(state);

  // Plan
  try {
    state.plan = await fetch(API_BASE + "/api/plan/" + state.userId).then(r => r.json());
    refreshSchedule();
  } catch (e) {}

  // View switcher
  document.querySelectorAll(".view-switch button").forEach(b => {
    b.addEventListener("click", () => setView(b.dataset.view));
  });

  // Prompt chips
  document.querySelectorAll(".chip").forEach(c => {
    c.addEventListener("click", () => sendChat(c.textContent));
  });

  // Chat form
  const form = document.getElementById("chat-form");
  form.addEventListener("submit", e => {
    e.preventDefault();
    const input = document.getElementById("chat-text");
    const text = input.value.trim();
    if (text) {
      sendChat(text);
      input.value = "";
    }
  });

  // SW
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/service-worker.js").catch(() => {});
  }
}

/* ─── toast helper, exported globally ─── */
export function toast(text, kind="info") {
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.textContent = text;
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

/* ─── agent-event dispatcher (called by chat) ─── */
export async function handleAgentEvent(ev) {
  if (ev.type === "tool_result" && ev.result && ev.result._ui) {
    const ui = ev.result._ui;
    if (ui.you_are_here) {
      setYouAreHere(ui.you_are_here);
    }
    if (ui.highlights && ui.highlights.length) {
      applyHighlights(ui.highlights, ui.from);
      if (state.view !== "map" && ev.name !== "search_entities") {
        // gentle nudge to switch view when location/nearby is the focus
        if (ev.name === "query_nearby" || ev.name === "highlight_on_map") {
          setView("map");
        }
      }
    }
    if (ui.plan_changed) {
      state.plan = await fetch(API_BASE + "/api/plan/" + state.userId).then(r => r.json());
      refreshSchedule();
      if (ev.name === "build_or_revise_plan") setView("schedule");
    }
    if (ui.annotation_updated) {
      state.annotations = await fetch(API_BASE + "/api/annotations/summary").then(r => r.json());
    }
  }
}

boot();
