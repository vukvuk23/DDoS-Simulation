from gunicorn.workers.sync import SyncWorker
from prometheus_client import Gauge

BUSY_WORKERS = Gauge(
    'workers_busy',
    'Number of Gunicorn workers that are busy right now',
    namespace='target',
    multiprocess_mode='livesum'
)

class InstrumentedSyncWorker(SyncWorker):
    def handle(self, listener, client, addr): # override SyncWorker handle fje
        BUSY_WORKERS.inc()
        try:
            super().handle(listener, client, addr)
        finally:
            BUSY_WORKERS.dec()
# TODO: manuelno testiranje DoSa