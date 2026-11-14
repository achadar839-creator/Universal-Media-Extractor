FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl unzip ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir -U -r requirements.txt

COPY . .

RUN mkdir -p downloads temp private cookies

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-7860}"]
