import os         
import time       
import requests  
import statistics                     
import csv                            
import threading                     
from datetime import datetime         
from collections import deque         
from flask import Flask, Response                                   
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST  

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090") # prometheus ime servisa

POLL_INTERVAL = int(os.environ.get("DETECTION_POLL_INTERVAL", 5))

METRICS_PORT = int(os.environ.get("DETECTION_METRICS_PORT", 8000)) # port na kome detektor izlaze spostvene metrike, gde ovaj flask slusa

LOG_FILE = os.environ.get("DETECTION_LOG_FILE", "detection_log.csv")

QUERIES = {
    "target_req_rate": "sum(rate(target_http_requests_total[1m]))", # ukupan pros br zahteva po sek u prethodnom min
    "target_active_conn": "sum(target_http_connections_active)", # trenutno obradjivane kon od strane flaska
    "target_busy_workers": "sum(target_workers_busy)", # na nivou gunicorna, worker.py
    "target_worker_pool": "max(worker_pool_size)",
    "traefik_open_conn": "sum(traefik_open_connections)", # trenutno otvorene konekcije na traefik entrypointima
    "target_latency_p95": "histogram_quantile(0.95, sum(rate(target_http_request_duration_seconds_bucket[1m])) by (le))", 
}

REQ_RATE_HISTORY_SIZE = 12 # koliko proslih upita se pamti, ukupno min
  
req_rate_history = deque(maxlen=REQ_RATE_HISTORY_SIZE) # kad se doda 13. izbaci 1.

latency_history = deque(maxlen=REQ_RATE_HISTORY_SIZE)

FLOOD_STDDEV_MULTIPLIER = 3 # 3 sigma pravilo, bilo sta sto je 3 stdev udaljeno od proseka

MIN_STDEV_FLOOR = 0.1

FLOOD_REQ_RATE_FALLBACK_THRESHOLD = 50.0 # rezervni

LATENCY_STDDEV_MULTIPLIER = 3 # isto Cebisevljev

MIN_LATENCY_STDEV_FLOOR = 0.002 

LATENCY_FALLBACK_THRESHOLD = 0.1 # vrednost dok latency_history nije pun

SATURATION_THRESHOLD = 0.5 

BASELINE_REQ_RATE_THRESHOLD = 15.0

POSSIBLE_VERDICTS = ["none", "http_flood", "slowpost", "unknown"]

DETECTION_VERDICT = Gauge(
    'detection_verdict',
    'Trenutna presuda detektora (1 = aktivno stanje, 0 = neaktivno)',
    labelnames=['verdict_type'], # kolona
)

DETECTION_FLOOD_THRESHOLD = Gauge(
    'detection_flood_threshold',
    'Trenutno izracunat adaptivni prag za HTTP flood (req/s)',
)

DETECTION_LATENCY_THRESHOLD = Gauge(
    'detection_latency_threshold',
    'Trenutno izracunat adaptivni prag za p95 latenciju (sekunde)',
) 

for v in POSSIBLE_VERDICTS:
    DETECTION_VERDICT.labels(verdict_type=v).set(0) # postavljanje vr u tabeli


def compute_flood_threshold(history):

    if len(history) < REQ_RATE_HISTORY_SIZE:
        return FLOOD_REQ_RATE_FALLBACK_THRESHOLD # prremalo podataka da bi se racunalo detaljno

    mean = statistics.mean(history) # srvr     
    stdev = statistics.stdev(history) # koliko se br u proseku razl od srvr

    return mean + FLOOD_STDDEV_MULTIPLIER * max(stdev, MIN_STDEV_FLOOR) # adaptivni prag


def compute_latency_threshold(history):

    if len(history) < REQ_RATE_HISTORY_SIZE: 
        return LATENCY_FALLBACK_THRESHOLD

    mean = statistics.mean(history) 
    stdev = statistics.stdev(history) 

    return mean + LATENCY_STDDEV_MULTIPLIER * max(stdev, MIN_LATENCY_STDEV_FLOOR) 


def decide(readings, history, latency_history):

    req_rate = readings.get("target_req_rate") 
    busy = readings.get("target_busy_workers")
    pool = readings.get("target_worker_pool")
    latency = readings.get("target_latency_p95") 

    if req_rate is None or busy is None or pool is None or latency is None: 
        return "unknown"

    if pool == 0:
        return "unknown"

    saturation = busy / pool 

    flood_threshold = compute_flood_threshold(history)
    latency_threshold = compute_latency_threshold(latency_history)

    if req_rate > flood_threshold and latency > latency_threshold: 
        return "http_flood"

    if saturation > SATURATION_THRESHOLD and req_rate < BASELINE_REQ_RATE_THRESHOLD:
        return "slowpost"

    return "none"


def query(promql):

    response = requests.get( # blokirajuce, upit ka pormetheusu
        f"{PROMETHEUS_URL}/api/v1/query",   
        params={"query": promql},         
        timeout=5,                          
    )

    payload = response.json()

    result = payload["data"]["result"] # izdvaja metrics, value

    if not result: 
        return None

    return float(result[0]["value"][1]) # konkretna vrednost


def update_verdict_metric(verdict):
    for v in POSSIBLE_VERDICTS:
        DETECTION_VERDICT.labels(verdict_type=v).set(1 if v == verdict else 0) # ternarni


def detection_loop():

    with open(LOG_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp", "verdict", "flood_threshold",
            "req_rate", "active_conn", "busy_workers", "worker_pool", "traefik_open_conn",
            "latency_p95", "latency_threshold" 
        ])

        while True:
            readings = {}    

            for name, promql in QUERIES.items(): # raspakuje tuple 
                try:
                    readings[name] = query(promql) # upisuje u readings pod kljucem name     
                except requests.exceptions.RequestException:
                    readings[name] = None                   

            verdict = decide(readings, req_rate_history, latency_history) 

            req_rate = readings.get("target_req_rate")
            latency = readings.get("target_latency_p95")

            flood_threshold = compute_flood_threshold(req_rate_history)
            latency_threshold = compute_latency_threshold(latency_history) # racuna se odvojeno da bi mogao da se loguje i prikaze kao gauge

            if verdict == "none" and req_rate is not None:
                req_rate_history.append(req_rate)

            if verdict == "none" and latency is not None: 
                latency_history.append(latency)

            update_verdict_metric(verdict)
            DETECTION_FLOOD_THRESHOLD.set(flood_threshold)
            DETECTION_LATENCY_THRESHOLD.set(latency_threshold) 

            ts = datetime.now().isoformat(timespec="seconds")

            writer.writerow([
                ts, verdict, round(flood_threshold, 4),
                readings.get("target_req_rate"),
                readings.get("target_active_conn"),
                readings.get("target_busy_workers"),
                readings.get("target_worker_pool"),
                readings.get("traefik_open_conn"),
                readings.get("target_latency_p95"), 
                round(latency_threshold, 4), 
            ])
            f.flush()

            print(f"[{verdict}] thr={flood_threshold:.3f} latency_thr={latency_threshold:.4f} {readings}", flush=True) 

            time.sleep(POLL_INTERVAL)


app = Flask(__name__)

@app.route('/metrics')
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST) # slicno kao u app


@app.route('/health')
def health():
    return {"status": "healthy"}, 200


if __name__ == "__main__":
    detection_thread = threading.Thread(target=detection_loop, daemon=True) # izvrsava detection loop
    detection_thread.start() # def samo pamti fje

    app.run(host="0.0.0.0", port=METRICS_PORT, threaded=True)