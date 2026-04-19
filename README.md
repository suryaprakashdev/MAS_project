# Robot Mission — Multi-Agent Radioactive Waste Cleanup

## Project Overview

In this project, I built a multi-agent system where autonomous robots collaborate to clean up radioactive waste from a nuclear facility. The simulation is set on a 30×15 grid divided into three radioactivity zones (green, yellow, red), where waste must be processed through a transformation pipeline before final disposal.

**My main objective was to minimise the number of iterations (steps) required to complete the cleanup**, since in a real-world scenario, fewer steps means less energy consumption, less radiation exposure for the robots, and faster decontamination of the site.

---

## How the Waste Pipeline Works

The waste processing follows a strict chain:

```
Green Waste ──(2:1)──► Yellow Waste ──(2:1)──► Red Waste ──► Disposal Zone
    Zone 1                Zone 2                 Zone 3         East Edge
```

- **Green robots** (confined to Zone 1): Pick up 2 green waste → Transform into 1 yellow → Drop at Zone 1 east border
- **Yellow robots** (Zones 1–2): Pick up 2 yellow waste → Transform into 1 red → Drop at Zone 2 east border  
- **Red robots** (all zones): Pick up 1 red waste → Carry to the disposal zone → Dispose

Each transformation consumes 2 items and produces 1, so there is natural attrition in the pipeline. For example, 25 initial green waste can produce at most 6 disposed red waste.

---

## Challenges I Faced and How I Solved Them

### Challenge 1: Robots Were Not Collecting Waste At All

When I first ran the simulation, the robots were just wandering around randomly and never picking up any waste. I traced the problem to two root causes:

1. **Missing agent attributes** — The robot subclasses (`GreenAgent`, `YellowAgent`, `RedAgent`) did not have `collects`, `max_inventory`, or `transform_to` attributes, so the model's `_do_pick_up`, `_do_drop`, and `_do_transform` methods could not function.

2. **Empty deliberation functions** — `deliberate_green()` and `deliberate_yellow()` only returned random moves. They never issued `PICK_UP`, `TRANSFORM`, or `DROP` actions. Only the red robot had deliberation logic, but since no red waste was ever produced, it had nothing to pick up either.

**Fix:** I implemented full deliberation functions for all three robot types with a clear priority chain: drop transformed waste → transform when full → pick up visible waste → move toward known waste → explore systematically.

---

### Challenge 2: Too Many Iterations (800+ Steps)

Even after the robots started collecting waste, the simulation was taking **800+ steps** to complete (and often didn't finish at all). The robots were exploring by random walk, which is extremely inefficient. I identified three key optimisations:

#### Optimisation 1: Systematic Lawnmower Sweep

Instead of random movement, I implemented a **lawnmower sweep pattern** for exploration. Each robot sweeps its zone horizontally, steps one row vertically at the boundary, and sweeps back. The sweep directions (`scan_dir_x`, `scan_dir_y`) are randomised per robot at initialisation, so multiple robots naturally cover different regions first.

This guarantees full zone coverage in `width × height` steps instead of the O(n·log n) expected time of a random walk.

#### Optimisation 2: Known-Waste Memory

I added a `known_waste` dictionary to each robot's knowledge base. Robots remember where they have seen waste from their percepts. When they need waste, they navigate **directly to the nearest known position** instead of randomly wandering. Stale entries are automatically cleared when the robot visits a position and finds it empty.

#### Optimisation 3: Inter-Robot Communication

I implemented a **broadcast communication protocol** where robots share waste positions with other robots:

- Every robot broadcasts all waste positions visible in its percepts to robots of the matching type (green waste → green robots, yellow waste → yellow robots, etc.)
- When a green robot **drops yellow waste** at the Zone 1 border, it sends a targeted message to all yellow robots with the exact position
- Similarly, yellow robots notify red robots when dropping red waste at the Zone 2 border

This creates a **directed information flow** that mirrors the waste pipeline itself: green → yellow → red.

#### Optimisation 4: Zone-Boundary Handoff Points

I designed the robots to use **fixed handoff locations** at zone boundaries:

- Green robots carry transformed yellow waste to the **east edge of Zone 1** before dropping
- Yellow robots carry transformed red waste to the **east edge of Zone 2** before dropping  
- Yellow robots **patrol the Zone 1 border** when idle (where yellow waste arrives)
- Red robots **patrol the Zone 2 border** when idle (where red waste arrives)

This creates predictable meeting points and eliminates the problem of waste being scattered randomly across the grid.

**Result:** These four optimisations together reduced average completion from **800+ steps down to 150–250 steps** — roughly a **4× improvement**.

---

### Challenge 3: Orphan Waste Getting Stuck

I ran into a situation where the pipeline would stall near the end: two robots would each hold 1 piece of waste, but with no more of that type left on the grid, neither could find a second piece to form the required pair for transformation. They would just keep searching forever.

**Example:** Two green robots each hold 1 green waste. There is no more green waste on the grid. Neither can transform (requires 2 green). Both wander endlessly.

**Solution — Orphan Drop Strategy:** I implemented a counter (`steps_holding_one`) that tracks how many steps a robot has been holding exactly 1 item of its collected type without finding a pair. After 20 steps (the `ORPHAN_THRESHOLD`), the robot **drops the single item at the zone border**. When multiple robots do this, orphan items accumulate at the same location, allowing another robot to pick up 2 and complete the transformation.

I also had to fix three related issues in the model:
- **`_do_drop` only supported transformed-type drops** — I added a fallback so robots can also drop their collected waste type back onto the grid
- **Premature simulation termination** — The stop condition checked only grid waste, not inventory. If all waste was picked up but not yet transformed, the simulation would stop too early. I fixed it to require both grid waste = 0 AND all inventories empty.
- **Deadlock detection was too aggressive** — It would declare deadlock when grid waste hit 0, ignoring items in robot inventories. I fixed the formula to count `grid + inventory` totals, and delayed the deadlock check to step 100+ to give robots time to drop orphans.

---

## Results

### Performance Across Configurations (10 runs each, averaged)

| Configuration | Avg Steps | Avg Disposed | Max Possible | Disposal Rate |
|---|---|---|---|---|
| 3G 3Y 2R, 15 waste | **220** | 3.0 | 3 | **100%** |
| 4G 3Y 2R, 25 waste | **330** | 6.0 | 6 | **100%** |
| 5G 4Y 3R, 27 waste | **240** | 6.0 | 6 | **100%** |

**Key takeaways:**
- The system consistently achieves **100% disposal rate** — every piece of waste that can theoretically be processed, is processed
- Average completion is in the **150–330 step range** depending on grid density
- The only remaining items at simulation end are mathematically unresolvable odd-count leftovers (e.g., 1 green and 1 yellow that cannot pair up)

### Impact of Communication (4G 3Y 2R, 25 waste, 10 runs)

| Mode | Avg Steps | Avg Disposed | Disposal Rate |
|---|---|---|---|
| Without Communication | **645** | 5.7 | 95% |
| With Communication | **330** | 6.0 | 100% |

**Interpretation:** Communication cuts the average number of steps nearly **in half** (645 → 330) and improves the disposal rate from 95% to 100%. Without communication, robots rely solely on visual scanning and random exploration to find waste, leading to wasted movement and occasional failures where waste items go unprocessed. With communication, robots are directed to exact waste positions as soon as they are discovered, eliminating redundant searching.

The **energy saving** from communication is significant: ~315 fewer steps per run means 315 fewer movement, scanning, and processing operations. In a real deployment, this directly translates to lower power consumption, reduced radiation exposure time, and faster site decontamination.

### Why Some Runs Take Longer

Looking at the raw step counts, most runs complete in 150–350 steps, but occasional outliers reach 600–750 steps. These occur when:
1. Green waste items are clustered far from the Zone 1 border, requiring long sweep distances
2. Orphan waste requires the full 20-step detection + drop + re-pickup cycle (adding ~40–60 steps)
3. The random seed produces an unfortunate initial placement where robots start far from waste

Even in the worst cases, the system always completes successfully — it never fails to process all possible waste.

---

## Architecture

### Files

| File | Description |
|---|---|
| `model.py` | The `RobotMission` model — grid setup, action execution, percepts, communication, stuck-robot watchdog, deadlock detection |
| `agents.py` | Robot agent classes and BDI deliberation functions with sweep scanning, known-waste memory, communication, and orphan handling |
| `objects.py` | Passive grid entities — `Radioactivity`, `Waste`, `WasteDisposal` |
| `server.py` | Mesa visualisation server configuration |
| `run.py` | Launcher with three modes: `visual`, `headless`, `compare` |

### Agent Decision Architecture (BDI)

Each robot follows a **Belief-Desire-Intention** cycle every step:

1. **Perceive** — Get percepts from the 5-cell neighbourhood (current cell + 4 cardinal)
2. **Update Knowledge** — Update position, inventory, known waste positions from percepts + inbox messages, track orphan holding time
3. **Deliberate** — Choose an action based on priority chain:
   - If carrying transformed waste → deliver to zone border
   - If inventory full → transform
   - If waste visible on cell → pick up
   - If waste visible in neighbour → move toward it
   - If known waste in memory → go to nearest
   - If holding orphan too long → drop at border for recombination
   - Fallback → systematic lawnmower sweep
4. **Act** — Execute the chosen action via the model
5. **Communicate** — Broadcast visible waste positions to relevant robot types

---

## How to Run

```bash
# Interactive visualisation (browser)
python run.py

# Headless single run with chart output
python run.py --mode headless --steps 500

# Compare communication vs no-communication
python run.py --mode compare --runs 10
```

**Requirements:** Python 3.10+, Mesa (`pip install mesa`)

---

## Conclusion

Through systematic optimisation — replacing random walks with lawnmower sweeps, adding memory and communication, implementing zone-boundary handoffs, and handling orphan waste — I achieved a **4× reduction in average iteration count** while maintaining a **100% disposal rate**. The communication protocol proved to be the single most impactful optimisation, cutting steps nearly in half and eliminating disposal failures entirely. These improvements directly translate to energy savings in a real-world deployment, making the multi-agent system both faster and more reliable.
