# syntax=docker/dockerfile:1.7

FROM python:3.14-slim-trixie@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.10@sha256:2bb3ebca0a796a155094a27773d290c4b074572e6107f171d88d086682fd2500 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0 UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /workspace/services/kb-mcp
COPY packages/mcp-configs /workspace/packages/mcp-configs
COPY packages/mcp-observability /workspace/packages/mcp-observability
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=services/kb-mcp/uv.lock,target=uv.lock \
    --mount=type=bind,source=services/kb-mcp/pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev --no-editable
COPY services/kb-mcp /workspace/services/kb-mcp
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim-trixie@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS runtime
WORKDIR /app
# 20250419 still trusts the eMudhra roots removed in the security update.
RUN apt-get update \
    && apt-get upgrade -y \
    && dpkg --compare-versions "$(dpkg-query -W -f '${Version}' ca-certificates)" ge "20250419+deb13u1" \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 app && useradd --system --uid 1000 --gid app app
RUN rm -rf /usr/local/lib/python*/site-packages/pip \
           /usr/local/lib/python*/site-packages/pip-*.dist-info \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.* \
 && ! python -c "import pip" 2>/dev/null
COPY --from=builder --chown=app:app /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
CMD ["kb-mcp"]
