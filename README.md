# Robot Mission — Multi-Agent Radioactive Waste Cleanup

## Objective

The primary objective I set for this project was to **minimise the number of simulation steps (iterations) required to complete the waste cleanup**. In a real-world scenario, every step a robot takes consumes energy — moving, scanning, picking up, transforming. If we can achieve the same cleanup in 200 steps instead of 800, that is a direct 4× reduction in energy expenditure. So the core question I tried to answer was: **how smart can we make the robots so they waste as little time as possible?**

---

## Approach

### Step 1: Getting the Basic Pipeline Working

I started by implementing the basic BDI (Belief-Desire-Intention) loop for each robot type. Each robot follows a `percepts → deliberate → do` cycle every step. The `deliberate()` function receives only the agent's `knowledge` dictionary and returns an action — it has no access to any external variables.

I defined the knowledge representation as a dictionary containing:
- Current position, inventory, robot type
- Percepts from the 5-cell neighbourhood (current cell + 4 cardinal neighbours)
- Position history (for loop detection)
- Known waste positions (memory of where waste was seen)
- Waste disposal zone location

The action space includes: `move_north`, `move_south`, `move_east`, `move_west`, `pick_up`, `drop`, `transform`, and `wait`.

### Step 2: Replacing Random Walk with Systematic Sweep

My first major optimisation was replacing **random exploration** with a **lawnmower sweep pattern**. Instead of choosing a random direction when no waste is visible, each robot sweeps its zone horizontally, steps one row vertically at the boundary, and sweeps back. I randomised the initial sweep direction (`scan_dir_x`, `scan_dir_y`) per robot so that multiple robots naturally cover different parts of the zone first.

This alone made a significant difference because random walk on a 10×15 grid has an expected full-coverage time of O(n·log n) ≈ 750 steps, while a systematic sweep covers the same area in exactly 150 steps.

### Step 3: Adding Known-Waste Memory

I added a `known_waste` dictionary to each robot's knowledge. Every time a robot perceives waste in its 5-cell neighbourhood, it stores the position and type. When the robot needs waste, it navigates **directly to the nearest remembered position** instead of wandering. Stale entries are automatically cleared when the robot visits a position and finds it empty.

### Step 4: Implementing Inter-Robot Communication

This was the single most impactful optimisation. I implemented a broadcast communication protocol:

- Every robot shares waste positions visible in its percepts with robots that collect that waste type
- When a green robot drops yellow waste at the Zone 1 border, it sends a **targeted message** to all yellow robots with the exact drop position
- Yellow robots do the same for red robots when dropping red waste at the Zone 2 border

This creates a directed information flow that mirrors the waste pipeline: green robots inform yellow robots, yellow robots inform red robots.

### Step 5: Zone-Boundary Handoff Strategy

I designed predictable **handoff points** at zone boundaries:

- Green robots carry transformed yellow waste to the **east edge of Zone 1** before dropping
- Yellow robots carry transformed red waste to the **east edge of Zone 2** before dropping
- Yellow robots **patrol the Zone 1 border** when idle, waiting for yellow waste
- Red robots **patrol the Zone 2 border** when idle, waiting for red waste

This eliminates the problem of waste being scattered randomly and makes the drop-off locations predictable for downstream robots.

### Step 6: Handling Orphan Waste

I encountered a problem where the pipeline would stall at the end: two robots each hold 1 item of waste, but no more exists on the grid to form the required pair for transformation. I solved this with an **orphan drop strategy**: if a robot holds 1 item for more than 20 steps without finding a pair, it drops the item at the zone border. When multiple robots do this, orphan items accumulate at the same spot, and another robot can pick up 2 and complete the transformation.

I also fixed the model to support this:
- `_do_drop` now allows robots to drop their collected waste type (not just the transformed type)
- The stop condition checks both grid waste AND robot inventories before terminating
- Deadlock detection counts inventory items, not just grid waste

---

## Results

### Performance Across Configurations (10 runs each, averaged)

| Configuration | Avg Steps | Avg Disposed | Max Theoretically Possible | Disposal Rate |
|---|---|---|---|---|
| 3 Green, 3 Yellow, 2 Red — 15 waste | **220** | 3.0 | 3 | **100%** |
| 4 Green, 3 Yellow, 2 Red — 25 waste | **330** | 6.0 | 6 | **100%** |
| 5 Green, 4 Yellow, 3 Red — 27 waste | **240** | 6.0 | 6 | **100%** |

The system consistently achieves a **100% disposal rate** — every piece of waste that can theoretically be processed through the pipeline is processed. The only items remaining at the end are mathematically unresolvable odd-count leftovers (e.g., 1 green that cannot pair up).

### Impact of Communication (4G 3Y 2R, 25 waste, 10 runs)

| Mode | Avg Steps | Avg Disposed | Disposal Rate |
|---|---|---|---|
| Without Communication | **645** | 5.7 | 95% |
| With Communication | **330** | 6.0 | 100% |

### Interpretation

1. **Communication cuts steps nearly in half** (645 → 330). Without communication, robots rely solely on their 5-cell visual range and random exploration to discover waste. With communication, a robot that spots waste immediately tells the relevant robot type exactly where it is — no searching required.

2. **Disposal rate improves from 95% to 100%**. Without communication, some runs (3 out of 10) fail to process all possible waste before the deadlock detector fires. With communication, every single run achieves the theoretical maximum.

3. **Energy interpretation**: The ~315 fewer steps per run with communication represents a direct energy saving. Each step involves movement, scanning, or processing — all of which consume energy. A 49% reduction in steps means 49% less energy consumed for the same cleanup result.

4. **The remaining iteration count (200–350 steps) represents a hard lower bound** imposed by the physics of the simulation: robots can only move 1 cell per step, the grid is 30 cells wide, and each transformation requires multiple pick-up and drop actions. The pipeline depth (green → yellow → red → disposal) means waste must traverse the full grid width plus multiple transformation cycles.

5. **Occasional outlier runs** (600–750 steps) occur when green waste is clustered far from the zone border or when orphan waste requires the full detection + drop + re-pickup cycle, adding ~40–60 extra steps.

---

## How to Run

```bash
# Interactive visualisation (browser at http://127.0.0.1:8521)
python run.py

# Headless single run with chart output
python run.py --mode headless --steps 500

# Compare communication vs no-communication
python run.py --mode compare --runs 10
```

**Requirements:** Python 3.10+, Mesa (`pip install mesa`)
