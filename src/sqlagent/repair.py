"""Schema-aware SQL repair.

LLMs often produce SQL that is almost right: a pluralised table name (`Tracks`), a snake_case
column (`invoice_date`), a column taken from the wrong joined table, or an ambiguous unqualified
column. These errors are fixed deterministically from the schema, without another LLM call.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from .schema import Schema


@dataclass
class Repair:
    sql: str
    changes: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.changes)


def _norm(name: str) -> str:
    """invoice_date, InvoiceDate, invoicedates -> invoicedate"""
    n = re.sub(r"[^a-z0-9]", "", name.lower())
    return n[:-1] if n.endswith("s") and len(n) > 3 else n


def _closest(name: str, candidates: list[str], cutoff: float = 0.75) -> str | None:
    by_norm = {_norm(c): c for c in candidates}
    if _norm(name) in by_norm:
        return by_norm[_norm(name)]
    match = difflib.get_close_matches(_norm(name), list(by_norm), n=1, cutoff=cutoff)
    return by_norm[match[0]] if match else None


def repair(sql: str, schema: Schema) -> Repair:
    try:
        tree = sqlglot.parse_one(sql, read="sqlite")
    except sqlglot.errors.ParseError:
        return Repair(sql)
    changes: list[str] = []
    table_names = list(schema.tables)
    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}

    # 1. tables
    for t in tree.find_all(exp.Table):
        if t.name.lower() in cte_names or schema.table(t.name):
            continue
        fix = _closest(t.name, table_names)
        if fix:
            changes.append(f"table {t.name} -> {fix}")
            t.set("this", exp.to_identifier(fix))

    # 2. columns, resolved in the scope of their own SELECT (subqueries have their own tables)
    for col in list(tree.find_all(exp.Column)):
        if isinstance(col.this, exp.Star):
            continue
        select = col.find_ancestor(exp.Select)
        if select is None:
            continue
        aliases = _scope_aliases(select, schema)  # alias -> real table name, in FROM/JOIN order
        if not aliases:
            continue
        name = col.name
        qual = col.table.lower() if col.table else ""
        if qual and qual in aliases:
            table = schema.tables[aliases[qual]]
            if name in table.columns:
                continue
            fix = _closest(name, table.columns)
            if fix:
                changes.append(f"column {col.table}.{name} -> {col.table}.{fix}")
                col.set("this", exp.to_identifier(fix))
                continue
            # the column belongs to another joined table: re-qualify it
            owners = [a for a, tn in aliases.items() if _closest(name, schema.tables[tn].columns, 0.9)]
            if owners:
                alias = _prefer_grouped(select, name, owners)
                fixed = _closest(name, schema.tables[aliases[alias]].columns, 0.9)
                changes.append(f"column {col.table}.{name} -> {alias}.{fixed}")
                col.set("table", exp.to_identifier(alias))
                col.set("this", exp.to_identifier(fixed))
            continue
        if qual or name.lower() in {a.alias.lower() for a in select.expressions if isinstance(a, exp.Alias)}:
            continue
        owners = [a for a, tn in aliases.items() if name in schema.tables[tn].columns]
        if len(owners) == 1:
            continue
        if len(owners) > 1:  # ambiguous: qualify with the first table of the FROM clause that has it
            changes.append(f"ambiguous column {name} -> {owners[0]}.{name}")
            col.set("table", exp.to_identifier(owners[0]))
            continue
        for tn in aliases.values():
            fix = _closest(name, schema.tables[tn].columns)
            if fix:
                changes.append(f"column {name} -> {fix}")
                col.set("this", exp.to_identifier(fix))
                break
    return Repair(tree.sql(dialect="sqlite") if changes else sql, changes)


def _scope_aliases(select: exp.Select, schema: Schema) -> dict[str, str]:
    """alias -> table for the tables of this SELECT only (not of its subqueries)."""
    out: dict[str, str] = {}
    for t in select.find_all(exp.Table):
        if t.find_ancestor(exp.Select) is not select:
            continue
        real = schema.table(t.name)
        if real:
            out[(t.alias or t.name).lower()] = real.name
    return out


def _prefer_grouped(select: exp.Select, name: str, owners: list[str]) -> str:
    """Prefer the candidate table whose column is in GROUP BY (SELECT g.Name ... GROUP BY g.Name)."""
    group = select.args.get("group")
    if group:
        for c in group.find_all(exp.Column):
            if c.name.lower() == name.lower() and c.table.lower() in owners:
                return c.table.lower()
    return owners[0]
