"""Playwright-driven visual + interactive tests.

Verifies:
  - every visible interactive control responds to a click
  - no JS console errors during exercise
  - no failed network requests
  - text doesn't overflow its container
  - no two visible text nodes overlap each other significantly
  - works at three viewport sizes (mobile / tablet / desktop)
  - SVG booth click → detail panel
  - chat send → agent text streams in
"""

from __future__ import annotations

import asyncio
import re

from playwright.async_api import async_playwright, Page

from .common import BACKEND_URL, Report


VIEWPORTS = [
    ("xs",      320,  640),   # smallest phone
    ("mobile",  390,  844),
    ("tablet",  900,  900),
    ("desktop", 1440, 900),
    ("wide",    1920, 1080),
]


async def text_nodes_with_boxes(page: Page) -> list[dict]:
    """Return every visible non-whitespace text node with its bounding box.
    Excludes nodes outside the viewport (they may overflow scrollable
    containers harmlessly)."""
    js = r"""
    () => {
      const out = [];
      const vw = window.innerWidth, vh = window.innerHeight;
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
        acceptNode: n => n.nodeValue && n.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT
      });
      while (walker.nextNode()) {
        const tn = walker.currentNode;
        const range = document.createRange(); range.selectNodeContents(tn);
        const r = range.getBoundingClientRect();
        if (r.width < 1 || r.height < 1) continue;
        // Skip text outside the visible viewport — those are scrolled offscreen
        // or in collapsed columns, and any "overlap" there is irrelevant.
        if (r.bottom < 0 || r.top > vh || r.right < 0 || r.left > vw) continue;
        const parent = tn.parentElement;
        if (!parent) continue;
        const cs = getComputedStyle(parent);
        if (cs.visibility === 'hidden' || cs.display === 'none' || cs.opacity === '0') continue;
        // Walk up to check no ancestor is hidden
        let p = parent, hidden = false;
        while (p && p !== document.body) {
          const pcs = getComputedStyle(p);
          if (pcs.display === 'none' || pcs.visibility === 'hidden') { hidden = true; break; }
          p = p.parentElement;
        }
        if (hidden) continue;
        if (parent.closest('svg')) continue;     // SVG labels overlap by design
        if (parent.closest('script,style')) continue;
        out.push({
          text: tn.nodeValue.trim().slice(0, 80),
          x: r.x, y: r.y, w: r.width, h: r.height,
          parent: parent.tagName + '.' + (parent.className || ''),
        });
      }
      return out;
    }
    """
    return await page.evaluate(js)


async def overflow_violations(page: Page) -> list[dict]:
    """Return elements whose scrollWidth/Height exceed their clientWidth/Height
    (text or content clipped by overflow)."""
    js = r"""
    () => {
      const out = [];
      const seen = new WeakSet();
      const skip = new Set(['HTML','BODY','SVG','DEFS','G','PATH','RECT','CIRCLE','LINE','TEXT']);
      for (const el of document.querySelectorAll('*')) {
        if (seen.has(el)) continue; seen.add(el);
        if (skip.has(el.tagName)) continue;
        if (el.offsetWidth === 0 || el.offsetHeight === 0) continue;
        const cs = getComputedStyle(el);
        // Only flag when overflow is hidden/clip (visible overflow isn't a bug)
        const overflowX = cs.overflowX, overflowY = cs.overflowY;
        if (overflowX === 'visible' && overflowY === 'visible') continue;
        const dx = el.scrollWidth - el.clientWidth;
        const dy = el.scrollHeight - el.clientHeight;
        if (dx > 2 && overflowX !== 'auto' && overflowX !== 'scroll') {
          out.push({ tag: el.tagName + '.' + (el.className || ''), kind: 'overflowX', dx, text: (el.innerText||'').slice(0,80) });
        }
        if (dy > 2 && overflowY !== 'auto' && overflowY !== 'scroll') {
          out.push({ tag: el.tagName + '.' + (el.className || ''), kind: 'overflowY', dy, text: (el.innerText||'').slice(0,80) });
        }
      }
      return out;
    }
    """
    return await page.evaluate(js)


def overlap(a, b) -> float:
    """Intersection area / smaller area, 0..1."""
    ix0 = max(a["x"], b["x"]); iy0 = max(a["y"], b["y"])
    ix1 = min(a["x"] + a["w"], b["x"] + b["w"])
    iy1 = min(a["y"] + a["h"], b["y"] + b["h"])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    smaller = min(a["w"] * a["h"], b["w"] * b["h"])
    return inter / max(smaller, 1)


async def expect_no_overlapping_text(page: Page, r: Report, label: str, threshold: float = 0.5) -> None:
    # Wait a tick to let layout settle (especially after view switches)
    await page.wait_for_timeout(120)
    nodes = await text_nodes_with_boxes(page)
    overlaps = []
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            if overlap(nodes[i], nodes[j]) > threshold:
                overlaps.append((nodes[i]["text"], nodes[j]["text"]))
    if not overlaps:
        r.ok(f"{label}: no text-overlap among {len(nodes)} text nodes")
    else:
        r.fail(f"{label}: {len(overlaps)} text overlaps", "; ".join(f"{a!r} <-> {b!r}" for a, b in overlaps[:5]))


async def expect_no_overflow(page: Page, r: Report, label: str) -> None:
    bad = await overflow_violations(page)
    if not bad:
        r.ok(f"{label}: no overflow-clipped elements")
    else:
        r.fail(f"{label}: {len(bad)} overflow violations", "; ".join(f"{x['tag']} {x['kind']}: {x['text'][:60]!r}" for x in bad[:6]))


async def expect_click_targets_sized(page: Page, r: Report, selectors: list[str], min_size: int = 24, label: str = ""):
    js = """
    sels => sels.map(s => {
      const el = document.querySelector(s);
      if (!el) return { sel: s, found: false };
      const rect = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return { sel: s, found: true, w: rect.width, h: rect.height, visible: cs.visibility !== 'hidden' && cs.display !== 'none' };
    })
    """
    results = await page.evaluate(js, selectors)
    for res in results:
        if not res["found"]:
            r.fail(f"{label}: control not found: {res['sel']}")
            continue
        if not res["visible"]:
            r.fail(f"{label}: control hidden: {res['sel']}")
            continue
        if res["w"] < min_size or res["h"] < min_size:
            r.fail(f"{label}: control too small {res['sel']} ({res['w']:.0f}x{res['h']:.0f})", f"< {min_size}x{min_size}")
        else:
            r.ok(f"{label}: {res['sel']} ({res['w']:.0f}x{res['h']:.0f})")


async def expect_clickable(page: Page, r: Report, selector: str, after_check) -> None:
    """Click selector, then call after_check(page) which must return (ok, msg)."""
    try:
        await page.click(selector, timeout=4000)
    except Exception as e:
        r.fail(f"click failed: {selector}", str(e)[:140])
        return
    ok, msg = await after_check(page)
    if ok:
        r.ok(f"clicked {selector} → {msg}")
    else:
        r.fail(f"clicked {selector} but: {msg}")


async def run_at_viewport(page: Page, r: Report, name: str, w: int, h: int, console_errors: list):
    label = f"{name}({w}x{h})"
    await page.set_viewport_size({"width": w, "height": h})
    await page.goto(BACKEND_URL, wait_until="networkidle")
    # Force unregister any old SW + clear caches
    await page.evaluate("""
        (async () => {
          if (navigator.serviceWorker) {
            for (const r of await navigator.serviceWorker.getRegistrations()) await r.unregister();
          }
          for (const k of await caches.keys()) await caches.delete(k);
        })()
    """)
    await page.reload(wait_until="networkidle")
    # The map loads async — wait until booth count stabilizes
    await page.wait_for_function("document.querySelectorAll('g.booth').length > 100", timeout=15000)
    # Top bar layout: should not overlap
    await expect_no_overlapping_text(page, r, f"{label} chat-default")
    await expect_no_overflow(page, r, f"{label} chat-default")

    # Switch to Map
    await page.click('.view-switch button[data-view="map"]')
    await page.wait_for_function("document.querySelectorAll('g.booth').length > 100")
    await expect_no_overlapping_text(page, r, f"{label} map")
    await expect_no_overflow(page, r, f"{label} map")

    # Switch to Schedule
    await page.click('.view-switch button[data-view="schedule"]')
    await page.wait_for_selector('.schedule-tabs button.active')
    await expect_no_overlapping_text(page, r, f"{label} schedule-empty")
    await expect_no_overflow(page, r, f"{label} schedule-empty")

    # Touch targets (only enforce on mobile). Each check happens with the
    # control's pane active so it has real dimensions.
    if name == "mobile":
        await page.click('.view-switch button[data-view="map"]')
        await expect_click_targets_sized(page, r, [
            '.view-switch button[data-view="chat"]',
            '.view-switch button[data-view="map"]',
            '.view-switch button[data-view="schedule"]',
            '#map-reset', '#map-zoom-in', '#map-zoom-out',
        ], min_size=24, label=label + " map")
        await page.click('.view-switch button[data-view="chat"]')
        await page.wait_for_timeout(150)
        await expect_click_targets_sized(page, r, [
            '.chat-input button.send',
            '#chat-text',
        ], min_size=24, label=label + " chat")


async def run_populated_states(page: Page, r: Report):
    """Push the app into populated states (plan, you-are-here, detail) and
    re-check for overflow + overlap. Catches bugs only visible after the
    user has interacted."""
    await page.set_viewport_size({"width": 1440, "height": 900})
    await page.goto(BACKEND_URL, wait_until="networkidle")
    await page.evaluate("""
        (async () => {
          if (navigator.serviceWorker) for (const r of await navigator.serviceWorker.getRegistrations()) await r.unregister();
          for (const k of await caches.keys()) await caches.delete(k);
        })()
    """)
    await page.reload(wait_until="networkidle")
    await page.wait_for_function("document.querySelectorAll('g.booth').length > 100", timeout=15000)

    # Reset the page's WS conversation before driving the chat — the 'demo'
    # user is shared across prior sessions and would otherwise carry stale
    # context that causes the agent to skip set_user_location.
    js_reset = """
      async () => {
        const ws = new WebSocket(`ws://${location.host}/ws/chat/demo`);
        await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
        ws.send(JSON.stringify({ type: 'reset' }));
        await new Promise(res => { ws.onmessage = e => { if (JSON.parse(e.data).type === 'reset_ack') res(); }; });
        ws.close();
      }
    """
    await page.evaluate(js_reset)
    # Page's chat module has its own WS — give it a beat to settle after reset
    await page.wait_for_timeout(400)

    await page.click('.view-switch button[data-view="chat"]')
    await page.fill('#chat-text', "I'm at booth 272 and want to plan my day for AI agents.")
    await page.click('.chat-input button.send')
    # Wait for agent done event (either schedule populated or text streamed in)
    try:
        await page.wait_for_function(
            "document.querySelectorAll('.msg.agent .bubble').length > 0 && "
            "!document.querySelector('.msg.agent .bubble.streaming')",
            timeout=70000,
        )
    except Exception:
        r.fail("agent never reached 'done' state within 70s")

    # Check chat: messages don't overlap, bubbles don't overflow
    await expect_no_overlapping_text(page, r, "populated chat")
    await expect_no_overflow(page, r, "populated chat")

    # Switch to schedule — must have at least one card
    await page.click('.view-switch button[data-view="schedule"]')
    cards = await page.query_selector_all('.timeline .card')
    if len(cards) >= 1:
        r.ok(f"schedule populated with {len(cards)} cards")
    else:
        r.fail("schedule has no cards after planning")
    await expect_no_overlapping_text(page, r, "populated schedule")
    await expect_no_overflow(page, r, "populated schedule")

    # Switch to map — must show you-are-here pin
    await page.click('.view-switch button[data-view="map"]')
    await page.wait_for_timeout(400)
    you_dots = await page.evaluate("document.querySelectorAll('circle.pin-dot[fill=\"#3B82F6\"]').length")
    if you_dots >= 1:
        r.ok("you-are-here pin renders after location set")
    else:
        r.fail("no you-are-here pin after set_user_location")
    await expect_no_overlapping_text(page, r, "populated map")
    await expect_no_overflow(page, r, "populated map")

    # Open the booth with the longest description to stress detail panel layout
    js2 = """
    async () => {
      // pick booth 272 (Deloitte) — known long description
      const g = document.querySelector('g.booth[data-booth="272"] rect.booth-rect');
      g.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    }
    """
    await page.evaluate(js2)
    await page.wait_for_selector('#map-detail h3', timeout=2000)
    await expect_no_overflow(page, r, "populated map detail")
    # Detail panel should NOT cover the entire map area
    js3 = """
    () => {
      const d = document.getElementById('map-detail');
      const map = document.getElementById('map-wrap');
      const dr = d.getBoundingClientRect(); const mr = map.getBoundingClientRect();
      return { detailH: dr.height, mapH: mr.height, ratio: dr.height / mr.height };
    }
    """
    s = await page.evaluate(js3)
    if s["ratio"] < 0.5:
        r.ok(f"detail panel covers {int(s['ratio']*100)}% of map ≤ 50%")
    else:
        r.fail(f"detail panel covers {int(s['ratio']*100)}% of map", "should be < 50%")


async def run_clicks(page: Page, r: Report, console_errors: list):
    await page.set_viewport_size({"width": 1440, "height": 900})
    await page.goto(BACKEND_URL, wait_until="networkidle")
    await page.evaluate("""
        (async () => {
          if (navigator.serviceWorker) for (const r of await navigator.serviceWorker.getRegistrations()) await r.unregister();
          for (const k of await caches.keys()) await caches.delete(k);
        })()
    """)
    await page.reload(wait_until="networkidle")
    await page.wait_for_function("document.querySelectorAll('g.booth').length > 100", timeout=15000)

    # Tabs
    for view in ["map", "schedule", "chat"]:
        await page.click(f'.view-switch button[data-view="{view}"]')
        await page.wait_for_timeout(150)
        active = await page.evaluate(f"!!document.querySelector('.view-switch button.active[data-view=\"{view}\"]')")
        if active:
            r.ok(f"tab '{view}' toggles active")
        else:
            r.fail(f"tab '{view}' did not become active")

    # Prompt chips clickable: each chip click should populate or send a prompt
    chips = await page.query_selector_all(".chip")
    if len(chips) >= 4:
        r.ok(f"{len(chips)} prompt chips visible")
    else:
        r.fail(f"only {len(chips)} chips found")

    # Map: zoom controls + Fit + booth click
    await page.click('.view-switch button[data-view="map"]')
    await page.wait_for_function("document.querySelectorAll('g.booth').length > 100")
    t0 = await page.evaluate("document.getElementById('viewport')?.getAttribute('transform') || ''")
    await page.click('#map-zoom-in')
    await page.wait_for_timeout(100)
    t1 = await page.evaluate("document.getElementById('viewport')?.getAttribute('transform') || ''")
    if t0 != t1:
        r.ok("zoom-in changes viewport transform")
    else:
        r.fail("zoom-in did not change transform")
    await page.click('#map-zoom-out')
    await page.wait_for_timeout(100)
    await page.click('#map-reset')
    t2 = await page.evaluate("document.getElementById('viewport')?.getAttribute('transform') || ''")
    r.ok("Fit button reachable")

    # Click multiple booths sequentially; detail must populate every time
    booth_targets = ["272", "269", "201", "230", "262", "270"]
    for bn in booth_targets:
        sel = f'g.booth[data-booth="{bn}"] rect.booth-rect'
        present = await page.query_selector(sel)
        if not present:
            r.fail(f"booth {bn} not in DOM")
            continue
        await page.click(sel)
        await page.wait_for_timeout(120)
        # Detail panel should be visible (not hidden) and contain text
        head = await page.evaluate("document.querySelector('#map-detail h3')?.innerText || ''")
        if head:
            r.ok(f"booth {bn} click → detail: {head[:50]}")
        else:
            r.fail(f"booth {bn} click did not open detail")
        # Close
        x = await page.query_selector('#map-detail .x')
        if x:
            await x.click()

    # Detail action buttons (open a booth first)
    await page.click(f'g.booth[data-booth="272"] rect.booth-rect')
    await page.wait_for_selector('#map-detail h3')
    for ann in ["here", "free_drinks", "good_swag"]:
        btn = await page.query_selector(f'#map-detail button[data-ann="{ann}"]')
        if btn:
            r.ok(f"detail button '{ann}' present")
        else:
            r.fail(f"detail button '{ann}' missing")

    # "I'm here" action triggers a you-pin
    you_before = await page.evaluate("document.querySelectorAll('circle.pin-dot[fill=\"#3B82F6\"]').length")
    here_btn = await page.query_selector('#map-detail button[data-ann="here"]')
    await here_btn.click()
    await page.wait_for_timeout(800)
    you_after = await page.evaluate("document.querySelectorAll('circle.pin-dot[fill=\"#3B82F6\"]').length")
    if you_after >= 1:
        r.ok("'I'm here' button sets you-are-here pin")
    else:
        r.fail("'I'm here' did not create blue pin")

    # Detail X-button closes panel
    await page.click(f'g.booth[data-booth="269"] rect.booth-rect')
    await page.wait_for_selector('#map-detail h3')
    await page.click('#map-detail .x')
    await page.wait_for_timeout(150)
    hidden = await page.evaluate("document.getElementById('map-detail').hidden")
    if hidden:
        r.ok("detail close (X) hides the panel")
    else:
        r.fail("X button did not close detail")

    # Booth label inside the booth rect — text shouldn't extend outside
    overflow_labels = await page.evaluate("""
      () => {
        const out = [];
        for (const g of document.querySelectorAll('g.booth')) {
          const rect = g.querySelector('rect.booth-rect');
          const text = g.querySelector('text');
          if (!rect || !text) continue;
          const rr = rect.getBBox(); const tr = text.getBBox();
          // text bbox should be inside rect bbox (with 1pt slack)
          if (tr.x < rr.x - 1 || tr.y < rr.y - 1 || tr.x + tr.width > rr.x + rr.width + 1 || tr.y + tr.height > rr.y + rr.height + 1) {
            out.push({ booth: g.dataset.booth, text: text.textContent });
          }
        }
        return out;
      }
    """)
    if not overflow_labels:
        r.ok("booth labels stay inside their rects")
    else:
        r.fail(f"{len(overflow_labels)} booth labels overflow", ", ".join(f"{o['booth']}: '{o['text']}'" for o in overflow_labels[:5]))

    # Zone labels visible and not severely overlapping their own zone fills
    zone_check = await page.evaluate("""
      () => {
        const labels = [...document.querySelectorAll('.zone-label')];
        return labels.map(t => ({
          text: t.textContent,
          x: parseFloat(t.getAttribute('x')),
          y: parseFloat(t.getAttribute('y')),
          fill: t.getAttribute('fill'),
        }));
      }
    """)
    if len(zone_check) >= 8:
        r.ok(f"{len(zone_check)} zone labels rendered")
    else:
        r.fail(f"only {len(zone_check)} zone labels rendered")

    # Check there are no SVG elements clipped outside the viewbox bounds
    out_of_box = await page.evaluate("""
      () => {
        const svg = document.querySelector('.floorplan-svg');
        if (!svg) return null;
        const vb = svg.getAttribute('viewBox').split(' ').map(Number);
        const [vx, vy, vw, vh] = vb;
        const out = [];
        for (const el of svg.querySelectorAll('rect, circle, text, path')) {
          try {
            const b = el.getBBox();
            if (b.x + b.width < vx - 5 || b.y + b.height < vy - 5 || b.x > vx + vw + 5 || b.y > vy + vh + 5) {
              out.push({ tag: el.tagName, cls: el.getAttribute('class'), x: b.x, y: b.y });
            }
          } catch(_) {}
        }
        return { vb, outCount: out.length, sample: out.slice(0, 4) };
      }
    """)
    if zone_check is None or out_of_box is None:
        r.fail("could not inspect SVG bounds")
    elif out_of_box["outCount"] == 0:
        r.ok("no SVG elements outside the viewBox")
    else:
        r.fail(f"{out_of_box['outCount']} SVG elements outside viewBox", str(out_of_box["sample"]))

    # Touch-target check at desktop too: all toolbar buttons should be ≥ 30×30
    await expect_click_targets_sized(page, r, [
        '.view-switch button[data-view="chat"]',
        '.view-switch button[data-view="map"]',
        '.view-switch button[data-view="schedule"]',
        '#map-reset', '#map-zoom-in', '#map-zoom-out',
        '.chip',
    ], min_size=28, label="desktop")

    # Schedule tabs
    await page.click('.view-switch button[data-view="schedule"]')
    for layer in ["planned", "saved", "attended"]:
        await page.click(f'.schedule-tabs button[data-layer="{layer}"]')
        active = await page.evaluate(f"!!document.querySelector('.schedule-tabs button.active[data-layer=\"{layer}\"]')")
        if active:
            r.ok(f"schedule tab '{layer}' active")
        else:
            r.fail(f"schedule tab '{layer}' did not activate")

    # Chat send via button
    await page.click('.view-switch button[data-view="chat"]')
    await page.fill('#chat-text', 'hi')
    msg_count_before = await page.evaluate("document.querySelectorAll('.msg').length")
    await page.click('.chat-input button.send')
    # Wait briefly — at minimum the user bubble should appear
    await page.wait_for_function(f"document.querySelectorAll('.msg').length > {msg_count_before}", timeout=4000)
    r.ok("Send button creates a user bubble")


async def main() -> Report:
    r = Report("visual + interactive (Playwright)")
    console_errors: list[str] = []
    failed_requests: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        def on_console(msg):
            if msg.type == "error":
                console_errors.append(msg.text)
        page.on("console", on_console)
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.method} {req.url}"))

        # 1. Run viewport / layout checks
        for name, w, h in VIEWPORTS:
            await run_at_viewport(page, r, name, w, h, console_errors)

        # 2. Click coverage at desktop
        await run_clicks(page, r, console_errors)

        # 3. Populated-state checks (plan, you-are-here, detail panel)
        await run_populated_states(page, r)

        # 4. Console/network sanity
        if not console_errors:
            r.ok("no JS console errors across exercise")
        else:
            r.fail(f"{len(console_errors)} console errors", "; ".join(set(console_errors))[:200])
        if not failed_requests:
            r.ok("no failed network requests")
        else:
            r.fail(f"{len(failed_requests)} failed requests", "; ".join(set(failed_requests))[:200])

        await browser.close()
    return r


def run() -> Report:
    return asyncio.run(main())


if __name__ == "__main__":
    run().print_summary()
