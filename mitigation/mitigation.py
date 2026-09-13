import os                                      
import time                                    
import csv                                     
import threading                              
from datetime import datetime                  
from flask import Flask, Response, request, jsonify  
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

MANUAL_OVERRIDE_SECONDS = int(os.environ.get("MANUAL_OVERRIDE_SECONDS", 120))  # protiv automatskog menajnja replika 

MIDDLEWARE_NAME = os.environ.get("MIDDLEWARE_NAME", "target-ratelimit") # iz yamla       

MIDDLEWARE_NAMESPACE = os.environ.get("MIDDLEWARE_NAMESPACE", "default")          

RATE_LIMIT_TARGET_AVERAGE = int(os.environ.get("RATE_LIMIT_TARGET_AVERAGE", 3))   

RATE_LIMIT_TARGET_BURST = int(os.environ.get("RATE_LIMIT_TARGET_BURST", 2))      

RATE_LIMIT_NORMAL_AVERAGE = int(os.environ.get("RATE_LIMIT_NORMAL_AVERAGE", 15))  

RATE_LIMIT_NORMAL_BURST = int(os.environ.get("RATE_LIMIT_NORMAL_BURST", 10))      

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

custom_api = client.CustomObjectsApi() # za stvari koje k8s po difoltu ne poznaje, ovde je traefik ovde registrovao u klasteru  

state_lock = threading.Lock() # samo jedna nit sme da bude unutar with state_lock              

shared_state = { # deljeno stanje izmedju ove dve niti
    "current_replicas": None,                
    "manual_override_until": 0.0,              
}


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


def set_rate_limit(average, burst): # setter za rl                                 

    custom_api.patch_namespaced_custom_object(                            
        group="traefik.io",                                                 
        version="v1alpha1",                                                 
        namespace=MIDDLEWARE_NAMESPACE,                                       
        plural="middlewares",                                                
        name=MIDDLEWARE_NAME,                                                  
        body={"spec": {"rateLimit": {"average": average, "burst": burst}}},    
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

    clear_streak = 0
    current_replicas = get_current_replicas()

    with state_lock:
        shared_state["current_replicas"] = current_replicas

    MITIGATION_TARGET_REPLICAS.set(current_replicas)  # gauge

    while True:

        with state_lock:
            override_active = time.time() < shared_state["manual_override_until"]
            current_replicas = shared_state["current_replicas"]

        attack_active = is_attack_active()

        if attack_active is True:
            clear_streak = 0
        elif attack_active is False:
            clear_streak += 1
        # ako je None, clear_streak se ne menja

        if override_active:

            target_replicas = current_replicas

        else:

            if attack_active is True:
                target_replicas = MAX_REPLICAS

            elif attack_active is False and clear_streak >= SCALE_DOWN_STREAK_REQUIRED:
                target_replicas = BASELINE_REPLICAS

            else:  
                target_replicas = current_replicas

            if target_replicas != current_replicas:
                set_replicas(target_replicas)

                direction = "up" if target_replicas > current_replicas else "down"
                MITIGATION_ACTIONS.labels(direction=direction).inc()

                current_replicas = target_replicas

                with state_lock:
                    shared_state["current_replicas"] = current_replicas

        MITIGATION_TARGET_REPLICAS.set(current_replicas)

        print(
            f"[mitigation] attack={attack_active} streak={clear_streak} "
            f"replicas={current_replicas} override={override_active}",
            flush=True,
        )

        time.sleep(POLL_INTERVAL)                                         

app = Flask(__name__)

@app.route('/metrics')
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

@app.route('/health')
def health():
    return {"status": "healthy"}, 200

@app.route('/api/manual/scale-up', methods=['POST'])                          
def manual_scale_up():

    with state_lock:                                                            
        shared_state["manual_override_until"] = time.time() + MANUAL_OVERRIDE_SECONDS # ako se manuelno postavi, u loopu ce da udje u onaj if

    try:
        set_replicas(MAX_REPLICAS)                                               
    except Exception as e:                                                        
        return jsonify({"error": str(e)}), 500                                      

    with state_lock:                                                               
        shared_state["current_replicas"] = MAX_REPLICAS                            

    MITIGATION_TARGET_REPLICAS.set(MAX_REPLICAS)                                      
    MITIGATION_ACTIONS.labels(direction="up").inc()                                   

    return jsonify({                                                                    
        "status": "ok",
        "replicas": MAX_REPLICAS,
        "manual_override_seconds": MANUAL_OVERRIDE_SECONDS,
    }), 200


@app.route('/api/manual/ratelimit', methods=['POST'])                            
def manual_ratelimit():

    data = request.get_json(silent=True) or {} # pokusa da parsira telo u json, ako ne uspe None -> {}                                     
    average = int(data.get("average", RATE_LIMIT_TARGET_AVERAGE)) # ako ne posalje telo, radi sa dioltnim vr                    
    burst = int(data.get("burst", RATE_LIMIT_TARGET_BURST))                           

    with state_lock:                                                                  
        shared_state["manual_override_until"] = time.time() + MANUAL_OVERRIDE_SECONDS

    try:
        set_rate_limit(average, burst)                                                  
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok", "average": average, "burst": burst}), 200            


@app.route('/api/manual/ratelimit/reset', methods=['POST'])                              
def manual_ratelimit_reset():

    try:
        set_rate_limit(RATE_LIMIT_NORMAL_AVERAGE, RATE_LIMIT_NORMAL_BURST) # reset na normal                      
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "status": "ok",
        "average": RATE_LIMIT_NORMAL_AVERAGE,
        "burst": RATE_LIMIT_NORMAL_BURST,
    }), 200


if __name__ == "__main__":
    mitigation_thread = threading.Thread(target=mitigation_loop, daemon=True)
    mitigation_thread.start()

    app.run(host="0.0.0.0", port=METRICS_PORT, threaded=True)