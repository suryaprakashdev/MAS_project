# ============================================================================
# run.py — Simulation launcher
# ============================================================================
# Project : Robot Mission MAS 2026
# Created : March 2026
# Description: Three run modes:
#     python run.py --mode visual       → Mesa browser visualisation
#     python run.py --mode headless     → single run with stats + chart
#     python run.py --mode compare      → side-by-side comms vs no-comms
# ============================================================================

import argparse


def run_visual():
    """Launch the Mesa interactive visualisation in a web browser."""
    from server import server
    print("Starting Mesa visualisation server on http://127.0.0.1:8521")
    print("Press Ctrl+C to stop.")
    server.launch()


def run_headless(steps: int = 500, seed: int = 42, communication: bool = True):
    """Run the simulation without visualisation and produce a summary chart."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from model import RobotMission

    mode_label = "WITH" if communication else "WITHOUT"
    print(f"Running {mode_label} communication for {steps} steps (seed={seed})…")

    model = RobotMission(
        width=50, height=25,
        n_green=3, n_yellow=3, n_red=2,
        n_initial_waste=15,
        communication_enabled=communication,
        seed=seed,
    )

    for i in range(steps):
        model.step()
        if not model.running:
            print(f"  All waste disposed at step {i + 1}!")
            break

    df = model.datacollector.get_model_vars_dataframe()
    print(f"  Final: disposed={model.disposed_count}, "
          f"remaining={df['Total waste'].iloc[-1]}, "
          f"messages={model.messages_sent}")

    fig, ax = plt.subplots(figsize=(10, 5))
    df[["Green waste", "Yellow waste", "Red waste", "Disposed"]].plot(ax=ax)
    ax.set_xlabel("Step")
    ax.set_ylabel("Count")
    ax.set_title(f"Waste over time ({mode_label} communication)")
    ax.legend()
    fig.tight_layout()
    fname = f"waste_over_time_{'comms' if communication else 'no_comms'}.png"
    fig.savefig(fname, dpi=150)
    print(f"  Chart saved to {fname}")
    return df, model


def run_compare(steps: int = 500, seed: int = 42, n_runs: int = 5):
    """Compare performance with and without communication over multiple runs.

    Produces a summary table and a comparison chart, which is exactly the
    kind of metric the course asks for (messages vs. collection time).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from model import RobotMission

    results = {"no_comms": [], "comms": []}

    for run_idx in range(n_runs):
        run_seed = seed + run_idx
        for comms_on, label in [(False, "no_comms"), (True, "comms")]:
            model = RobotMission(
                width=30, height=15,
                n_green=3, n_yellow=3, n_red=2,
                n_initial_waste=15,
                communication_enabled=comms_on,
                seed=run_seed,
            )
            finished_step = steps
            for i in range(steps):
                model.step()
                if not model.running:
                    finished_step = i + 1
                    break

            results[label].append({
                "seed": run_seed,
                "steps_to_finish": finished_step,
                "disposed": model.disposed_count,
                "remaining": sum(1 for a in model.schedule.agents
                                 if hasattr(a, 'waste_type')),
                "messages": model.messages_sent,
            })

    # Print comparison table
    print("\n" + "=" * 70)
    print("COMPARISON: No Communication vs. With Communication")
    print("=" * 70)
    print(f"{'':>6}  {'--- No Comms ---':^30}  {'--- With Comms ---':^30}")
    print(f"{'Seed':>6}  {'Steps':>8} {'Disposed':>9} {'Msgs':>8}  "
          f"{'Steps':>8} {'Disposed':>9} {'Msgs':>8}")
    print("-" * 70)

    for i in range(n_runs):
        nc = results["no_comms"][i]
        wc = results["comms"][i]
        print(f"{nc['seed']:>6}  "
              f"{nc['steps_to_finish']:>8} {nc['disposed']:>9} {nc['messages']:>8}  "
              f"{wc['steps_to_finish']:>8} {wc['disposed']:>9} {wc['messages']:>8}")

    # Averages
    def avg(lst, key):
        return sum(d[key] for d in lst) / len(lst)

    print("-" * 70)
    print(f"{'AVG':>6}  "
          f"{avg(results['no_comms'], 'steps_to_finish'):>8.1f} "
          f"{avg(results['no_comms'], 'disposed'):>9.1f} "
          f"{avg(results['no_comms'], 'messages'):>8.1f}  "
          f"{avg(results['comms'], 'steps_to_finish'):>8.1f} "
          f"{avg(results['comms'], 'disposed'):>9.1f} "
          f"{avg(results['comms'], 'messages'):>8.1f}")
    print("=" * 70)

    # Comparison chart
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))

    # Steps to finish
    nc_steps = [r["steps_to_finish"] for r in results["no_comms"]]
    wc_steps = [r["steps_to_finish"] for r in results["comms"]]
    axes[0].bar(["No Comms", "With Comms"],
                [sum(nc_steps)/len(nc_steps), sum(wc_steps)/len(wc_steps)],
                color=["#dc3545", "#28a745"])
    axes[0].set_title("Avg Steps to Complete")
    axes[0].set_ylabel("Steps")

    # Disposed count
    nc_disp = [r["disposed"] for r in results["no_comms"]]
    wc_disp = [r["disposed"] for r in results["comms"]]
    axes[1].bar(["No Comms", "With Comms"],
                [sum(nc_disp)/len(nc_disp), sum(wc_disp)/len(wc_disp)],
                color=["#dc3545", "#28a745"])
    axes[1].set_title("Avg Waste Disposed")
    axes[1].set_ylabel("Count")

    # Messages (trade-off)
    nc_msgs = [r["messages"] for r in results["no_comms"]]
    wc_msgs = [r["messages"] for r in results["comms"]]
    axes[2].bar(["No Comms", "With Comms"],
                [sum(nc_msgs)/len(nc_msgs), sum(wc_msgs)/len(wc_msgs)],
                color=["#dc3545", "#28a745"])
    axes[2].set_title("Avg Messages Sent")
    axes[2].set_ylabel("Messages")

    fig.suptitle(f"Communication Impact ({n_runs} runs, {steps} max steps)", fontsize=14)
    fig.tight_layout()
    fig.savefig("comparison_comms_vs_no_comms.png", dpi=150)
    print("\nComparison chart saved to comparison_comms_vs_no_comms.png")


def main():
    parser = argparse.ArgumentParser(description="Robot Mission MAS 2026")
    parser.add_argument(
        "--mode", choices=["visual", "headless", "compare"], default="visual",
        help="'visual' for browser UI, 'headless' for single run, 'compare' for benchmark",
    )
    parser.add_argument("--steps", type=int, default=500, help="Max steps per run")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--runs", type=int, default=5, help="Number of runs for compare mode")
    parser.add_argument(
        "--no-comms", action="store_true",
        help="Disable communication in headless mode",
    )
    args = parser.parse_args()

    if args.mode == "visual":
        run_visual()
    elif args.mode == "headless":
        run_headless(steps=args.steps, seed=args.seed, communication=not args.no_comms)
    elif args.mode == "compare":
        run_compare(steps=args.steps, seed=args.seed, n_runs=args.runs)


if __name__ == "__main__":
    main()
