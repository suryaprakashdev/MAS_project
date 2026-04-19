# ============================================================================
# objects.py — Non-behavioral entities placed on the grid
# ============================================================================
# Project : Robot Mission MAS 2026
# Created : March 2026
# Description: Defines passive grid objects — radioactivity markers, waste
#              items, and the waste-disposal zone. None of these have a step()
#              method; they only carry attributes that robot agents read.
# ============================================================================

from mesa import Agent


# ---------------------------------------------------------------------------
# Constants for zone boundaries (column ranges, inclusive)
# ---------------------------------------------------------------------------
# These are set once by the model at startup via configure_zone_bounds().
ZONE_BOUNDS = {
    "z1": (0, 0),   # will be overwritten
    "z2": (0, 0),
    "z3": (0, 0),
}


def configure_zone_bounds(grid_width: int) -> None:
    """Split the grid into three equal vertical zones (west → east).

    Called once by the model at init time so every module shares the
    same boundaries without hard-coding magic numbers.
    """
    third = grid_width // 3
    ZONE_BOUNDS["z1"] = (0, third - 1)
    ZONE_BOUNDS["z2"] = (third, 2 * third - 1)
    ZONE_BOUNDS["z3"] = (2 * third, grid_width - 1)


def get_zone_for_x(x: int) -> str:
    """Return the zone name ('z1', 'z2', 'z3') for a given x-coordinate."""
    for zone_name, (lo, hi) in ZONE_BOUNDS.items():
        if lo <= x <= hi:
            return zone_name
    return "z3"  # fallback: rightmost


# ---------------------------------------------------------------------------
# Radioactivity — one per cell, marks zone + radioactivity level
# ---------------------------------------------------------------------------
class Radioactivity(Agent):
    """A passive marker placed on every grid cell.

    Attributes
    ----------
    zone : str
        Which zone this cell belongs to ('z1', 'z2', or 'z3').
    level : float
        Radioactivity intensity, sampled uniformly within the zone's band:
          z1 → [0, 0.33)   z2 → [0.33, 0.66)   z3 → [0.66, 1.0]
    """

    def __init__(self, unique_id, model, zone: str, level: float):
        super().__init__(unique_id, model)
        self.zone = zone
        self.level = level
        self.agent_type = "radioactivity"

    # No step — this agent is purely informational.


# ---------------------------------------------------------------------------
# Waste — collectable objects that robots pick up / transform / deposit
# ---------------------------------------------------------------------------
class Waste(Agent):
    """A waste item sitting on the grid.

    Attributes
    ----------
    waste_type : str
        One of 'green', 'yellow', or 'red'.
    """

    def __init__(self, unique_id, model, waste_type: str):
        super().__init__(unique_id, model)
        if waste_type not in ("green", "yellow", "red"):
            raise ValueError(f"Unknown waste type: {waste_type}")
        self.waste_type = waste_type
        self.agent_type = "waste"

    # No step — waste is passive.


# ---------------------------------------------------------------------------
# WasteDisposal — the final destination for fully-transformed (red) waste
# ---------------------------------------------------------------------------
class WasteDisposal(Agent):
    """Marks a single cell on the eastern edge as the disposal zone.

    Red robots that reach this cell with a red waste can deposit it here,
    completing the waste lifecycle.
    """

    def __init__(self, unique_id, model):
        super().__init__(unique_id, model)
        self.agent_type = "waste_disposal"

    # No step — the disposal zone is passive.
