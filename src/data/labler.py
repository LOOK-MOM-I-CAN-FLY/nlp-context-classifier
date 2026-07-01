CONFLICT_KEYWORDS = [
    "war", "attack", "invasion", "missile", "troops", "military",
    "weapons", "sanctions", "bomb", "offensive", "casualties",
    "occupied", "shelling", "ceasefire", "NATO", "frontline"
]

NEUTRAL_KEYWORDS = [
    "cuisine", "culture", "tourism", "history", "language",
    "geography", "music", "art", "sport", "recipe", "landscape"
]

def auto_label(text: str) -> tuple[int, float]:
    """
    Возвращает (label, confidence).
    confidence < 0.7 → нужна ручная проверка.
    """
    text_lower = text.lower()
    conflict_hits = sum(1 for kw in CONFLICT_KEYWORDS if kw in text_lower)
    neutral_hits = sum(1 for kw in NEUTRAL_KEYWORDS if kw in text_lower)
    
    if conflict_hits >= 2 and neutral_hits == 0:
        return 1, 0.9
    elif neutral_hits >= 2 and conflict_hits == 0:
        return 0, 0.9
    else:
        return -1, 0.0  # нужна ручная разметка

def review_uncertain(items: list[dict]) -> list[dict]:
    """
    CLI-интерфейс для ручной разметки сомнительных примеров.
    Показывает текст, ты вводишь 0/1/s (skip).
    """
    ...
