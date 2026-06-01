# DocRunner — single-container image.
# Diverges from PyRunner in one significant way: LibreOffice is baked in for
# DOCX/XLSX → PDF conversion. That's the bulk of the image size.

FROM python:3.12-slim

# ──────────────────────────────────────────────
# System deps: LibreOffice (headless) + fonts for faithful PDF rendering.
# --no-install-recommends keeps the image as lean as LibreOffice allows.
# ──────────────────────────────────────────────
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

# Sanity-check that soffice is on PATH at build time.
RUN soffice --headless --version

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/app/data

WORKDIR /app

# ──────────────────────────────────────────────
# Python deps first (cached layer)
# ──────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ──────────────────────────────────────────────
# App code
# ──────────────────────────────────────────────
COPY . .

# The data volume holds SQLite, uploaded templates, generated outputs, static.
RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8000

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
