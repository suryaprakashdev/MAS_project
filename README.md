# Robot Mission — Multi-Agent System (MAS 2026)

**CentraleSupélec · MAS Course 2025–2026**

## Overview

A multi-agent simulation of autonomous robots cleaning radioactive waste. Three robot types collaborate (without, then with communication) to collect waste from a low-radioactivity zone, progressively transform it, and deposit the final product in a high-radioactivity waste disposal area.

### The Problem

The environment is a 2D grid divided into three zones (west → east) with increasing radioactivity:

| Zone | Radioactivity | Purpose |
|------|--------------|---------|
| z1 (west) | Low (0–0.33) | Initial green waste is scattered here |
| z2 (middle) | Medium (0.33–0.66) | Transit zone for yellow waste |
| z3 (east) | High (0.66–1.0) | Contains the waste disposal zone |

Three robot types work as a pipeline:

1. **Green robots** (z1 only): collect 2 green wastes → transform into 1 yellow → drop at z1 border
2. **Yellow robots** (z1 + z2): collect 2 yellow wastes → transform into 1 red → drop at z2 border
3. **Red robots** (all zones): collect 1 red waste → transport to disposal zone

## Architecture

### Agent Design: Percept → Deliberate → Do

Every robot follows this strict loop each step:

```
update(knowledge, last_percepts)
action = deliberate(knowledge)       # pure function — no side effects
percepts = model.do(self, action)    # model validates & executes
```

**Key constraint**: `deliberate()` only accesses its `knowledge` argument. This enforces a clean separation between the agent's internal reasoning and the environment.

### Knowledge Base

Each robot maintains a `knowledge` dict containing:
- Current position, inventory, zone bounds
- Percepts (what it sees in neighbouring cells)
- Map of known waste locations (updated from percepts)
- Message inbox (for Step 2)

### Actions

`move_north`, `move_south`, `move_east`, `move_west`, `pick_up`, `drop`, `transform`, `wait`

The **model** is the authority — it validates every action before executing it (e.g., a robot cannot walk outside its allowed zone even if it tries).

### File Structure

```
robot_mission_MAS2026/
├── README.md            ← you are here
├── requirements.txt     ← pip dependencies
├── objects.py           ← passive entities: Radioactivity, Waste, WasteDisposal
├── agents.py            ← robot agents with percept-deliberate-do loop
├── model.py             ← RobotMission model, grid setup, do() method
├── server.py            ← Mesa browser visualisation
└── run.py               ← entry point (visual or headless mode)
```

## Setup & Running

### Requirements

```bash
pip install -r requirements.txt
```

Requires Python 3.9+ and Mesa 2.x.

### Run with Browser Visualisation

```bash
python run.py --mode visual
```

Opens at `http://127.0.0.1:8521`. Use the controls to step through or play the simulation. Sliders let you adjust robot counts and initial waste.

### Run Headless (CLI + Chart)

```bash
python run.py --mode headless --steps 500 --seed 42           # with communication (default)
python run.py --mode headless --steps 500 --seed 42 --no-comms  # without communication
```

Produces `waste_over_time_comms.png` (or `_no_comms.png`) and prints final statistics.

### Compare Communication vs. No Communication

```bash
python run.py --mode compare --steps 500 --runs 5 --seed 42
```

Runs 5 seeds in both modes, prints a comparison table, and saves `comparison_comms_vs_no_comms.png`.

## Progress Log

### Step 1 — Agents without Communication ✅

**Implemented:**
- Full grid environment with 3 radioactivity zones
- Three robot types with zone-restricted movement
- Percept → Deliberate → Do architecture
- Knowledge base with waste location memory
- Smart movement: robots remember waste locations and navigate toward them
- Transform chain: green → yellow → red → disposed
- Mesa CanvasGrid visualisation with zone colouring
- Data collection and charting (waste counts over time)

**Design choices:**
- `deliberate()` is a module-level pure function (not a method) to strictly enforce the "no external access" rule from the assignment.
- Actions are strings for readability; the model's `do()` method is a single dispatch point.
- Radioactivity agents serve as zone markers — robots read them to know which zone they're in.
- The knowledge base caches discovered waste locations and removes stale entries when percepts show the waste is gone.

**Evaluation criteria:**
- *Correctness*: The waste pipeline (green → yellow → red → disposed) operates end-to-end.
- *Efficiency*: Memory-based navigation is faster than pure random walk (robots remember and revisit known waste locations).
- *Metric*: Number of steps until all waste is disposed.

### Step 2 — Agents with Communication ✅

**Implemented — full claim-based coordination protocol:**

**Message types:**
| Message | Sender | Receivers | Purpose |
|---------|--------|-----------|---------|
| `waste_found` | Any robot | Matching type only | "I see green waste at (3,7)" |
| `waste_dropped` | Green/Yellow robot | Downstream type | "I dropped yellow waste at (9,5)" |
| `claim` | Any robot | Same type | "I'm going for waste at (3,7), priority=(True, -4, 5)" |
| `claim_release` | Any robot | All | "I gave up on waste at (3,7)" |
| `waste_picked_up` | Any robot | All | "Waste at (3,7) is gone" |

**Priority scheme** (compared lexicographically, higher = better):
1. `has_partial_inventory` (bool): A bot already holding 1 waste of its type gets priority — it's one pickup from a transform.
2. `-manhattan_distance` (int): Among equal inventory status, closer bot wins.
3. `agent_id` (int): Deterministic tiebreaker.

**Claim lifecycle:**
1. Robot discovers waste → broadcasts `waste_found` (scoped to matching robot type only, reducing message spam)
2. Robot decides to pursue → broadcasts `claim` with priority
3. Other robots with lower-priority claims on the same position → auto-release their claim
4. Robot picks up waste → broadcasts `waste_picked_up` so everyone clears their maps
5. If a bot hasn't reached its claimed waste within 15 steps → claim auto-expires, others can re-claim

**Cross-type handoff:** When a green robot drops yellow waste at the z1/z2 border, it broadcasts `waste_dropped` specifically to yellow robots. Same for yellow→red handoff. This eliminates the "blind search" gap where downstream robots would otherwise wander randomly until discovering new waste.

**Evaluation:**
- `python run.py --mode compare` runs 5 seeds with and without communication, producing a comparison chart.
- Key metrics: steps-to-completion, total waste disposed, total messages sent.
- Trade-off analysis: communication costs messages but should reduce collection time — the compare chart quantifies this.

### Step 3 — Uncertainties 🔜

TBA per course schedule.

## Conceptual Foundations

This system models a **distributed MAS** where:
- Agents have a **local view** — they only perceive adjacent cells.
- The **environment is partially observable** — robots build a mental map over time.
- **Coordination emerges** from the pipeline structure (green produces yellow's input, etc.).
- The `deliberate()` constraint ensures agents are **autonomous** — they reason independently.
- The model's `do()` method ensures the **environment is authoritative** — no cheating.

### Properties respected (Lecture 1):
- **Autonomy**: Each agent decides its own actions via `deliberate()`.
- **Reactivity**: Agents respond to percepts each step.
- **Proactivity**: Agents pursue goals (collect waste, transform, deposit).
- **Social ability**: Full communication protocol with scoped broadcasting and claim coordination.

### MAS scope (Lecture 2):
- **System**: Robots cleaning radioactive waste in a zone-segmented environment.
- **Objective**: Dispose of all waste in minimum time.
- **Agents**: Three specialised types forming a processing pipeline.
- **Environment**: Grid with radioactivity gradients, zone-restricted access.

### Communication design (Lecture 3):
- **Scoped broadcasting**: Messages are routed only to relevant robot types, reducing bandwidth.
- **Claim-based coordination**: Prevents duplicated effort (two robots chasing the same waste).
- **Priority-driven conflict resolution**: Distributed — each agent resolves conflicts locally using priority tuples, no central arbiter.
- **Expiry mechanism**: Handles failures gracefully (stuck robots, disappeared waste).
- **Measurable trade-off**: `messages_sent` vs. `steps_to_finish` — quantifies the cost of coordination.
- **Cross-type handoff**: `waste_dropped` messages bridge the pipeline stages, converting blind search into directed pursuit.

## Mesa Version Compatibility

This code targets **Mesa 2.x** (tested with 2.1+). If you're using Mesa 3.x, the visualisation imports may differ — check the [Mesa migration guide](https://mesa.readthedocs.io/).

**Known Mesa quirk**: If `model.run_for(n)` doesn't exist in your version, use:
```python
for _ in range(n):
    model.step()
```
