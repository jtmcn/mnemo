# The toolchain a cell of mnemo runs.
FROM saffron/cell-base:python

# Pinned to the uv that wrote uv.lock. Bump the two together.
ARG UV_VERSION=0.12.18
RUN python -m pip install --no-cache-dir --break-system-packages "uv==${UV_VERSION}" \
 && uv --version

# Built where it runs: a moved venv keeps a dead path in each script's shebang.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv

# mnemo reads its version from package metadata, so the project itself is
# installed, editable at /work/src, where a cell mounts the worktree.
COPY pyproject.toml uv.lock README.md LICENSE /work/
COPY src /work/src
RUN cd /work && uv sync --frozen --all-extras \
 && find /work -mindepth 1 -delete
# `uv run` would re-resolve through a proxy that allows one host.
ENV VIRTUAL_ENV=/opt/venv PATH="/opt/venv/bin:$PATH" UV_NO_SYNC=1

# tiktoken fetches cl100k_base on first use, and a cell reaches one host.
ENV TIKTOKEN_CACHE_DIR=/opt/tiktoken ANONYMIZED_TELEMETRY=False
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

# Run every gate's tool, never merely locate it.
RUN ruff --version && mypy --version && pytest --version && coverage --version \
 && git --version \
 && python -c "import importlib.metadata as m; print('mnemo', m.version('mnemo'))"
