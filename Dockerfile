FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends procps gcc fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-api.txt requirements-api-vision.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-api-vision.txt

COPY . .

EXPOSE 5000

CMD ["python", "entrypoint.py"]
