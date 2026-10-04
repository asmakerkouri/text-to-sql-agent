"""Database introspection: the schema the agent is allowed to see."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Table:
    name: str
    columns: list[str]
    foreign_keys: list[tuple[str, str, str]] = field(default_factory=list)  # (column, ref_table, ref_column)


@dataclass
class Schema:
    tables: dict[str, Table]

    @classmethod
    def from_sqlite(cls, path: str | Path) -> Schema:
        con = connect_readonly(path)
        try:
            names = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            tables = {}
            for n in names:
                cols = [r[1] for r in con.execute(f'PRAGMA table_info("{n}")')]
                fks = [(r[3], r[2], r[4]) for r in con.execute(f'PRAGMA foreign_key_list("{n}")')]
                tables[n] = Table(n, cols, fks)
            return cls(tables)
        finally:
            con.close()

    def table(self, name: str) -> Table | None:
        """Case-insensitive table lookup."""
        for t in self.tables.values():
            if t.name.lower() == name.lower():
                return t
        return None

    def to_prompt(self) -> str:
        """Compact DDL-like description used in the LLM prompt."""
        lines = []
        for t in self.tables.values():
            fk = "".join(f"; {c} -> {rt}.{rc}" for c, rt, rc in t.foreign_keys)
            lines.append(f"{t.name}({', '.join(t.columns)}{fk})")
        return "\n".join(lines)


def connect_readonly(path: str | Path) -> sqlite3.Connection:
    """Open the database in read-only mode: writes fail at the SQLite level, whatever the SQL says."""
    uri = f"file:{Path(path).resolve()}?mode=ro"
    return sqlite3.connect(uri, uri=True, check_same_thread=False)
