# syntax=docker/dockerfile:1
# Flaky Debug Agent API: FastAPI + the LangGraph graph, plus the tools the graph
# shells out to: git (clone_repo, code_fix) and IBM Bob Shell (`bob`, Node.js 22.15+).
# Built by deploy/compose.yaml with backend/ as the build context.

FROM node:24-bookworm-slim AS node

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Node.js + npm, which Bob Shell runs on.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# IBM Bob Shell, installed globally with the official script (it checks the package's
# SHA-256). `--pm npm` skips its interactive package-manager prompt.
ARG BOB_VERSION=2.0.5
RUN curl -fsSL https://bob.ibm.com/download/bobshell.sh \
        | bash -s -- --pm npm --version "${BOB_VERSION}" \
    && bob --version

# graph/tools.py and api/routes/runs.py locate the reports folder relative to their
# own files (<repo>/flaky_debug), so keep the repo layout: /app/backend/src/...
WORKDIR /app/backend
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY README.md ./
COPY src ./src
# uv installs the project editable by default, so modules run from /app/backend/src —
# which the report paths above rely on.
RUN uv sync --frozen --no-dev

# Bob's agent mode runs commands inside cloned user repos: never as root.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/flaky_debug \
    && chown app:app /app/flaky_debug
USER app

ENV PATH="/app/backend/.venv/bin:${PATH}" PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1
# No --reload: main.main() hardcodes it for development.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
