# Fly.io 部署用 Dockerfile（Streamlit + Python 3.11）
FROM python:3.11-slim

WORKDIR /app

# 系統相依（lxml 編譯需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gcc g++ libxml2-dev libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

# Python 套件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 程式碼 + 壓縮 DB
COPY . .

# 開機時自動把 data/market.db.gz 解壓
# （由 ui/_common.py 第一次 import 時呼叫 bootstrap_db）
# 這裡先預解壓避免第一個 request 等

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl --fail http://localhost:8501/_stcore/health || exit 1

# Streamlit 啟動參數
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["streamlit", "run", "ui/app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--server.enableXsrfProtection=false", \
     "--browser.gatherUsageStats=false"]
