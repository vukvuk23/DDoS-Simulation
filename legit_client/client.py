import os
import time
import random
import threading
import requests

TARGET_HOST = "target.local"          
LEGIT_ROUTES = ["/", "/api/products", "/api/products/1", "/api/products/2", "/api/products/3"]

UPLOAD_ROUTE = "/api/upload" # izdvojena, zahteva telo

UPLOAD_PROBABILITY = 0.1

NUM_VIRTUAL_USERS = int(os.environ.get("NUM_VIRTUAL_USERS", 50)) 


def simulate_user():

    while True: 

        wait_time = random.expovariate(1 / 8) # 8 je prosek kroz mnogo poziva, wait time ce biti br koji prati eksp rasp
        time.sleep(wait_time) # zavrsava izvrsavanje na zadat br s

        number_of_clicks = random.randint(1, 4) 

        for _ in range(number_of_clicks):

            if random.random() < UPLOAD_PROBABILITY:
                # vraca rand iz 0.0 - 1.0
                try:
                    requests.post(
                        "http://host.docker.internal" + UPLOAD_ROUTE,
                        headers={"Host": TARGET_HOST},
                        timeout=5,
                    )
                except requests.exceptions.RequestException:
                    pass 

            else:
                route = random.choice(LEGIT_ROUTES)

                try:
                    requests.get(
                        "http://host.docker.internal" + route,   
                        headers={"Host": TARGET_HOST},
                        timeout=5,
                    )
                except requests.exceptions.RequestException:
                    pass  

            time.sleep(random.uniform(0.5, 3))   


def main(): 

    for _ in range(NUM_VIRTUAL_USERS): 
        t = threading.Thread(target=simulate_user, daemon=True) 
        t.start() # pokreni odmah

    while True: # glavna nit samo spava zauvek dok pozadinske niti rade posao
        time.sleep(60)


if __name__ == "__main__":
    main()