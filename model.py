# ============================================================================
# model.py — RobotMission simulation model
# ============================================================================
# Project : Robot Mission MAS 2026
# Created : March 2026
# Description: Sets up the grid, places radioactivity / waste / robots,
#              implements the do() method that executes agent actions, and
#              collects data for analysis.
# ============================================================================

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
    """Cumulative messages sent (for Step 2 communication metrics)."""
    return model.messages_sent


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
        self.disposed_count = 0
        self.messages_sent = 0
        self.current_step = 0

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
                "Green waste":  count_green_waste,
                "Yellow waste": count_yellow_waste,
                "Red waste":    count_red_waste,
                "Total waste":  count_total_waste,
                "Disposed":     count_disposed,
                "Messages":     count_messages_sent,
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
                # Radioactivity agents don't need scheduling (no step)

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
            self.schedule.add(w)  # added so DataCollector can iterate

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
                # Start inside allowed zone
                sx = random.randint(start_zone_bounds[0], start_zone_bounds[1])
                sy = random.randint(0, self.grid.height - 1)
                self.grid.place_agent(a, (sx, sy))
                self.schedule.add(a)

        # Green robots: restricted to z1
        place(GreenAgent, n_green, z1_lo, z1_hi, (z1_lo, z1_hi))

        # Yellow robots: zones z1 + z2
        place(YellowAgent, n_yellow, z1_lo, z2_hi, (z1_lo, z2_hi))

        # Red robots: all zones z1 + z2 + z3
        place(RedAgent, n_red, z1_lo, z3_hi, (z1_lo, z3_hi))

    # ==================================================================
    # Percepts — what the agent can "see" around it
    # ==================================================================
    def get_percepts(self, agent: RobotAgent) -> dict:
        """Return a dict mapping nearby positions to their visible contents.

        The agent sees its own cell plus the 4 cardinal neighbours.
        Each entry is: { 'wastes': [list of waste types],
                         'robots': [list of robot types],
                         'zone': str,
                         'radioactivity': float,
                         'has_disposal': bool }
        """
        percepts = {}
        x, y = agent.pos
        # Own cell + 4 neighbours
        positions = [(x, y)]
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = x + dx, y + dy
            if 0 <= nx < self.grid.width and 0 <= ny < self.grid.height:
                positions.append((nx, ny))

        for pos in positions:
            cell_agents = self.grid.get_cell_list_contents([pos])
            wastes = [a.waste_type for a in cell_agents if isinstance(a, Waste)]
            robots = [a.robot_type for a in cell_agents
                      if isinstance(a, RobotAgent) and a is not agent]
            zone = "z1"
            rad_level = 0.0
            has_disposal = False
            for a in cell_agents:
                if isinstance(a, Radioactivity):
                    zone = a.zone
                    rad_level = a.level
                if isinstance(a, WasteDisposal):
                    has_disposal = True

            percepts[pos] = {
                "wastes": wastes,
                "robots": robots,
                "zone": zone,
                "radioactivity": rad_level,
                "has_disposal": has_disposal,
            }
        return percepts

    # ==================================================================
    # do() — execute an agent's chosen action
    # ==================================================================
    def do(self, agent: RobotAgent, action: str) -> dict:
        """Validate and execute *action* for *agent*, return new percepts.

        The model is the authority: even if the agent *thinks* an action is
        valid, the model may reject it (e.g. moving outside allowed zone).
        """

        if action in MOVE_ACTIONS:
            self._do_move(agent, action)

        elif action == PICK_UP:
            self._do_pick_up(agent)

        elif action == DROP:
            self._do_drop(agent)

        elif action == TRANSFORM:
            self._do_transform(agent)

        elif action == WAIT:
            pass  # do nothing

        # Return fresh percepts after the action
        return self.get_percepts(agent)

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------
    def _do_move(self, agent: RobotAgent, action: str):
        """Move the agent one cell in the given direction if feasible."""
        dx, dy = DIRECTION_DELTAS[action]
        new_x = agent.pos[0] + dx
        new_y = agent.pos[1] + dy

        # Check grid boundaries
        if not (0 <= new_x < self.grid.width and 0 <= new_y < self.grid.height):
            return  # blocked by wall

        # Check zone restrictions
        if not (agent.zone_x_min <= new_x <= agent.zone_x_max):
            return  # not allowed in that zone

        self.grid.move_agent(agent, (new_x, new_y))

    def _do_pick_up(self, agent: RobotAgent):
        """Pick up one waste of the type this robot collects, if present."""
        if len(agent.inventory) >= agent.max_inventory:
            return  # inventory full

        cell_agents = self.grid.get_cell_list_contents([agent.pos])
        for a in cell_agents:
            if isinstance(a, Waste) and a.waste_type == agent.collects:
                # Remove waste from grid and schedule
                agent.inventory.append(a.waste_type)
                self.grid.remove_agent(a)
                self.schedule.remove(a)
                return  # pick up one at a time

    def _do_drop(self, agent: RobotAgent):
        """Drop the transformed/collected waste at the current position.

        Green robot drops yellow waste; yellow drops red; red drops at disposal.
        """
        if not agent.inventory:
            return

        if agent.robot_type == "red":
            # Red robot must be at disposal zone
            if agent.pos != self.disposal_pos:
                return
            if "red" in agent.inventory:
                agent.inventory.remove("red")
                self.disposed_count += 1
                return

        # Green/yellow robots drop their transformed waste
        drop_type = agent.transform_to  # yellow for green-robot, red for yellow-robot
        if drop_type and drop_type in agent.inventory:
            agent.inventory.remove(drop_type)
            new_waste = Waste(self._get_next_id(), self, drop_type)
            self.grid.place_agent(new_waste, agent.pos)
            self.schedule.add(new_waste)

    def _do_transform(self, agent: RobotAgent):
        """Transform collected waste into the next tier.

        Green: 2 green → 1 yellow (stays in inventory)
        Yellow: 2 yellow → 1 red (stays in inventory)
        Red: no transform ability.
        """
        if agent.transform_to is None:
            return  # red robots can't transform

        source = agent.collects  # "green" for green-robot, etc.
        count = sum(1 for w in agent.inventory if w == source)
        if count < 2:
            return  # not enough waste to transform

        # Remove 2 source wastes, add 1 transformed waste
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
    # Communication support (Step 2)
    # ==================================================================
    def send_message(self, sender: RobotAgent, receiver: RobotAgent, message: dict):
        """Deliver a message from sender to receiver's inbox.

        Messages are dictionaries — their structure is up to the agents.
        Example: {'type': 'waste_found', 'waste_type': 'yellow', 'pos': (5, 3)}
        """
        receiver.inbox.append({
            "from": sender.unique_id,
            "from_type": sender.robot_type,
            "content": message,
        })
        self.messages_sent += 1

    def broadcast_message(self, sender: RobotAgent, message: dict, target_type: str = None):
        """Send a message to all robots (optionally filtered by type)."""
        for a in self.schedule.agents:
            if isinstance(a, RobotAgent) and a is not sender:
                if target_type is None or a.robot_type == target_type:
                    self.send_message(sender, a, message)

    # ==================================================================
    # Model step
    # ==================================================================
    def step(self):
        """Advance the simulation by one tick."""
        self.datacollector.collect(self)
        self.schedule.step()
        self.current_step += 1

        # Optional: stop when all waste is disposed
        total = count_total_waste(self)
        if total == 0:
            self.running = False