from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sqlagent import SQLAgent, api, guard
from sqlagent.chart import render, suggest
from sqlagent.llm import Scripted
from sqlagent.repair import repair
from sqlagent.schema import Schema

DB = Path(__file__).resolve().parents[1] / "data" / "chinook.sqlite"
GOOD = ("```sql\nSELECT BillingCountry, ROUND(SUM(Total), 2) AS revenue FROM Invoice "
        "GROUP BY BillingCountry ORDER BY revenue DESC LIMIT 5\n```")


@pytest.fixture(scope="module")
def schema():
    return Schema.from_sqlite(DB)


# ---------- guardrail ----------
@pytest.mark.parametrize("sql", [
    "DROP TABLE Customer", "DELETE FROM Invoice", "SELECT 1; DROP TABLE Customer",
    "UPDATE Track SET UnitPrice = 0", "ATTACH DATABASE 'x.db' AS x", "SELECT load_extension('evil.so')",
])
def test_guard_blocks_writes(sql):
    assert not guard.check(sql).ok


def test_guard_adds_limit():
    g = guard.check("SELECT * FROM Track")
    assert g.ok and "LIMIT 500" in g.sql


def test_readonly_connection_refuses_writes(schema):
    agent = SQLAgent(DB, Scripted([]))
    with pytest.raises(Exception, match="readonly"):
        agent.con.execute("DELETE FROM Genre")


# ---------- repair ----------
@pytest.mark.parametrize("bad, expected", [
    ("SELECT COUNT(*) FROM Tracks", "FROM Track"),
    ("SELECT invoice_date FROM Invoice", "InvoiceDate"),
    ("SELECT Miliseconds FROM Track", "Milliseconds"),
    ("SELECT Name FROM Track t JOIN Genre g ON g.GenreId = t.GenreId", "t.Name"),
])
def test_repair(schema, bad, expected):
    r = repair(bad, schema)
    assert r.changed and expected in r.sql


def test_repair_respects_subquery_scope(schema):
    r = repair("SELECT COUNT(*) FROM Track WHERE TrackId NOT IN (SELECT TrackId FROM InvoiceLines)", schema)
    assert r.changes == ["table InvoiceLines -> InvoiceLine"]


# ---------- agent loop ----------
def test_agent_first_try():
    res = SQLAgent(DB, Scripted([GOOD])).ask("Top 5 countries by revenue")
    assert res.ok and res.llm_calls == 1 and res.rows[0][0] == "USA"


def test_agent_repairs_without_new_llm_call():
    llm = Scripted(["```sql\nSELECT BillingCountry, SUM(total) FROM Invoices GROUP BY BillingCountry\n```"])
    res = SQLAgent(DB, llm).ask("Revenue per country")
    assert res.ok and res.llm_calls == 1
    assert [s.kind for s in res.steps] == ["generate", "sql_error", "repair", "ok"]


def test_agent_retries_after_guard_rejection():
    llm = Scripted(["```sql\nDELETE FROM Invoice\n```", GOOD])
    res = SQLAgent(DB, llm).ask("Top 5 countries by revenue")
    assert res.ok and res.llm_calls == 2
    assert "guardrail" in llm.calls[1][-1]["content"]


def test_agent_sends_sqlite_error_back_to_llm():
    llm = Scripted(["```sql\nSELECT Popularity FROM Track\n```", GOOD])
    res = SQLAgent(DB, llm).ask("Top 5 countries by revenue")
    assert res.ok and "no such column" in llm.calls[1][-1]["content"]


def test_agent_gives_up():
    res = SQLAgent(DB, Scripted(["```sql\nSELECT Popularity FROM Track\n```"] * 3)).ask("?")
    assert not res.ok and res.llm_calls == 3


# ---------- chart ----------
def test_chart_kinds(tmp_path):
    assert suggest(["year", "revenue"], [("2009", 1.0), ("2010", 2.0)]) == "line"
    assert suggest(["country", "revenue"], [("USA", 1.0), ("France", 2.0)]) == "bar"
    assert suggest(["n"], [(59,)]) is None
    assert render(["country", "revenue"], [("USA", 1.0), ("France", 2.0)], "t", tmp_path / "c.png").exists()


# ---------- API ----------
def test_api(monkeypatch):
    monkeypatch.setattr(api, "get_agent", lambda: SQLAgent(DB, Scripted([GOOD])))
    client = TestClient(api.app)
    assert client.get("/health").json() == {"status": "ok"}
    r = client.post("/ask", json={"question": "Top 5 countries by revenue"})
    assert r.status_code == 200 and r.json()["chart"] == "bar" and r.json()["row_count"] == 5
