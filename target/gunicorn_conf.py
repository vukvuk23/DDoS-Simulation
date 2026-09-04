import os
from prometheus_client import multiprocess

workers = int(os.environ.get('GUNICORN_WORKERS', 4))

worker_class = 'worker.InstrumentedSyncWorker'

timeout = 120 # prisilno gasenje i podizanje novog workera ako ne daje znake zivota

bind = "0.0.0.0:5000"

def child_exit(server, worker):
    multiprocess.mark_process_dead(worker.pid)
