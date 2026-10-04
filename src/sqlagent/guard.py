"""SQL guardrail: only a single read-only SELECT reaches the database.

Defence in depth: the guard rejects anything that is not a SELECT, and the connection itself is
opened read-only (see schema.connect_readonly).
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

FORBIDDEN_FUNCTIONS = {"load_extension", "readfile", "writefile", "fts3_tokenizer", "edit"}
MAX_ROWS = 500


@dataclass
class GuardResult:
    ok: bool
    sql: str
    reason: str = ""


def check(sql: str, max_rows: int = MAX_ROWS) -> GuardResult:
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        return GuardResult(False, sql, "empty query")
    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except sqlglot.errors.ParseError as e:
        return GuardResult(False, sql, f"syntax error: {str(e).splitlines()[0]}")
    if len(statements) != 1:
        return GuardResult(False, sql, "only one statement is allowed")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        return GuardResult(False, sql, f"only SELECT is allowed, got {tree.key.upper()}")
    for node in tree.walk():
        if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command)):
            return GuardResult(False, sql, f"write operation {node.key.upper()} is not allowed")
        if isinstance(node, exp.Anonymous) and node.name.lower() in FORBIDDEN_FUNCTIONS:
            return GuardResult(False, sql, f"function {node.name} is not allowed")
    if isinstance(tree, exp.Select) and tree.args.get("limit") is None:
        tree = tree.limit(max_rows)
    return GuardResult(True, tree.sql(dialect="sqlite"))
