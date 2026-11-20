FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Bake the AI models into the image so the app starts fast and works without downloading them.
ENV HF_HOME=/models
RUN python -c "from sentence_transformers import SentenceTransformer as S; S('clip-ViT-B-32'); S('sentence-transformers/clip-ViT-B-32-multilingual-v1')"
COPY . .
# Videos, thumbnails and the search index live here. Mount a persistent volume at /data.
ENV DATA_DIR=/data PYTHONUNBUFFERED=1
CMD gunicorn -w 1 --threads 16 --timeout 0 -b 0.0.0.0:${PORT:-8000} app:app
