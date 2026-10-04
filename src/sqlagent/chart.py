"""Pick a chart for a query result: line for time series, horizontal bar for categories."""

from __future__ import annotations

import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

DATE_RE = re.compile(r"^\d{4}(-\d{2})?(-\d{2})?")
COLOR = "#1E90FF"


def suggest(columns: list[str], rows: list[tuple]) -> str | None:
    """'line', 'bar' or None when the result is not chartable (1 row, no numeric column...)."""
    if len(rows) < 2 or len(columns) < 2:
        return None
    label, value = [r[0] for r in rows], [r[-1] for r in rows]
    if not all(isinstance(v, (int, float)) for v in value):
        return None
    if all(isinstance(x, str) and DATE_RE.match(x) for x in label):
        return "line"
    return "bar" if len(rows) <= 25 else None


def render(columns: list[str], rows: list[tuple], title: str, path: str | Path, kind: str | None = None) -> Path | None:
    kind = kind or suggest(columns, rows)
    if kind is None:
        return None
    labels, values = [str(r[0]) for r in rows], [r[-1] for r in rows]
    fig, ax = plt.subplots(figsize=(7, 4), dpi=110)
    if kind == "line":
        ax.plot(labels, values, color=COLOR, marker="o", lw=2, ms=3)
        step = max(1, len(labels) // 8)
        ax.set_xticks(range(0, len(labels), step), labels[::step], rotation=30, ha="right")
        ax.set_ylabel(columns[-1])
    else:
        ax.barh(labels[::-1], values[::-1], color=COLOR)
        ax.set_xlabel(columns[-1])
    ax.set_title(title, fontsize=11, loc="left")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x" if kind == "bar" else "y", alpha=0.3)
    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path
