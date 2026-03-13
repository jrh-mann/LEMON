"""Generate evaluation charts from eval log files.

Usage:
    python -m eval.plot                          # all logs
    python -m eval.plot eval/logs/summary_*.csv  # specific summary CSV
    python -m eval.plot --log-dir eval/logs      # specific log directory

Produces:
    eval/plots/scores_by_model.png       — grouped bar chart (mean ± std per model)
    eval/plots/dimensions_heatmap.png    — heatmap of all dimensions × model × sample
    eval/plots/functional_vs_structural.png — scatter: structural avg vs functional
    eval/plots/cost_vs_score.png         — cost vs overall score per model
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import matplotlib
matplotlib.use("Agg")  # non-interactive backend
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

# Score dimensions in display order.
DIMENSIONS = ["variables", "nodes", "topology", "conditions", "outputs", "functional"]
DIM_LABELS = ["Vars", "Nodes", "Topo", "Cond", "Out", "Func"]

# Model display order and colours.
MODEL_ORDER = ["haiku", "sonnet", "opus", "gpt54", "gpt_oss", "deepseek"]
MODEL_COLOURS = {
    "haiku": "#6BAED6", "sonnet": "#2171B5", "opus": "#08306B",
    "gpt54": "#2CA02C", "gpt_oss": "#FF7F0E", "deepseek": "#D62728",
}


def load_results(log_dir: Path) -> List[Dict[str, Any]]:
    """Load all eval result JSON files from a directory.

    Only includes results that have all 6 scoring dimensions (i.e. were scored
    with the current scorer that includes functional scoring).
    """
    results = []
    for path in sorted(log_dir.glob("*.json")):
        if path.name.startswith("summary"):
            continue
        try:
            data = json.loads(path.read_text())
            scores = data.get("scores")
            # Skip results without scores or without functional dimension.
            if not scores or "score_functional" not in scores:
                continue
            results.append(data)
        except (json.JSONDecodeError, KeyError):
            continue
    return results


def _group_by_model(results: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group results by model name."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in results:
        model = r["model"]
        groups.setdefault(model, []).append(r)
    return groups


def _group_by_model_sample(
    results: List[Dict[str, Any]],
) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    """Group results by (model, sample_name)."""
    groups: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for r in results:
        model = r["model"]
        sample = r["sample_name"]
        groups.setdefault(model, {}).setdefault(sample, []).append(r)
    return groups


# ---------------------------------------------------------------------------
# Chart 1: Overall score by model (bar chart with error bars)
# ---------------------------------------------------------------------------


def plot_scores_by_model(results: List[Dict[str, Any]], out_path: Path) -> None:
    """Grouped bar chart: mean overall score ± std per model, broken down by sample."""
    grouped = _group_by_model_sample(results)
    models = [m for m in MODEL_ORDER if m in grouped]
    if not models:
        return

    # Collect all sample names in consistent order.
    all_samples = sorted({r["sample_name"] for r in results})

    fig, ax = plt.subplots(figsize=(10, 6))
    x = np.arange(len(models))
    n_samples = len(all_samples)
    width = 0.8 / max(n_samples, 1)

    # Sample colours.
    sample_cmap = plt.cm.Set2
    sample_colours = [sample_cmap(i / max(n_samples - 1, 1)) for i in range(n_samples)]

    for i, sample in enumerate(all_samples):
        means, stds = [], []
        for model in models:
            runs = grouped.get(model, {}).get(sample, [])
            scores = [r["scores"]["score_overall"] for r in runs]
            means.append(np.mean(scores) if scores else 0)
            stds.append(np.std(scores) if len(scores) > 1 else 0)
        offset = (i - n_samples / 2 + 0.5) * width
        bars = ax.bar(
            x + offset, means, width, yerr=stds,
            label=sample.replace("_", " ").title(),
            color=sample_colours[i], edgecolor="white", capsize=3,
        )
        # Annotate mean values on bars.
        for bar, mean in zip(bars, means):
            if mean > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                    f"{mean:.0%}", ha="center", va="bottom", fontsize=8,
                )

    # Model-level average line.
    for j, model in enumerate(models):
        all_scores = [r["scores"]["score_overall"] for r in grouped.get(model, {}).values() for r in r]
        # Flatten properly.
        flat_scores = []
        for sample_runs in grouped.get(model, {}).values():
            for r in sample_runs:
                flat_scores.append(r["scores"]["score_overall"])
        if flat_scores:
            avg = np.mean(flat_scores)
            ax.hlines(avg, j - 0.4, j + 0.4, colors="red", linewidth=2, linestyle="--")
            ax.text(j + 0.42, avg, f"avg {avg:.0%}", va="center", fontsize=9, color="red")

    ax.set_xticks(x)
    ax.set_xticklabels([m.title() for m in models])
    ax.set_ylabel("Overall Score")
    ax.set_title("LEMON Eval: Overall Score by Model")
    ax.set_ylim(0, 1.1)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out_path}")


# ---------------------------------------------------------------------------
# Chart 2: Dimension heatmap
# ---------------------------------------------------------------------------


def plot_dimensions_heatmap(results: List[Dict[str, Any]], out_path: Path) -> None:
    """Heatmap: rows = (model, sample), columns = scoring dimensions."""
    grouped = _group_by_model_sample(results)
    models = [m for m in MODEL_ORDER if m in grouped]
    if not models:
        return
    all_samples = sorted({r["sample_name"] for r in results})

    # Build matrix: rows = (model, sample), cols = dimensions.
    row_labels = []
    data_matrix = []
    for model in models:
        for sample in all_samples:
            runs = grouped.get(model, {}).get(sample, [])
            if not runs:
                continue
            row_labels.append(f"{model} / {sample.replace('_', ' ')}")
            means = []
            for dim in DIMENSIONS:
                vals = [r["scores"][f"score_{dim}"] for r in runs]
                means.append(np.mean(vals))
            data_matrix.append(means)

    if not data_matrix:
        return

    matrix = np.array(data_matrix)
    fig, ax = plt.subplots(figsize=(10, max(4, len(row_labels) * 0.5 + 1)))
    im = ax.imshow(matrix, cmap="RdYlGn", vmin=0, vmax=1, aspect="auto")

    ax.set_xticks(np.arange(len(DIMENSIONS)))
    ax.set_xticklabels(DIM_LABELS, fontsize=10)
    ax.set_yticks(np.arange(len(row_labels)))
    ax.set_yticklabels(row_labels, fontsize=9)

    # Annotate cells with values.
    for i in range(len(row_labels)):
        for j in range(len(DIMENSIONS)):
            val = matrix[i, j]
            colour = "white" if val < 0.4 or val > 0.8 else "black"
            ax.text(j, i, f"{val:.0%}", ha="center", va="center", fontsize=9, color=colour)

    ax.set_title("LEMON Eval: Score Dimensions (mean across runs)")
    fig.colorbar(im, ax=ax, shrink=0.8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out_path}")


# ---------------------------------------------------------------------------
# Chart 3: Functional vs structural scatter
# ---------------------------------------------------------------------------


def plot_functional_vs_structural(results: List[Dict[str, Any]], out_path: Path) -> None:
    """Scatter plot: structural avg (vars+nodes+topo+cond+out) vs functional score."""
    fig, ax = plt.subplots(figsize=(8, 6))

    for r in results:
        s = r["scores"]
        structural = np.mean([s["score_variables"], s["score_nodes"], s["score_topology"],
                              s["score_conditions"], s["score_outputs"]])
        functional = s["score_functional"]
        model = r["model"]
        colour = MODEL_COLOURS.get(model, "grey")
        ax.scatter(structural, functional, c=colour, s=60, alpha=0.7, edgecolors="white",
                   label=model.title())

    # De-duplicate legend.
    handles, labels = ax.get_legend_handles_labels()
    unique = dict(zip(labels, handles))
    ax.legend(unique.values(), unique.keys(), loc="lower right")

    ax.set_xlabel("Structural Score (avg of 5 dimensions)")
    ax.set_ylabel("Functional Score")
    ax.set_title("Structural vs Functional Accuracy")
    ax.set_xlim(0, 1.05)
    ax.set_ylim(0, 1.05)
    # Diagonal reference line.
    ax.plot([0, 1], [0, 1], "k--", alpha=0.2)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out_path}")


# ---------------------------------------------------------------------------
# Chart 4: Cost vs score
# ---------------------------------------------------------------------------


def plot_cost_vs_score(results: List[Dict[str, Any]], out_path: Path) -> None:
    """Scatter plot: cost (USD) vs overall score, sized by wall time."""
    fig, ax = plt.subplots(figsize=(8, 6))

    for r in results:
        cost = r["cost_usd"]
        score = r["scores"]["score_overall"]
        wall = r["wall_time_s"]
        model = r["model"]
        colour = MODEL_COLOURS.get(model, "grey")
        # Size proportional to wall time (scaled for visibility).
        size = max(20, wall / 20)
        ax.scatter(cost, score, c=colour, s=size, alpha=0.7, edgecolors="white",
                   label=model.title())

    handles, labels = ax.get_legend_handles_labels()
    unique = dict(zip(labels, handles))
    ax.legend(unique.values(), unique.keys(), loc="lower right")

    ax.set_xlabel("Cost (USD)")
    ax.set_ylabel("Overall Score")
    ax.set_title("Cost vs Score (bubble size = wall time)")
    ax.set_ylim(0, 1.05)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out_path}")


# ---------------------------------------------------------------------------
# Chart 5: Pareto frontier — cost vs score per model (aggregated)
# ---------------------------------------------------------------------------


def plot_pareto(results: List[Dict[str, Any]], out_path: Path) -> None:
    """Pareto frontier: mean cost vs mean score per model.

    Each model is a single point (mean across all successful runs).
    The Pareto frontier connects models where no other model achieves
    a better score at the same or lower cost.
    """
    grouped = _group_by_model(results)
    models = [m for m in MODEL_ORDER if m in grouped]
    if not models:
        return

    fig, ax = plt.subplots(figsize=(9, 6))

    # Compute mean cost and score per model.
    points = []  # (cost, score, model)
    for model in models:
        runs = grouped[model]
        costs = [r["cost_usd"] for r in runs]
        scores = [r["scores"]["score_overall"] for r in runs]
        mean_cost = np.mean(costs)
        mean_score = np.mean(scores)
        std_cost = np.std(costs) if len(costs) > 1 else 0
        std_score = np.std(scores) if len(scores) > 1 else 0
        points.append((mean_cost, mean_score, std_cost, std_score, model))

        # Plot individual runs as small dots.
        colour = MODEL_COLOURS.get(model, "grey")
        ax.scatter(costs, scores, c=colour, s=25, alpha=0.3, edgecolors="none")

        # Plot mean as large marker with error bars.
        ax.errorbar(
            mean_cost, mean_score,
            xerr=std_cost, yerr=std_score,
            fmt="o", markersize=12, color=colour,
            ecolor=colour, elinewidth=1.5, capsize=4,
            label=f"{model.title()} ({mean_score:.0%}, ${mean_cost:.2f})",
            zorder=5,
        )

    # Compute and draw Pareto frontier.
    # Sort by cost ascending; a point is Pareto-optimal if no other point
    # has both lower cost AND higher score.
    sorted_pts = sorted(points, key=lambda p: p[0])
    frontier = []
    best_score = -1
    for cost, score, _, _, model in sorted_pts:
        if score > best_score:
            frontier.append((cost, score, model))
            best_score = score

    if len(frontier) >= 2:
        fx = [p[0] for p in frontier]
        fy = [p[1] for p in frontier]
        ax.plot(fx, fy, "k--", alpha=0.4, linewidth=1.5, label="Pareto frontier")

    # Annotate frontier models.
    for cost, score, model in frontier:
        ax.annotate(
            f" {model.title()}", (cost, score),
            fontsize=9, fontweight="bold",
            xytext=(8, -4), textcoords="offset points",
        )

    ax.set_xlabel("Mean Cost per Run (USD)", fontsize=11)
    ax.set_ylabel("Mean Overall Score", fontsize=11)
    ax.set_title("LEMON Eval: Cost–Accuracy Pareto Frontier", fontsize=13)
    ax.set_ylim(0, 1.05)
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_PLOT_DIR = Path(__file__).resolve().parent / "plots"


def generate_all(log_dir: Path, plot_dir: Path = _PLOT_DIR) -> None:
    """Load results and generate all charts."""
    results = load_results(log_dir)
    if not results:
        print("No scored results found.")
        return

    print(f"Loaded {len(results)} scored results from {log_dir}")
    plot_dir.mkdir(parents=True, exist_ok=True)

    plot_scores_by_model(results, plot_dir / "scores_by_model.png")
    plot_dimensions_heatmap(results, plot_dir / "dimensions_heatmap.png")
    plot_functional_vs_structural(results, plot_dir / "functional_vs_structural.png")
    plot_cost_vs_score(results, plot_dir / "cost_vs_score.png")
    plot_pareto(results, plot_dir / "pareto.png")

    print(f"\nAll plots saved to {plot_dir}/")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate LEMON eval charts")
    parser.add_argument(
        "--log-dir", type=str,
        default=str(Path(__file__).resolve().parent / "logs"),
        help="Directory containing eval JSON logs",
    )
    parser.add_argument(
        "--plot-dir", type=str,
        default=str(_PLOT_DIR),
        help="Output directory for charts",
    )
    args = parser.parse_args()
    generate_all(Path(args.log_dir), Path(args.plot_dir))


if __name__ == "__main__":
    main()
