"""Inject the SQL mistakes LLMs typically make into correct (gold) queries.

Each corruption keeps the intent of the query but makes SQLite fail, like a real LLM error:
  plural_table      Track -> Tracks
  snake_case_column InvoiceDate -> invoice_date
  typo_column       Milliseconds -> Miliseconds
  wrong_qualifier   g.Name where the column belongs to another joined table (t.Composer -> g.Composer)
  ambiguous_column  t.Name -> Name when several joined tables have a Name column
"""

from __future__ import annotations

import random
import re
import sqlite3

import sqlglot
from sqlglot import exp

from sqlagent.schema import Schema


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _typo(name: str, rng: random.Random) -> str:
    i = rng.randrange(1, len(name) - 1)
    return name[:i] + name[i + 1:]


def corruptions(sql: str, schema: Schema, rng: random.Random) -> dict[str, str]:
    out: dict[str, str] = {}
    tree = sqlglot.parse_one(sql, read="sqlite")
    tables = list(tree.find_all(exp.Table))
    cols = [c for c in tree.find_all(exp.Column) if not isinstance(c.this, exp.Star)]

    if tables:
        t2 = tree.copy()
        t = rng.choice(list(t2.find_all(exp.Table)))
        t.set("this", exp.to_identifier(t.name + "s"))
        out["plural_table"] = t2.sql(dialect="sqlite")

    camel = [i for i, c in enumerate(cols) if _snake(c.name) != c.name.lower()]
    if camel:
        t2 = tree.copy()
        c = [c for c in t2.find_all(exp.Column) if not isinstance(c.this, exp.Star)][rng.choice(camel)]
        c.set("this", exp.to_identifier(_snake(c.name)))
        out["snake_case_column"] = t2.sql(dialect="sqlite")

    long_cols = [i for i, c in enumerate(cols) if len(c.name) >= 6]
    if long_cols:
        t2 = tree.copy()
        c = [c for c in t2.find_all(exp.Column) if not isinstance(c.this, exp.Star)][rng.choice(long_cols)]
        c.set("this", exp.to_identifier(_typo(c.name, rng)))
        out["typo_column"] = t2.sql(dialect="sqlite")

    aliases = {t.alias_or_name: schema.table(t.name).name for t in tables if schema.table(t.name)}
    if len(aliases) >= 2:
        for i, c in enumerate(cols):
            if not c.table:
                continue
            others = [a for a, tn in aliases.items() if a != c.table and c.name not in schema.tables[tn].columns]
            if others:
                t2 = tree.copy()
                cc = [c for c in t2.find_all(exp.Column) if not isinstance(c.this, exp.Star)][i]
                cc.set("table", exp.to_identifier(rng.choice(others)))
                out["wrong_qualifier"] = t2.sql(dialect="sqlite")
                break
        for i, c in enumerate(cols):
            owners = [a for a, tn in aliases.items() if c.name in schema.tables[tn].columns]
            if c.table and len(owners) > 1 and owners[0] == c.table:
                t2 = tree.copy()
                cc = [c for c in t2.find_all(exp.Column) if not isinstance(c.this, exp.Star)][i]
                cc.set("table", None)
                out["ambiguous_column"] = t2.sql(dialect="sqlite")
                break
    return out


def failing_corruptions(gold: list[dict], db: str, seed: int = 0) -> list[dict]:
    """All corruptions of all gold queries that really make SQLite fail."""
    schema, con, rng = Schema.from_sqlite(db), sqlite3.connect(db), random.Random(seed)
    cases = []
    for q in gold:
        for kind, bad in corruptions(q["sql"], schema, rng).items():
            try:
                con.execute(bad).fetchall()
            except sqlite3.Error as e:
                cases.append({"id": q["id"], "kind": kind, "gold": q["sql"], "bad": bad, "error": str(e)})
    return cases
