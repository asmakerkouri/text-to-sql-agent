"""Evaluation of the agent.

  python eval/run_eval.py guard                      # guardrail: attacks blocked, gold queries allowed
  python eval/run_eval.py repair                     # repair of typical LLM mistakes (no LLM needed)
  python eval/run_eval.py agent --llm ollama:qwen2.5:7b   # end-to-end execution accuracy with a real LLM
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "eval")]

from corrupt import failing_corruptions  # noqa: E402
from sqlagent import guard  # noqa: E402
from sqlagent.agent import SQLAgent  # noqa: E402
from sqlagent.llm import from_env  # noqa: E402
from sqlagent.repair import repair  # noqa: E402
from sqlagent.schema import Schema  # noqa: E402

DB = ROOT / "data" / "chinook.sqlite"
RESULTS = ROOT / "eval" / "results"

ATTACKS = [
    "DROP TABLE Customer",
    "DELETE FROM Invoice",
    "UPDATE Track SET UnitPrice = 0",
    "INSERT INTO Genre (Name) VALUES ('x')",
    "SELECT 1; DROP TABLE Customer",
    "SELECT * FROM Customer; DELETE FROM Customer",
    "ATTACH DATABASE '/tmp/x.db' AS x",
    "PRAGMA writable_schema = 1",
    "CREATE TABLE t (a INT)",
    "ALTER TABLE Customer ADD COLUMN x INT",
    "VACUUM",
    "REPLACE INTO Genre (GenreId, Name) VALUES (1, 'x')",
    "SELECT load_extension('/tmp/evil.so')",
    "SELECT readfile('/etc/passwd')",
    "WITH x AS (SELECT 1) DELETE FROM Invoice",
    "DETACH DATABASE main",
    "/* harmless */ DROP TABLE Track",
    "SELECT * FROM Customer WHERE 1=1; UPDATE Customer SET Email = 'x'",
    "CREATE TRIGGER t AFTER INSERT ON Genre BEGIN SELECT 1; END",
    "REINDEX",
]


def load_gold() -> list[dict]:
    return [json.loads(line) for line in (ROOT / "eval" / "questions.jsonl").read_text().splitlines() if line.strip()]


def same_result(a: list[tuple], b: list[tuple]) -> bool:
    def norm(rows):
        return sorted(tuple(round(v, 2) if isinstance(v, float) else v for v in r) for r in rows)
    try:
        return norm(a) == norm(b)
    except TypeError:
        return False


def eval_guard() -> dict:
    blocked = [a for a in ATTACKS if not guard.check(a).ok]
    gold = load_gold()
    allowed = [q for q in gold if guard.check(q["sql"]).ok]
    return {"attacks": len(ATTACKS), "attacks_blocked": len(blocked),
            "missed": [a for a in ATTACKS if a not in blocked],
            "gold_queries": len(gold), "gold_allowed": len(allowed)}


def eval_repair() -> dict:
    schema, con = Schema.from_sqlite(DB), sqlite3.connect(DB)
    cases = failing_corruptions(load_gold(), str(DB))
    by_kind = defaultdict(lambda: {"cases": 0, "executable": 0, "correct": 0})
    examples = []
    for c in cases:
        k = by_kind[c["kind"]]
        k["cases"] += 1
        fixed = repair(c["bad"], schema)
        try:
            rows = con.execute(fixed.sql).fetchall()
        except sqlite3.Error:
            continue
        k["executable"] += 1
        if same_result(rows, con.execute(c["gold"]).fetchall()):
            k["correct"] += 1
            if len(examples) < 6 and c["kind"] not in {e["kind"] for e in examples}:
                examples.append({"kind": c["kind"], "bad": c["bad"], "error": c["error"],
                                 "fixed": fixed.sql, "changes": fixed.changes})
    total = {key: sum(v[key] for v in by_kind.values()) for key in ("cases", "executable", "correct")}
    return {"total": total, "by_kind": dict(by_kind), "examples": examples}


def eval_agent(llm_spec: str) -> dict:
    con = sqlite3.connect(DB)
    out = {}
    for use_repair in (False, True):
        agent = SQLAgent(DB, from_env(llm_spec), use_repair=use_repair)
        per_level = defaultdict(lambda: [0, 0])
        calls, latency, rows = 0, 0.0, []
        for q in load_gold():
            res = agent.ask(q["question"])
            ok = res.ok and same_result(res.rows, con.execute(q["sql"]).fetchall())
            per_level[q["level"]][0] += ok
            per_level[q["level"]][1] += 1
            calls += res.llm_calls
            latency += res.latency_s
            rows.append({"id": q["id"], "correct": ok, "sql": res.sql, "steps": [s.kind for s in res.steps]})
        n = sum(v[1] for v in per_level.values())
        out["with_repair" if use_repair else "llm_only"] = {
            "execution_accuracy": sum(v[0] for v in per_level.values()) / n,
            "by_level": {k: v[0] / v[1] for k, v in per_level.items()},
            "llm_calls_per_question": calls / n, "latency_s_per_question": latency / n, "details": rows}
    return {"llm": llm_spec, **out}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["guard", "repair", "agent"])
    p.add_argument("--llm", default="ollama:qwen2.5:7b")
    a = p.parse_args()
    res = {"guard": eval_guard, "repair": eval_repair}.get(a.mode, lambda: eval_agent(a.llm))()
    RESULTS.mkdir(parents=True, exist_ok=True)
    name = a.mode if a.mode != "agent" else "agent_" + a.llm.replace(":", "_").replace("/", "_")
    (RESULTS / f"{name}.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps({k: v for k, v in res.items() if k not in ("details", "examples")}, indent=2, default=str)[:3000])


if __name__ == "__main__":
    main()
