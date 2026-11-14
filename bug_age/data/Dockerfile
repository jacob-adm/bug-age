# Per-commit build environment for bug-age (spike and `bug-age sweep --runner docker`).
# rustup and its cargo/rustc proxies live in the image; toolchains (RUSTUP_HOME=/rustup) and the
# cargo registry (CARGO_HOME=/cargo) live in named volumes so they persist across commits. Before
# v4, rustup itself lived in the /cargo volume, so deleting that volume broke the image.
# safe.directory: index repos are staged from the host; ownership must not block cargo's libgit2.
FROM debian:bookworm-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gcc g++ libc6-dev make cmake pkg-config git clang libclang-dev libssl-dev \
 && rm -rf /var/lib/apt/lists/*
RUN curl -sSf https://sh.rustup.rs | CARGO_HOME=/opt/rustup-bin RUSTUP_HOME=/tmp/rustup-init \
      sh -s -- -y --profile minimal --default-toolchain none --no-modify-path \
 && rm -rf /tmp/rustup-init
RUN git config --system --add safe.directory "*"
ENV RUSTUP_HOME=/rustup CARGO_HOME=/cargo PATH=/opt/rustup-bin/bin:$PATH
