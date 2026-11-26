FROM ubuntu:24.04@sha256:562111b88caa79c71391c0c4d3c2114a7d5c35915c20561fd893cb1e07929e6b
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libstdc++6 socat \
    && rm -rf /var/lib/apt/lists/*
COPY --chmod=0755 zebrad /usr/local/bin/zebrad
COPY --chmod=0755 entrypoint.sh /usr/local/bin/entrypoint.sh
USER 501:20
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
