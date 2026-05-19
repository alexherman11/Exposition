/* Map — renders the official TechEx NA 2026 floorplan as pure SVG.
 *
 * Layout JSON (served from /api/floorplan_layout.json) is extracted from the
 * official PDF. We re-draw every shape (floor, walls, zones, amenities,
 * booths) in our own palette, with proper rounded corners, hover states,
 * and a separate highlight overlay layer that the agent operates via the
 * §2.2 pin protocol.
 *
 * Interactions:
 *   - mouse wheel / pinch zooms into the cursor
 *   - drag pans the map
 *   - tap a booth to open detail
 *   - "Fit" button resets the view, "+/-" buttons step zoom
 */

import { state, toast } from "./app.js";

// PDF coordinate space is the SVG viewBox.
const ZONE_THEME = {
  zone_ai:    { fill: "#FFD7E8", stroke: "#E33D8C", text: "#7A1B45" },  // pink — AI & Big Data
  zone_cyber: { fill: "#FFD7BD", stroke: "#E66128", text: "#7A2E0B" },  // orange — Cyber Security
  zone_iot:   { fill: "#CDEFFF", stroke: "#1FB8E8", text: "#0A4A66" },  // cyan — IoT Tech
  zone_edge:  { fill: "#CFEFE2", stroke: "#26A47A", text: "#0E4A36" },  // green — Edge Computing
  zone_dt:    { fill: "#CFDBEF", stroke: "#3157A4", text: "#1A2C5B" },  // blue — Digital Transformation / Data Center
  zone_ia:    { fill: "#E2D4EE", stroke: "#7A4FB0", text: "#3A1E5F" },  // purple — Intelligent Automation
  zone_phys:  { fill: "#FFD0CD", stroke: "#DD4D44", text: "#7A1F19" },  // pink-red — Physical AI / AI Developer
};

const COLORS = {
  floor:      "#F4F0E6",
  floor_edge: "#E5DECD",
  wall:       "#1F2937",
  outer_wall: "#9CA3AF",
  booth:      "#FFFFFF",
  booth_edge: "#D8D4C8",
  booth_text: "#475569",
  yellow:     "#FFD43B",
  yellow_edge:"#E7B400",
  yellow_text:"#5C4400",
  amenity_text:"#1F2937",
};

const PIN = {
  you:     { fill: "#3B82F6", stroke: "#FFFFFF", halo: "rgba(59,130,246,0.30)" },
  plan:    { fill: "#FFFFFF", stroke: "#7C3AED", halo: "rgba(124,58,237,0.18)" },
  focus:   { fill: "#FB7185", stroke: "#FFFFFF", halo: "rgba(251,113,133,0.30)" },
  match:   { fill: "#34D399", stroke: "#FFFFFF", halo: "rgba(52,211,153,0.20)" },
  visited: { fill: "#9CA3AF", stroke: "#FFFFFF", halo: "rgba(156,163,175,0.15)" },
};

const SVG_NS = "http://www.w3.org/2000/svg";
const el = (tag, attrs = {}, parent = null) => {
  const n = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null) continue;
    n.setAttribute(k, String(v));
  }
  if (parent) parent.appendChild(n);
  return n;
};

const text = (str, attrs = {}, parent = null) => {
  const n = el("text", attrs, parent);
  n.textContent = str;
  return n;
};

/* Fit a company name inside a booth rect.
 *   - tries multiple font sizes from large to tiny
 *   - wraps onto up to 2 lines (line-break at word boundary)
 *   - if even tiny+2-lines doesn't fit, truncates with "…"
 *
 * We use an offscreen <text> in the SVG to measure widths since the
 * browser hasn't laid out our viewport yet at this point.
 */
let _measureSvg = null;
function ensureMeasureSvg() {
  if (_measureSvg) return _measureSvg;
  _measureSvg = document.createElementNS(SVG_NS, "svg");
  _measureSvg.setAttribute("style", "position:absolute; left:-9999px; top:-9999px;");
  document.body.appendChild(_measureSvg);
  return _measureSvg;
}
function measureText(str, fontSize, weight = 500) {
  const svg = ensureMeasureSvg();
  const t = document.createElementNS(SVG_NS, "text");
  t.setAttribute("font-size", fontSize);
  t.setAttribute("font-weight", weight);
  t.setAttribute("font-family", "Inter, sans-serif");
  t.textContent = str;
  svg.appendChild(t);
  const bb = t.getBBox();
  svg.removeChild(t);
  return { w: bb.width, h: bb.height };
}
function truncateToWidth(str, fontSize, maxW, weight = 500) {
  if (measureText(str, fontSize, weight).w <= maxW) return str;
  let lo = 1, hi = str.length;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (measureText(str.slice(0, mid) + "…", fontSize, weight).w <= maxW) lo = mid;
    else hi = mid - 1;
  }
  return str.slice(0, lo) + "…";
}
function fitCompanyLabel(g, bbox, company) {
  const [x0, y0, x1, y1] = bbox;
  const w = (x1 - x0) - 4;
  const h = (y1 - y0) - 4;
  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2;
  if (w < 8 || h < 6) return;
  const weight = 600;
  // Try font sizes from large to small; for each, try 1 line then 2 lines.
  const sizes = [11, 10, 9, 8, 7, 6.5, 6, 5.5];
  for (const fs of sizes) {
    if (fs > h * 0.95) continue;       // single line wouldn't even fit vertically
    const m = measureText(company, fs, weight);
    if (m.w <= w) {
      // Single line at this size fits
      text(company, {
        x: cx, y: cy,
        "text-anchor": "middle",
        "dominant-baseline": "central",
        "font-size": fs, "font-weight": weight,
        fill: COLORS.booth_text,
        "pointer-events": "none",
      }, g);
      return;
    }
    // Try 2-line wrap (only if we have vertical room: 2 * fs * 1.05 ≤ h)
    if (2 * fs * 1.05 <= h) {
      const words = company.split(/\s+/);
      // Find best split that minimizes the longer line width
      let best = null;
      for (let i = 1; i < words.length; i++) {
        const line1 = words.slice(0, i).join(" ");
        const line2 = words.slice(i).join(" ");
        const m1 = measureText(line1, fs, weight).w;
        const m2 = measureText(line2, fs, weight).w;
        const score = Math.max(m1, m2);
        if (m1 <= w && m2 <= w && (!best || score < best.score)) {
          best = { line1, line2, score };
        }
      }
      if (best) {
        const t = el("text", {
          x: cx, y: cy,
          "text-anchor": "middle",
          "dominant-baseline": "central",
          "font-size": fs, "font-weight": weight,
          fill: COLORS.booth_text,
          "pointer-events": "none",
        }, g);
        // Two tspans, vertically centered around cy
        const lineH = fs * 1.1;
        const ts1 = document.createElementNS(SVG_NS, "tspan");
        ts1.setAttribute("x", cx); ts1.setAttribute("dy", `${-lineH / 2}`);
        ts1.textContent = best.line1;
        const ts2 = document.createElementNS(SVG_NS, "tspan");
        ts2.setAttribute("x", cx); ts2.setAttribute("dy", `${lineH}`);
        ts2.textContent = best.line2;
        t.appendChild(ts1); t.appendChild(ts2);
        return;
      }
    }
  }
  // Nothing fit cleanly — truncate at the smallest size, single line
  const fs = Math.max(5.5, Math.min(7, h * 0.7));
  const truncated = truncateToWidth(company, fs, w, weight);
  text(truncated, {
    x: cx, y: cy,
    "text-anchor": "middle",
    "dominant-baseline": "central",
    "font-size": fs, "font-weight": weight,
    fill: COLORS.booth_text,
    "pointer-events": "none",
  }, g);
}

let layout = null;
let svg = null;
let viewport = null;        // pan/zoom group
let overlayGroup = null;    // highlight pins
let exhibitorByBooth = {};
let boothNodes = {};
let pinNodes = {};
let viewState = { tx: 0, ty: 0, scale: 1 };
let viewBox = [0, 0, 1, 1];

const INTEREST_KEYWORDS = ["lora", "iot", "edge", "cooling", "data center", "llm", "agent", "cyber", "post-quantum", "pqc", "gemini", "robot"];

export async function initMap(_state) {
  const wrap = document.getElementById("map-wrap");
  wrap.innerHTML = "";

  // Fetch layout
  try {
    layout = await fetch(state.apiBase + "/api/floorplan_layout.json").then(r => r.json());
  } catch (e) {
    console.error("layout fetch failed", e);
    wrap.innerHTML = `<div class="map-fallback">Couldn't load floorplan layout. Run <code>python scripts/extract_floorplan.py</code> in the backend.</div>`;
    return;
  }

  viewBox = layout.viewbox || [0, 0, layout.page_size[0], layout.page_size[1]];

  svg = el("svg", {
    xmlns: SVG_NS,
    viewBox: viewBox.join(" "),
    preserveAspectRatio: "xMidYMid meet",
    class: "floorplan-svg",
  });
  wrap.appendChild(svg);

  // Defs — filters & gradients
  const defs = el("defs", {}, svg);
  defs.innerHTML = `
    <filter id="softShadow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur in="SourceAlpha" stdDeviation="6"/>
      <feOffset dx="0" dy="4"/>
      <feComponentTransfer><feFuncA type="linear" slope="0.18"/></feComponentTransfer>
      <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="zoneShadow" x="-10%" y="-10%" width="120%" height="120%">
      <feGaussianBlur in="SourceAlpha" stdDeviation="2"/>
      <feOffset dx="0" dy="1"/>
      <feComponentTransfer><feFuncA type="linear" slope="0.10"/></feComponentTransfer>
      <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  `;

  viewport = el("g", { id: "viewport" }, svg);

  // 1. Floor background — render every floor rect with the same fill so they
  //    union visually into one continuous building footprint. No stroke (no
  //    seams). A soft drop shadow sits behind the union via filter.
  const floorGroup = el("g", { filter: "url(#softShadow)" }, viewport);
  for (const f of layout.floors) {
    el("rect", {
      x: f.bbox[0], y: f.bbox[1],
      width: f.bbox[2] - f.bbox[0],
      height: f.bbox[3] - f.bbox[1],
      rx: 14, ry: 14,
      fill: COLORS.floor,
      stroke: "none",
    }, floorGroup);
  }

  // 2. Zone fills (colored regions) — soft rounded fills with subtle stroke
  for (const z of layout.zones) {
    const theme = ZONE_THEME[z.tag] || ZONE_THEME.zone_ai;
    const [x0, y0, x1, y1] = z.bbox;
    el("rect", {
      x: x0, y: y0,
      width: x1 - x0, height: y1 - y0,
      rx: 10, ry: 10,
      fill: theme.fill,
      stroke: theme.stroke,
      "stroke-width": 1.5,
      "fill-opacity": 0.92,
      filter: "url(#zoneShadow)",
      class: "zone-rect",
      "data-tag": z.tag,
    }, viewport);

    // Zone label (large, friendly)
    if (z.label) {
      const cx = (x0 + x1) / 2;
      const cy = (y0 + y1) / 2;
      const lines = z.label.split(/[\s/]/).reduce((acc, w) => {
        // simple wrap into 2 lines when long
        if (!acc.length) return [w];
        if (acc[acc.length - 1].length + w.length < 12) acc[acc.length - 1] += " " + w;
        else acc.push(w);
        return acc;
      }, []);
      const lineH = Math.min(22, (y1 - y0) / (lines.length + 1));
      const startY = cy - ((lines.length - 1) * lineH) / 2;
      lines.forEach((ln, i) => {
        text(ln, {
          x: cx, y: startY + i * lineH,
          "text-anchor": "middle",
          "dominant-baseline": "central",
          fill: theme.text,
          "font-weight": 700,
          "font-size": Math.max(11, Math.min(18, (x1 - x0) / 9)),
          class: "zone-label",
        }, viewport);
      });
    }
  }

  // 3. Yellow amenity rectangles (catering / lounges / startup / featured).
  //    The PDF builds each entrance arrow from a shaft + small head + tail
  //    cap rects sitting just outside the south wall. We collect every
  //    yellow rect in that south band and group them by x position to draw
  //    one clean arrow glyph per group.
  const buildingBbox = layout.building_bbox || [0, 0, viewBox[2], viewBox[3]];
  // Entrance pieces are tiny yellow rects in the south band (within 80pt of
  // the south wall or below it). Group them per arrow shaft.
  const SOUTH_BAND = buildingBbox[3] - 80;
  const entrancePieces = [];
  for (const y of layout.yellow_rects) {
    const [x0, y0, x1, y1] = y.bbox;
    const w = x1 - x0, h = y1 - y0;
    const area = w * h;
    const isEntrancePiece = y0 > SOUTH_BAND && area < 600;
    if (isEntrancePiece) { entrancePieces.push(y); continue; }
    el("rect", {
      x: x0, y: y0, width: w, height: h,
      rx: 6, ry: 6,
      fill: COLORS.yellow,
      stroke: COLORS.yellow_edge,
      "stroke-width": 1.2,
    }, viewport);
  }
  // Cluster entrance pieces by x-position (within 25pt → same arrow)
  const arrowGroups = [];
  for (const p of entrancePieces.sort((a, b) => a.bbox[0] - b.bbox[0])) {
    const cx = (p.bbox[0] + p.bbox[2]) / 2;
    const last = arrowGroups[arrowGroups.length - 1];
    if (last && Math.abs(last.cx - cx) < 25) {
      last.parts.push(p);
      last.minY = Math.min(last.minY, p.bbox[1]);
      last.maxY = Math.max(last.maxY, p.bbox[3]);
    } else {
      arrowGroups.push({ cx, parts: [p], minY: p.bbox[1], maxY: p.bbox[3] });
    }
  }
  for (const g of arrowGroups) {
    const top = g.minY;
    const bot = g.maxY;
    const cx = g.cx;
    const headH = Math.min(14, (bot - top) * 0.25);
    const headW = 10;
    el("path", {
      d: `M ${cx} ${top} L ${cx} ${bot - headH}`,
      stroke: COLORS.yellow_edge, "stroke-width": 5, "stroke-linecap": "round",
      fill: "none", "pointer-events": "none",
    }, viewport);
    el("path", {
      d: `M ${cx - headW} ${bot - headH} L ${cx} ${bot} L ${cx + headW} ${bot - headH} Z`,
      fill: COLORS.yellow_edge, stroke: "none", "pointer-events": "none",
    }, viewport);
  }

  // 4. Walls — we no longer render walls as filled rectangles. The booth grid
  //    and zone fills carry the layout, and the floor union already provides
  //    the building outline. Drawing each ~partition as a faint dark rect was
  //    visual noise.

  // 5. Empty booth rectangles (everything in booth_rects that has no number) —
  //    keep them dimmer/quieter than numbered booths.
  const numberedBooths = new Set((layout.booths || []).map(b => b.booth_number));
  for (const r of layout.booth_rects || []) {
    if (r.assigned) continue;
    const [x0, y0, x1, y1] = r.bbox;
    el("rect", {
      x: x0, y: y0,
      width: x1 - x0, height: y1 - y0,
      rx: 3, ry: 3,
      fill: COLORS.booth, "fill-opacity": 0.5,
      stroke: COLORS.booth_edge, "stroke-width": 0.6,
    }, viewport);
  }

  // 6. Numbered booths — interactive. Label = company name (auto-fit to rect)
  //    when an exhibitor is assigned; otherwise the booth number.
  // Build a quick lookup
  const exByBooth = {};
  for (const ex of state.exhibitors) exByBooth[ex.booth_number] = ex;

  for (const b of layout.booths) {
    const [x0, y0, x1, y1] = b.bbox;
    const w = x1 - x0;
    const h = y1 - y0;
    const g = el("g", {
      class: "booth",
      "data-booth": b.booth_number,
    }, viewport);
    const rect = el("rect", {
      x: x0, y: y0, width: w, height: h,
      rx: 4, ry: 4,
      fill: COLORS.booth,
      stroke: COLORS.booth_edge,
      "stroke-width": 0.8,
      class: "booth-rect",
    }, g);
    const ex = exByBooth[b.booth_number];
    if (ex && ex.company) {
      fitCompanyLabel(g, b.bbox, ex.company);
    } else if (w > 14 && h > 10) {
      // Fallback: faint booth number (so empty/unstaffed booths stay legible)
      text(b.booth_number, {
        x: (x0 + x1) / 2,
        y: (y0 + y1) / 2,
        "text-anchor": "middle",
        "dominant-baseline": "central",
        "font-size": Math.max(6, Math.min(9, w * 0.28, h * 0.5)),
        "font-weight": 500,
        fill: "#94A3B8",
        "pointer-events": "none",
      }, g);
    }
    g.addEventListener("click", (e) => {
      e.stopPropagation();
      showDetail(b.booth_number);
    });
    g.addEventListener("mouseenter", () => rect.setAttribute("stroke", "#2563EB"));
    g.addEventListener("mouseleave", () => rect.setAttribute("stroke", COLORS.booth_edge));
    boothNodes[b.booth_number] = { g, rect, bbox: b.bbox, center: b.center, company: ex?.company || null };
  }

  // 7. Soft white rounded "rooms" for Meeting Rooms / Meet Up Zone so the
  //    cream floor extension doesn't look empty. We use the amenity label
  //    center and inflate a generous rect around it.
  const ROOM_SIZE = { meeting_room: [180, 70], meetup: [200, 90], learning_lab: [180, 70] };
  for (const a of layout.amenities) {
    const size = ROOM_SIZE[a.kind];
    if (!size) continue;
    const [w, h] = size;
    const cx = (a.bbox[0] + a.bbox[2]) / 2;
    const cy = (a.bbox[1] + a.bbox[3]) / 2;
    el("rect", {
      x: cx - w / 2, y: cy - h / 2,
      width: w, height: h,
      rx: 8, ry: 8,
      fill: "#FFFFFF",
      stroke: "#D8D4C8", "stroke-width": 1,
    }, viewport);
  }

  // 8. Amenity text callouts on top — keep the official labels
  for (const a of layout.amenities) {
    const [x0, y0, x1, y1] = a.bbox;
    const fontSize = a.kind === "entrance" ? 16 : 11;
    text(a.label, {
      x: (x0 + x1) / 2,
      y: (y0 + y1) / 2,
      "text-anchor": "middle",
      "dominant-baseline": "central",
      "font-size": fontSize,
      "font-weight": a.kind === "entrance" ? 800 : 600,
      fill: COLORS.amenity_text,
      class: "amenity-label",
      "data-kind": a.kind,
    }, viewport);
  }

  // 8. Highlight overlay layer (pins ride on top)
  overlayGroup = el("g", { id: "highlight-overlay", "pointer-events": "none" }, viewport);

  // Build exhibitor index
  for (const ex of state.exhibitors) exhibitorByBooth[ex.booth_number] = ex;

  // Initial match-pins for user interests
  for (const b of layout.booths) {
    if (isMatch(b.booth_number)) {
      setPinState(b.booth_number, { match: true });
    }
  }

  // Zoom & pan wiring
  attachPanZoom(wrap);

  // Toolbar buttons
  document.getElementById("map-reset")?.addEventListener("click", () => {
    fitToView();
    clearFocus();
  });
  document.getElementById("map-zoom-in")?.addEventListener("click", () => zoomBy(1.25));
  document.getElementById("map-zoom-out")?.addEventListener("click", () => zoomBy(1 / 1.25));

  // Note: we don't auto-close the detail panel on map click — the panel has its
  // own × button. A misfired svg-click handler used to swallow booth clicks.

  // Defer fit until the wrap has real dimensions
  requestAnimationFrame(() => fitToView());
  // Also re-fit on resize
  window.addEventListener("resize", () => fitToView());
}


/* ────── Zoom & pan ─────────────────────────────────────────────── */

function setTransform() {
  if (!viewport) return;
  viewport.setAttribute(
    "transform",
    `translate(${viewState.tx} ${viewState.ty}) scale(${viewState.scale})`,
  );
}

function fitToView() {
  if (!svg) return;
  const wrap = svg.parentElement;
  const wRect = wrap.getBoundingClientRect();
  if (!wRect.width || !wRect.height) return;
  // viewBox aspect ratio
  const vbW = viewBox[2], vbH = viewBox[3];
  const scale = Math.min(wRect.width / vbW, wRect.height / vbH) * 0.98;
  viewState.scale = 1;  // baseline — viewBox handles the fit
  viewState.tx = 0;
  viewState.ty = 0;
  setTransform();
}

function zoomBy(factor, cx = null, cy = null) {
  const wrap = svg.parentElement;
  const r = wrap.getBoundingClientRect();
  cx = cx ?? r.width / 2;
  cy = cy ?? r.height / 2;
  // Convert wrap-pixel into svg-viewBox coords
  const pt = clientToSvg(cx + r.left, cy + r.top);
  const newScale = Math.max(0.5, Math.min(8, viewState.scale * factor));
  // We want pt to stay under cursor: pt' = (pt - center) * (newScale/scale)
  const sRatio = newScale / viewState.scale;
  viewState.tx = pt.x - (pt.x - viewState.tx) * sRatio;
  viewState.ty = pt.y - (pt.y - viewState.ty) * sRatio;
  viewState.scale = newScale;
  setTransform();
}

function clientToSvg(clientX, clientY) {
  const pt = svg.createSVGPoint();
  pt.x = clientX; pt.y = clientY;
  const ctm = svg.getScreenCTM();
  if (!ctm) return { x: 0, y: 0 };
  return pt.matrixTransform(ctm.inverse());
}

function attachPanZoom(wrap) {
  // Pan/zoom with a drag threshold: clicks under 5px of motion are NOT eaten
  // by pan capture — they propagate to whatever booth/button is under the
  // pointer. Only sustained drags start panning (and only then is pointer
  // capture taken).
  const DRAG_THRESHOLD = 5;
  let downX = 0, downY = 0;
  let lastX = 0, lastY = 0;
  let isPanning = false;
  let activePointers = new Map();
  let pinchStart = null;
  let activePanPointer = null;

  wrap.addEventListener("pointerdown", (e) => {
    activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (activePointers.size === 2) {
      const pts = [...activePointers.values()];
      pinchStart = {
        dist: Math.hypot(pts[1].x - pts[0].x, pts[1].y - pts[0].y),
        scale: viewState.scale,
        cx: (pts[0].x + pts[1].x) / 2,
        cy: (pts[0].y + pts[1].y) / 2,
      };
      isPanning = false;
      activePanPointer = null;
    } else if (activePointers.size === 1) {
      downX = lastX = e.clientX;
      downY = lastY = e.clientY;
      isPanning = false;
      activePanPointer = e.pointerId;
      // No setPointerCapture here — let clicks reach the booth.
    }
  });

  wrap.addEventListener("pointermove", (e) => {
    if (!activePointers.has(e.pointerId)) return;
    activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

    if (activePointers.size === 2 && pinchStart) {
      const pts = [...activePointers.values()];
      const dist = Math.hypot(pts[1].x - pts[0].x, pts[1].y - pts[0].y);
      const factor = (dist / pinchStart.dist) * (pinchStart.scale / viewState.scale);
      zoomBy(factor, pinchStart.cx, pinchStart.cy);
      return;
    }
    if (e.pointerId !== activePanPointer) return;

    // Promote to drag once we've moved enough
    if (!isPanning) {
      const dx0 = e.clientX - downX;
      const dy0 = e.clientY - downY;
      if (Math.hypot(dx0, dy0) < DRAG_THRESHOLD) return;
      isPanning = true;
      try { wrap.setPointerCapture(e.pointerId); } catch (_) {}
    }

    const dx = e.clientX - lastX;
    const dy = e.clientY - lastY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return;
    const sx = ctm.a, sy = ctm.d;
    if (!sx || !sy) return;
    viewState.tx += dx / sx;
    viewState.ty += dy / sy;
    lastX = e.clientX; lastY = e.clientY;
    setTransform();
  });

  const endPointer = (e) => {
    activePointers.delete(e.pointerId);
    if (e.pointerId === activePanPointer) {
      // Suppress the click if we actually panned, by adding a one-shot capture
      // listener that swallows the next click.
      if (isPanning) {
        const swallow = (ev) => { ev.stopPropagation(); ev.preventDefault(); wrap.removeEventListener("click", swallow, true); };
        wrap.addEventListener("click", swallow, true);
        try { wrap.releasePointerCapture(e.pointerId); } catch (_) {}
      }
      activePanPointer = null;
      isPanning = false;
    }
    if (activePointers.size < 2) pinchStart = null;
  };
  wrap.addEventListener("pointerup", endPointer);
  wrap.addEventListener("pointercancel", endPointer);

  wrap.addEventListener("wheel", (e) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    const rect = wrap.getBoundingClientRect();
    zoomBy(factor, e.clientX - rect.left, e.clientY - rect.top);
  }, { passive: false });
}


/* ────── Pin state — §2.2 protocol ──────────────────────────────── */

function isMatch(boothNumber) {
  const ex = exhibitorByBooth[boothNumber];
  if (!ex) return false;
  const blob = (ex.tags || []).join(" ").toLowerCase() + " " + (ex.description || "").toLowerCase();
  return INTEREST_KEYWORDS.some(k => blob.includes(k));
}

function setPinState(boothNumber, partial) {
  const node = boothNodes[boothNumber];
  if (!node) return;
  const cur = pinNodes[boothNumber] || { state: {} };
  cur.state = { ...cur.state, ...partial };
  pinNodes[boothNumber] = cur;
  renderPin(boothNumber);
}

function renderPin(boothNumber) {
  const node = boothNodes[boothNumber];
  const data = pinNodes[boothNumber];
  if (!node || !data) return;
  // Remove old pin shapes
  data.shapes?.forEach(s => s.remove());
  data.shapes = [];

  const s = data.state;
  let style = null;
  let strong = false;  // strong states (focus/you) recolor the booth rect; weak states (match/plan/visited) just add a dot
  if (s.visited) style = PIN.visited;
  if (s.match)   style = PIN.match;
  if (s.plan)    { style = PIN.plan;  strong = true; }
  if (s.focus)   { style = PIN.focus; strong = true; }
  if (s.you)     { style = PIN.you;   strong = true; }

  if (!style) {
    // No state — keep the booth crisp
    node.rect.setAttribute("fill", COLORS.booth);
    node.rect.setAttribute("stroke", COLORS.booth_edge);
    node.rect.setAttribute("stroke-width", 0.8);
    return;
  }

  if (strong) {
    // Strong states recolor the booth so the user sees it from a distance
    node.rect.setAttribute("fill", lighten(style.fill, 0.55));
    node.rect.setAttribute("stroke", style.stroke === "#FFFFFF" ? style.fill : style.stroke);
    node.rect.setAttribute("stroke-width", 2.2);
  } else {
    // Weak states (match/visited) — keep booth white, just add a small dot
    node.rect.setAttribute("fill", COLORS.booth);
    node.rect.setAttribute("stroke", style.fill);
    node.rect.setAttribute("stroke-width", 1.1);
  }

  // Pin marker
  const [bx0, by0, bx1, by1] = node.bbox;
  const [cx, cy] = node.center;
  if (strong) {
    // Strong state: large halo + dot on top of the booth
    const halo = el("circle", {
      cx, cy, r: 16, fill: style.halo, "pointer-events": "none", class: "pin-halo",
    }, overlayGroup);
    const dot = el("circle", {
      cx, cy, r: 7, fill: style.fill, stroke: "#FFFFFF", "stroke-width": 2,
      "pointer-events": "none", class: "pin-dot",
    }, overlayGroup);
    data.shapes.push(halo, dot);
  } else {
    // Weak state: small dot in the top-right corner of the booth
    const dx = Math.min(4, (bx1 - bx0) / 6);
    const dy = Math.min(4, (by1 - by0) / 6);
    const dot = el("circle", {
      cx: bx1 - dx, cy: by0 + dy, r: 2.6,
      fill: style.fill, stroke: "#FFFFFF", "stroke-width": 0.8,
      "pointer-events": "none", class: "pin-dot-corner",
    }, overlayGroup);
    data.shapes.push(dot);
  }

  // Pulse for focus/you-are-here — fires once
  if (s.pulseRequested && (s.focus || s.you)) {
    pulse(cx, cy, style.fill);
    s.pulseRequested = false;
  }
}

function pulse(cx, cy, fill) {
  const pulseEl = el("circle", {
    cx, cy, r: 6,
    fill: "none", stroke: fill, "stroke-width": 2.5,
    "pointer-events": "none", opacity: 0.85,
    class: "pin-pulse",
  }, overlayGroup);
  pulseEl.animate(
    [{ r: 8, opacity: 0.85 }, { r: 38, opacity: 0 }],
    { duration: 1300, easing: "cubic-bezier(.2,.8,.2,1)", fill: "forwards" }
  );
  setTimeout(() => pulseEl.remove(), 1400);
}

function lighten(hex, amt) {
  // Mix hex with white by amt (0..1)
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const lr = Math.round(r + (255 - r) * amt);
  const lg = Math.round(g + (255 - g) * amt);
  const lb = Math.round(b + (255 - b) * amt);
  return `rgb(${lr},${lg},${lb})`;
}


/* ────── External API (called by app.js) ────────────────────────── */

export function setYouAreHere(boothNumber) {
  for (const bn of Object.keys(pinNodes)) {
    if (pinNodes[bn].state.you) setPinState(bn, { you: false });
  }
  setPinState(boothNumber, { you: true, pulseRequested: true });
  zoomToBooth(boothNumber);
}

export function applyHighlights(booths, from = null) {
  // clear previous focus
  for (const bn of Object.keys(pinNodes)) {
    if (pinNodes[bn].state.focus) setPinState(bn, { focus: false });
  }
  for (const b of (booths || [])) {
    setPinState(b, { focus: true, pulseRequested: true });
  }
  drawWalkingLine(from);
  // Center map on the highlights
  const valid = booths.map(b => boothNodes[b]).filter(Boolean);
  if (valid.length === 1) zoomToBooth(booths[0]);
}

function clearFocus() {
  for (const bn of Object.keys(pinNodes)) {
    setPinState(bn, { focus: false });
  }
  const line = overlayGroup?.querySelector(".walk-line");
  if (line) line.remove();
}

function drawWalkingLine(from) {
  const prev = overlayGroup?.querySelector(".walk-line");
  if (prev) prev.remove();
  let origin = from;
  if (!origin) {
    for (const bn of Object.keys(pinNodes)) if (pinNodes[bn].state.you) origin = bn;
  }
  if (!origin) return;
  let target = null;
  for (const bn of Object.keys(pinNodes)) if (pinNodes[bn].state.focus) { target = bn; break; }
  if (!target || target === origin) return;
  const a = boothNodes[origin]; const z = boothNodes[target];
  if (!a || !z) return;
  el("line", {
    x1: a.center[0], y1: a.center[1],
    x2: z.center[0], y2: z.center[1],
    stroke: "#FB7185", "stroke-width": 3,
    "stroke-dasharray": "10 6",
    "stroke-linecap": "round",
    fill: "none",
    class: "walk-line",
  }, overlayGroup);
}

function zoomToBooth(boothNumber) {
  const node = boothNodes[boothNumber];
  if (!node) return;
  const [bx, by] = node.center;
  // After `translate(tx, ty) scale(s)`, a viewport-space point (px, py)
  // lands at (s*px + tx, s*py + ty) in viewBox space. To put booth at the
  // viewBox center: tx = vbCenterX - s*bx, ty = vbCenterY - s*by.
  const s = 2.5;
  const vbX = viewBox[0], vbY = viewBox[1];
  const vbW = viewBox[2], vbH = viewBox[3];
  viewState.scale = s;
  viewState.tx = (vbX + vbW / 2) - s * bx;
  viewState.ty = (vbY + vbH / 2) - s * by;
  setTransform();
}


/* ────── Booth detail panel ─────────────────────────────────────── */

function showDetail(boothNumber) {
  const ex = exhibitorByBooth[boothNumber];
  const node = boothNodes[boothNumber];
  if (!node) return;
  const el = document.getElementById("map-detail");
  el.hidden = false;
  const ann = state.annotations[ex?.id] || {};
  const flagIcons = (ann.flags || []).map(f => f === "free_drinks" ? "☕" : "🎁").join(" ");
  const rating = ann.rating_mean ? `★ ${ann.rating_mean} (${ann.rating_count})` : "";
  el.innerHTML = `
    <div class="detail-head">
      <div>
        <h3>${ex ? escape(ex.company) : "Open booth"}</h3>
        <div class="sub">Booth ${boothNumber}${ex && ex.hall_zone ? " · " + escape(ex.hall_zone) : ""}</div>
      </div>
      <button class="x" aria-label="Close">✕</button>
    </div>
    <div class="desc">${ex ? escape(ex.description || "No description on file.") : "This booth is unstaffed in the current schedule."}</div>
    ${ex && ex.tags && ex.tags.length ? `<div class="tags">${ex.tags.slice(0,8).map(t => `<span class="tag">${escape(t)}</span>`).join("")}</div>` : ""}
    <div class="ann-row">
      ${flagIcons ? `<span class="badges">${flagIcons}</span>` : ""}
      ${rating ? `<span class="rating">${rating}</span>` : ""}
    </div>
    ${ex ? `<div class="actions">
      <button class="ann" data-ann="here">📍 I'm here</button>
      <button class="ann" data-ann="free_drinks">☕ Free drinks</button>
      <button class="ann" data-ann="good_swag">🎁 Good swag</button>
    </div>` : ""}
  `;
  el.querySelector("button.x")?.addEventListener("click", () => { el.hidden = true; });
  el.querySelectorAll("button.ann").forEach(btn => {
    btn.addEventListener("click", async () => {
      const k = btn.dataset.ann;
      if (k === "here") {
        await fetch(state.apiBase + "/api/tool/set_user_location", {
          method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ user_id: state.userId, reference: boothNumber }),
        }).then(r => r.json());
        setYouAreHere(boothNumber);
        toast(`You're at booth ${boothNumber}`);
        return;
      }
      await fetch(state.apiBase + "/api/tool/submit_annotation", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ user_id: state.userId, entity_id: ex.id, ann_type: k, payload: {} }),
      }).then(r => r.json());
      const summary = await fetch(state.apiBase + "/api/annotations/summary").then(r => r.json());
      state.annotations = summary;
      toast("Thanks — noted");
      showDetail(boothNumber);
    });
  });
}

function escape(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
  }[c]));
}
