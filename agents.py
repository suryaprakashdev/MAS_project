# ============================================================================
# agents.py — Robot agents with percept → deliberate → do architecture
# ============================================================================
# Project : Robot Mission MAS 2026
# Created : March 2026
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
CLAIM_EXPIRY_STEPS = 15   # claims older than this are automatically released

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

    - has_partial_inventory: True if the robot already holds >=1 waste of its
      collecting type. This bot is one pickup from a transform → top priority.
    - -manhattan_distance: closer robots rank higher (negative so bigger = closer).
    - agent_id: deterministic tiebreaker.
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
        return _random_walk(knowledge)

    best_dist = max(c[0] for c in candidates)
    best = [c[1] for c in candidates if c[0] == best_dist]
    return random.choice(best)


def _random_walk(knowledge: dict) -> str:
    """Return a random move that stays within the agent's allowed zone."""
    cx, cy = knowledge["pos"]
    min_x = knowledge["zone_x_min"]
    max_x = knowledge["zone_x_max"]
    grid_h = knowledge["grid_height"]

    options = []
    if cx + 1 <= max_x:
        options.append(MOVE_EAST)
    if cx - 1 >= min_x:
        options.append(MOVE_WEST)
    if cy + 1 < grid_h:
        options.append(MOVE_NORTH)
    if cy - 1 >= 0:
        options.append(MOVE_SOUTH)

    return random.choice(options) if options else WAIT


def _find_nearest_unclaimed_waste(knowledge: dict, waste_type: str):
    """Return (pos, priority) for the best available waste, or (None, None).

    A waste is "available" if either:
      - nobody has claimed it, OR
      - our priority for it beats the current claimer's priority
    """
    my_pos = knowledge["pos"]
    others_claims = knowledge.get("others_claims", {})
    best_pos, best_priority = None, None

    for loc, wtype in knowledge["known_waste_positions"].items():
        if wtype != waste_type:
            continue

        my_priority = _calc_priority(knowledge, loc)

        # Skip if someone else has a higher-or-equal priority claim
        existing = others_claims.get(loc)
        if existing is not None and tuple(existing["priority"]) >= my_priority:
            continue

        # Among available wastes, prefer the closest one
        if best_pos is None or _manhattan(my_pos, loc) < _manhattan(my_pos, best_pos):
            best_pos = loc
            best_priority = my_priority

    return best_pos, best_priority


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

            # Keep the highest-priority claim we know about per position
            existing = knowledge["others_claims"].get(pos)
            if existing is None or their_priority > tuple(existing["priority"]):
                knowledge["others_claims"][pos] = {
                    "claimer_id": their_id,
                    "priority": their_priority,
                    "step": step,
                }

            # If they outrank me for something I claimed → release my claim
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
            "_target_type": wtype,   # route to matching robot type
            "type": "waste_found",
            "waste_type": wtype,
            "pos": list(pos),
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

    # 5. Random walk
    return _random_walk(knowledge), outgoing


def deliberate_yellow(knowledge: dict) -> tuple:
    """Yellow robot: collect yellow waste, transform to red, drop at z2 border."""
    outgoing = _deliberate_preamble(knowledge)
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

    return _random_walk(knowledge), outgoing


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

    return _random_walk(knowledge), outgoing


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
    """Base class for all robots.

    The step follows the mandated architecture:
        update(knowledge, percepts)
        (action, msgs) = deliberate(knowledge)   [pure function]
        percepts = model.do(self, action)
        send msgs via model                       [side effect in step]
    """

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
            "percepts": {},
            "known_waste_positions": {},
            "waste_disposal_pos": None,
            "messages": [],
            "step_count": 0,
            "communication_enabled": getattr(self.model, "communication_enabled", False),
            # Communication state
            "my_claims": {},
            "others_claims": {},
            "current_target": None,
            "new_discoveries": [],
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
                # Clean up stale claims for empty cells
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
