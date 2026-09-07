import time
import random
import requests

TARGET_HOST = "target.local"          
LEGIT_ROUTES = ["/", "/api/products", "/api/products/1", "/api/products/2", "/api/products/3"]

UPLOAD_ROUTE = "/api/upload" # izdvojena, zahteva telo

UPLOAD_PROBABILITY = 0.1


def main():

    while True: 

        wait_time = random.expovariate(1 / 30) # 30 je prosek kroz mnogo poziva, wait time ce biti br koji prati eksp rasp
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

if __name__ == "__main__":
    main()