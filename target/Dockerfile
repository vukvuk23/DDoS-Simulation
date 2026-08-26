FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install -r requirements.txt

COPY . .

RUN mkdir -p /tmp/prometheus_multiproc

ENV PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc

ENV GUNICORN_WORKERS=4

EXPOSE 5000

CMD ["gunicorn", "--config", "gunicorn_conf.py", "app:app"]