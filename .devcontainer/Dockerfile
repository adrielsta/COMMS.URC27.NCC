FROM python:3.12.10-bookworm@sha256:91487c05f87617b9d1165274c07a9b0040dfef21a855b5b418a0ebc6aa26c5de

# apt verifies repository signatures and package hashes using Debian's keyring.
RUN apt-get update -o APT::Update::Error-Mode=any \
    && DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends ca-certificates g++ git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash vscode

USER vscode
