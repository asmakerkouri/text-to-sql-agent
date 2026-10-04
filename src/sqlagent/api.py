"""FastAPI service: POST /ask {"question": "..."} -> SQL, rows and steps of the agent."""

from __future__ import annotations

import os
from dataclasses import asdict
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .agent import SQLAgent
from .chart import suggest
from .llm import from_env

app = FastAPI(title="Text-to-SQL agent", version="1.0.0")


class Ask(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@lru_cache
def get_agent() -> SQLAgent:
    return SQLAgent(os.getenv("DB_PATH", "data/chinook.sqlite"), from_env(os.getenv("LLM", "ollama:qwen2.5:7b")))


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/schema")
def schema() -> dict:
    return {"schema": get_agent().schema.to_prompt()}


@app.post("/ask")
def ask(body: Ask) -> dict:
    res = get_agent().ask(body.question)
    if not res.ok:
        raise HTTPException(422, detail={"error": res.error, "steps": [asdict(s) for s in res.steps]})
    return {
        "sql": res.sql,
        "columns": res.columns,
        "rows": res.rows[:100],
        "row_count": len(res.rows),
        "chart": suggest(res.columns, res.rows),
        "llm_calls": res.llm_calls,
        "latency_s": round(res.latency_s, 3),
        "steps": [asdict(s) for s in res.steps],
    }
