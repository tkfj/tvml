#FROM python:3.11-slim-bookworm
FROM nvcr.io/nvidia/pytorch:26.05-py3

# タイムゾーンと最小限のパッケージ
ENV TZ=Asia/Tokyo
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    sqlite3 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依存関係
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ソースコードのコピー
COPY ./src ./src
COPY static_tokens.yaml static_tokens.yaml

# 本番実行用コマンド
CMD ["python", "src/main.py"]
