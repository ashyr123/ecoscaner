import random
import string
import time

_active_tokens: dict[int, tuple[str, float]] = {}

def generate_token(user_id: int) -> str:
    token = "ECO-" + "".join(random.choices(string.digits, k=4))
    _active_tokens[user_id] = (token, time.time())
    return token

def get_active_token(user_id: int) -> str | None:
    data = _active_tokens.get(user_id)
    if not data:
        return None
    token, ts = data
    if time.time() - ts > 300:  # 5 dakika
        del _active_tokens[user_id]
        return None
    return token

def consume_token(user_id: int) -> bool:
    if user_id in _active_tokens:
        del _active_tokens[user_id]
        return True
    return False