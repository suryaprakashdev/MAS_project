# ============================================================================
# server.py — Mesa visualisation server
# ============================================================================
# Project : Robot Mission MAS 2026
# Created : March 2026
# Description: Configures the Mesa ModularServer with a CanvasGrid and
#              a chart showing waste counts over time.
# ============================================================================

from mesa.visualization.modules import CanvasGrid, ChartModule
from mesa.visualization.ModularVisualization import ModularServer
from mesa.visualization.UserParam import Slider, Checkbox

from model import RobotMission
from objects import Radioactivity, Waste, WasteDisposal
from agents import RobotAgent


# ---------------------------------------------------------------------------
# Portrayal function — how each agent is drawn on the canvas
# ---------------------------------------------------------------------------

# Zone background colours (light tints)
ZONE_COLORS = {
    "z1": "#d4edda",   # light green
    "z2": "#fff3cd",   # light yellow
    "z3": "#f8d7da",   # light red / pink
}

# Waste dot colours
WASTE_COLORS = {
    "green":  "#28a745", 
    "yellow": "#ffc107", 
    "red":    "#dc3545",
}

# Robot shapes & colours
ROBOT_PORTRAYAL = {
    "green":  {"Color": "#155724", "Shape": "circle", "r": 0.7},
    "yellow": {"Color": "#856404", "Shape": "circle", "r": 0.7},
    "red":    {"Color": "#721c24", "Shape": "circle", "r": 0.7},
}


def agent_portrayal(agent):
    """Return a dict telling Mesa's CanvasGrid how to render *agent*."""

    # --- Radioactivity background ---
    if isinstance(agent, Radioactivity):
        return {
            "Shape": "rect",
            "Filled": "true",
            "w": 1, "h": 1,
            "Color": ZONE_COLORS.get(agent.zone, "#ffffff"),
            "Layer": 0,
        }

    # --- Waste disposal zone ---
    if isinstance(agent, WasteDisposal):
        return {
            "Shape": "rect",
            "Filled": "true",
            "w": 1, "h": 1,
            "Color": "#6c757d",
            "Layer": 1,
            "text": "DISP",
            "text_color": "white",
        }

    # --- Waste items ---
    if isinstance(agent, Waste):
        color = WASTE_COLORS.get(agent.waste_type, "gray")
        return {
            "Shape": "circle",
            "Filled": "true",
            "r": 0.3,
            "Color": color,
            "Layer": 2,
        }

    # --- Robot agents ---
    if isinstance(agent, RobotAgent):
        p = ROBOT_PORTRAYAL.get(agent.robot_type, {})
        inv_label = ",".join(w[0].upper() for w in agent.inventory) if agent.inventory else ""
        return {
            "Shape": p.get("Shape", "circle"),
            "Filled": "true",
            "r": p.get("r", 0.6),
            "Color": p.get("Color", "black"),
            "Layer": 3,
            "text": inv_label,
            "text_color": "white",
        }

    return {}


# ---------------------------------------------------------------------------
# Server configuration
# ---------------------------------------------------------------------------

GRID_W, GRID_H = 30, 15
CELL_PX = 30  # pixels per cell

canvas = CanvasGrid(agent_portrayal, GRID_W, GRID_H, GRID_W * CELL_PX, GRID_H * CELL_PX)

waste_chart = ChartModule(
    [
        {"Label": "Green waste",  "Color": "#28a745"},
        {"Label": "Yellow waste", "Color": "#ffc107"},
        {"Label": "Red waste",    "Color": "#dc3545"},
        {"Label": "Total waste",  "Color": "#007bff"},
        {"Label": "Disposed",     "Color": "#6c757d"},
    ],
    data_collector_name="datacollector",
)

message_chart = ChartModule(
    [
        {"Label": "Messages", "Color": "#17a2b8"},
    ],
    data_collector_name="datacollector",
)

model_params = {
    "width":  GRID_W,
    "height": GRID_H,
    "n_green":  Slider("Green robots",  3, 1, 10, 1),
    "n_yellow": Slider("Yellow robots", 3, 1, 10, 1),
    "n_red":    Slider("Red robots",    2, 1, 10, 1),
    "n_initial_waste": Slider("Initial green waste", 15, 5, 50, 1),
    "communication_enabled": Checkbox("Communication enabled", value=True),
}

server = ModularServer(
    RobotMission,
    [canvas, waste_chart, message_chart],
    "Robot Mission – Radioactive Waste Cleanup",
    model_params,
)

server.port = 8521  # default Mesa port

if __name__ == "__main__":
    server.launch()
