FROM rust:1.91-slim AS verifier
WORKDIR /build
COPY pool-verifier/ pool-verifier/
RUN cargo build --manifest-path pool-verifier/Cargo.toml --release --locked

FROM python:3.12-slim
WORKDIR /app
COPY pool_server.py pool_accounting.py pool_client.py preflight.py solo.py template_work.py ./
COPY --from=verifier /build/pool-verifier/target/release/catecash-pool-verifier /usr/local/bin/catecash-pool-verifier
ENV PYTHONDONTWRITEBYTECODE=1
USER 999:988
ENTRYPOINT ["python3", "-u", "pool_server.py"]
