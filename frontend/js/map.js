/* Map module — base PNG + SVG pin overlay. §2.1, §2.2 protocol.
   Pin states (priority high→low): you_are_here, in_plan, focus, match, visited, default. */

import { state, toast } from "./app.js";

const W = 1600, H = 1000;
let svg, pinsByBooth = {}, exhibitorByBooth = {};

const COLORS = {
  you:     { fill: "#4cc4ff", stroke: "#0a0e1f", halo: "#4cc4ff" },
  plan:    { fill: "transparent", stroke: "#a78bfa", halo: null },
  focus:   { fill: "#38e1c4", stroke: "#053e36", halo: "#38e1c4" },
  match:   { fill: "rgba(94,226,199,0.55)", stroke: "rgba(94,226,199,0.0)" },
  visited: { fill: "#94a3b8", stroke: "#1a2042" },
  default: { fill: "#3b446e", stroke: "#0a0e1f" },
};

export function initMap(_state) {
  svg = document.getElementById("map-overlay");
  const img = document.getElementById("map-base");
  img.src = (state.apiBase || "") + "/api/floorplan.png";

  // build exhibitor index
  for (const ex of state.exhibitors) exhibitorByBooth[ex.booth_number] = ex;

  for (const b of state.booths) {
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.classList.add("pin");
    g.dataset.booth = b.booth_number;
    const [cx, cy] = b.center;
    const halo = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    halo.classList.add("halo");
    halo.setAttribute("cx", cx); halo.setAttribute("cy", cy);
    halo.setAttribute("r", 0); halo.setAttribute("fill", "transparent");
    g.appendChild(halo);
    const pulse = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    pulse.classList.add("pulse"); pulse.setAttribute("cx", cx); pulse.setAttribute("cy", cy);
    pulse.setAttribute("r", 0); pulse.setAttribute("fill", "transparent");
    g.appendChild(pulse);
    const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    dot.classList.add("pin-dot");
    dot.setAttribute("cx", cx); dot.setAttribute("cy", cy);
    dot.setAttribute("r", 6);
    dot.setAttribute("fill", COLORS.default.fill);
    dot.setAttribute("stroke", COLORS.default.stroke);
    dot.setAttribute("stroke-width", 1.4);
    g.appendChild(dot);
    g.addEventListener("click", () => showDetail(b.booth_number));
    g.addEventListener("mouseenter", () => dot.setAttribute("r", 8));
    g.addEventListener("mouseleave", () => paintPin(b.booth_number));
    svg.appendChild(g);
    pinsByBooth[b.booth_number] = { g, dot, halo, pulse, state: { match: isMatch(b) } };
  }

  // initial paint: match pins for user's interests
  for (const k of Object.keys(pinsByBooth)) paintPin(k);

  document.getElementById("map-reset")?.addEventListener("click", () => {
    state.highlights = [];
    for (const k of Object.keys(pinsByBooth)) {
      pinsByBooth[k].state.focus = false;
      pinsByBooth[k].state.from = false;
      paintPin(k);
    }
    document.getElementById("map-detail").hidden = true;
  });
}

function isMatch(booth) {
  const ex = exhibitorByBooth[booth.booth_number];
  if (!ex) return false;
  const interests = ["lora","iot","edge","cooling","data center","llm","agent","cyber","post-quantum","pqc","gemini"];
  const tagstr = (ex.tags || []).join(" ").toLowerCase() + " " + (ex.description||"").toLowerCase();
  return interests.some(i => tagstr.includes(i));
}

function paintPin(booth) {
  const p = pinsByBooth[booth];
  if (!p) return;
  const { dot, halo, pulse, state: s } = p;
  let style = COLORS.default, r = 5, haloR = 0, haloFill = "transparent";
  if (s.visited) { style = COLORS.visited; r = 5; }
  if (s.match)   { style = COLORS.match; r = 5; }
  if (s.in_plan) { style = COLORS.plan; r = 7; haloR = 10; haloFill = "rgba(167,139,250,0.15)"; }
  if (s.focus)   { style = COLORS.focus; r = 8; haloR = 14; haloFill = "rgba(56,225,196,0.25)"; }
  if (s.you)     { style = COLORS.you; r = 9; haloR = 18; haloFill = "rgba(76,196,255,0.3)"; }
  dot.setAttribute("fill", style.fill);
  dot.setAttribute("stroke", style.stroke);
  dot.setAttribute("r", r);
  halo.setAttribute("r", haloR);
  halo.setAttribute("fill", haloFill);
}

function pulseOnce(booth) {
  const p = pinsByBooth[booth];
  if (!p) return;
  const { pulse, dot } = p;
  pulse.setAttribute("fill", "rgba(56,225,196,0.45)");
  pulse.setAttribute("r", parseFloat(dot.getAttribute("r")));
  pulse.animate(
    [{ r: 6, opacity: 0.9 }, { r: 28, opacity: 0 }],
    { duration: 1600, easing: "ease-out", fill: "forwards" }
  );
}

export function setYouAreHere(booth) {
  for (const k of Object.keys(pinsByBooth)) {
    pinsByBooth[k].state.you = false;
  }
  if (pinsByBooth[booth]) {
    pinsByBooth[booth].state.you = true;
    pulseOnce(booth);
  }
  for (const k of Object.keys(pinsByBooth)) paintPin(k);
}

export function applyHighlights(booths, from=null) {
  // clear previous focus
  for (const k of Object.keys(pinsByBooth)) pinsByBooth[k].state.focus = false;
  for (const b of (booths || [])) {
    if (pinsByBooth[b]) {
      pinsByBooth[b].state.focus = true;
      pulseOnce(b);
    }
  }
  for (const k of Object.keys(pinsByBooth)) paintPin(k);
  // walking-line from current location (or 'from') to first highlight
  drawWalkingLine(from);
}

function drawWalkingLine(from) {
  let line = svg.querySelector(".walk-line");
  if (line) line.remove();
  // Find user-location
  let origin = from;
  if (!origin) {
    for (const k of Object.keys(pinsByBooth)) if (pinsByBooth[k].state.you) origin = k;
  }
  if (!origin) return;
  const target = Object.keys(pinsByBooth).find(k => pinsByBooth[k].state.focus);
  if (!target || target === origin) return;
  const a = state.booths.find(b => b.booth_number === origin);
  const z = state.booths.find(b => b.booth_number === target);
  if (!a || !z) return;
  line = document.createElementNS("http://www.w3.org/2000/svg", "line");
  line.classList.add("walk-line");
  line.setAttribute("x1", a.center[0]); line.setAttribute("y1", a.center[1]);
  line.setAttribute("x2", z.center[0]); line.setAttribute("y2", z.center[1]);
  line.setAttribute("stroke", "rgba(56,225,196,0.7)");
  line.setAttribute("stroke-width", 2.5);
  line.setAttribute("stroke-dasharray", "8 6");
  line.setAttribute("fill", "none");
  svg.insertBefore(line, svg.firstChild);
}

function showDetail(booth) {
  const ex = exhibitorByBooth[booth];
  const el = document.getElementById("map-detail");
  el.hidden = false;
  const ann = state.annotations[ex?.id] || {};
  const flagIcons = (ann.flags || []).map(f => f === "free_drinks" ? "☕" : "🎁").join(" ");
  const rating = ann.rating_mean ? `★ ${ann.rating_mean} (${ann.rating_count})` : "";
  el.innerHTML = `
    <h3>${ex ? ex.company : "Empty booth"}</h3>
    <div class="sub">${booth} · ${ex?.hall_zone || ""}</div>
    <div class="desc">${ex ? ex.description : "(no exhibitor assigned)"}</div>
    <div class="ann-row">
      ${flagIcons ? `<span>${flagIcons}</span>` : ""}
      ${rating ? `<span>${rating}</span>` : ""}
    </div>
    ${ex ? `<div class="ann-row" style="margin-top:8px">
      <button class="ann" data-ann="free_drinks">+ Free drinks</button>
      <button class="ann" data-ann="good_swag">+ Good swag</button>
      <button class="ann" data-ann="here">I'm here</button>
    </div>` : ""}
  `;
  el.querySelectorAll("button.ann").forEach(btn => {
    btn.addEventListener("click", async () => {
      const k = btn.dataset.ann;
      if (k === "here") {
        await fetch(state.apiBase + "/api/tool/set_user_location", {
          method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ user_id: state.userId, reference: booth })
        }).then(r => r.json());
        setYouAreHere(booth);
        toast(`📍 You're at ${booth}`);
        return;
      }
      await fetch(state.apiBase + "/api/tool/submit_annotation", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ user_id: state.userId, entity_id: ex.id, ann_type: k, payload: {} })
      }).then(r => r.json());
      const summary = await fetch(state.apiBase + "/api/annotations/summary").then(r => r.json());
      state.annotations = summary;
      toast("Thanks — added");
      showDetail(booth);
    });
  });
}
