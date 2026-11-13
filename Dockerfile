FROM python:3.12-slim

# सर्वर पर ffmpeg, curl और unzip इंस्टॉल करना
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl unzip ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# YouTube सपोर्ट के लिए Deno इंस्टॉल करना
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p downloads temp private

# सर्वर चालू करना (Render और HuggingFace दोनों के पोर्ट को सपोर्ट करेगा)
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-7860}"]
