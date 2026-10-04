LLM ?= ollama:qwen2.5:7b

install:
	pip install -r requirements-dev.txt

test:
	ruff check . && pytest -q

eval:            ## guardrail + repair benchmarks (no LLM needed)
	python eval/run_eval.py guard
	python eval/run_eval.py repair
	python scripts/make_figures.py

eval-llm:        ## end-to-end accuracy with a real model, e.g. make eval-llm LLM=ollama:llama3.1:8b
	python eval/run_eval.py agent --llm $(LLM)

serve:
	PYTHONPATH=src LLM=$(LLM) uvicorn sqlagent.api:app --reload --port 8000

.PHONY: install test eval eval-llm serve
