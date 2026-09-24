import time

_last_alert = 0
COOLDOWN = 2.0


def trigger_alert(message="ALERT: CHAM TRANH"):
    global _last_alert

    now = time.time()

    if now - _last_alert < COOLDOWN:
        return False

    print(f"\033[91m{message}\033[0m", flush=True)
    _last_alert = now
    return True
