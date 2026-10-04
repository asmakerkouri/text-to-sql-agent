FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ src/
COPY data/ data/
RUN useradd -m app && chown -R app /app
USER app
ENV PYTHONPATH=/app/src \
    DB_PATH=/app/data/chinook.sqlite \
    LLM=ollama:qwen2.5:7b \
    LLM_BASE_URL=http://host.docker.internal:11434/v1
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "sqlagent.api:app", "--host", "0.0.0.0", "--port", "8000"]
