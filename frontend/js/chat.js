/* Streaming chat over WebSocket with tool-call pills inline. §4.6. */

import { state, handleAgentEvent, toast } from "./app.js";

let ws = null;
let currentAgentBubble = null;
let currentPills = null;

const TOOL_LABEL = {
  search_entities:       "Searching the corpus…",
  get_entity:            "Looking up details…",
  set_user_location:     "Updating your location…",
  query_nearby:          "Scanning what's nearby…",
  build_or_revise_plan:  "Building your day plan…",
  update_schedule:       "Updating your schedule…",
  highlight_on_map:      "Highlighting on the map…",
  mark_visited:          "Marking visited…",
  save_for_later:        "Saving for later…",
  submit_annotation:     "Recording your note…",
  summarize_day:         "Drafting your recap…",
  web_search:            "Looking it up online…",
};

const TOOL_DONE = {
  search_entities: (r) => `✓ Found ${(r.results||[]).length} matches`,
  set_user_location: (r) => r.error ? `× Couldn't locate "${r.reference}"` : `✓ You're at ${r.booth_number}${r.exhibitor ? " · " + r.exhibitor : ""}`,
  query_nearby: (r) => `✓ ${(r.results||[]).length} nearby`,
  build_or_revise_plan: (r) => `✓ ${(r.plan||[]).length}-stop plan`,
  update_schedule: (r) => `✓ Schedule updated`,
  highlight_on_map: (r) => `✓ Highlighted ${(r.booths||[]).length}`,
  mark_visited: () => `✓ Marked visited`,
  save_for_later: () => `✓ Saved`,
  submit_annotation: () => `✓ Recorded`,
  summarize_day: () => `✓ Recap ready`,
  web_search: (r) => r.error ? `× Web search failed` : `✓ Web result`,
  get_entity: () => `✓ Loaded`,
};

export function initChat(_state) {
  connectWs();
}

function connectWs() {
  const url = state.wsBase + "/ws/chat/" + state.userId;
  ws = new WebSocket(url);
  ws.onopen = () => console.log("ws open");
  ws.onclose = () => { ws = null; setTimeout(connectWs, 2000); };
  ws.onerror = e => console.error("ws err", e);
  ws.onmessage = e => {
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }
    onAgentEvent(msg);
  };
}

export function sendChat(text) {
  if (!ws || ws.readyState !== 1) {
    toast("Reconnecting…");
    setTimeout(() => sendChat(text), 600);
    return;
  }
  appendUserMessage(text);
  startAgentMessage();
  ws.send(JSON.stringify({ text }));
}

function appendUserMessage(text) {
  const scroll = document.getElementById("chat-scroll");
  const wrap = document.createElement("div");
  wrap.className = "msg user";
  wrap.innerHTML = `<div class="bubble"></div>`;
  wrap.querySelector(".bubble").textContent = text;
  scroll.appendChild(wrap);
  scroll.scrollTop = scroll.scrollHeight;
}

function startAgentMessage() {
  const scroll = document.getElementById("chat-scroll");
  const wrap = document.createElement("div");
  wrap.className = "msg agent";
  wrap.innerHTML = `
    <div class="pills"></div>
    <div class="bubble streaming"></div>
  `;
  scroll.appendChild(wrap);
  currentAgentBubble = wrap.querySelector(".bubble");
  currentPills = wrap.querySelector(".pills");
  scroll.scrollTop = scroll.scrollHeight;
}

function onAgentEvent(ev) {
  if (ev.type === "tool_call") {
    if (!currentPills) startAgentMessage();
    const pill = document.createElement("span");
    pill.className = "toolpill";
    pill.dataset.tool = ev.name;
    pill.innerHTML = `<span class="dot"></span>${TOOL_LABEL[ev.name] || ev.name}`;
    currentPills.appendChild(pill);
  } else if (ev.type === "tool_result") {
    if (currentPills) {
      const pills = currentPills.querySelectorAll(`.toolpill[data-tool="${ev.name}"]`);
      const pill = pills[pills.length - 1];
      if (pill) {
        pill.classList.add("done");
        pill.innerHTML = `<span class="dot"></span>${TOOL_DONE[ev.name] ? TOOL_DONE[ev.name](ev.result || {}) : "✓ Done"}`;
      }
    }
    handleAgentEvent(ev);
  } else if (ev.type === "text_delta") {
    if (!currentAgentBubble) startAgentMessage();
    currentAgentBubble.textContent += ev.delta;
    const scroll = document.getElementById("chat-scroll");
    scroll.scrollTop = scroll.scrollHeight;
  } else if (ev.type === "done") {
    if (currentAgentBubble) currentAgentBubble.classList.remove("streaming");
    currentAgentBubble = null;
    currentPills = null;
  } else if (ev.type === "error") {
    if (currentAgentBubble) {
      currentAgentBubble.classList.remove("streaming");
      currentAgentBubble.textContent = "Sorry — " + (ev.message || "something went wrong.");
      currentAgentBubble = null;
    }
  }
}
