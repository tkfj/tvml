FROM nvidia/cuda:12.8.0-runtime-ubuntu24.04

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
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt --break-system-packages

# ソースコードのコピー
COPY ./src ./src
COPY ./conf ./conf

# 本番実行用コマンド
CMD ["python", "src/main.py"]
