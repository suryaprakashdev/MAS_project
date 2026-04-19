"""
generate_plots.py — Generate all comparison plots for the README report.

Run:  python generate_plots.py   (or .venv/bin/python generate_plots.py)
Outputs saved to plots/ directory.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import os

from model import RobotMission
from agents import RobotAgent
from objects import Waste

# ---------- Style ----------
plt.rcParams.update({
    "figure.facecolor": "#0d1117",
    "axes.facecolor":   "#161b22",
    "axes.edgecolor":   "#30363d",
    "axes.labelcolor":  "#c9d1d9",
    "text.color":       "#c9d1d9",
    "xtick.color":      "#8b949e",
    "ytick.color":      "#8b949e",
    "grid.color":       "#21262d",
    "legend.facecolor": "#161b22",
    "legend.edgecolor": "#30363d",
    "font.family":      "sans-serif",
    "font.size":        11,
})

COLORS = {
    "green":  "#3fb950",
    "yellow": "#d29922",
    "red":    "#f85149",
    "blue":   "#58a6ff",
    "purple": "#bc8cff",
    "grey":   "#8b949e",
}

os.makedirs("plots", exist_ok=True)

# =====================================================================
# Plot 1: Waste Over Time (single run with comms)
# =====================================================================
print("Generating Plot 1: Waste over time ...")

model = RobotMission(width=30, height=15, n_green=4, n_yellow=3, n_red=2,
                     n_initial_waste=25, communication_enabled=True, seed=42)
for _ in range(500):
    model.step()
    if not model.running:
        break

df = model.datacollector.get_model_vars_dataframe()

fig, ax = plt.subplots(figsize=(10, 5))
ax.plot(df.index, df["Green waste"],  color=COLORS["green"],  linewidth=2, label="Green waste")
ax.plot(df.index, df["Yellow waste"], color=COLORS["yellow"], linewidth=2, label="Yellow waste")
ax.plot(df.index, df["Red waste"],    color=COLORS["red"],    linewidth=2, label="Red waste")
ax.plot(df.index, df["Total waste"],  color=COLORS["blue"],   linewidth=2, label="Total waste", linestyle="--")
ax.plot(df.index, df["Disposed"],     color=COLORS["purple"], linewidth=2, label="Disposed")
ax.set_xlabel("Step")
ax.set_ylabel("Count")
ax.set_title("Waste Processing Over Time (With Communication)", fontsize=14, fontweight="bold")
ax.legend(loc="center right")
ax.grid(True, alpha=0.3)
fig.tight_layout()
fig.savefig("plots/waste_over_time.png", dpi=150)
plt.close(fig)
print("  → plots/waste_over_time.png")

# =====================================================================
# Plot 2: Communication vs No-Communication — Steps comparison
# =====================================================================
print("Generating Plot 2: Communication comparison ...")

N_RUNS = 10
results = {"comms": {"steps": [], "disposed": [], "msgs": []},
           "no_comms": {"steps": [], "disposed": [], "msgs": []}}

for seed in range(1, N_RUNS + 1):
    for comms_on, label in [(True, "comms"), (False, "no_comms")]:
        m = RobotMission(width=30, height=15, n_green=4, n_yellow=3, n_red=2,
                         n_initial_waste=25, communication_enabled=comms_on, seed=seed)
        for step in range(1000):
            m.step()
            if not m.running:
                break
        results[label]["steps"].append(step + 1)
        results[label]["disposed"].append(m.disposed_count)
        results[label]["msgs"].append(m.messages_sent)

fig, axes = plt.subplots(1, 3, figsize=(15, 5))

# --- Bar chart: Avg Steps ---
ax = axes[0]
means = [np.mean(results["no_comms"]["steps"]), np.mean(results["comms"]["steps"])]
bars = ax.bar(["Without\nCommunication", "With\nCommunication"], means,
              color=[COLORS["red"], COLORS["green"]], width=0.5, edgecolor="#30363d")
for bar, val in zip(bars, means):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 10,
            f"{val:.0f}", ha="center", va="bottom", fontweight="bold", fontsize=13)
ax.set_ylabel("Average Steps")
ax.set_title("Steps to Complete", fontsize=13, fontweight="bold")
ax.grid(axis="y", alpha=0.3)

# --- Bar chart: Avg Disposed ---
ax = axes[1]
means = [np.mean(results["no_comms"]["disposed"]), np.mean(results["comms"]["disposed"])]
bars = ax.bar(["Without\nCommunication", "With\nCommunication"], means,
              color=[COLORS["red"], COLORS["green"]], width=0.5, edgecolor="#30363d")
for bar, val in zip(bars, means):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.05,
            f"{val:.1f}", ha="center", va="bottom", fontweight="bold", fontsize=13)
ax.set_ylabel("Average Disposed")
ax.set_title("Waste Disposed", fontsize=13, fontweight="bold")
ax.grid(axis="y", alpha=0.3)

# --- Bar chart: Messages ---
ax = axes[2]
means = [np.mean(results["no_comms"]["msgs"]), np.mean(results["comms"]["msgs"])]
bars = ax.bar(["Without\nCommunication", "With\nCommunication"], means,
              color=[COLORS["red"], COLORS["green"]], width=0.5, edgecolor="#30363d")
for bar, val in zip(bars, means):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 10,
            f"{val:.0f}", ha="center", va="bottom", fontweight="bold", fontsize=13)
ax.set_ylabel("Average Messages")
ax.set_title("Messages Sent", fontsize=13, fontweight="bold")
ax.grid(axis="y", alpha=0.3)

fig.suptitle("Communication Impact — 4G 3Y 2R, 25 Waste (10 runs)",
             fontsize=15, fontweight="bold", y=1.02)
fig.tight_layout()
fig.savefig("plots/comms_comparison.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print("  → plots/comms_comparison.png")

# =====================================================================
# Plot 3: Per-run step breakdown (scatter / strip plot)
# =====================================================================
print("Generating Plot 3: Per-run step scatter ...")

fig, ax = plt.subplots(figsize=(8, 5))
seeds = list(range(1, N_RUNS + 1))
ax.scatter(seeds, results["no_comms"]["steps"], color=COLORS["red"],
           s=100, zorder=3, label="Without Comms", edgecolors="#30363d", linewidth=1)
ax.scatter(seeds, results["comms"]["steps"], color=COLORS["green"],
           s=100, zorder=3, label="With Comms", edgecolors="#30363d", linewidth=1)

ax.axhline(np.mean(results["no_comms"]["steps"]), color=COLORS["red"],
           linestyle="--", alpha=0.6, label=f"Avg no-comms ({np.mean(results['no_comms']['steps']):.0f})")
ax.axhline(np.mean(results["comms"]["steps"]), color=COLORS["green"],
           linestyle="--", alpha=0.6, label=f"Avg comms ({np.mean(results['comms']['steps']):.0f})")

ax.set_xlabel("Run (seed)")
ax.set_ylabel("Steps to Complete")
ax.set_title("Steps Per Run — With vs Without Communication", fontsize=13, fontweight="bold")
ax.legend()
ax.grid(True, alpha=0.3)
ax.xaxis.set_major_locator(ticker.MultipleLocator(1))
fig.tight_layout()
fig.savefig("plots/steps_per_run.png", dpi=150)
plt.close(fig)
print("  → plots/steps_per_run.png")

# =====================================================================
# Plot 4: Waste over time — side by side (comms vs no-comms)
# =====================================================================
print("Generating Plot 4: Waste timeline comparison ...")

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5), sharey=True)

for ax, comms_on, title in [(ax1, False, "Without Communication"),
                             (ax2, True, "With Communication")]:
    m = RobotMission(width=30, height=15, n_green=4, n_yellow=3, n_red=2,
                     n_initial_waste=25, communication_enabled=comms_on, seed=99)
    for _ in range(1000):
        m.step()
        if not m.running:
            break
    d = m.datacollector.get_model_vars_dataframe()

    ax.plot(d.index, d["Green waste"],  color=COLORS["green"],  linewidth=2, label="Green")
    ax.plot(d.index, d["Yellow waste"], color=COLORS["yellow"], linewidth=2, label="Yellow")
    ax.plot(d.index, d["Red waste"],    color=COLORS["red"],    linewidth=2, label="Red")
    ax.plot(d.index, d["Disposed"],     color=COLORS["purple"], linewidth=2, label="Disposed")
    ax.set_xlabel("Step")
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.legend(loc="center right")
    ax.grid(True, alpha=0.3)

ax1.set_ylabel("Count")
fig.suptitle("Waste Timeline — Same Seed, Different Communication Settings",
             fontsize=14, fontweight="bold")
fig.tight_layout()
fig.savefig("plots/timeline_comparison.png", dpi=150)
plt.close(fig)
print("  → plots/timeline_comparison.png")

# =====================================================================
# Plot 5: Scalability — different robot/waste configs
# =====================================================================
print("Generating Plot 5: Scalability across configs ...")

configs = [
    ("3G 3Y 2R\n15 waste",  3, 3, 2, 15),
    ("4G 3Y 2R\n25 waste",  4, 3, 2, 25),
    ("5G 4Y 3R\n27 waste",  5, 4, 3, 27),
]

config_labels = []
avg_steps_list = []
avg_disp_list = []

for label, ng, ny, nr, nw in configs:
    steps_all, disp_all = [], []
    for seed in range(1, 11):
        m = RobotMission(width=30, height=15, n_green=ng, n_yellow=ny, n_red=nr,
                         n_initial_waste=nw, communication_enabled=True, seed=seed)
        for step in range(1000):
            m.step()
            if not m.running:
                break
        steps_all.append(step + 1)
        disp_all.append(m.disposed_count)
    config_labels.append(label)
    avg_steps_list.append(np.mean(steps_all))
    avg_disp_list.append(np.mean(disp_all))

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

bars = ax1.bar(config_labels, avg_steps_list,
               color=[COLORS["green"], COLORS["blue"], COLORS["purple"]],
               width=0.5, edgecolor="#30363d")
for bar, val in zip(bars, avg_steps_list):
    ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 5,
             f"{val:.0f}", ha="center", va="bottom", fontweight="bold", fontsize=12)
ax1.set_ylabel("Average Steps")
ax1.set_title("Steps to Complete", fontsize=13, fontweight="bold")
ax1.grid(axis="y", alpha=0.3)

bars = ax2.bar(config_labels, avg_disp_list,
               color=[COLORS["green"], COLORS["blue"], COLORS["purple"]],
               width=0.5, edgecolor="#30363d")
for bar, val in zip(bars, avg_disp_list):
    ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.05,
             f"{val:.1f}", ha="center", va="bottom", fontweight="bold", fontsize=12)
ax2.set_ylabel("Average Disposed")
ax2.set_title("Waste Disposed", fontsize=13, fontweight="bold")
ax2.grid(axis="y", alpha=0.3)

fig.suptitle("Performance Across Different Configurations (10 runs each)",
             fontsize=14, fontweight="bold")
fig.tight_layout()
fig.savefig("plots/scalability.png", dpi=150)
plt.close(fig)
print("  → plots/scalability.png")

print("\n✅ All plots saved to plots/ directory.")
