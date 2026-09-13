import os
import threading
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send" # url expa na koji se sa tokenom mobilnog salje push notif ka fcmu

registered_tokens = set()
tokens_lock = threading.Lock()


@app.route('/api/register', methods=['POST']) # mobilna app pokrece jednom na pocektu kad dobije expo token
def register_device():

    data = request.get_json(silent=True) or {}
    push_token = data.get('push_token')

    if not push_token:
        return jsonify({"error": "push_token je obavezan"}), 400

    with tokens_lock:
        registered_tokens.add(push_token)

    print(f"[notifier] registrovan token, ukupno uredjaja: {len(registered_tokens)}", flush=True)

    return jsonify({"status": "registrovan", "total_devices": len(registered_tokens)}), 200


def send_expo_push(title, body):

    with tokens_lock:
        tokens = list(registered_tokens)

    if not tokens: # ako je prazan nema sta da se salje
        print("[notifier] nema registrovanih uredjaja, notifikacija se ne salje", flush=True)
        return

    messages = [ # moze imati vise poruka za vise telefona
        {
            "to": token,
            "sound": "default",
            "title": title,
            "body": body,
            "priority": "high",
        }
        for token in tokens
    ]

    try:
        response = requests.post(
            EXPO_PUSH_URL,
            json=messages,
            headers={ # sadrzi ono sto expo dokumentacija trazi 
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate",
                "Content-Type": "application/json",
            },
            timeout=5,
        )
        print(f"[notifier] Expo odgovor: {response.status_code} {response.text}", flush=True)
    except requests.exceptions.RequestException as e:
        print(f"[notifier] slanje ka Expo nije uspelo: {e}", flush=True)


@app.route('/webhook/grafana', methods=['POST']) # poziva grafana autoamtski kad njeno alert pravilo promeni stanje
def grafana_webhook():

    payload = request.get_json(force=True, silent=True) or {}

    alerts = payload.get('alerts', []) # prihvata listu alarma ako ih ima vise

    for alert in alerts:

        status = alert.get('status')
        labels = alert.get('labels', {})
        annotations = alert.get('annotations', {})

        alertname = labels.get('alertname', 'DDoS alarm')

        if status == 'firing':
            title = "\u26a0\ufe0f DDoS napad detektovan"
            body = annotations.get('summary', alertname)
        elif status == 'resolved':
            title = "\u2705 Napad zavrsen"
            body = f"{alertname} vise nije aktivan"
        else:
            continue

        send_expo_push(title, body)

    return jsonify({"status": "primljeno"}), 200


@app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("NOTIFIER_HTTP_PORT", 9000))
    app.run(host="0.0.0.0", port=port, threaded=True)