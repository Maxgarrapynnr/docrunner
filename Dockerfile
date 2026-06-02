FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        libreoffice-calc \
        fonts-liberation \
        fonts-dejavu-core \
        fontconfig \
        curl \
    && fc-cache -f \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN soffice --headless --version

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/app/data \
    SECRET_KEY=JlVjTn8-e8GB7RH2M_EuoG6ZbCHpXfcznFEqekSoVNEs4WEYc1gVpRS41n_CmZuoUNs \
    ENCRYPTION_KEY=gP6tOZofqzf7gVimDlbulZ_g-5INC1e-meD3gKWMa_4= \
    DEBUG=False \
    ALLOWED_HOSTS=docrunner.owncpanel.online \
    CSRF_TRUSTED_ORIGINS=https://docrunner.owncpanel.online \
    TIME_ZONE=UTC \
    Q_WORKERS=2 \
    WEB_WORKERS=3

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/data
VOLUME ["/app/data"]
EXPOSE 8000
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
