"""python -m sqlagent.cli "Which 5 countries generate the most revenue?" --llm ollama:qwen2.5:7b"""

from __future__ import annotations

import argparse

from .agent import SQLAgent
from .chart import render
from .llm import from_env


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("question")
    p.add_argument("--db", default="data/chinook.sqlite")
    p.add_argument("--llm", default="ollama:qwen2.5:7b")
    p.add_argument("--chart", default="output/chart.png")
    a = p.parse_args()

    res = SQLAgent(a.db, from_env(a.llm)).ask(a.question)
    for s in res.steps:
        print(f"[{s.kind:>12}] {s.detail}\n{s.sql}\n")
    if not res.ok:
        raise SystemExit(res.error)
    print(" | ".join(res.columns))
    for r in res.rows[:20]:
        print(" | ".join(map(str, r)))
    if render(res.columns, res.rows, a.question, a.chart):
        print(f"\nchart saved to {a.chart}")


if __name__ == "__main__":
    main()
