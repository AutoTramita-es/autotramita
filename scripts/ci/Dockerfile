# Local stand-in for the `ubuntu-24.04` runner of .github/workflows/ci.yml. It holds only the
# toolchain; the code under test is a snapshot mounted at run time, never copied into the image.
# Every build argument is passed by scripts/ci/lib/runner.py (versions from ci.yml, digests from
# images.lock.json), so there is no second place where a version is chosen.
ARG UBUNTU_IMAGE
ARG UV_IMAGE
ARG NODE_IMAGE

FROM ${UV_IMAGE} AS uv
FROM ${NODE_IMAGE} AS node

FROM ${UBUNTU_IMAGE}
ARG PYTHON_VERSION
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git jq python3 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /uvx /usr/local/bin/
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
# The same managed CPython build that astral-sh/setup-uv installs on GitHub.
ENV UV_PYTHON_INSTALL_DIR=/opt/python
RUN uv python install "${PYTHON_VERSION}" && chmod -R a+rX /opt/python
# Unprivileged, with the uid of the GitHub runner user. The cache directories are owned by it so
# that fresh named volumes inherit the ownership.
RUN groupadd --gid 1001 runner \
 && useradd --uid 1001 --gid 1001 --create-home runner \
 && install -d -o 1001 -g 1001 /cache/uv /cache/npm
USER 1001:1001
