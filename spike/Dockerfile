# Per-commit build environment for the BUGAGE-1 spike. Toolchains and the cargo registry live in
# named volumes (RUSTUP_HOME=/rustup, CARGO_HOME=/cargo) so they persist across commits.
FROM debian:bookworm-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gcc g++ libc6-dev make cmake pkg-config git clang libclang-dev libssl-dev \
 && rm -rf /var/lib/apt/lists/*
ENV RUSTUP_HOME=/rustup CARGO_HOME=/cargo PATH=/cargo/bin:$PATH
