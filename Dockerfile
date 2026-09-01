# A pinned, dependency-complete image so the demo behaves the same on any host.
# The reviewer is deliberately absent: the browser UI sends `skip_llm: true` on
# every request, so a public deployment needs no model key and cannot spend.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY cli.py ./

RUN pip install --no-cache-dir ".[web]"

# Hosts assign the port; 8000 is only the local default.
EXPOSE 8000
CMD ["python", "cli.py", "serve"]
