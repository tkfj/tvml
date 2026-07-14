FROM nvidia/cuda:12.8.0-runtime-ubuntu24.04

# # ベースイメージはUID,GID 1000はubuntuとして作られているのでそのまま使用
ARG USERNAME=ubuntu
# ARG USERNAME=appuser
ARG USER_UID=1000
ARG USER_GID=$USER_UID

# RUN groupadd --gid $USER_GID $USERNAME \
#     && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME \
#     && echo $USERNAME ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/$USERNAME \
#     && chmod 0440 /etc/sudoers.d/$USERNAME

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"
    
ENV TZ=Asia/Tokyo
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    sqlite3 \
    python3 \
    python3-pip \
    python-is-python3 \
    build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --chown=$USERNAME:$USER_GID ./pyproject.toml ./uv.lock* ./
RUN uv sync

COPY --chown=$USERNAME:$USER_GID ./src ./src
COPY --chown=$USERNAME:$USER_GID ./conf ./conf

USER $USERNAME

CMD ["uv", "run", "src/main.py"]
