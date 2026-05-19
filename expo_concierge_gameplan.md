# Expo Concierge — Game Plan

**Hackathon:** TechEx "Transforming Enterprise Through AI" (lablab.ai × Google × Veea)
**Target track:** Track 2 — AI Agents with Google AI Studio
**Demo event:** TechEx North America 2026, San Jose McEnery Convention Center, May 18–19
**Submission:** May 19, on the AI Developer Track stage
**Build mode:** Solo, agent-coded (Claude Code / Hermes), text-only chat, web + mobile PWA
**Status:** Internal build doc. Some sections may be lifted into the public README.

---

## 0. The one-paragraph pitch

Every event app on the market — Grip, Brella, Swapcard, Bizzabo, and TechEx's own built-in Networking Tool — does the same thing: registration-gated, tag-based recommendations served as static lists. Expo Concierge is a **conversational agent** that an attendee can bring to *any* conference and use in under sixty seconds. Sign in with LinkedIn, say "I'm here for LoRa-based IoT and edge inference," and a real day-by-day plan appears alongside a live floor map with the right booths pinned. Ask "I just talked to Semtech, who's similar?" and the agent searches the exhibitor corpus, surfaces matches, and shows who you know at each. Ask "I'm at Semtech, what's near me with 20 minutes left?" and the agent reasons over location, time budget, and your interest profile to give you the best next move. The map, schedule, and chat are not three separate views — they are one shared state that the agent actively operates on your behalf.

---

## 1. Data ingestion — the substrate everything else stands on

### 1.1 Sources of truth

The TechEx public web presence is the only data source. Three logical entity types, scattered across multiple subsites:

- **Sessions** (talks, panels, keynotes) — live across seven co-located event microsites (`ai-expo.net`, `iottechexpo.com`, `cybersecurityexpo.com`, `digitaltransformation-week.com`, `datacentre-expo.com`, `iotaexpo.net`, `edgecomputing-expo.com`). Each has its own agenda page with inconsistent HTML schemas.
- **Speakers** (~250) — listed on each microsite with name, title, company, headshot, bio, session links.
- **Exhibitors** (~250) — listed on `ai-expo.net/northamerica/exhibitors/` with company name, booth number, description.
- **Floorplan** — a single downloadable image at `techexevent.com/floorplan-na/` showing numbered booth rectangles across hall zones.

There is no public structured API. Everything is scraped.

### 1.2 Pipeline shape

A one-shot ingestion job, runnable on demand and on a cron during the event. Three stages:

**Stage A — Scrape.** A per-site Playwright adapter for each of the seven microsites plus the central exhibitor page. Each adapter emits a normalized JSON record. Adapters are not hand-written from scratch — Gemini 2.5 Pro is given a sample page and prompted to produce a parser, which is then committed. When a site's HTML changes, regenerate the parser. Total raw record count: roughly 250 sessions, 250 speakers, 250 exhibitors plus the floorplan image.

**Stage B — Floorplan extraction.** Gemini 2.5 Pro is called *once* with the floorplan image and a structured-output prompt: return every numbered booth as `{booth_number, bbox: [x1, y1, x2, y2], center: [x, y], hall_zone}`. This is the only place multimodal Gemini is used at ingest time. Output is a JSON file committed to the repo, then human-spot-checked for the ~30 highest-priority booths. Re-runs are cheap if the layout changes, but the goal is "run once, fix the obvious errors, ship."

**Stage C — Join, embed, store.** Exhibitor records join to floorplan records on booth number. Sessions join to speakers on speaker name. Every record (sessions, speakers, exhibitors) is embedded with Gemini `text-embedding-004`, with the embedding text being a structured concatenation: `[entity_type] | [name] | [tags] | [description/abstract] | [related entities]`. Total: roughly 750 vectors at 768 dimensions — trivial to hold in pgvector or even an in-memory FAISS index. The same normalized records are also stored as plain JSON for the agent's structured retrieval tools.

### 1.3 Schema (entity-level, not field-level)

Four top-level tables. Each entity has a stable string ID, an embedding vector, a "freshness" timestamp, and a flat metadata blob. Relationships are by ID, not foreign-key constraints — keep it simple.

- `sessions` — title, abstract, track, day, start, end, room, speaker_ids, tags
- `speakers` — name, title, company, bio, session_ids, headshot_url
- `exhibitors` — company, booth_number, description, tags, hall_zone, website
- `booths` — booth_number, bbox, center, hall_zone, exhibitor_id (nullable — empty booths exist)

A fifth, runtime-only table holds **community annotations** (see §2.3) and is keyed by `entity_id`.

### 1.4 Freshness strategy

Conference data is mostly static once the doors open. Speakers cancel, rooms get changed, but at low rate. Re-scrape on a 60-minute cron during the event. When a record changes, bump its freshness timestamp; the agent surfaces this in chat ("FYI, the LoRa panel moved rooms an hour ago"). For demo purposes, freeze a known-good snapshot at 7 AM May 19 and use it as the canonical ground truth.

### 1.5 Why this design

The dominant alternative — having the agent re-read raw HTML or the floorplan image at query time — is appealing for "agentic" framing but wrong on every other axis: slower, more expensive, less reliable, harder to debug, and impossible to test deterministically. The static-ingestion-with-live-overlay approach gives the agent fast structured tools, keeps the multimodal call to one well-bounded place, and lets the whole pipeline be re-run cleanly when the source data changes.

---

## 2. The map — static base, live overlay, agent-operable

### 2.1 The core mental model

The floorplan image is the **base layer**. It never changes during a session. On top of it sits a transparent SVG overlay rendered from the booth coordinate table. Every booth is a pin (a small circle, absolutely positioned at the booth center coordinates). The overlay is what the agent operates. The base image is just background.

This is the architecture that makes "things light up, change color, pathing visible" feel real. The agent is not generating images — it is updating a small state object (which pins to highlight, in what color, with what label) and the overlay re-renders. Cheap, fast, and the agent can do it inside a tool call that returns in milliseconds.

### 2.2 Pin states and the highlight protocol

A pin is in exactly one visual state at a time. Priority order, highest to lowest:

1. **You-are-here** — large blue dot with halo. Set by the user via "I'm at [booth]" or by tapping a pin and selecting "I'm here." Sticky until replaced.
2. **In-plan** — outlined ring in the user's plan color. Sticky for the duration of the schedule entry.
3. **Agent-highlighted (current focus)** — vivid teal, pulse animation for 2 seconds, then static. Lifetime: until the next agent response that doesn't carry it forward, or until the user explicitly clears.
4. **Interest-match** — soft blue dot. Computed at ingest from the user's profile; refreshed when the profile changes.
5. **Visited** — filled circle with check, low opacity. Sticky.
6. **Default** — small grey dot.

Pulse-on-highlight is doing real work. In bright sunlight, color alone doesn't distinguish teal from blue from grey; motion does. The pulse fires exactly once per highlight event, then stops, so a long session doesn't become a strobe.

### 2.3 Community annotations — the lightweight extensibility hook

A small per-entity annotation surface that lives in a Postgres table and updates in near-real-time. Each annotation has a type and a payload:

- `free_drinks` — a flag, surfaced as a small icon on the pin (☕ or 🍷)
- `good_swag` — a flag, ditto
- `rating` — 1–5, aggregated as a small star count
- `comment` — short user-submitted text
- `presenter_contact` — when a user has talked to someone at the booth, mark it (and let the agent help draft a follow-up)

The MVP supports `free_drinks`, `good_swag`, and `comment`. Ratings and follow-up drafting are stretch. Annotations are visible to all users; submitting one requires being logged in. No moderation in v1 — for a hackathon this is fine; in production it would need to be tiered.

The reason this matters beyond "cute feature": it gives the agent something to *talk about* that no incumbent has access to. "There's free coffee at the Vantage booth and 3 people rated their demo 5 stars — worth the 6-minute walk."

### 2.4 The "what's near me right now" mechanic

The user does not have indoor GPS. We fake location through declared state. Three ways the user_location field gets set:

- **Explicit**: "I'm at booth B14." Agent calls `set_user_location(reference="B14")`.
- **Implicit, from talking**: "I just talked to Semtech." Agent resolves to Semtech's booth and calls `set_user_location(reference="B14")` — and **confirms in chat**: "Got it, you're at B14. What's next?"
- **Inferred from session attendance**: "I just left the LoRa panel." Agent sets location to that room's exit point.

Once `user_location` is set, the `query_nearby(radius_meters, filter)` tool can be called. The "20 minutes left, what should I see?" pattern is then: agent calls `query_nearby` with radius computed from walking-speed × time-budget, filters by interest match and not-yet-visited, returns ranked list, highlights pins on map.

The genuinely non-trivial part is that a single user message can contain both a state update and a query ("I'm at Semtech, what's near me?"). The agent must call `set_user_location` *first*, then `query_nearby` — in that order. This is handled by tool ordering in the system prompt and by making the tools idempotent so a misordered call is recoverable.

### 2.5 Pathing — what we will and won't do

We will not do shortest-path routing across the convention center. Indoor pathfinding requires a navmesh, which we do not have. What we *will* do is render a straight-line indicator from the user's declared location to a target pin, with an annotated "approx. X minutes" computed from Euclidean distance × an estimated walking speed (~1.2 m/s through crowded halls). This is honest, demoable, and ten times less work than real routing.

---

## 3. The schedule — Google Calendar feel, agent-operated

### 3.1 What it looks like

A vertical timeline view, scrollable, with **proportional time spacing**. Gaps between events look like gaps; back-to-back transitions look tight. Each scheduled item is a card with:

- Title, time, location (room or booth area)
- Track / interest match percentage (only shown if confidence is high)
- A speaker thumbnail if it's a session
- A small map-pin icon that, when tapped, switches to map view with that pin highlighted
- Color-coded by track or interest-match tier

Between cards, the agent inserts annotations:

- Walking time annotations ("8 min walk to Hall B")
- Suggested fillers ("You have 30 minutes — Semtech is 2 minutes away")
- Track changes ("Crossing into IoT Tech Expo zone")

The "Google Calendar feel" is the proportional spacing and the tactile, draggable card behavior, not pixel-perfect Google styling.

### 3.2 Card interactions

- **Tap** — opens the card detail (full abstract, speaker bio, who's attending if shared)
- **Long press** — drag to reorder, or drag to chat to ask about it
- **Swipe right** — quick-add to favorites / save for later
- **Swipe left** — quick-remove or open replace menu

The agent operates on cards just like the user can. When the user says "drop the 2pm, swap in something on edge AI," the agent calls `update_schedule(remove=[card_id], add_query="edge AI 2pm")`, the old card animates out, a new one animates in. The animation is the proof of work — it is what makes the user feel that the system did something, not just said it.

### 3.3 Plan state separation

Three layers of plan state, kept distinct:

- **Saved** — things the user has bookmarked but isn't committed to. Lives in a "Saved" tab.
- **Planned** — things the user has explicitly added to today's schedule. Lives in the timeline.
- **Attended** — things the user has actually been at, marked by either explicit "I went" or inferred from chat context. Stored permanently for end-of-day summary and Day 2 planning.

The agent reads all three layers when reasoning. The model behavior we want: the agent gently notices when *planned* doesn't match *attended* and adjusts. "You planned the 11am panel but I see you're still asking about the keynote — should I move the panel to your saved list and pick up the LoRa talk at 11:30 instead?"

### 3.4 Saved-for-later

A small pile of bookmarked entities that the agent can reason over. "You saved three things about post-quantum crypto yesterday — there's a panel at 4pm today, want me to add it?" The pile is browsable in its own view, but its real purpose is to give the agent retrievable user-declared interests beyond the initial profile.

### 3.5 End-of-day summary

Triggered both automatically (push at 6pm or on next session start) and on demand ("recap my day"). Includes:

- Sessions attended and saved highlights from chat
- Booths visited
- People you said you wanted to follow up with
- A drafted follow-up message for each person, with the right context pulled from chat
- One-tap "save this recap" that exports a markdown summary

For the hackathon demo, this is a strong closer — it makes the ROI legible to enterprise judges.

---

## 4. The agent — model, memory, tools, behavior

### 4.1 Two-model architecture

- **Gemini 2.5 Flash** — conversational front. Handles the chat turn, tool dispatch, follow-up questions, summaries. Fast, cheap, streams tokens.
- **Gemini 2.5 Pro** — planning tool. Called when the agent needs to construct or restructure a multi-hour itinerary with constraints (no time conflicts, walking time, meal slots, interest weighting). Slower, smarter, called rarely.

The split is implemented as a single internal tool called `build_or_revise_plan` that the Flash front calls when needed. Pro is invisible to the user; from the outside it looks like one agent.

We will benchmark this split against a Flash-only configuration during testing (§5). If Flash-only produces acceptable plans, we collapse to one model. If Pro produces dramatically better plans, we keep the split.

### 4.2 Grounding — search before guessing

The agent grounds in local data first, then web, then never just guesses about real entities. Concretely:

- **For any named entity** (a company, speaker, session title, booth number) the agent **must** call `search_entities` first. If the entity isn't in the corpus, the agent says so explicitly and offers to web-search.
- **For company-level questions** ("what does Acme do?"), the agent first checks the local exhibitor description, then falls back to web search if the description is thin, then falls back to its own knowledge only if both fail — and labels which it's doing.
- **Famous companies** (NVIDIA, Microsoft, Samsung) Gemini knows from training. **Startups and smaller exhibitors** it does not — for these, web search is mandatory before answering anything substantive.

The agent's responses include explicit provenance markers when uncertainty is meaningful: "(from their booth page)" vs "(from web search)" vs "(general knowledge)." For the enterprise judging audience, provenance is part of the product.

### 4.3 User profile — three layers, evolving but not stale

Three logical layers, all in one document but with different update rules:

**Stable profile** — from LinkedIn (role, company, career history) and the first conversation (declared interests). Doesn't decay. Editable by the user via a small pill-row near the top of chat: `LoRa IoT · edge compute · data center cooling · ✏️`.

**Session intent** — what the user said they're focused on *today*. Resets per session start. Heavily weighted in recommendations until contradicted.

**Behavioral signal** — every entity the user has asked about, added to plan, marked visited, or saved. Stored as a timestamped log. The agent reads this as a chronological record, not as a static tag set; recency matters and the agent reasons about it in context.

The profile document is shown to the model on every turn as part of system context, formatted as a structured block. The model is instructed to:

- Weight recent signals heavier than old ones
- Notice when stated intent and observed behavior diverge, and gently surface the difference
- Never silently override stable profile or session intent — always confirm changes with the user

### 4.4 Conversation memory across sessions

End of each session, the agent writes a structured summary to the user profile: visited entities, people met, key questions asked, follow-ups noted, plan items completed. On next session start, the user is greeted with awareness of this history: "Welcome back, Alex. Yesterday you hit five LoRa booths and saved Tom Park's contact at Semtech. Want to pick up where you left off, or is today different?"

Day 2 planning explicitly inherits Day 1 context unless the user starts fresh.

### 4.5 Tool surface

The agent has a small, tight set of tools. Internal naming is deliberate; user-facing labels are the friendly versions in §4.7.

- `search_entities(query, type, k)` — semantic search over sessions/speakers/exhibitors. Returns top-k with snippets.
- `get_entity(entity_id)` — fetch full record.
- `query_nearby(reference_point, radius, filter)` — spatial query over the booth grid.
- `set_user_location(reference)` — update declared user position.
- `build_or_revise_plan(goals, constraints, existing_plan)` — invokes Gemini 2.5 Pro for itinerary work.
- `update_schedule(add, remove, replace)` — direct edit on the user's planned schedule.
- `highlight_on_map(entity_ids, label?)` — agent operates the map overlay.
- `web_search(query)` — fallback for entities not in local corpus.
- `mark_visited(entity_id)` and `save_for_later(entity_id)` — annotate behavioral state.
- `submit_annotation(entity_id, type, payload)` — community annotations (free drinks, swag, ratings, comments).
- `summarize_day(scope)` — produce the end-of-day recap.

Tools are designed to be **idempotent** where possible — calling `set_user_location` twice with the same value is harmless. This matters because Flash will sometimes call tools redundantly, and the cost of guarding against it inside the tool is much lower than the cost of guarding in the prompt.

### 4.6 Token streaming and tool-call visibility

The agent streams prose tokens to the chat surface as they arrive. Tool calls are surfaced as friendly inline pills that resolve when the tool returns:

- "Updating your schedule..." → "✓ Schedule updated"
- "Searching 247 companies..." → "✓ Found 4 matches"
- "Showing on the map..." → "✓ Highlighted in teal"
- "Checking who you might know there..." → "✓ Found 2 second-degree connections"

What the user **does not** see: tool names, JSON arguments, raw model output, retry traces. Tool calls are a feature, not a debugging surface. The verbal labels are part of the product copy and worth iterating on.

### 4.7 Failure modes and graceful degradation

Each failure mode has a defined behavior:

- **Entity not found** — confirm spelling, offer the nearest fuzzy match, offer to web-search.
- **Location can't be resolved** — ask which hall, or offer a list of recently mentioned booths.
- **Plan with overlapping times** — the constraint post-processor catches it before showing the user; agent re-asks Pro for a substitute from the top-k candidates.
- **Web search fails or returns nothing** — say so plainly, do not fabricate.
- **User contradicts themselves** — gently surface: "Earlier you said LoRa, now you're asking about LLMs — want me to add LLM eval to your interests, or is this a one-off question?"
- **Rate limit on Gemini** — fall back to a smaller model for the current turn and tell the user the system is at capacity, retry in a moment.

Hackathon demos die at failure modes. Each of these has a known happy-path script and is exercised by the test bench in §5.

### 4.8 Discover flow specifics — "who do I know there?"

LinkedIn's official API does not expose connections. We support two paths:

- **CSV import** — user drag-drops their LinkedIn connections export (a CSV they can pull from `linkedin.com/mypreferences/d/download-my-data`). We parse it into a small graph keyed on company name. The agent uses this to answer "who do I know at Semtech?" with real names and the user's prior context.
- **Company-affinity fallback** — if the user hasn't imported the CSV, the agent uses career history overlap ("you and 2 Semtech engineers both worked at Cisco") and degrades the answer accordingly.

In the demo, we show the CSV path. In the README and pitch, we name the affinity fallback as a privacy-respecting option.

---

## 5. Testing, benchmarking, and `/goal iterate till done` — the hardest piece

The premise of solo + agent-coded means we cannot manually test every change. The test bench is therefore a first-class deliverable, not an afterthought.

### 5.1 What "tests" mean for an agent

Three categories, each different in kind:

**Deterministic unit tests** for the pipeline and tools. Standard. Pytest over the ingestion, the embeddings, the spatial queries, the schedule constraint solver, the user profile updates. Fast, run on every commit, must always be green. ~80% of total test count, ~10% of total interesting bug surface.

**Scripted scenario tests** for the agent. A fixed set of canonical user scenarios, each scripted as a multi-turn conversation. Each turn has expected behaviors expressed as **assertions over the agent's response and tool-call trace**, not over exact text. Example assertions:

- "The agent's response mentions Semtech"
- "Tool `search_entities` was called with `type='exhibitor'`"
- "Tool `set_user_location` was called before `query_nearby`"
- "No more than 1 web_search call in this turn"
- "Response length under 200 tokens"

These run against a real Gemini call (with a low-temperature setting and a seed where possible). They are not deterministic — they pass probabilistically. The bench runs each scenario N times and reports pass rate per assertion. Acceptance threshold: 95% pass rate over N=10 runs.

**LLM-as-judge evaluations** for response *quality*. For each canonical scenario, a rubric is defined ("did the agent ground in local data before guessing?", "did the agent surface uncertainty appropriately?", "was the day plan actually executable given walking times?"). A separate Gemini 2.5 Pro instance scores the response against the rubric. Used for things that can't be expressed as crisp assertions.

### 5.2 The canonical scenario set

A small, opinionated set of ~12 scenarios that cover the demo paths and the failure modes. Each scenario lives in its own YAML file with: initial user state, the script of user messages, per-turn assertions, and a quality rubric. Approximate list:

- Cold start: LinkedIn-only profile, "plan my day for LoRa IoT"
- Replan: existing schedule, "drop the 2pm, want something on edge AI"
- Discover: "I just talked to Semtech, who's similar?"
- Discover with connections: same, after CSV import
- Locate: "I'm at booth B14, what's nearby?"
- Locate with time budget: "I have 15 minutes before my next talk, what should I see?"
- Combined location update + query in one message
- Contradicting interests: morning LoRa, afternoon LLMs
- Entity not in corpus: "tell me about Foo Industries" (doesn't exist)
- Stale data: room change since last refresh
- Multi-day continuity: Day 1 → Day 2 reopen
- End-of-day recap

### 5.3 The `/goal` loop

The agent-coded build loop is: Claude Code reads the spec, writes code, runs the test bench, reads the results, iterates. For this to work, the test bench must produce **machine-readable structured output** that the coding agent can reason about. Specifically:

- Each test run emits a JSON report: per-scenario pass/fail, per-assertion pass/fail with the actual vs expected, LLM-judge scores per rubric, total cost in tokens, total wall-clock time.
- The summary at the top is a single block the coding agent reads first: "12 scenarios, 9 passing, 3 failing — scenario `discover_similar` failing on assertion 'no more than 1 web_search call'; scenario `replan` failing on assertion 'response includes new card'."
- Failure traces include the full conversation, the tool-call trace, and the model's own reasoning where available.

The acceptance criterion for `/goal iterate till done` is encoded as: all 12 scenarios pass at ≥95% rate, all LLM-judge rubrics score ≥4.0/5.0 mean, no scenario regresses below its prior best score. The coding agent runs the bench, reads the report, fixes the worst-failing scenario, re-runs. Cap iterations at 8 to prevent runaway.

### 5.4 Smoke + sanity layer

A separate, fast layer that runs in under 30 seconds and catches catastrophic regressions:

- Does the pipeline still ingest?
- Does the floorplan still parse to N booths (where N is the known count ± 5)?
- Does the agent respond to "hi" with a non-error?
- Does the map render with at least one pin?
- Does the schedule view render with at least one card?

This runs on every save. The scenario bench runs on demand and pre-submission.

### 5.5 Cost discipline

Each test run reports total Gemini token spend. There is a daily soft cap; exceeding it requires the coding agent to switch to Flash-only for cheap iteration and only re-enable Pro for the final acceptance run. This is real — token budgets matter and we will hit them.

### 5.6 What we are explicitly not testing

- End-to-end browser tests with real LinkedIn OAuth — too slow, too flaky, mock the auth.
- Real map image regression — visual diff testing is overkill for a hackathon; spot check.
- Multi-user concurrency — single user only.
- Production load — N/A.

---

## 6. Non-goals, risks, and the things we will explicitly cut

### 6.1 Non-goals (v1)

- Voice input/output. Text only. Listed as roadmap.
- Native mobile apps. PWA only.
- Multi-conference support. TechEx only, hardcoded data path.
- Organizer-side dashboards or admin tools.
- Real-time chat between attendees.
- Indoor turn-by-turn navigation.
- Multi-language support beyond English.
- Production-grade moderation of community annotations.

### 6.2 Known risks

- **Scraping fragility** — site HTML changes mid-build. Mitigated by Gemini-generated adapters that can be regenerated in minutes, and by freezing a snapshot for the demo.
- **Floorplan extraction accuracy** — Gemini may miss or misnumber booths. Mitigated by human spot-check of the top ~30 booths, which is the demo surface.
- **Gemini rate limits on free tier** — possible during demo. Mitigated by pre-warming the demo path and caching responses for the canonical demo questions.
- **Demo wifi at the convention center** — historically terrible. Mitigated by tethering or recording a backup demo video indoors before the show floor recording.
- **LinkedIn CSV friction in live demo** — users won't have the file ready. Mitigated by pre-loading a demo account on the demo device and showing the import flow as a recording rather than live.
- **Time** — the perennial hackathon risk. Mitigated by the scope cuts above and the staged build plan below.

### 6.3 What gets cut first if we're behind

In order of cuts:

1. Community annotations beyond `free_drinks` and `good_swag` (no ratings, no comments)
2. End-of-day automatic push (keep on-demand recap)
3. Day-2 continuity beyond a simple greeting
4. Behavioral-signal decay (use simple recency weighting only)
5. Web search fallback for unknown entities (just say "not in my data")
6. LinkedIn CSV import (keep auth, drop the connections graph)
7. Two-model split (collapse to Flash only)
8. Schedule view's proportional time spacing (use flat list)

We do not cut: the conversation loop, the map with at least basic pinning, the agent's grounding-first behavior, the test bench.

### 6.4 What we are deliberately doing that is risky but worth it

- Treating the map, schedule, and chat as one shared state rather than three separate features. This is harder to build but it's the entire differentiator.
- Running real Gemini calls in the test bench rather than mocking. More expensive but it's the only way the agent's behavior is actually tested.
- Committing to the demo being on the TechEx data, not a synthetic dataset. The risk is that ingestion breaks; the reward is that the demo is real.

---

*End of game plan v0.1. Open questions live in this same doc as inline `TODO` markers until resolved.*
