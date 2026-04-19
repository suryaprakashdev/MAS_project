# ============================================================================
# agents.py — Robot agents with percept → deliberate → do architecture
# ============================================================================
# Project : Robot Mission MAS 2026
# Created : March 2026
# Updated : April 2026 — boustrophedon scan walk + dynamic row coordination
# Description: Three robot classes (GreenAgent, YellowAgent, RedAgent) that
#              collect, transform, and transport radioactive waste.
#
#              Each follows the strict loop:
#                  1. update knowledge with percepts
#                  2. (action, messages) = deliberate(knowledge)  [pure fn]
#                  3. percepts = model.do(self, action)
#                  4. step() sends the outgoing messages
#
# Communication protocol (Step 2):
#   - waste_found    : "I see waste of type X at position Y"
#   - waste_dropped  : "I just dropped waste of type X at position Y"
#   - claim          : "I'm going for waste at Y, my priority is P"
#   - claim_release  : "I gave up on waste at Y"
#   - waste_picked_up: "Waste at Y is gone, clear your maps"
#   - row_claim      : "I'm sweeping row R, don't duplicate" (same type only)
#   - row_release    : "I finished row R, others can take it" (same type only)
#
# Scan walk design:
#   - Each robot sweeps its allowed zone in a boustrophedon (lawnmower) pattern
#     instead of random walk when no known waste target exists.
#   - Robots of the same type coordinate via row_claim / row_release messages
#     to avoid sweeping the same row simultaneously.
#   - Yellow robots use a two-phase scan zone:
#       Phase 1 (priority): last column of z1 + all of z2  (yellow waste drops here)
#       Phase 2 (fallback): rest of z1                     (only if phase 1 exhausted)
# ============================================================================

import random
from mesa import Agent
from objects import ZONE_BOUNDS

# ---------------------------------------------------------------------------
# Action vocabulary — shared by all robots and the model's do() method
# ---------------------------------------------------------------------------
MOVE_NORTH = "move_north"
MOVE_SOUTH = "move_south"
MOVE_EAST  = "move_east"
MOVE_WEST  = "move_west"
PICK_UP    = "pick_up"
DROP        = "drop"
TRANSFORM  = "transform"
WAIT       = "wait"

MOVE_ACTIONS = {MOVE_NORTH, MOVE_SOUTH, MOVE_EAST, MOVE_WEST}
ALL_ACTIONS  = MOVE_ACTIONS | {PICK_UP, DROP, TRANSFORM, WAIT}

DIRECTION_DELTAS = {
    MOVE_NORTH: (0, 1),
    MOVE_SOUTH: (0, -1),
    MOVE_EAST:  (1, 0),
    MOVE_WEST:  (-1, 0),
}

# ---------------------------------------------------------------------------
# Communication constants
# ---------------------------------------------------------------------------
CLAIM_EXPIRY_STEPS = 15    # claims older than this are automatically released
LAST_WASTE_THRESHOLD = 3   # relax claim exclusivity when ≤ this many wastes known
LOOP_WINDOW = 10           # position history window for loop detection
LOOP_REPEAT  = 3           # how many times same cell triggers a loop reset

# What each robot type collects, and what it produces after transform
ROBOT_CONFIG = {
    "green":  {"collects": "green",  "max_inv": 2, "transform_to": "yellow"},
    "yellow": {"collects": "yellow", "max_inv": 2, "transform_to": "red"},
    "red":    {"collects": "red",    "max_inv": 1, "transform_to": None},
}


# ============================================================================
# Helper functions used by deliberate (all pure — no side effects)
# ============================================================================

def _manhattan(a: tuple, b: tuple) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _calc_priority(knowledge: dict, waste_pos: tuple) -> tuple:
    """Compute claim priority for a waste position.

    Returns a tuple compared lexicographically (higher = better):
      (has_partial_inventory: bool, -manhattan_distance: int, agent_id: int)
    """
    collects = ROBOT_CONFIG[knowledge["robot_type"]]["collects"]
    has_partial = any(w == collects for w in knowledge["inventory"])
    dist = _manhattan(knowledge["pos"], waste_pos)
    return (has_partial, -dist, knowledge["my_id"])


def _move_toward(knowledge: dict, target: tuple) -> str:
    """Return a move action that brings the agent closer to *target*."""
    cx, cy = knowledge["pos"]
    tx, ty = target
    min_x = knowledge["zone_x_min"]
    max_x = knowledge["zone_x_max"]

    candidates = []
    if tx > cx and cx + 1 <= max_x:
        candidates.append((abs(tx - cx), MOVE_EAST))
    if tx < cx and cx - 1 >= min_x:
        candidates.append((abs(tx - cx), MOVE_WEST))
    if ty > cy:
        candidates.append((abs(ty - cy), MOVE_NORTH))
    if ty < cy:
        candidates.append((abs(ty - cy), MOVE_SOUTH))

    if not candidates:
        return _scan_walk(knowledge)

    best_dist = max(c[0] for c in candidates)
    best = [c[1] for c in candidates if c[0] == best_dist]
    return random.choice(best)


# ---------------------------------------------------------------------------
# Boustrophedon scan walk — replaces random walk as the idle fallback
# ---------------------------------------------------------------------------

def _pick_unclaimed_row(knowledge: dict) -> int:
    """Return the nearest unclaimed row within the grid.

    Prefers rows closest to the robot's current y-position so movement
    overhead when transitioning rows is minimised.
    """
    cy = knowledge["pos"][1]
    grid_h = knowledge["grid_height"]
    claimed = knowledge.get("claimed_rows", set())

    candidates = [r for r in range(grid_h) if r not in claimed]
    if not candidates:
        # All rows claimed by teammates — pick nearest anyway to avoid deadlock
        return cy

    return min(candidates, key=lambda r: abs(r - cy))


def _detect_loop(knowledge: dict) -> bool:
    """Return True if the robot has been cycling through the same cell too often.

    Uses a sliding window of the last LOOP_WINDOW positions. If the current
    position appears LOOP_REPEAT or more times the robot is stuck in a loop.
    """
    history = knowledge.get("pos_history", [])
    pos = knowledge["pos"]
    recent = history[-LOOP_WINDOW:]
    return recent.count(pos) >= LOOP_REPEAT


def _reset_scan(knowledge: dict) -> None:
    """Break out of a loop by resetting scan state and flipping sweep direction.

    Clears pos_history so the next LOOP_WINDOW steps are fresh.  Forces a
    new row assignment so the robot doesn't re-enter the same sweep it just
    escaped.
    """
    knowledge["scan_row"]  = None
    knowledge["scan_dir"]  = -knowledge.get("scan_dir", 1)   # flip direction
    knowledge["pos_history"] = []                              # clear history


def _scan_walk(knowledge: dict) -> str:
    """Boustrophedon (lawnmower) scan within the robot's current scan zone.

    Fixes vs. naive implementation:
      - Single-column zone: scan_x_min == scan_x_max → sweep north/south only,
        no east/west attempt that would deadlock the robot.
      - Loop detection: if robot has visited the same cell ≥ LOOP_REPEAT times
        in the last LOOP_WINDOW steps, _reset_scan() is called to force a new
        row and flip direction before continuing.
      - Same-row fallback: when all peer rows are claimed and next_row == cy,
        immediately sweep in the new direction rather than trying to move
        vertically (which would oscillate back to the same cell).
    """
    cx, cy = knowledge["pos"]
    scan_x_min = knowledge.get("scan_x_min", knowledge["zone_x_min"])
    scan_x_max = knowledge.get("scan_x_max", knowledge["zone_x_max"])
    scan_dir   = knowledge.get("scan_dir", 1)

    # --- Guard: single-column scan zone — sweep north/south only ---
    if scan_x_min >= scan_x_max:
        grid_h = knowledge["grid_height"]
        # Simple up/down sweep using scan_dir as vertical direction
        if cy + scan_dir >= grid_h or cy + scan_dir < 0:
            knowledge["scan_dir"] = -scan_dir
        return MOVE_NORTH if knowledge["scan_dir"] == 1 else MOVE_SOUTH

    # --- Loop detection: escape before doing anything else ---
    if _detect_loop(knowledge):
        _reset_scan(knowledge)
        scan_dir = knowledge["scan_dir"]   # refreshed after reset

    scan_row = knowledge.get("scan_row")

    # --- Claim a row if we don't have one ---
    if scan_row is None:
        scan_row = _pick_unclaimed_row(knowledge)
        knowledge["scan_row"] = scan_row
        knowledge["scan_pending_claim"] = scan_row

    # --- Navigate to the assigned row first ---
    if cy != scan_row:
        return MOVE_NORTH if scan_row > cy else MOVE_SOUTH

    # --- On the assigned row — check if we've reached the boundary ---
    at_east_boundary = (scan_dir == 1  and cx >= scan_x_max)
    at_west_boundary = (scan_dir == -1 and cx <= scan_x_min)

    if at_east_boundary or at_west_boundary:
        knowledge["scan_pending_release"] = scan_row
        knowledge["scan_dir"] = -scan_dir

        next_row = _pick_unclaimed_row(knowledge)
        knowledge["scan_row"] = next_row
        knowledge["scan_pending_claim"] = next_row

        if next_row > cy:
            return MOVE_NORTH
        elif next_row < cy:
            return MOVE_SOUTH
        else:
            # All peer rows claimed — same row, just start sweeping immediately
            # (avoids oscillating north/south at the boundary)
            return MOVE_EAST if knowledge["scan_dir"] == 1 else MOVE_WEST

    # --- Sweep in current direction ---
    return MOVE_EAST if scan_dir == 1 else MOVE_WEST


# ---------------------------------------------------------------------------
# Yellow two-phase scan zone management (pure helper)
# ---------------------------------------------------------------------------

def _update_yellow_scan_zone(knowledge: dict) -> None:
    """Set scan_x_min / scan_x_max for yellow robots based on scan phase.

    Phase 1 (default, priority):
        Sweep from the last column of z1 (where green robots drop yellow
        waste) through all of z2.  This is where yellow waste appears first.

    Phase 2 (fallback, only after Phase 1 is exhausted):
        Sweep the remainder of z1.  Yellow waste here is uncommon but
        possible if communication is off.

    Phase transition: switch to Phase 2 when the robot has completed at
    least one full scan pass in Phase 1 (scan_full_passes >= 1) AND there
    are no known yellow waste positions within the Phase 1 zone.
    """
    bounds = knowledge.get("zone_bounds", {})
    z1_lo = bounds.get("z1_lo", knowledge["zone_x_min"])
    z1_hi = bounds.get("z1_hi", knowledge["zone_x_min"])
    z2_hi = knowledge["zone_x_max"]

    phase = knowledge.get("scan_phase", 1)

    # Check whether we should promote to Phase 2
    if phase == 1:
        passes = knowledge.get("scan_full_passes", 0)
        if passes >= 1:
            # Any yellow waste known inside Phase 1 zone?
            phase1_has_waste = any(
                pos[0] >= z1_hi and wtype == "yellow"
                for pos, wtype in knowledge["known_waste_positions"].items()
            )
            if not phase1_has_waste:
                knowledge["scan_phase"] = 2
                knowledge["scan_row"] = None   # force re-claim in new zone
                phase = 2

    if phase == 1:
        knowledge["scan_x_min"] = z1_hi
        knowledge["scan_x_max"] = z2_hi
    else:
        knowledge["scan_x_min"] = z1_lo
        knowledge["scan_x_max"] = max(z1_hi - 1, z1_lo)


# ---------------------------------------------------------------------------
# Message processing (pure — mutates knowledge dict only)
# ---------------------------------------------------------------------------

def _process_incoming_messages(knowledge: dict) -> None:
    """Fold incoming messages into the knowledge base."""
    for msg in knowledge.get("messages", []):
        content = msg["content"]
        msg_type = content.get("type")

        if msg_type in ("waste_found", "waste_dropped"):
            pos = tuple(content["pos"])
            knowledge["known_waste_positions"][pos] = content["waste_type"]

        elif msg_type == "claim":
            pos = tuple(content["pos"])
            their_priority = tuple(content["priority"])
            their_id = msg["from"]
            step = content.get("step", knowledge["step_count"])

            existing = knowledge["others_claims"].get(pos)
            if existing is None or their_priority > tuple(existing["priority"]):
                knowledge["others_claims"][pos] = {
                    "claimer_id": their_id,
                    "priority": their_priority,
                    "step": step,
                }

            # If they outrank me on something I claimed → release my claim
            if pos in knowledge["my_claims"]:
                if their_priority > tuple(knowledge["my_claims"][pos]["priority"]):
                    del knowledge["my_claims"][pos]
                    if knowledge.get("current_target") == pos:
                        knowledge["current_target"] = None

        elif msg_type == "claim_release":
            pos = tuple(content["pos"])
            releaser = msg["from"]
            existing = knowledge["others_claims"].get(pos)
            if existing and existing["claimer_id"] == releaser:
                del knowledge["others_claims"][pos]

        elif msg_type == "waste_picked_up":
            pos = tuple(content["pos"])
            knowledge["known_waste_positions"].pop(pos, None)
            knowledge["others_claims"].pop(pos, None)
            knowledge["my_claims"].pop(pos, None)
            if knowledge.get("current_target") == pos:
                knowledge["current_target"] = None

        # --- Scan row coordination ---
        elif msg_type == "row_claim":
            row = content["row"]
            knowledge["claimed_rows"].add(row)

        elif msg_type == "row_release":
            row = content["row"]
            knowledge["claimed_rows"].discard(row)
            # If our scan_row happens to be this row (very rare race), keep it —
            # we already own it; the release was sent by the OTHER robot.


def _expire_old_claims(knowledge: dict) -> list:
    """Remove expired claims. Return outgoing release messages."""
    outgoing = []
    step_now = knowledge["step_count"]

    expired_mine = [
        pos for pos, info in knowledge["my_claims"].items()
        if step_now - info["step"] > CLAIM_EXPIRY_STEPS
    ]
    for pos in expired_mine:
        del knowledge["my_claims"][pos]
        if knowledge.get("current_target") == pos:
            knowledge["current_target"] = None
        outgoing.append({
            "_target_type": None,
            "type": "claim_release",
            "pos": list(pos),
        })

    expired_others = [
        pos for pos, info in knowledge["others_claims"].items()
        if step_now - info["step"] > CLAIM_EXPIRY_STEPS
    ]
    for pos in expired_others:
        del knowledge["others_claims"][pos]

    return outgoing


def _build_discovery_messages(knowledge: dict) -> list:
    """Build broadcast messages for waste discovered THIS step."""
    outgoing = []
    for pos, wtype in knowledge.get("new_discoveries", []):
        outgoing.append({
            "_target_type": wtype,
            "type": "waste_found",
            "waste_type": wtype,
            "pos": list(pos),
        })
    return outgoing


def _build_scan_messages(knowledge: dict) -> list:
    """Emit row_claim / row_release messages queued by _scan_walk this step.

    These are scoped to same-type robots only (no need for cross-type
    coordination since scan zones don't overlap between types).
    """
    outgoing = []
    robot_type = knowledge["robot_type"]

    pending_claim = knowledge.pop("scan_pending_claim", None)
    if pending_claim is not None:
        outgoing.append({
            "_target_type": robot_type,
            "type": "row_claim",
            "row": pending_claim,
        })

    pending_release = knowledge.pop("scan_pending_release", None)
    if pending_release is not None:
        outgoing.append({
            "_target_type": robot_type,
            "type": "row_release",
            "row": pending_release,
        })

    return outgoing


# ============================================================================
# Shared deliberation preamble — every robot runs this first
# ============================================================================

def _deliberate_preamble(knowledge: dict) -> list:
    """Common first phase: process messages, expire claims, broadcast discoveries."""
    _process_incoming_messages(knowledge)
    outgoing = _expire_old_claims(knowledge)
    outgoing.extend(_build_discovery_messages(knowledge))
    outgoing.extend(_build_scan_messages(knowledge))
    return outgoing


def _claim_and_move(knowledge: dict, target_pos, priority, target_type: str, outgoing: list) -> str:
    """Record a claim, append the claim message, and return a move action."""
    comms = knowledge.get("communication_enabled", False)
    if comms:
        knowledge["my_claims"][target_pos] = {
            "step": knowledge["step_count"],
            "priority": priority,
        }
        knowledge["current_target"] = target_pos
        outgoing.append({
            "_target_type": target_type,
            "type": "claim",
            "pos": list(target_pos),
            "priority": list(priority),
            "step": knowledge["step_count"],
        })
    return _move_toward(knowledge, target_pos)


def _pickup_and_notify(knowledge: dict, waste_type: str, outgoing: list) -> None:
    """Append waste_picked_up message and clean up claims for this cell."""
    comms = knowledge.get("communication_enabled", False)
    pos = knowledge["pos"]
    if comms:
        outgoing.append({
            "_target_type": None,
            "type": "waste_picked_up",
            "pos": list(pos),
            "waste_type": waste_type,
        })
        knowledge["my_claims"].pop(pos, None)


def _drop_and_notify(knowledge: dict, product_type: str, target_robot_type: str, outgoing: list) -> None:
    """Append waste_dropped message so downstream robots know about new waste."""
    comms = knowledge.get("communication_enabled", False)
    pos = knowledge["pos"]
    if comms:
        outgoing.append({
            "_target_type": target_robot_type,
            "type": "waste_dropped",
            "waste_type": product_type,
            "pos": list(pos),
        })


def _find_nearest_unclaimed_waste(knowledge: dict, waste_type: str):
    """Return (pos, priority) for the best available waste, or (None, None).

    Claim relaxation: when <= LAST_WASTE_THRESHOLD wastes of this type are
    known, claim exclusivity is dropped so all robots converge on the
    remaining items.  The first to arrive picks it up; others see it gone
    next percept and re-scan immediately — preventing end-game idle looping.
    """
    my_pos = knowledge["pos"]
    others_claims = knowledge.get("others_claims", {})

    known_of_type = {
        loc: wtype
        for loc, wtype in knowledge["known_waste_positions"].items()
        if wtype == waste_type
    }
    relax_claims = len(known_of_type) <= LAST_WASTE_THRESHOLD

    best_pos, best_priority = None, None
    for loc in known_of_type:
        my_priority = _calc_priority(knowledge, loc)
        if not relax_claims:
            existing = others_claims.get(loc)
            if existing is not None and tuple(existing["priority"]) >= my_priority:
                continue
        if best_pos is None or _manhattan(my_pos, loc) < _manhattan(my_pos, best_pos):
            best_pos = loc
            best_priority = my_priority

    return best_pos, best_priority


# ============================================================================
# Deliberation functions — PURE, return (action, outgoing_messages)
# ============================================================================

def deliberate_green(knowledge: dict) -> tuple:
    """Green robot: collect green waste, transform to yellow, drop at z1 border."""
    outgoing = _deliberate_preamble(knowledge)
    inv = knowledge["inventory"]
    pos = knowledge["pos"]
    max_x = knowledge["zone_x_max"]

    # 1. Transform: 2 green → 1 yellow
    green_count = sum(1 for w in inv if w == "green")
    if green_count >= 2:
        return TRANSFORM, outgoing

    # 2. Carry yellow east to z1/z2 border, drop it
    if "yellow" in inv:
        if pos[0] >= max_x:
            _drop_and_notify(knowledge, "yellow", "yellow", outgoing)
            return DROP, outgoing
        return _move_toward(knowledge, (max_x, pos[1])), outgoing

    # 3. Pick up green waste at current cell
    if len(inv) < 2:
        percepts = knowledge.get("percepts", {})
        current_cell = percepts.get(pos, {})
        if "green" in current_cell.get("wastes", []):
            _pickup_and_notify(knowledge, "green", outgoing)
            return PICK_UP, outgoing

    # 4. Move toward known unclaimed green waste
    if len(inv) < 2:
        target_pos, priority = _find_nearest_unclaimed_waste(knowledge, "green")
        if target_pos is not None:
            action = _claim_and_move(knowledge, target_pos, priority, "green", outgoing)
            return action, outgoing

    # 5. Scan walk (boustrophedon) — no known waste, sweep the zone
    return _scan_walk(knowledge), outgoing


def deliberate_yellow(knowledge: dict) -> tuple:
    """Yellow robot: collect yellow waste, transform to red, drop at z2 border.

    Scan strategy (two-phase):
      Phase 1: sweep last col of z1 + all of z2 — yellow waste drops at z1/z2 border
      Phase 2: sweep rest of z1 — fallback after Phase 1 fully exhausted
    """
    outgoing = _deliberate_preamble(knowledge)

    # Update scan zone based on phase before potentially calling _scan_walk
    _update_yellow_scan_zone(knowledge)

    inv = knowledge["inventory"]
    pos = knowledge["pos"]
    max_x = knowledge["zone_x_max"]

    yellow_count = sum(1 for w in inv if w == "yellow")
    if yellow_count >= 2:
        return TRANSFORM, outgoing

    if "red" in inv:
        if pos[0] >= max_x:
            _drop_and_notify(knowledge, "red", "red", outgoing)
            return DROP, outgoing
        return _move_toward(knowledge, (max_x, pos[1])), outgoing

    if len(inv) < 2:
        percepts = knowledge.get("percepts", {})
        current_cell = percepts.get(pos, {})
        if "yellow" in current_cell.get("wastes", []):
            _pickup_and_notify(knowledge, "yellow", outgoing)
            return PICK_UP, outgoing

    if len(inv) < 2:
        target_pos, priority = _find_nearest_unclaimed_waste(knowledge, "yellow")
        if target_pos is not None:
            action = _claim_and_move(knowledge, target_pos, priority, "yellow", outgoing)
            return action, outgoing

    # Track full passes: when scan_walk transitions rows, increment counter
    # A "full pass" = robot returned to scan_x_min or scan_x_max on its row.
    # We detect this via the pending_release that _scan_walk queues.
    # Check before calling _scan_walk so the increment happens once per row finish.
    if knowledge.get("scan_pending_release") is not None:
        knowledge["scan_full_passes"] = knowledge.get("scan_full_passes", 0) + 1

    # 5. Scan walk (phase-aware)
    return _scan_walk(knowledge), outgoing


def deliberate_red(knowledge: dict) -> tuple:
    """Red robot: collect red waste, transport to disposal zone."""
    outgoing = _deliberate_preamble(knowledge)
    inv = knowledge["inventory"]
    pos = knowledge["pos"]

    if "red" in inv:
        disposal = knowledge.get("waste_disposal_pos")
        if disposal is not None:
            disposal = tuple(disposal)
            if pos == disposal:
                return DROP, outgoing
            return _move_toward(knowledge, disposal), outgoing
        max_x = knowledge["zone_x_max"]
        return _move_toward(knowledge, (max_x, pos[1])), outgoing

    if len(inv) < 1:
        percepts = knowledge.get("percepts", {})
        current_cell = percepts.get(pos, {})
        if "red" in current_cell.get("wastes", []):
            _pickup_and_notify(knowledge, "red", outgoing)
            return PICK_UP, outgoing

    if len(inv) < 1:
        target_pos, priority = _find_nearest_unclaimed_waste(knowledge, "red")
        if target_pos is not None:
            action = _claim_and_move(knowledge, target_pos, priority, "red", outgoing)
            return action, outgoing

    # Scan walk (boustrophedon) — no known red waste
    return _scan_walk(knowledge), outgoing


# Map robot type → deliberation function
DELIBERATE_FN = {
    "green":  deliberate_green,
    "yellow": deliberate_yellow,
    "red":    deliberate_red,
}


# ============================================================================
# Base robot class — implements the percept-deliberate-do loop
# ============================================================================

class RobotAgent(Agent):
    """Base class for all robots."""

    def __init__(self, unique_id, model, robot_type: str):
        super().__init__(unique_id, model)
        self.robot_type = robot_type
        self.agent_type = "robot"

        cfg = ROBOT_CONFIG[robot_type]
        self.collects = cfg["collects"]
        self.max_inventory = cfg["max_inv"]
        self.transform_to = cfg["transform_to"]

        self.zone_x_min = 0
        self.zone_x_max = 0

        self.inventory = []
        self._last_percepts = {}
        self._deliberate = DELIBERATE_FN[robot_type]

        self.inbox = []
        self.knowledge = {}

    # ------------------------------------------------------------------
    # Knowledge management
    # ------------------------------------------------------------------
    def _init_knowledge(self):
        # Snapshot zone bounds at init time so deliberate() stays pure
        zone_bounds = {
            "z1_lo": ZONE_BOUNDS["z1"][0],
            "z1_hi": ZONE_BOUNDS["z1"][1],
            "z2_lo": ZONE_BOUNDS["z2"][0],
            "z2_hi": ZONE_BOUNDS["z2"][1],
            "z3_lo": ZONE_BOUNDS["z3"][0],
            "z3_hi": ZONE_BOUNDS["z3"][1],
        }

        # Default scan zone = full allowed zone (yellow overrides in deliberate)
        scan_x_min = self.zone_x_min
        scan_x_max = self.zone_x_max
        if self.robot_type == "yellow":
            # Phase 1 priority zone: last col of z1 → z2_hi
            scan_x_min = zone_bounds["z1_hi"]
            scan_x_max = zone_bounds["z2_hi"]

        self.knowledge = {
            "pos": self.pos,
            "my_id": self.unique_id,
            "robot_type": self.robot_type,
            "inventory": list(self.inventory),
            "max_inventory": self.max_inventory,
            "zone_x_min": self.zone_x_min,
            "zone_x_max": self.zone_x_max,
            "grid_width": self.model.grid.width,
            "grid_height": self.model.grid.height,
            "zone_bounds": zone_bounds,
            "percepts": {},
            "known_waste_positions": {},
            "waste_disposal_pos": None,
            "messages": [],
            "step_count": 0,
            "communication_enabled": getattr(self.model, "communication_enabled", False),
            # Waste claim state
            "my_claims": {},
            "others_claims": {},
            "current_target": None,
            "new_discoveries": [],
            # Scan walk state
            "scan_row": None,
            "scan_dir": 1,          # +1 = sweep east first
            "scan_x_min": scan_x_min,
            "scan_x_max": scan_x_max,
            "claimed_rows": set(),  # rows claimed by teammates (same type)
            "scan_phase": 1,        # yellow only: 1=priority zone, 2=fallback
            "scan_full_passes": 0,  # yellow only: completed passes in phase 1
            # Loop detection
            "pos_history": [],      # last LOOP_WINDOW positions visited
        }

    def _update_knowledge(self, percepts: dict):
        """Merge new percepts into the knowledge base."""
        k = self.knowledge
        k["pos"] = self.pos
        k["inventory"] = list(self.inventory)
        k["percepts"] = percepts
        k["step_count"] = k.get("step_count", 0) + 1

        k["messages"] = list(self.inbox)
        self.inbox.clear()

        # Track position history for loop detection (keep last LOOP_WINDOW entries)
        history = k.setdefault("pos_history", [])
        history.append(self.pos)
        if len(history) > LOOP_WINDOW:
            del history[0]

        # Detect newly-discovered waste
        k["new_discoveries"] = []
        old_known = set(k["known_waste_positions"].keys())

        for cell_pos, cell_info in percepts.items():
            wastes_here = cell_info.get("wastes", [])
            if wastes_here:
                k["known_waste_positions"][cell_pos] = wastes_here[0]
                if cell_pos not in old_known:
                    k["new_discoveries"].append((cell_pos, wastes_here[0]))
            else:
                k["known_waste_positions"].pop(cell_pos, None)
                k["my_claims"].pop(cell_pos, None)
                k["others_claims"].pop(cell_pos, None)
                if k.get("current_target") == cell_pos:
                    k["current_target"] = None

            if cell_info.get("has_disposal", False):
                k["waste_disposal_pos"] = cell_pos

    # ------------------------------------------------------------------
    # The main step — percept / deliberate / do / communicate
    # ------------------------------------------------------------------
    def step(self):
        if not self.knowledge:
            self._init_knowledge()
            self._last_percepts = self.model.get_percepts(self)

        # 1. Update knowledge
        self._update_knowledge(self._last_percepts)

        # 2. Deliberate (pure)
        action, outgoing = self._deliberate(self.knowledge)

        # 3. Execute action
        self._last_percepts = self.model.do(self, action)

        # 4. Send messages (side effect — only if communication is on)
        if self.knowledge.get("communication_enabled", False):
            for msg in outgoing:
                target_type = msg.pop("_target_type", None)
                self.model.broadcast_message(self, msg, target_type=target_type)


# ============================================================================
# Concrete robot subclasses
# ============================================================================

class GreenAgent(RobotAgent):
    """Robot restricted to zone z1. Collects green waste → yellow."""
    def __init__(self, unique_id, model):
        super().__init__(unique_id, model, robot_type="green")


class YellowAgent(RobotAgent):
    """Robot allowed in zones z1 + z2. Collects yellow waste → red."""
    def __init__(self, unique_id, model):
        super().__init__(unique_id, model, robot_type="yellow")


class RedAgent(RobotAgent):
    """Robot allowed in all zones. Transports red waste to disposal."""
    def __init__(self, unique_id, model):
        super().__init__(unique_id, model, robot_type="red")