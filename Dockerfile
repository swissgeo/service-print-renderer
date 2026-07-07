###########################################################
# Container that contains basic configurations used by all other containers
# It should only contain variables that don't change or change very infrequently
# so that the cache is not needlessly invalidated
FROM python:3.14-slim-trixie AS base
ENV USER=swissgeo
ENV GROUP=swissgeo
ENV INSTALL_DIR=/opt/service-print-renderer

RUN apt-get -qq update > /dev/null \
    && apt-get -qq install -y --no-install-recommends gnupg wget > /dev/null \
    && wget -qO- https://dl-ssl.google.com/linux/linux_signing_key.pub \
       | gpg --dearmor > /etc/apt/trusted.gpg.d/google-archive.gpg \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" \
       > /etc/apt/sources.list.d/google.list \
    && apt-get -qq update > /dev/null \
    && apt-get -qq install -y --no-install-recommends \
       google-chrome-stable \
       mesa-utils \
       mesa-utils-extra \
       > /dev/null \
    && apt-get -qq clean \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r ${GROUP} \
    && useradd -r -m -s /bin/false -g ${GROUP} ${USER} \
    && mkdir -p /home/${USER} && chown ${USER}:${GROUP} /home/${USER}

###########################################################
# Builder container
FROM base AS builder
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1
# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy
# Omit development dependencies
ENV UV_NO_DEV=1
# Ensure installed tools can be executed out of the box
ENV UV_TOOL_BIN_DIR=/usr/local/bin

# Disable Python downloads, because we want to use the system interpreter
# across both images.
ENV UV_PYTHON_DOWNLOADS=0

# Install all the dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked

COPY --chown=${USER}:${GROUP} app/ ${INSTALL_DIR}/app/
RUN mkdir -p ${INSTALL_DIR}/logs && chown ${USER}:${GROUP} ${INSTALL_DIR}/logs


###########################################################
# Container to perform tests/management/dev tasks
FROM builder AS debug
LABEL target=debug
ENV DEBUG=1

RUN apt-get -qq update > /dev/null \
    && apt-get -qq -y install \
    curl \
    net-tools \
    iputils-ping \
    jq \
    openssh-client \
    binutils \
    # silent the install
    > /dev/null \
    && apt-get -qq clean \
    && rm -rf /var/lib/apt/lists/*

# Install all dev dependencies
ENV UV_NO_DEV=0
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked

COPY --from=builder ${INSTALL_DIR}/ ${INSTALL_DIR}/

# Activate virtualenv
ENV VIRTUAL_ENV=${INSTALL_DIR}/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
ENV PYTHONHOME=""

# Overwrite the version.py from source with the actual version
ARG VERSION=unknown
RUN echo "APP_VERSION = '$VERSION'" > ${INSTALL_DIR}/app/config/version.py

ARG GIT_HASH=unknown
ARG GIT_BRANCH=unknown
ARG GIT_DIRTY=""
ARG AUTHOR=unknown
LABEL git.hash=$GIT_HASH
LABEL git.branch=$GIT_BRANCH
LABEL git.dirty="$GIT_DIRTY"
LABEL author=$AUTHOR
LABEL version=$VERSION

WORKDIR ${INSTALL_DIR}
USER ${USER}

# entrypoint is python; pass -m app.worker as command
ENTRYPOINT ["python"]
CMD ["-m", "app.worker"]



###########################################################
# Container to use in production
FROM base AS production
LABEL target=production
ENV DEBUG=0

COPY --from=builder .venv/ ${INSTALL_DIR}/.venv/

COPY --from=builder ${INSTALL_DIR}/ ${INSTALL_DIR}/

# Activate virtual environment
ENV VIRTUAL_ENV=${INSTALL_DIR}/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
ENV PYTHONHOME=""

# Overwrite the version.py from source with the actual version
ARG VERSION=unknown
RUN echo "APP_VERSION = '$VERSION'" > ${INSTALL_DIR}/app/config/version.py

ARG GIT_HASH=unknown
ARG GIT_BRANCH=unknown
ARG GIT_DIRTY=""
ARG AUTHOR=unknown
LABEL git.hash=$GIT_HASH
LABEL git.branch=$GIT_BRANCH
LABEL git.dirty="$GIT_DIRTY"
LABEL author=$AUTHOR
LABEL version=$VERSION
# production container must not run as root
WORKDIR ${INSTALL_DIR}
USER ${USER}

# entrypoint is python; pass -m app.worker as command
ENTRYPOINT ["python"]
CMD ["-m", "app.worker"]
