# Per-commit environment for bug-age's python profile (`bug-age sweep --profile python`).
# PY is the CPython minor chosen for the commit's date. The full image, not -slim, because packages
# from older years often build C extensions from source. uv resolves and installs dependencies with
# --exclude-newer set to the commit time; it supports Python 3.8 and later.
ARG PY
FROM python:${PY}
COPY --from=ghcr.io/astral-sh/uv:0.9.2 /uv /usr/local/bin/uv
RUN git config --system --add safe.directory "*"
