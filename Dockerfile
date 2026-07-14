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

# 依存関係
COPY --chown=$USERNAME:$USER_GID requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt --break-system-packages

# ソースコードのコピー
COPY --chown=$USERNAME:$USER_GID ./src ./src
COPY --chown=$USERNAME:$USER_GID ./conf ./conf

USER $USERNAME

# 本番実行用コマンド
CMD ["python", "src/main.py"]
