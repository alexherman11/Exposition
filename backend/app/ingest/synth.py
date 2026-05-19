"""Synthetic TechEx 2026 snapshot.

The plan's preferred source is live scraping from the seven microsites
(§1.1). For the offline demo path we generate a realistic, opinionated
snapshot that exercises every demo scenario (LoRa IoT, edge inference,
data center cooling, LLM eval, post-quantum, etc.).

About 250 sessions / 250 speakers / 250 exhibitors / one floorplan, per the
plan's stated cardinality.
"""

from __future__ import annotations

import json
import os
import random
from datetime import datetime
from pathlib import Path

from ..models import Booth, Exhibitor, Session, Speaker

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

RNG = random.Random(20260519)

DAYS = ["2026-05-18", "2026-05-19"]
ROOMS = [
    "Keynote Hall A", "Theatre A", "Theatre B", "Theatre C",
    "Workshop Room 1", "Workshop Room 2", "Demo Stage",
    "Hall B Stage", "AI Track Stage", "Edge Stage",
]
HALL_ZONES = ["Hall A — AI", "Hall B — IoT/Edge", "Hall C — Cyber", "Hall D — Data Center"]
TRACKS = [
    "AI & Big Data", "IoT Tech", "Edge Computing", "Cyber Security",
    "Digital Transformation", "Data Centre", "Intelligent Automation",
]
MICROSITES = {
    "AI & Big Data": "ai-expo.net",
    "IoT Tech": "iottechexpo.com",
    "Edge Computing": "edgecomputing-expo.com",
    "Cyber Security": "cybersecurityexpo.com",
    "Digital Transformation": "digitaltransformation-week.com",
    "Data Centre": "datacentre-expo.com",
    "Intelligent Automation": "iotaexpo.net",
}

# Companies — a mix of real (well-known) and plausible-but-synthetic.
COMPANIES = [
    # IoT / LoRa
    ("Semtech", ["LoRa", "IoT", "low-power"]),
    ("Helium", ["LoRaWAN", "wireless", "decentralized"]),
    ("Senet", ["LoRa", "asset tracking"]),
    ("Actility", ["LoRaWAN", "network server"]),
    ("Sierra Wireless", ["cellular IoT", "modules"]),
    # Edge / inference
    ("NVIDIA", ["GPUs", "edge inference", "Jetson"]),
    ("Hailo", ["edge AI", "NPU"]),
    ("Edge Impulse", ["TinyML", "on-device"]),
    ("Latent AI", ["edge optimization", "compiler"]),
    ("Modular", ["MAX engine", "compilers", "AI infra"]),
    # AI infra / LLMs
    ("Together AI", ["LLM hosting", "fine-tuning"]),
    ("Fireworks AI", ["LLM inference", "function-calling"]),
    ("Pinecone", ["vector DB", "RAG"]),
    ("LangChain", ["agent frameworks", "orchestration"]),
    ("Weights & Biases", ["ML observability", "experiments"]),
    # Data center / cooling
    ("Vantage Data Centers", ["colocation", "liquid cooling"]),
    ("Iceotope", ["immersion cooling"]),
    ("Submer", ["immersion cooling", "sustainability"]),
    ("Vertiv", ["power", "cooling", "rack PDU"]),
    ("Schneider Electric", ["power management", "EcoStruxure"]),
    # Cyber / PQC
    ("PQShield", ["post-quantum", "cryptography"]),
    ("ISARA", ["quantum-safe", "PKI"]),
    ("Crowdstrike", ["EDR", "threat intel"]),
    ("SentinelOne", ["XDR", "endpoint"]),
    ("Cloudflare", ["zero trust", "edge networking"]),
    # Hyperscale / cloud
    ("Google Cloud", ["Vertex AI", "TPU", "Gemini"]),
    ("Microsoft Azure", ["OpenAI service", "AI Foundry"]),
    ("AWS", ["Bedrock", "Trainium"]),
    ("Oracle Cloud", ["OCI", "GPU clusters"]),
    # Telco / 5G
    ("Ericsson", ["5G", "private networks"]),
    ("Nokia", ["5G", "fixed wireless"]),
    ("Veea", ["smart hubs", "edge platform", "mesh"]),
    # Robotics / industrial
    ("Boston Dynamics", ["robotics", "Spot", "Atlas"]),
    ("ABB Robotics", ["industrial robotics", "automation"]),
    ("Cognex", ["machine vision"]),
    # Misc enterprise
    ("Databricks", ["lakehouse", "MLflow"]),
    ("Snowflake", ["cloud warehouse", "Cortex"]),
    ("Salesforce", ["Einstein", "Agentforce"]),
    ("ServiceNow", ["Now Assist", "workflows"]),
    ("UiPath", ["RPA", "agentic automation"]),
    ("Cisco", ["networking", "secure connect"]),
]

# pad up to ~250 with synthetic-but-realistic names
INDUSTRY_SUFFIXES = ["Labs", "AI", "Systems", "Networks", "Robotics", "Cloud", "Edge", "Quantum", "Compute", "Logic", "Cortex", "Foundry"]
THEMES = {
    "IoT": ["IoT", "LoRa", "asset tracking", "fleet telemetry"],
    "Edge": ["edge AI", "on-device inference", "TinyML"],
    "AI": ["LLM", "RAG", "agents", "fine-tuning"],
    "Cyber": ["zero trust", "EDR", "post-quantum"],
    "DataCenter": ["liquid cooling", "rack PDU", "power optimization"],
    "Robotics": ["industrial robotics", "vision", "manipulation"],
}

def _pad_companies():
    extra = []
    used = {c[0] for c in COMPANIES}
    while len(COMPANIES) + len(extra) < 250:
        theme = RNG.choice(list(THEMES.keys()))
        name = f"{RNG.choice(['Vanta','Lyra','Nimbus','Foxglove','Helix','Orbital','Strato','Photon','Beacon','Tessera','Loom','Mira','Onyx','Aether','Pulse','Cortex','Hydra','Nova','Vertex','Quanta','Echo','Mesh','Atlas','Iris','Calyx','Helios','Solstice','Forge','Halo','Prism'])} {RNG.choice(INDUSTRY_SUFFIXES)}"
        if name in used:
            continue
        used.add(name)
        extra.append((name, RNG.sample(THEMES[theme], k=min(2, len(THEMES[theme])))))
    return COMPANIES + extra


def _floorplan_zones():
    """Lay out booth coordinates on a 1600x1000 canvas, in four hall zones."""
    booths: list[Booth] = []
    # 16 cols x 16 rows of candidate slots, partitioned into four quadrants
    width, height = 1600, 1000
    margin_x, margin_y = 40, 60
    cols, rows = 16, 16
    cell_w = (width - 2 * margin_x) / cols
    cell_h = (height - 2 * margin_y) / rows
    seq = 0
    for r in range(rows):
        for c in range(cols):
            # Skip aisles
            if c % 4 == 3 or r % 4 == 3:
                continue
            seq += 1
            x1 = margin_x + c * cell_w + 4
            y1 = margin_y + r * cell_h + 4
            x2 = x1 + cell_w - 8
            y2 = y1 + cell_h - 8
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            if c < cols / 2 and r < rows / 2:
                zone = "Hall A — AI"
                prefix = "A"
            elif c >= cols / 2 and r < rows / 2:
                zone = "Hall B — IoT/Edge"
                prefix = "B"
            elif c < cols / 2 and r >= rows / 2:
                zone = "Hall D — Data Center"
                prefix = "D"
            else:
                zone = "Hall C — Cyber"
                prefix = "C"
            booth_number = f"{prefix}{seq:02d}"
            booths.append(Booth(
                booth_number=booth_number,
                bbox=[x1, y1, x2, y2],
                center=[cx, cy],
                hall_zone=zone,
            ))
    return booths


def _speaker_pool(companies: list[tuple[str, list[str]]]):
    first_names = ["Alex","Priya","Hiroshi","Marta","Sven","Aisha","Tom","Mei","Jordan","Linh","Diego","Sara","Yusuf","Eva","Noah","Layla","Kai","Ines","Marcus","Anya","Felix","Naomi","Owen","Rhea","Theo","Vera"]
    last_names = ["Park","Choudhury","Tanaka","Rivera","Lindqvist","Khan","Romano","Wong","Reyes","Nguyen","Garcia","Holm","Aydin","Larsen","Brown","Hadid","Yoon","Costa","Webb","Petrov","Bauer","Liu","Singh","Okafor","Schmidt","Almeida"]
    titles = ["Chief Architect","VP Engineering","CTO","Principal Engineer","Director of AI","Head of Product","Research Lead","Field CTO","Distinguished Engineer","Staff Researcher"]
    speakers: list[Speaker] = []
    for i in range(260):
        company, tags = RNG.choice(companies)
        first = RNG.choice(first_names)
        last = RNG.choice(last_names)
        speakers.append(Speaker(
            id=f"sp_{i:03d}",
            name=f"{first} {last}",
            title=RNG.choice(titles),
            company=company,
            bio=f"{first} leads work on {', '.join(tags)} at {company}. {RNG.choice(['Frequent conference speaker.','Author of two books on systems engineering.','Background in distributed systems and ML.','15+ years building enterprise infrastructure.'])}",
        ))
    return speakers


SESSION_TEMPLATES = [
    ("LoRa-based IoT at industrial scale", "AI & Big Data", ["LoRa","IoT","industrial"]),
    ("Edge inference: when to compile, when to quantize", "Edge Computing", ["edge AI","quantization","compilers"]),
    ("Post-quantum cryptography for the practical CTO", "Cyber Security", ["post-quantum","cryptography","cto"]),
    ("Liquid cooling architectures for AI training clusters", "Data Centre", ["liquid cooling","HPC"]),
    ("Building agentic workflows that actually ship", "AI & Big Data", ["agents","LLM","production"]),
    ("RAG without regret: evaluation patterns", "AI & Big Data", ["RAG","evals","LLM"]),
    ("From RPA to agents: the migration playbook", "Intelligent Automation", ["RPA","agents"]),
    ("Zero-trust for hybrid AI workloads", "Cyber Security", ["zero trust","AI security"]),
    ("Spectrum strategy for private 5G + LoRa coexistence", "IoT Tech", ["5G","LoRa","spectrum"]),
    ("TinyML on Cortex-M: a maker's tour", "Edge Computing", ["TinyML","Cortex-M"]),
    ("Cooling 50kW racks without a chiller plant", "Data Centre", ["immersion cooling","sustainability"]),
    ("Function-calling at scale: tool routing in agents", "AI & Big Data", ["function calling","agents"]),
    ("The asset-tracking stack in 2026", "IoT Tech", ["asset tracking","fleet"]),
    ("LLM eval in production: what to actually measure", "AI & Big Data", ["LLM","evals"]),
    ("Multimodal agents for field operations", "Intelligent Automation", ["multimodal","field ops"]),
    ("Modernizing legacy SCADA without breaking it", "Digital Transformation", ["SCADA","industrial"]),
    ("Power optimization for hyperscale AI inference", "Data Centre", ["power","inference"]),
    ("Hardware roots of trust for IoT", "Cyber Security", ["IoT","RoT","HSM"]),
    ("Vision models on $20 cameras", "Edge Computing", ["vision","cheap hardware"]),
    ("Building a Gemini-powered concierge in 48 hours", "AI & Big Data", ["Gemini","agents","hackathon"]),
]


def _sessions_for(speakers: list[Speaker]):
    sessions: list[Session] = []
    # ensure each session has 1–3 speakers
    for i in range(250):
        title_base, track, tags = RNG.choice(SESSION_TEMPLATES)
        # add a variation suffix
        suffix = RNG.choice(["", " — panel", " — case study", " — workshop", " — fireside", " — lightning"])
        day = RNG.choice(DAYS)
        start_hour = RNG.choice(["09","10","11","13","14","15","16","17"])
        start_min = RNG.choice(["00","15","30","45"])
        start = f"{start_hour}:{start_min}"
        duration = RNG.choice([25, 40, 55])
        sh, sm = int(start_hour), int(start_min)
        em = sm + duration
        eh = sh + em // 60
        em = em % 60
        end = f"{eh:02d}:{em:02d}"
        chosen = RNG.sample(speakers, k=RNG.choice([1, 1, 2, 3]))
        spk_ids = [s.id for s in chosen]
        room = RNG.choice(ROOMS)
        sess = Session(
            id=f"se_{i:03d}",
            title=f"{title_base}{suffix}",
            abstract=f"{title_base}. Featuring {', '.join(s.name for s in chosen)} from {', '.join(set(s.company for s in chosen))}. Topics include {', '.join(tags)}.",
            track=track,
            day=day,
            start=start,
            end=end,
            room=room,
            speaker_ids=spk_ids,
            tags=tags,
            microsite=MICROSITES.get(track, ""),
        )
        for s in chosen:
            s.session_ids.append(sess.id)
        sessions.append(sess)
    return sessions


def _exhibitors_for(companies: list[tuple[str, list[str]]], booths: list[Booth]):
    exhibitors: list[Exhibitor] = []
    # leave some booths empty so the agent can correctly say "that booth is unstaffed"
    populated_booths = RNG.sample(booths, k=min(len(companies), len(booths)))
    for idx, (company, tags) in enumerate(companies):
        if idx >= len(populated_booths):
            break
        b = populated_booths[idx]
        ex = Exhibitor(
            id=f"ex_{idx:03d}",
            company=company,
            booth_number=b.booth_number,
            description=f"{company} — focused on {', '.join(tags)}. Drop by for live demos and conversation with engineers.",
            tags=tags,
            hall_zone=b.hall_zone,
            website=f"https://example.com/{company.lower().replace(' ', '-')}",
        )
        b.exhibitor_id = ex.id
        exhibitors.append(ex)
    return exhibitors


def generate_snapshot() -> dict:
    companies = _pad_companies()
    booths = _floorplan_zones()
    speakers = _speaker_pool(companies)
    sessions = _sessions_for(speakers)
    exhibitors = _exhibitors_for(companies, booths)
    return {
        "sessions": [s.model_dump(mode="json") for s in sessions],
        "speakers": [s.model_dump(mode="json") for s in speakers],
        "exhibitors": [e.model_dump(mode="json") for e in exhibitors],
        "booths": [b.model_dump(mode="json") for b in booths],
    }


def write_snapshot():
    snap = generate_snapshot()
    for key, rows in snap.items():
        with open(DATA_DIR / f"{key}.json", "w") as f:
            json.dump(rows, f, indent=2)
    print(f"Wrote snapshot to {DATA_DIR}")
    for key, rows in snap.items():
        print(f"  {key}: {len(rows)}")
    return snap


if __name__ == "__main__":
    write_snapshot()
