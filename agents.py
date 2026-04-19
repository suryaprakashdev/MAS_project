import random
from mesa import Agent
from objects import ZONE_BOUNDS

# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
MOVE_NORTH = "move_north"
MOVE_SOUTH = "move_south"
MOVE_EAST  = "move_east"
MOVE_WEST  = "move_west"
PICK_UP    = "pick_up"
DROP       = "drop"
TRANSFORM  = "transform"
WAIT       = "wait"

MOVE_ACTIONS = {MOVE_NORTH, MOVE_SOUTH, MOVE_EAST, MOVE_WEST}

DIRECTION_DELTAS = {
    MOVE_NORTH: (0, 1),
    MOVE_SOUTH: (0, -1),
    MOVE_EAST:  (1, 0),
    MOVE_WEST:  (-1, 0),
}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOOP_WINDOW = 10
ORPHAN_THRESHOLD = 20   # steps holding 1 item before dropping at border


# ============================================================================
# Helpers
# ============================================================================

def _manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _detect_loop(k):
    history = k.get("pos_history", [])
    if len(history) < LOOP_WINDOW:
        return False
    recent = history[-LOOP_WINDOW:]
    if len(set(recent)) <= 2:
        return True
    xs = [p[0] for p in recent]
    if max(xs) - min(xs) <= 1:
        return True
    return False


def _reset_loop(k):
    """Break a detected loop by flipping sweep dirs and clearing stale data."""
    k["pos_history"] = []
    k["scan_dir_x"] = -k.get("scan_dir_x", 1)
    k["scan_dir_y"] = -k.get("scan_dir_y", 1)
    # Clear stale known-waste near current position
    pos = k["pos"]
    stale = [p for p in k.get("known_waste", {}) if _manhattan(pos, p) <= 3]
    for p in stale:
        k["known_waste"].pop(p, None)


def _move_toward(k, target):
    cx, cy = k["pos"]
    tx, ty = target
    # Red bias: prioritise east to reach disposal quickly
    if k["robot_type"] == "red" and tx > cx:
        return MOVE_EAST
    moves = []
    if tx > cx:
        moves.append(MOVE_EAST)
    elif tx < cx:
        moves.append(MOVE_WEST)
    if ty > cy:
        moves.append(MOVE_NORTH)
    elif ty < cy:
        moves.append(MOVE_SOUTH)
    return random.choice(moves) if moves else WAIT


def _sweep_step(k, x_min, x_max):
    """Lawnmower sweep: horizontal passes, step vertically at edges.

    This guarantees full coverage of the rectangular area [x_min..x_max] ×
    [0..grid_height-1] in exactly (x_max-x_min+1)*grid_height steps.
    Directions (scan_dir_x, scan_dir_y) are randomised per robot at init
    so multiple robots naturally cover different regions first.
    """
    cx, cy = k["pos"]
    grid_h = k.get("grid_height", 15)
    sdx = k.get("scan_dir_x", 1)
    sdy = k.get("scan_dir_y", 1)

    # Try horizontal move
    if sdx == 1 and cx < x_max:
        return MOVE_EAST
    if sdx == -1 and cx > x_min:
        return MOVE_WEST

    # At horizontal edge → flip, step vertically
    k["scan_dir_x"] = -sdx
    if sdy == 1 and cy < grid_h - 1:
        return MOVE_NORTH
    if sdy == -1 and cy > 0:
        return MOVE_SOUTH
    # At vertical edge → flip vertical too
    k["scan_dir_y"] = -sdy
    return MOVE_NORTH if sdy == -1 else MOVE_SOUTH


def _broadcast_visible_waste(percepts):
    """Create broadcast messages for all waste visible in percepts."""
    messages = []
    for pos, info in percepts.items():
        for wtype in info.get("wastes", []):
            messages.append({
                "_target_type": wtype,
                "waste_at": pos,
                "waste_type": wtype,
            })
    return messages


def _find_nearest_known(known_waste, pos, waste_type):
    """Return the nearest known position holding *waste_type*, or None."""
    candidates = [p for p, types in known_waste.items()
                  if waste_type in types and p != pos]
    if not candidates:
        return None
    return min(candidates, key=lambda p: _manhattan(pos, p))


# ============================================================================
# Green deliberation
# ============================================================================

def deliberate_green(k):
    inv        = k["inventory"]
    pos        = k["pos"]
    percepts   = k.get("percepts", {})
    z1_hi      = ZONE_BOUNDS["z1"][1]
    known      = k.get("known_waste", {})
    msgs       = _broadcast_visible_waste(percepts)

    if _detect_loop(k):
        _reset_loop(k)

    # --- Carrying transformed yellow → deliver to z1 east edge ---
    if "yellow" in inv:
        if pos[0] >= z1_hi:
            # Notify yellow robots about the drop location
            msgs.append({"_target_type": "yellow",
                         "waste_at": pos, "waste_type": "yellow"})
            return DROP, msgs
        return MOVE_EAST, msgs

    # 2 green in inventory → transform immediately
    if sum(1 for w in inv if w == "green") >= 2:
        return TRANSFORM, msgs

    # Green waste on current cell → pick up
    if "green" in percepts.get(pos, {}).get("wastes", []) and len(inv) < 2:
        return PICK_UP, msgs

    # Green waste visible in a neighbour → walk there
    for npos, info in percepts.items():
        if npos != pos and "green" in info.get("wastes", []):
            return _move_toward(k, npos), msgs

    # Known green waste from memory / messages → go to nearest
    if len(inv) < 2:
        target = _find_nearest_known(known, pos, "green")
        if target:
            return _move_toward(k, target), msgs

    # --- Orphan drop: holding 1 green for too long without pairing ---
    green_count = sum(1 for w in inv if w == "green")
    if green_count == 1 and k.get("steps_holding_one", 0) > ORPHAN_THRESHOLD:
        # Drop at z1 east border so orphans accumulate for recombination
        if pos[0] >= z1_hi:
            k["steps_holding_one"] = 0
            msgs.append({"_target_type": "green",
                         "waste_at": pos, "waste_type": "green"})
            return DROP, msgs
        return MOVE_EAST, msgs

    # Fallback: systematic sweep of zone 1
    return _sweep_step(k, k["zone_x_min"], z1_hi), msgs


# ============================================================================
# Yellow deliberation
# ============================================================================

def deliberate_yellow(k):
    inv        = k["inventory"]
    pos        = k["pos"]
    percepts   = k.get("percepts", {})
    z1_hi      = ZONE_BOUNDS["z1"][1]
    z2_hi      = ZONE_BOUNDS["z2"][1]
    known      = k.get("known_waste", {})
    msgs       = _broadcast_visible_waste(percepts)

    if _detect_loop(k):
        _reset_loop(k)

    # --- Carrying transformed red → deliver to z2 east edge ---
    if "red" in inv:
        if pos[0] >= z2_hi:
            # Notify red robots about the drop location
            msgs.append({"_target_type": "red",
                         "waste_at": pos, "waste_type": "red"})
            return DROP, msgs
        return MOVE_EAST, msgs

    # 2 yellow → transform immediately
    if sum(1 for w in inv if w == "yellow") >= 2:
        return TRANSFORM, msgs

    # Yellow waste on current cell → pick up
    if "yellow" in percepts.get(pos, {}).get("wastes", []) and len(inv) < 2:
        return PICK_UP, msgs

    # Yellow waste in a neighbour → walk there
    for npos, info in percepts.items():
        if npos != pos and "yellow" in info.get("wastes", []):
            return _move_toward(k, npos), msgs

    # Known yellow waste → go to nearest
    if len(inv) < 2:
        target = _find_nearest_known(known, pos, "yellow")
        if target:
            return _move_toward(k, target), msgs

    # --- Orphan drop: holding 1 yellow for too long without pairing ---
    yellow_count = sum(1 for w in inv if w == "yellow")
    if yellow_count == 1 and k.get("steps_holding_one", 0) > ORPHAN_THRESHOLD:
        # Drop at z1 east border so orphans accumulate for recombination
        if pos[0] >= z1_hi:
            k["steps_holding_one"] = 0
            msgs.append({"_target_type": "yellow",
                         "waste_at": pos, "waste_type": "yellow"})
            return DROP, msgs
        return _move_toward(k, (z1_hi, pos[1])), msgs

    # Patrol z1 east border (where green drops yellow)
    if abs(pos[0] - z1_hi) > 1:
        return _move_toward(k, (z1_hi, pos[1])), msgs
    return random.choice([MOVE_NORTH, MOVE_SOUTH]), msgs


# ============================================================================
# Red deliberation
# ============================================================================

def deliberate_red(k):
    inv        = k["inventory"]
    pos        = k["pos"]
    percepts   = k.get("percepts", {})
    z2_hi      = ZONE_BOUNDS["z2"][1]
    known      = k.get("known_waste", {})
    msgs       = _broadcast_visible_waste(percepts)

    if _detect_loop(k):
        _reset_loop(k)

    # --- Carrying red → head straight to disposal ---
    if "red" in inv:
        disposal = k.get("waste_disposal_pos")
        if disposal:
            if pos == disposal:
                return DROP, msgs
            return _move_toward(k, disposal), msgs
        return MOVE_EAST, msgs

    # Red waste on current cell → pick up
    if "red" in percepts.get(pos, {}).get("wastes", []):
        return PICK_UP, msgs

    # Red waste in a neighbour → walk there
    for npos, info in percepts.items():
        if npos != pos and "red" in info.get("wastes", []):
            return _move_toward(k, npos), msgs

    # Known red waste → go to nearest
    target = _find_nearest_known(known, pos, "red")
    if target:
        return _move_toward(k, target), msgs

    # Patrol z2 east border (where yellow drops red)
    if abs(pos[0] - z2_hi) > 1:
        return _move_toward(k, (z2_hi, pos[1])), msgs
    return random.choice([MOVE_NORTH, MOVE_SOUTH]), msgs


DELIB = {
    "green":  deliberate_green,
    "yellow": deliberate_yellow,
    "red":    deliberate_red,
}


# ============================================================================
# Base Agent
# ============================================================================

class RobotAgent(Agent):

    def __init__(self, uid, model, robot_type):
        super().__init__(uid, model)

        self.robot_type = robot_type
        self.inventory = []
        self.inbox = []

        self.zone_x_min = 0
        self.zone_x_max = 0

        self.knowledge = {}

    # ------------------------------------------------------------------
    def _init_knowledge(self):
        self.knowledge = {
            "pos":                self.pos,
            "inventory":          list(self.inventory),
            "robot_type":         self.robot_type,
            "percepts":           {},
            "pos_history":        [],
            "waste_disposal_pos": None,
            # --- new efficiency fields ---
            "known_waste":        {},                        # {pos: [types]}
            "scan_dir_x":         random.choice([1, -1]),    # randomised per robot
            "scan_dir_y":         random.choice([1, -1]),
            "grid_height":        self.model.grid.height,
            "zone_x_min":         self.zone_x_min,
            "zone_x_max":         self.zone_x_max,
        }

    # ------------------------------------------------------------------
    def _update_knowledge(self, percepts):
        k = self.knowledge

        k["pos"]       = self.pos
        k["inventory"] = list(self.inventory)
        k["percepts"]  = percepts

        # Track movement history (for loop detection)
        k["pos_history"].append(self.pos)
        if len(k["pos_history"]) > LOOP_WINDOW:
            k["pos_history"].pop(0)

        # ----- Update known waste from *direct observation* (authoritative) -----
        for pos, info in percepts.items():
            if info.get("has_disposal"):
                k["waste_disposal_pos"] = pos
            wastes = info.get("wastes", [])
            if wastes:
                k["known_waste"][pos] = list(wastes)
            else:
                # Cell visible and empty → remove stale entry
                k["known_waste"].pop(pos, None)

        # ----- Process inbox messages (remote waste info) -----
        for msg in self.inbox:
            content = msg["content"]
            if "waste_at" in content:
                wpos = content["waste_at"]
                if isinstance(wpos, list):
                    wpos = tuple(wpos)
                wtype = content["waste_type"]
                # Only add if we haven't directly observed this cell
                if wpos not in percepts:
                    existing = k["known_waste"].get(wpos, [])
                    if wtype not in existing:
                        k["known_waste"][wpos] = existing + [wtype]
        self.inbox.clear()

        # ----- Track orphan holding time -----
        collects = getattr(self, 'collects', None)
        if collects:
            count_collected = sum(1 for w in self.inventory if w == collects)
            if count_collected == 1:
                k["steps_holding_one"] = k.get("steps_holding_one", 0) + 1
            else:
                k["steps_holding_one"] = 0

    # ------------------------------------------------------------------
    def step(self):
        if not self.knowledge:
            self._init_knowledge()

        percepts = self.model.get_percepts(self)
        self._update_knowledge(percepts)

        action, messages = DELIB[self.robot_type](self.knowledge)

        # Send broadcast messages to other robots
        if messages and self.model.communication_enabled:
            for msg in messages:
                target_type = msg.pop("_target_type", None)
                self.model.broadcast_message(self, msg, target_type=target_type)

        self.model.do(self, action)


# ============================================================================
# Concrete Agent Classes
# ============================================================================

class GreenAgent(RobotAgent):
    def __init__(self, uid, model):
        super().__init__(uid, model, "green")
        self.collects = "green"
        self.max_inventory = 2
        self.transform_to = "yellow"


class YellowAgent(RobotAgent):
    def __init__(self, uid, model):
        super().__init__(uid, model, "yellow")
        self.collects = "yellow"
        self.max_inventory = 2
        self.transform_to = "red"


class RedAgent(RobotAgent):
    def __init__(self, uid, model):
        super().__init__(uid, model, "red")
        self.collects = "red"
        self.max_inventory = 1
        self.transform_to = None