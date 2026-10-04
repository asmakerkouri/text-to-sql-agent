"""Figures for the README, from eval/results/*.json and the Chinook database."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"
BLUE, GREY, RED = "#1E90FF", "#C9CED6", "#E5534B"
LABELS = {"plural_table": "Plural table name\nTracks → Track", "typo_column": "Typo in column\nMiliseconds",
          "snake_case_column": "snake_case column\ninvoice_date",
          "ambiguous_column": "Ambiguous column\nName (2 tables)",
          "wrong_qualifier": "Column on wrong table\nil.Name"}


def repair_figure() -> None:
    rep = json.loads((ROOT / "eval/results/repair.json").read_text())
    grd = json.loads((ROOT / "eval/results/guard.json").read_text())
    kinds = sorted(rep["by_kind"], key=lambda k: rep["by_kind"][k]["correct"] / rep["by_kind"][k]["cases"])
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(11, 4.2), dpi=120, gridspec_kw={"width_ratios": [2.3, 1]})
    for i, k in enumerate(kinds):
        v = rep["by_kind"][k]
        pct = 100 * v["correct"] / v["cases"]
        ax.barh(i, 100, color=GREY, height=0.6)
        ax.barh(i, pct, color=BLUE, height=0.6)
        ax.text(pct - 2, i, f"{v['correct']}/{v['cases']}", va="center", ha="right", color="white", fontsize=9,
                fontweight="bold")
    ax.set_yticks(range(len(kinds)), [LABELS[k] for k in kinds], fontsize=8.5)
    ax.set_xlim(0, 100)
    ax.set_xlabel("% of failing queries fixed with the correct result")
    t = rep["total"]
    ax.set_title(f"Schema-aware repair: {t['correct']}/{t['cases']} broken queries fixed, no extra LLM call",
                 loc="left", fontsize=10.5)
    ax.spines[["top", "right"]].set_visible(False)

    vals = [grd["attacks_blocked"], grd["gold_allowed"]]
    tots = [grd["attacks"], grd["gold_queries"]]
    ax2.bar([0, 1], tots, color=GREY, width=0.55)
    ax2.bar([0, 1], vals, color=[RED, BLUE], width=0.55)
    for x, (v, n) in enumerate(zip(vals, tots, strict=True)):
        ax2.text(x, v + 0.6, f"{v}/{n}", ha="center", fontweight="bold")
    ax2.set_xticks([0, 1], ["write / injection\nattempts blocked", "valid analytical\nqueries allowed"], fontsize=8.5)
    ax2.set_title("Guardrail", loc="left", fontsize=10.5)
    ax2.spines[["top", "right"]].set_visible(False)
    ax2.set_ylim(0, max(tots) + 4)
    fig.tight_layout()
    fig.savefig(OUT / "evaluation.png")
    plt.close(fig)


def gallery() -> None:
    con = sqlite3.connect(ROOT / "data/chinook.sqlite")
    qs = {q["id"]: q for q in map(json.loads, (ROOT / "eval/questions.jsonl").read_text().splitlines())}
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), dpi=110)
    for ax, qid, kind in zip(axes.flat, [9, 19, 12, 18], ["bar", "bar", "line", "line"], strict=True):
        rows = con.execute(qs[qid]["sql"]).fetchall()
        labels, values = [str(r[0]) for r in rows], [r[-1] for r in rows]
        if kind == "bar":
            ax.barh(labels[::-1], values[::-1], color=BLUE)
            for y, v in enumerate(values[::-1]):
                ax.text(v, y, f" {v:,.0f}", va="center", fontsize=8)
        else:
            ax.plot(labels, values, color=BLUE, marker="o", lw=2)
            ax.set_xticks(range(len(labels)), [lb[-5:] for lb in labels], rotation=30, fontsize=8)
        ax.set_title(f"“{qs[qid]['question']}”", loc="left", fontsize=10)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="x" if kind == "bar" else "y", alpha=0.3)
    fig.suptitle("Charts selected automatically from the query result (bar for categories, line for time)",
                 x=0.01, ha="left", fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / "charts.png")
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    repair_figure()
    gallery()
    print("figures written to", OUT)
