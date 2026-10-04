"""Text-to-SQL agent: generate -> guard -> execute -> repair / self-correct -> chart.

    question ──► LLM writes SQL ──► guard (read-only, single SELECT, LIMIT)
                     ▲                    │ rejected: reason sent back to the LLM
                     │                    ▼
                     │               execute (read-only connection)
                     │                    │ SQLite error
                     │                    ▼
                     │          schema-aware repair (no LLM call)
                     │                    │ still failing
                     └── error message ◄──┘          (max_attempts)
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import guard
from .llm import LLM
from .repair import repair
from .schema import Schema, connect_readonly

SYSTEM = """You are a senior data analyst. Write ONE SQLite SELECT query that answers the question.
Use only the tables and columns of this schema:
{schema}
Rules: read-only SELECT, no comments, use explicit JOINs, round money to 2 decimals.
Answer with the query only, inside a ```sql block."""

FEEDBACK = """The query failed.
Query:
```sql
{sql}
```
Error: {error}
Fix the query. Answer with the corrected query only, inside a ```sql block."""


@dataclass
class Step:
    kind: str  # generate | guard_reject | sql_error | repair | retry | ok
    sql: str
    detail: str = ""


@dataclass
class AgentResult:
    question: str
    sql: str | None
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    llm_calls: int = 0
    latency_s: float = 0.0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def extract_sql(text: str) -> str:
    m = re.search(r"```(?:sql)?\s*(.+?)```", text, flags=re.S | re.I)
    return (m.group(1) if m else text).strip().rstrip(";")


class SQLAgent:
    def __init__(self, db_path: str | Path, llm: LLM, max_attempts: int = 3, use_repair: bool = True):
        self.db_path = Path(db_path)
        self.schema = Schema.from_sqlite(db_path)
        self.llm = llm
        self.max_attempts = max_attempts
        self.use_repair = use_repair
        self.con = connect_readonly(db_path)

    def _execute(self, sql: str) -> tuple[list[str], list[tuple]]:
        cur = self.con.execute(sql)
        return [d[0] for d in cur.description], cur.fetchall()

    def _try(self, sql: str, res: AgentResult) -> str | None:
        """Guard + execute (+ repair). Returns an error message, or None on success."""
        g = guard.check(sql)
        if not g.ok:
            res.steps.append(Step("guard_reject", sql, g.reason))
            return f"rejected by the guardrail: {g.reason}"
        try:
            res.columns, res.rows = self._execute(g.sql)
            res.sql = g.sql
            return None
        except sqlite3.Error as e:
            err = str(e)
            res.steps.append(Step("sql_error", g.sql, err))
        if self.use_repair:
            fixed = repair(g.sql, self.schema)
            if fixed.changed:
                res.steps.append(Step("repair", fixed.sql, "; ".join(fixed.changes)))
                try:
                    res.columns, res.rows = self._execute(fixed.sql)
                    res.sql = fixed.sql
                    return None
                except sqlite3.Error as e:
                    err = str(e)
                    res.steps.append(Step("sql_error", fixed.sql, err))
        return err

    def ask(self, question: str) -> AgentResult:
        t0 = time.perf_counter()
        res = AgentResult(question, None)
        messages = [{"role": "system", "content": SYSTEM.format(schema=self.schema.to_prompt())},
                    {"role": "user", "content": question}]
        for attempt in range(self.max_attempts):
            answer = self.llm.complete(messages)
            res.llm_calls += 1
            sql = extract_sql(answer)
            res.steps.append(Step("generate" if attempt == 0 else "retry", sql))
            error = self._try(sql, res)
            if error is None:
                res.steps.append(Step("ok", res.sql, f"{len(res.rows)} rows"))
                break
            messages += [{"role": "assistant", "content": answer},
                         {"role": "user", "content": FEEDBACK.format(sql=sql, error=error)}]
        else:
            res.error = f"no valid query after {self.max_attempts} attempts"
        res.latency_s = time.perf_counter() - t0
        return res
