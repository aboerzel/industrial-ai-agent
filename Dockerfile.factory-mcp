FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --create-home app

COPY pyproject.toml ./
COPY src ./src

# The container exposes only factory_mcp, so it avoids optional retrieval and LLM runtimes.
RUN pip install --no-cache-dir "mcp>=2.0,<3.0" \
    && pip install --no-cache-dir --no-deps .

USER app

EXPOSE 8001

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8001), 2).close()"

CMD ["python", "-m", "industrial_ai_agent.infrastructure.factory_mcp_server", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8001"]
