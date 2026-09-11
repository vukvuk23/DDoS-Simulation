import os                                      
import time                                    
import csv                                     
import threading                              
from datetime import datetime                  
from flask import Flask, Response              
from prometheus_client import Gauge, Counter, generate_latest, CONTENT_TYPE_LATEST  
import requests                                
from kubernetes import client, config          

# --------- KONFIGURACIJA ---------

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")   

POLL_INTERVAL = int(os.environ.get("MITIGATION_POLL_INTERVAL", 5))           

METRICS_PORT = int(os.environ.get("MITIGATION_METRICS_PORT", 8001))           

LOG_FILE = os.environ.get("MITIGATION_LOG_FILE", "mitigation_log.csv")        

TARGET_DEPLOYMENT_NAME = os.environ.get("TARGET_DEPLOYMENT_NAME", "target")  
TARGET_NAMESPACE = os.environ.get("TARGET_NAMESPACE", "default")             

BASELINE_REPLICAS = int(os.environ.get("BASELINE_REPLICAS", 1))              
MAX_REPLICAS = int(os.environ.get("MAX_REPLICAS", 4))                        

SCALE_DOWN_STREAK_REQUIRED = int(os.environ.get("SCALE_DOWN_STREAK_REQUIRED", 6))  

QUERIES = {
    "http_flood_active": 'detection_verdict{verdict_type="http_flood"}',
    "slowpost_active": 'detection_verdict{verdict_type="slowpost"}',
    "unknown_active": 'detection_verdict{verdict_type="unknown"}',
}

# --------- METRIKE KOJE OVAJ SERVIS IZLAZE ---------

MITIGATION_TARGET_REPLICAS = Gauge(
    'mitigation_target_replicas',
    'Broj replika koji mitigation servis trenutno drzi kao ciljni',
)

MITIGATION_ACTIONS = Counter(
    'mitigation_scale_actions_total',
    'Broj stvarnih promena broja replika koje je mitigation servis izvrsio',
    labelnames=['direction'], # up i down             
)

# --------- KUBERNETES KLIJENT ---------

config.load_incluster_config() # kao autorizacija ali za porces   
                                  

apps_v1 = client.AppsV1Api() # obj koji sastavlja zahteve ka jednom delu kubernetes apija (onaj koji upravlja deploymentima)    


def get_current_replicas(): # getter, komunikacija sa k8s api serverom
    scale = apps_v1.read_namespaced_deployment_scale(
        name=TARGET_DEPLOYMENT_NAME,
        namespace=TARGET_NAMESPACE,
    )
    return scale.spec.replicas


def set_replicas(n): # setter, komunikacija sa k8s api serverom
    apps_v1.patch_namespaced_deployment_scale(
        name=TARGET_DEPLOYMENT_NAME,
        namespace=TARGET_NAMESPACE,
        body={"spec": {"replicas": n}},          
    )


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


def is_attack_active(): 
    try:
        flood = query(QUERIES["http_flood_active"])
        slowpost = query(QUERIES["slowpost_active"])
        unknown = query(QUERIES["unknown_active"]) 

    except requests.exceptions.RequestException:
        return None

    if flood is None or slowpost is None or unknown is None:
        return None

    if unknown == 1.0:                                  
        return None 

    return flood == 1.0 or slowpost == 1.0 # True False ili None


def mitigation_loop():

    clear_streak = 0 # br uzastponih krugova u kome je active_attack False, 6 = scale down                          
    current_replicas = get_current_replicas()    

    MITIGATION_TARGET_REPLICAS.set(current_replicas)   

    with open(LOG_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "attack_active", "clear_streak", "current_replicas", "target_replicas"])

        while True:
            attack_active = is_attack_active()

            if attack_active is True:
                clear_streak = 0                         
                target_replicas = MAX_REPLICAS # odmah na maks skaliranje      

            elif attack_active is False:
                clear_streak += 1                      

                if clear_streak >= SCALE_DOWN_STREAK_REQUIRED:
                    target_replicas = BASELINE_REPLICAS # scale down na 1
                else:
                    target_replicas = current_replicas # faksticki ni scale up ni down   

            else:                                       
                target_replicas = current_replicas # faksticki ni scale up ni down    

            if target_replicas != current_replicas: # ako je potreban scale up ili down
                set_replicas(target_replicas)           

                direction = "up" if target_replicas > current_replicas else "down" # gauge brihac
                MITIGATION_ACTIONS.labels(direction=direction).inc()

                current_replicas = target_replicas

            MITIGATION_TARGET_REPLICAS.set(current_replicas)

            ts = datetime.now().isoformat(timespec="seconds")
            writer.writerow([ts, attack_active, clear_streak, current_replicas, target_replicas])
            f.flush()

            print(f"[mitigation] attack={attack_active} streak={clear_streak} replicas={current_replicas}", flush=True)

            time.sleep(POLL_INTERVAL)


app = Flask(__name__)

@app.route('/metrics')
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

@app.route('/health')
def health():
    return {"status": "healthy"}, 200


if __name__ == "__main__":
    mitigation_thread = threading.Thread(target=mitigation_loop, daemon=True)
    mitigation_thread.start()

    app.run(host="0.0.0.0", port=METRICS_PORT, threaded=True)