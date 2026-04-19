

import random
from mesa import Model
from mesa.space import MultiGrid
from mesa.time import RandomActivation
from mesa.datacollection import DataCollector

from objects import (
    Radioactivity, Waste, WasteDisposal,
    ZONE_BOUNDS, configure_zone_bounds, get_zone_for_x,
)
from agents import (
    GreenAgent, YellowAgent, RedAgent, RobotAgent,
    MOVE_ACTIONS, DIRECTION_DELTAS,
    MOVE_NORTH, MOVE_SOUTH, MOVE_EAST, MOVE_WEST,
    PICK_UP, DROP, TRANSFORM, WAIT,
)

# ---------------------------------------------------------------------------
# Stuck-robot watchdog threshold (steps at the same cell before intervention)
# ---------------------------------------------------------------------------
STUCK_THRESHOLD = 20


# ---------------------------------------------------------------------------
# Data-collector helper functions
# ---------------------------------------------------------------------------
def count_green_waste(model):
    return sum(1 for a in model.schedule.agents
               if isinstance(a, Waste) and a.waste_type == "green")

def count_yellow_waste(model):
    return sum(1 for a in model.schedule.agents
               if isinstance(a, Waste) and a.waste_type == "yellow")

def count_red_waste(model):
    return sum(1 for a in model.schedule.agents
               if isinstance(a, Waste) and a.waste_type == "red")

def count_disposed(model):
    return model.disposed_count

def count_total_waste(model):
    return sum(1 for a in model.schedule.agents if isinstance(a, Waste))

def count_messages_sent(model):
    return model.messages_sent

def count_stuck_interventions(model):
    """Total number of times the model intervened to un-stick a robot."""
    return model.stuck_interventions


# ============================================================================
# The Model
# ============================================================================

class RobotMission(Model):
    """Multi-agent simulation of robots collecting radioactive waste.

    Parameters
    ----------
    width, height : int
        Grid dimensions.  Width is split into 3 equal zones (west → east).
    n_green, n_yellow, n_red : int
        Number of each robot type.
    n_initial_waste : int
        Number of green waste items placed randomly in zone z1 at start.
    communication_enabled : bool
        Whether the communication protocol is active.
    seed : int or None
        Random seed for reproducibility.
    """

    def __init__(
        self,
        width: int = 30,
        height: int = 15,
        n_green: int = 3,
        n_yellow: int = 3,
        n_red: int = 2,
        n_initial_waste: int = 15,
        communication_enabled: bool = True,
        seed=None,
    ):
        super().__init__()
        if seed is not None:
            random.seed(seed)

        self.grid = MultiGrid(width, height, torus=False)
        self.schedule = RandomActivation(self)
        self._next_id = 0
        self.running = True
        self.communication_enabled = communication_enabled

        # Metrics
        self.disposed_count      = 0
        self.messages_sent       = 0
        self.current_step        = 0
        self.stuck_interventions = 0   # how many times watchdog fired

        # Stuck-robot tracking: uid → (last_pos, consecutive_stuck_steps)
        self._robot_stuck_counter: dict = {}

        # Configure shared zone boundaries
        configure_zone_bounds(width)

        # ---- 1. Place radioactivity on every cell ----
        self._place_radioactivity()

        # ---- 2. Place waste disposal zone (eastern edge) ----
        self.disposal_pos = self._place_waste_disposal()

        # ---- 3. Place initial green waste in zone z1 ----
        self._place_initial_waste(n_initial_waste)

        # ---- 4. Place robot agents ----
        self._place_robots(n_green, n_yellow, n_red)

        # ---- 5. Data collector ----
        self.datacollector = DataCollector(
            model_reporters={
                "Green waste":         count_green_waste,
                "Yellow waste":        count_yellow_waste,
                "Red waste":           count_red_waste,
                "Total waste":         count_total_waste,
                "Disposed":            count_disposed,
                "Messages":            count_messages_sent,
                "Stuck interventions": count_stuck_interventions,
            }
        )

    # ------------------------------------------------------------------
    # ID generator
    # ------------------------------------------------------------------
    def _get_next_id(self) -> int:
        uid = self._next_id
        self._next_id += 1
        return uid

    # ------------------------------------------------------------------
    # Initialization helpers
    # ------------------------------------------------------------------
    def _place_radioactivity(self):
        """Put a Radioactivity marker on every cell with zone-appropriate level."""
        for x in range(self.grid.width):
            zone = get_zone_for_x(x)
            for y in range(self.grid.height):
                if zone == "z1":
                    level = random.uniform(0, 0.33)
                elif zone == "z2":
                    level = random.uniform(0.33, 0.66)
                else:
                    level = random.uniform(0.66, 1.0)
                rad = Radioactivity(self._get_next_id(), self, zone, level)
                self.grid.place_agent(rad, (x, y))

    def _place_waste_disposal(self) -> tuple:
        """Place the WasteDisposal agent on a random cell in the easternmost column."""
        east_x = self.grid.width - 1
        y = random.randint(0, self.grid.height - 1)
        wd = WasteDisposal(self._get_next_id(), self)
        self.grid.place_agent(wd, (east_x, y))
        return (east_x, y)

    def _place_initial_waste(self, n: int):
        """Place n green waste items randomly in zone z1."""
        z1_lo, z1_hi = ZONE_BOUNDS["z1"]
        for _ in range(n):
            x = random.randint(z1_lo, z1_hi)
            y = random.randint(0, self.grid.height - 1)
            w = Waste(self._get_next_id(), self, "green")
            self.grid.place_agent(w, (x, y))
            self.schedule.add(w)

    def _place_robots(self, n_green: int, n_yellow: int, n_red: int):
        """Create and place robots, setting their zone movement limits."""
        z1_lo, z1_hi = ZONE_BOUNDS["z1"]
        z2_lo, z2_hi = ZONE_BOUNDS["z2"]
        z3_lo, z3_hi = ZONE_BOUNDS["z3"]

        def place(agent_cls, count, x_min, x_max, start_zone_bounds):
            for _ in range(count):
                a = agent_cls(self._get_next_id(), self)
                a.zone_x_min = x_min
                a.zone_x_max = x_max
                sx = random.randint(start_zone_bounds[0], start_zone_bounds[1])
                sy = random.randint(0, self.grid.height - 1)
                self.grid.place_agent(a, (sx, sy))
                # Init knowledge immediately so model can inject disposal pos
                a._init_knowledge()
                self.schedule.add(a)

        place(GreenAgent, n_green, z1_lo, z1_hi, (z1_lo, z1_hi))
        place(YellowAgent, n_yellow, z1_lo, z2_hi, (z1_lo, z2_hi))
        place(RedAgent, n_red, z1_lo, z3_hi, (z1_lo, z3_hi))

        # Inject disposal pos into every red robot's knowledge right away.
        # This avoids a cold-start where red robots wander east searching for
        # the disposal zone instead of heading directly there.
        self.broadcast_disposal_pos()

    # ==================================================================
    # Percepts — what the agent can "see" around it
    # ==================================================================
    def get_percepts(self, agent: RobotAgent) -> dict:
        """Return a dict mapping nearby positions to their visible contents.

        The agent sees its own cell plus the 4 cardinal neighbours.
        Each entry: { 'wastes', 'robots', 'zone', 'radioactivity', 'has_disposal' }
        """
        percepts = {}
        x, y = agent.pos
        positions = [(x, y)]
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = x + dx, y + dy
            if 0 <= nx < self.grid.width and 0 <= ny < self.grid.height:
                positions.append((nx, ny))

        for pos in positions:
            cell_agents = self.grid.get_cell_list_contents([pos])
            wastes       = [a.waste_type  for a in cell_agents if isinstance(a, Waste)]
            robots       = [a.robot_type  for a in cell_agents
                            if isinstance(a, RobotAgent) and a is not agent]
            zone         = "z1"
            rad_level    = 0.0
            has_disposal = False
            for a in cell_agents:
                if isinstance(a, Radioactivity):
                    zone      = a.zone
                    rad_level = a.level
                if isinstance(a, WasteDisposal):
                    has_disposal = True

            percepts[pos] = {
                "wastes":        wastes,
                "robots":        robots,
                "zone":          zone,
                "radioactivity": rad_level,
                "has_disposal":  has_disposal,
            }
        return percepts

    # ==================================================================
    # do() — execute an agent's chosen action
    # ==================================================================
    def do(self, agent: RobotAgent, action: str) -> dict:
        """Validate and execute *action* for *agent*, return new percepts."""
        if action in MOVE_ACTIONS:
            self._do_move(agent, action)
        elif action == PICK_UP:
            self._do_pick_up(agent)
        elif action == DROP:
            self._do_drop(agent)
        elif action == TRANSFORM:
            self._do_transform(agent)
        elif action == WAIT:
            pass

        return self.get_percepts(agent)

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------
    def _do_move(self, agent: RobotAgent, action: str):
        dx, dy = DIRECTION_DELTAS[action]
        new_x = agent.pos[0] + dx
        new_y = agent.pos[1] + dy

        if not (0 <= new_x < self.grid.width and 0 <= new_y < self.grid.height):
            return
        if not (agent.zone_x_min <= new_x <= agent.zone_x_max):
            return

        self.grid.move_agent(agent, (new_x, new_y))

    def _do_pick_up(self, agent: RobotAgent):
        if len(agent.inventory) >= agent.max_inventory:
            return

        cell_agents = self.grid.get_cell_list_contents([agent.pos])
        for a in cell_agents:
            if isinstance(a, Waste) and a.waste_type == agent.collects:
                agent.inventory.append(a.waste_type)
                self.grid.remove_agent(a)
                self.schedule.remove(a)
                return

    def _do_drop(self, agent: RobotAgent):
        """Drop waste at current position.
        """
        if not agent.inventory:
            return

        if agent.robot_type == "red":
            # Authoritative check: does THIS cell have a disposal zone?
            cell_agents = self.grid.get_cell_list_contents([agent.pos])
            at_disposal = any(isinstance(a, WasteDisposal) for a in cell_agents)
            if not at_disposal:
                return
            if "red" in agent.inventory:
                agent.inventory.remove("red")
                self.disposed_count += 1
                # Correct agent knowledge in case it stored a wrong disposal pos
                if agent.knowledge:
                    agent.knowledge["waste_disposal_pos"] = agent.pos
            return

        # Green / yellow: prefer dropping transformed waste.
        # Fallback: drop collected‑type waste (orphan recombination).
        drop_type = agent.transform_to
        if not (drop_type and drop_type in agent.inventory):
            # No transformed waste to drop → try orphan drop (collected type)
            drop_type = agent.collects if agent.collects in agent.inventory else None

        if drop_type and drop_type in agent.inventory:
            agent.inventory.remove(drop_type)
            new_waste = Waste(self._get_next_id(), self, drop_type)
            self.grid.place_agent(new_waste, agent.pos)
            self.schedule.add(new_waste)

    def _do_transform(self, agent: RobotAgent):
        if agent.transform_to is None:
            return

        source = agent.collects
        count  = sum(1 for w in agent.inventory if w == source)
        if count < 2:
            return

        removed = 0
        new_inv = []
        for w in agent.inventory:
            if w == source and removed < 2:
                removed += 1
            else:
                new_inv.append(w)
        new_inv.append(agent.transform_to)
        agent.inventory = new_inv

    # ==================================================================
    # Communication support
    # ==================================================================
    def send_message(self, sender: RobotAgent, receiver: RobotAgent, message: dict):
        receiver.inbox.append({
            "from":      sender.unique_id,
            "from_type": sender.robot_type,
            "content":   message,
        })
        self.messages_sent += 1

    def broadcast_message(self, sender: RobotAgent, message: dict, target_type: str = None):
        for a in self.schedule.agents:
            if isinstance(a, RobotAgent) and a is not sender:
                if target_type is None or a.robot_type == target_type:
                    self.send_message(sender, a, message)

    def broadcast_disposal_pos(self):
        for a in self.schedule.agents:
            if isinstance(a, RedAgent) and a.knowledge:
                a.knowledge["waste_disposal_pos"] = self.disposal_pos

    # ==================================================================
    # Stuck-robot watchdog
    # ==================================================================
    def _check_stuck_robots(self):
        for agent in self.schedule.agents:
            if not isinstance(agent, RobotAgent):
                continue

            uid = agent.unique_id
            last_pos, stuck_count = self._robot_stuck_counter.get(uid, (None, 0))

            if agent.pos == last_pos:
                stuck_count += 1
            else:
                stuck_count = 0

            self._robot_stuck_counter[uid] = (agent.pos, stuck_count)

            if stuck_count < STUCK_THRESHOLD:
                continue

            # ---- Intervention ----
            self.stuck_interventions += 1
            self._robot_stuck_counter[uid] = (agent.pos, 0)  # reset counter

            k = agent.knowledge
            if not k:
                continue

            # 1. Flip sweep directions so robot takes a new exploration path
            k["scan_dir_x"] = -k.get("scan_dir_x", 1)
            k["scan_dir_y"] = -k.get("scan_dir_y", 1)
            k["pos_history"] = []

            # 2. Clear stale waste entries near current cell
            stale = [p for p in k.get("known_waste", {})
                     if abs(p[0] - agent.pos[0]) + abs(p[1] - agent.pos[1]) <= 3]
            for p in stale:
                k["known_waste"].pop(p, None)

            # 3. For red robots carrying waste: re-inject the correct disposal pos
            if agent.robot_type == "red" and "red" in agent.inventory:
                k["waste_disposal_pos"] = self.disposal_pos

    # ==================================================================
    # Model step
    # ==================================================================
    def step(self):
        """Advance the simulation by one tick."""
        self.datacollector.collect(self)
        self.schedule.step()
        self.current_step += 1

        # Stuck-robot watchdog — runs every step, O(n_robots)
        self._check_stuck_robots()

        # Stop when all waste is gone AND no robot is still carrying items
        if count_total_waste(self) == 0:
            any_inv = any(a.inventory for a in self.schedule.agents
                         if isinstance(a, RobotAgent))
            if not any_inv:
                self.running = False
                return

        # Deadlock detection: delayed start (step 100) and coarse interval
        # (every 50 steps) so robots have time to drop orphan items at the
        # border for recombination before the model gives up.
        if self.current_step >= 100 and self.current_step % 50 == 0:
            if self._is_deadlocked():
                self.running = False

    def _is_deadlocked(self) -> bool:
        on_grid: dict = {"green": 0, "yellow": 0, "red": 0}
        for a in self.schedule.agents:
            if isinstance(a, Waste):
                on_grid[a.waste_type] += 1

        in_inv: dict = {"green": 0, "yellow": 0, "red": 0}
        for a in self.schedule.agents:
            if isinstance(a, RobotAgent):
                for w in a.inventory:
                    in_inv[w] += 1

        total_green  = on_grid["green"]  + in_inv["green"]
        total_yellow = on_grid["yellow"] + in_inv["yellow"]
        total_red    = on_grid["red"]    + in_inv["red"]

        # Nothing left anywhere → truly done (stop condition handles this too)
        if total_green + total_yellow + total_red == 0:
            return True

        effective_yellow = total_yellow + (total_green // 2)
        can_dispose = total_red > 0 or effective_yellow >= 2
        return not can_dispose
