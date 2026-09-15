import os         
import time       
import requests  
import csv                            
import threading                     
from datetime import datetime         
from flask import Flask, Response                                   
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST  

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")

POLL_INTERVAL = int(os.environ.get("DETECTION_POLL_INTERVAL", 5))

METRICS_PORT = int(os.environ.get("DETECTION_METRICS_PORT", 8000))

LOG_FILE = os.environ.get("DETECTION_LOG_FILE", "detection_log.csv")

QUERIES = {
    "traefik_req_rate": "sum(rate(traefik_entrypoint_requests_total[1m]))",
    "traefik_open_conn": "sum(traefik_open_connections)",
    "traefik_latency_p95": "histogram_quantile(0.95, sum(rate(traefik_entrypoint_request_duration_seconds_bucket[1m])) by (le))",
    "target_active_conn": "sum(target_http_connections_active)",
    "stuck_min": "min_over_time((sum(traefik_open_connections) - sum(target_http_connections_active))[20s:5s])",
}

FLOOD_REQ_RATE_THRESHOLD = 50.0

STUCK_CONN_THRESHOLD = 0.0

BASELINE_REQ_RATE_THRESHOLD = 15.0

POSSIBLE_VERDICTS = ["none", "http_flood", "slowpost", "unknown"]

DETECTION_VERDICT = Gauge(
    'detection_verdict',
    'Trenutna presuda detektora (1 = aktivno stanje, 0 = neaktivno)',
    labelnames=['verdict_type'],
)

DETECTION_FLOOD_THRESHOLD = Gauge(
    'detection_flood_threshold',
    'Fiksni prag za HTTP flood (req/s)',
)

DETECTION_STUCK_CONN_THRESHOLD = Gauge(
    'detection_stuck_conn_threshold',
    'Fiksni prag za min_over_time(traefik_open_conn - target_active_conn) (slowpost)',
)

for v in POSSIBLE_VERDICTS:
    DETECTION_VERDICT.labels(verdict_type=v).set(0)


def decide(readings):

    req_rate = readings.get("traefik_req_rate")
    stuck_min = readings.get("stuck_min")

    if req_rate is None or stuck_min is None:
        return "unknown"

    if req_rate > FLOOD_REQ_RATE_THRESHOLD:
        return "http_flood"

    if stuck_min > STUCK_CONN_THRESHOLD and req_rate < BASELINE_REQ_RATE_THRESHOLD:
        return "slowpost"

    return "none"


def query(promql):

    response = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query",
        params={"query": promql},
        timeout=5,
    )

    payload = response.json()

    result = payload["data"]["result"]

    if not result:
        return None

    return float(result[0]["value"][1])


def update_verdict_metric(verdict):
    for v in POSSIBLE_VERDICTS:
        DETECTION_VERDICT.labels(verdict_type=v).set(1 if v == verdict else 0)


def detection_loop():

    with open(LOG_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp", "verdict",
            "traefik_req_rate", "traefik_open_conn", "traefik_latency_p95",
            "target_active_conn", "stuck_min",
        ])

        while True:
            readings = {}

            for name, promql in QUERIES.items():
                try:
                    readings[name] = query(promql)
                except requests.exceptions.RequestException:
                    readings[name] = None

            verdict = decide(readings)

            update_verdict_metric(verdict)
            DETECTION_FLOOD_THRESHOLD.set(FLOOD_REQ_RATE_THRESHOLD)
            DETECTION_STUCK_CONN_THRESHOLD.set(STUCK_CONN_THRESHOLD)

            ts = datetime.now().isoformat(timespec="seconds")

            writer.writerow([
                ts, verdict,
                readings.get("traefik_req_rate"),
                readings.get("traefik_open_conn"),
                readings.get("traefik_latency_p95"),
                readings.get("target_active_conn"),
                readings.get("stuck_min"),
            ])
            f.flush()

            print(f"[{verdict}] {readings}", flush=True)

            time.sleep(POLL_INTERVAL)


app = Flask(__name__)

@app.route('/metrics')
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


@app.route('/health')
def health():
    return {"status": "healthy"}, 200


if __name__ == "__main__":
    detection_thread = threading.Thread(target=detection_loop, daemon=True)
    detection_thread.start()

    app.run(host="0.0.0.0", port=METRICS_PORT, threaded=True)