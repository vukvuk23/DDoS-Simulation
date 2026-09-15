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

TRAEFIK_DEPLOYMENT_NAME = os.environ.get("TRAEFIK_DEPLOYMENT_NAME", "traefik")

TRAEFIK_NAMESPACE = os.environ.get("TRAEFIK_NAMESPACE", "kube-system")

TARGET_NAMESPACE = os.environ.get("TARGET_NAMESPACE", "default")             

TARGET_INGRESS_NAME = os.environ.get("TARGET_INGRESS_NAME", "target")

BASELINE_REPLICAS = int(os.environ.get("BASELINE_REPLICAS", 1))   

MAX_REPLICAS = int(os.environ.get("MAX_REPLICAS", 4))                        

SCALE_DOWN_STREAK_REQUIRED = int(os.environ.get("SCALE_DOWN_STREAK_REQUIRED", 6))  

MANUAL_OVERRIDE_SECONDS = int(os.environ.get("MANUAL_OVERRIDE_SECONDS", 120))

MIDDLEWARE_NAME = os.environ.get("MIDDLEWARE_NAME", "target-ratelimit")

MIDDLEWARE_NAMESPACE = os.environ.get("MIDDLEWARE_NAMESPACE", "default")          

BUFFERING_MIDDLEWARE_NAME = os.environ.get("BUFFERING_MIDDLEWARE_NAME", "target-buffering")

ROUTER_MIDDLEWARES_ANNOTATION = "traefik.ingress.kubernetes.io/router.middlewares"

RATELIMIT_MIDDLEWARE_REF = f"{MIDDLEWARE_NAMESPACE}-{MIDDLEWARE_NAME}@kubernetescrd"

BUFFERING_MIDDLEWARE_REF = f"{MIDDLEWARE_NAMESPACE}-{BUFFERING_MIDDLEWARE_NAME}@kubernetescrd"

RATE_LIMIT_TARGET_AVERAGE = int(os.environ.get("RATE_LIMIT_TARGET_AVERAGE", 10))   

RATE_LIMIT_TARGET_BURST = int(os.environ.get("RATE_LIMIT_TARGET_BURST", 10))      

QUERIES = {
    "http_flood_active": 'detection_verdict{verdict_type="http_flood"}',
    "slowpost_active": 'detection_verdict{verdict_type="slowpost"}',
    "unknown_active": 'detection_verdict{verdict_type="unknown"}',
}

# --------- METRIKE KOJE OVAJ SERVIS IZLAZE ---------

MITIGATION_TRAEFIK_REPLICAS = Gauge(
    'mitigation_traefik_replicas',
    'Broj replika Traefik-a koji mitigation servis trenutno drzi kao ciljni',
)

MITIGATION_RATE_LIMIT_ACTIVE = Gauge(
    'mitigation_rate_limit_active',
    'Da li je rate limit middleware trenutno prikacen na ingress (1 = da, 0 = ne)',
)

MITIGATION_ACTIONS = Counter(
    'mitigation_scale_actions_total',
    'Broj stvarnih promena broja replika koje je mitigation servis izvrsio',
    labelnames=['direction'],
)

MITIGATION_RATE_LIMIT_ACTIONS = Counter(
    'mitigation_ratelimit_actions_total',
    'Broj stvarnih (de)aktivacija rate limit middleware-a na ingressu',
    labelnames=['direction'],
)

# --------- KUBERNETES KLIJENT ---------

config.load_incluster_config()

apps_v1 = client.AppsV1Api()

networking_v1 = client.NetworkingV1Api()

custom_api = client.CustomObjectsApi()

state_lock = threading.Lock()

shared_state = {
    "current_replicas": None,
    "scale_override_until": 0.0,
    "rate_limit_enabled": False,
    "ratelimit_override_until": 0.0,
}


def get_current_replicas():
    scale = apps_v1.read_namespaced_deployment_scale(
        name=TRAEFIK_DEPLOYMENT_NAME,
        namespace=TRAEFIK_NAMESPACE,
    )
    return scale.spec.replicas


def set_replicas(n):
    apps_v1.patch_namespaced_deployment_scale(
        name=TRAEFIK_DEPLOYMENT_NAME,
        namespace=TRAEFIK_NAMESPACE,
        body={"spec": {"replicas": n}},          
    )


def set_rate_limit(average, burst):
    custom_api.patch_namespaced_custom_object(
        group="traefik.io",
        version="v1alpha1",
        namespace=MIDDLEWARE_NAMESPACE,
        plural="middlewares",
        name=MIDDLEWARE_NAME,
        body={"spec": {"rateLimit": {"average": average, "burst": burst}}},
    )


def set_ingress_rate_limit_enabled(enabled):

    refs = []

    if enabled:
        refs.append(RATELIMIT_MIDDLEWARE_REF)

    refs.append(BUFFERING_MIDDLEWARE_REF)

    networking_v1.patch_namespaced_ingress(
        name=TARGET_INGRESS_NAME,
        namespace=TARGET_NAMESPACE,
        body={"metadata": {"annotations": {ROUTER_MIDDLEWARES_ANNOTATION: ",".join(refs)}}},
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

    return flood == 1.0 or slowpost == 1.0


def mitigation_loop():

    clear_streak = 0
    current_replicas = get_current_replicas()

    with state_lock:
        shared_state["current_replicas"] = current_replicas

    MITIGATION_TRAEFIK_REPLICAS.set(current_replicas)
    MITIGATION_RATE_LIMIT_ACTIVE.set(0)

    while True:

        with state_lock:
            scale_override_active = time.time() < shared_state["scale_override_until"]
            ratelimit_override_active = time.time() < shared_state["ratelimit_override_until"]
            current_replicas = shared_state["current_replicas"]
            rate_limit_enabled = shared_state["rate_limit_enabled"]

        attack_active = is_attack_active()

        if attack_active is True:
            clear_streak = 0
        elif attack_active is False:
            clear_streak += 1

        if attack_active is True:
            desired_replicas = MAX_REPLICAS
        elif scale_override_active:
            desired_replicas = current_replicas
        elif attack_active is False and clear_streak >= SCALE_DOWN_STREAK_REQUIRED:
            desired_replicas = BASELINE_REPLICAS
        else:
            desired_replicas = current_replicas

        if desired_replicas != current_replicas:
            set_replicas(desired_replicas)

            direction = "up" if desired_replicas > current_replicas else "down"
            MITIGATION_ACTIONS.labels(direction=direction).inc()

            current_replicas = desired_replicas

            with state_lock:
                shared_state["current_replicas"] = current_replicas

        if attack_active is True:
            desired_rate_limit_enabled = True
        elif ratelimit_override_active:
            desired_rate_limit_enabled = rate_limit_enabled
        elif attack_active is False and clear_streak >= SCALE_DOWN_STREAK_REQUIRED:
            desired_rate_limit_enabled = False
        else:
            desired_rate_limit_enabled = rate_limit_enabled

        if desired_rate_limit_enabled != rate_limit_enabled:

            if desired_rate_limit_enabled:
                set_rate_limit(RATE_LIMIT_TARGET_AVERAGE, RATE_LIMIT_TARGET_BURST)

            set_ingress_rate_limit_enabled(desired_rate_limit_enabled)

            direction = "on" if desired_rate_limit_enabled else "off"
            MITIGATION_RATE_LIMIT_ACTIONS.labels(direction=direction).inc()

            rate_limit_enabled = desired_rate_limit_enabled

            with state_lock:
                shared_state["rate_limit_enabled"] = rate_limit_enabled

        MITIGATION_TRAEFIK_REPLICAS.set(current_replicas)
        MITIGATION_RATE_LIMIT_ACTIVE.set(1 if rate_limit_enabled else 0)

        print(
            f"[mitigation] attack={attack_active} streak={clear_streak} "
            f"traefik_replicas={current_replicas} ratelimit={rate_limit_enabled} "
            f"scale_override={scale_override_active} ratelimit_override={ratelimit_override_active}",
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
        shared_state["scale_override_until"] = time.time() + MANUAL_OVERRIDE_SECONDS

    try:
        set_replicas(MAX_REPLICAS)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    with state_lock:
        shared_state["current_replicas"] = MAX_REPLICAS

    MITIGATION_TRAEFIK_REPLICAS.set(MAX_REPLICAS)
    MITIGATION_ACTIONS.labels(direction="up").inc()

    return jsonify({
        "status": "ok",
        "replicas": MAX_REPLICAS,
        "manual_override_seconds": MANUAL_OVERRIDE_SECONDS,
    }), 200


@app.route('/api/manual/ratelimit', methods=['POST'])
def manual_ratelimit():

    data = request.get_json(silent=True) or {}
    average = int(data.get("average", RATE_LIMIT_TARGET_AVERAGE))
    burst = int(data.get("burst", RATE_LIMIT_TARGET_BURST))

    with state_lock:
        shared_state["ratelimit_override_until"] = time.time() + MANUAL_OVERRIDE_SECONDS

    try:
        set_rate_limit(average, burst)
        set_ingress_rate_limit_enabled(True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    with state_lock:
        shared_state["rate_limit_enabled"] = True

    MITIGATION_RATE_LIMIT_ACTIVE.set(1)
    MITIGATION_RATE_LIMIT_ACTIONS.labels(direction="on").inc()

    return jsonify({"status": "ok", "average": average, "burst": burst}), 200


@app.route('/api/manual/scale-down', methods=['POST'])
def manual_scale_down():
    if is_attack_active() is True:
        return jsonify({"error": "DDoS napad je trenutno aktivan. Smanjenje kapaciteta nije dozvoljeno."}), 403

    with state_lock:
        shared_state["scale_override_until"] = time.time() + MANUAL_OVERRIDE_SECONDS

    try:
        set_replicas(BASELINE_REPLICAS)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    with state_lock:
        shared_state["current_replicas"] = BASELINE_REPLICAS

    MITIGATION_TRAEFIK_REPLICAS.set(BASELINE_REPLICAS)
    MITIGATION_ACTIONS.labels(direction="down").inc()

    return jsonify({
        "status": "ok",
        "replicas": BASELINE_REPLICAS,
        "manual_override_seconds": MANUAL_OVERRIDE_SECONDS,
    }), 200


@app.route('/api/manual/ratelimit/reset', methods=['POST'])
def manual_ratelimit_reset():
    if is_attack_active() is True:
        return jsonify({"error": "DDoS napad je aktivan. Ukidanje Rate Limita nije dozvoljeno."}), 403

    with state_lock:
        shared_state["ratelimit_override_until"] = time.time() + MANUAL_OVERRIDE_SECONDS

    try:
        set_ingress_rate_limit_enabled(False)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    with state_lock:
        shared_state["rate_limit_enabled"] = False

    MITIGATION_RATE_LIMIT_ACTIVE.set(0)
    MITIGATION_RATE_LIMIT_ACTIONS.labels(direction="off").inc()

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    mitigation_thread = threading.Thread(target=mitigation_loop, daemon=True)
    mitigation_thread.start()

    app.run(host="0.0.0.0", port=METRICS_PORT, threaded=True)