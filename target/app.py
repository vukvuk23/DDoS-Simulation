import os
import time
from flask import Flask, jsonify, render_template, request
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST, CollectorRegistry, multiprocess

app = Flask(__name__)

# --------- PROMETHEUS ---------
REQUEST_COUNT = Counter(
    'requests_total', 
    'Total requests', 
    labelnames=['method', 'endpoint', 'status'], 
    namespace='target', 
    subsystem='http'
    )

ACTIVE_CONNECTIONS = Gauge(
    'connections_active',
    'Active HTTP connections',
    namespace='target', 
    subsystem='http',
    multiprocess_mode='livesum'
)

REQUEST_DURATION = Histogram( # da li su zahtevi brzi ili spori
    'request_duration_seconds',
    'HTTP request latency',
    labelnames=['endpoint'],
    namespace='target',
    subsystem='http',
    buckets=[.01, .05, .1, .5, 1, 5, 10, 30, 60, 120]
)

WORKER_POOL_SIZE = Gauge( # kontekst, da li je 3 od 4 kriticno ?
    'worker_pool_size',
    'Max number of concurent workers',
    multiprocess_mode='max'
)
WORKER_POOL_SIZE.set(int(os.environ.get("GUNICORN_WORKERS", 4))) # kada workeri importuju app.py, svaki od njih dobije ovu vrednost, zato mora max

# --------- MIDDLEWARE ---------
# vreme kada je zahtev stigao, ali pre nego sto je pocela da se obradjuje konkretna ruta
# zahev stize ceo, vec isparsiran od strane wsgi sloja
@app.before_request 
def before_request():
    request.start_time = time.time() # moze novo polje start_time da se doda u obj u hodu
    ACTIVE_CONNECTIONS.inc()

@app.after_request
def after_request(response):
    duration = time.time() - request.start_time
    REQUEST_DURATION.labels(endpoint=request.endpoint).observe(duration)
    REQUEST_COUNT.labels(method=request.method, endpoint=request.endpoint, status=response.status_code).inc() # pre inc/observe mora se navedu lble
    ACTIVE_CONNECTIONS.dec()
    return response


# --------- APP LOGIC ---------
PRODUCTS = [
    {"id": 1, "name": "Laptop", "price": 999.99},
    {"id": 2, "name": "Keyboard", "price": 49.99},
    {"id": 3, "name": "Monitor", "price": 99.99}
]

@app.route('/')
def index():
    return render_template('index.html', products=PRODUCTS)


@app.route('/api/products')
def get_products():
    return jsonify(PRODUCTS)

@app.route('/api/products/<int:id>')
def get_product(id):
    product = next((prod for prod in PRODUCTS if prod["id"]==id), None)

    if product is None:
        return jsonify({"error": "Product is not found!"}), 404
    
    return jsonify(product) 

@app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

@app.route('/metrics')
def metrics():
    registry = CollectorRegistry() # novi registar, a ne globalni podrazumevani
    multiprocess.MultiProcessCollector(registry) # cita sve iz .db fajlova iz PROMETHEUS_MULTIPROC_DIR i upisuje u registry
    return generate_latest(registry), 200, {"Content-Type": CONTENT_TYPE_LATEST} 
# formatiranje za Prometheus i Prometheus tekstualni format
# ako je generate_latest bez arg onda cita iz podrazumevanog globalnog registra

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)