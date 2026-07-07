"""
Полуавтоматическая разметка сырых текстов из data/raw/*.jsonl.

Идея:
1) Сначала авторазметка по весовым keyword-сигналам.
2) Всё, что не добирает уверенность, уходит в uncertain.csv
   и при желании может быть вручную просмотрено.

Запуск:
    python -m src.data.labeler data/raw/wikipedia.jsonl \
        --output data/labeled/dataset.csv \
        --uncertain-output data/labeled/uncertain.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Iterable


# Более сильные сигналы имеют вес 2, слабые — вес 1.
# Важно: тут нет слова Kyiv в нейтральной категории — оно слишком шумное.
CONFLICT_TERMS: dict[str, int] = {
    "war": 2,
    "attack": 2,
    "attacks": 2,
    "invasion": 2,
    "invaded": 2,
    "invade": 2,
    "missile": 2,
    "missiles": 2,
    "troop": 2,
    "troops": 2,
    "military": 2,
    "weapon": 2,
    "weapons": 2,
    "sanction": 1,
    "sanctions": 1,
    "bomb": 2,
    "bombing": 2,
    "offensive": 1,
    "casualty": 2,
    "casualties": 2,
    "occupied": 1,
    "occupation": 2,
    "shelling": 2,
    "ceasefire": 1,
    "nato": 1,
    "frontline": 2,
    "front line": 2,
    "soldier": 1,
    "soldiers": 1,
    "battalion": 1,
    "artillery": 1,
    "strike": 1,
    "strikes": 1,
    "drone strike": 2,
    "airstrike": 2,
    "air strikes": 2,
    "killed": 1,
    "killing": 1,
    "dead": 1,
    "annexation": 2,
    "mobilization": 2,
    "hostilities": 2,
    "combat": 1,
    "militia": 1,
    "crossfire": 1,
    "explosion": 1,
    "explosions": 1,
    "evacuation": 1,
    "curfew": 1,
}


NEUTRAL_TERMS: dict[str, int] = {
    "cuisine": 2,
    "culture": 1,
    "tourism": 1,
    "history": 1,
    "language": 1,
    "geography": 2,
    "music": 1,
    "art": 1,
    "sports": 1,
    "sport": 1,
    "recipe": 2,
    "landscape": 1,
    "museum": 1,
    "river": 1,
    "rivers": 1,
    "mountain": 1,
    "mountains": 1,
    "literature": 1,
    "festival": 1,
    "festivals": 1,
    "economy": 1,
    "education": 1,
    "transport": 1,
    "climate": 2,
    "flora": 1,
    "fauna": 1,
    "demography": 2,
    "architecture": 1,
    "religion": 1,
    "film": 1,
    "novel": 1,
    "university": 1,
    "science": 1,
    "technology": 1,
    "industry": 1,
    "population": 1,
    "district": 1,
    "province": 1,
}


def _normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _build_pattern(term: str) -> re.Pattern[str]:
    """
    Делает шаблон с границами слов.
    Для фраз с пробелами тоже работает нормально.
    """
    escaped = re.escape(term.lower())
    return re.compile(rf"\b{escaped}\b", re.IGNORECASE)


def _compile_terms(terms: dict[str, int]) -> list[tuple[re.Pattern[str], int, str]]:
    compiled: list[tuple[re.Pattern[str], int, str]] = []
    # Сначала длинные фразы, потом короткие слова — так меньше шума.
    for term, weight in sorted(terms.items(), key=lambda x: (-len(x[0]), -x[1], x[0])):
        compiled.append((_build_pattern(term), weight, term))
    return compiled


CONFLICT_PATTERNS = _compile_terms(CONFLICT_TERMS)
NEUTRAL_PATTERNS = _compile_terms(NEUTRAL_TERMS)


def _score(text: str, patterns: list[tuple[re.Pattern[str], int, str]]) -> tuple[int, list[str]]:
    """
    Возвращает сумму весов и список сработавших терминов.
    """
    score = 0
    hits: list[str] = []
    for pattern, weight, term in patterns:
        if pattern.search(text):
            score += weight
            hits.append(term)
    return score, hits


def build_search_text(item: dict) -> str:
    """
    Склеивает полезные поля в один текст.
    Если в jsonl есть title/section/heading — они тоже помогают.
    """
    parts: list[str] = []
    for key in ("title", "heading", "section", "text", "content"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return _normalize_text("\n".join(parts))


def auto_label(text: str) -> tuple[int, float, str]:
    """
    Возвращает:
        label: 0/1 или -1 если неуверенно
        confidence: 0.0..1.0
        reason: краткое объяснение решения

    Логика:
    - считаем конфликтные и нейтральные сигналы;
    - если одна сторона явно сильнее другой — ставим метку;
    - иначе отправляем в uncertain.
    """
    conflict_score, conflict_hits = _score(text, CONFLICT_PATTERNS)
    neutral_score, neutral_hits = _score(text, NEUTRAL_PATTERNS)

    if conflict_score == 0 and neutral_score == 0:
        return -1, 0.0, "no_signals"

    margin = abs(conflict_score - neutral_score)
    total = conflict_score + neutral_score

    # Порог можно крутить:
    # - MIN_SCORE = 2 даёт хороший баланс
    # - если хочешь ещё больше строк, снизь до 1
    MIN_SCORE = 2
    MIN_MARGIN = 1

    if conflict_score >= MIN_SCORE and conflict_score > neutral_score and margin >= MIN_MARGIN:
        confidence = min(0.55 + 0.10 * conflict_score - 0.03 * neutral_score, 0.98)
        return 1, round(confidence, 3), f"conflict:{','.join(conflict_hits)}"

    if neutral_score >= MIN_SCORE and neutral_score > conflict_score and margin >= MIN_MARGIN:
        confidence = min(0.55 + 0.10 * neutral_score - 0.03 * conflict_score, 0.98)
        return 0, round(confidence, 3), f"neutral:{','.join(neutral_hits)}"

    # Если есть один очень сильный сигнал и почти нет шума — тоже можно доверять.
    strong_conflict = any(term in conflict_hits for term in ("war", "invasion", "shelling", "airstrike", "drone strike", "occupation"))
    strong_neutral = any(term in neutral_hits for term in ("cuisine", "geography", "climate", "demography", "recipe"))

    if strong_conflict and conflict_score >= 2 and conflict_score >= neutral_score:
        confidence = min(0.70 + 0.06 * conflict_score, 0.99)
        return 1, round(confidence, 3), f"strong_conflict:{','.join(conflict_hits)}"

    if strong_neutral and neutral_score >= 2 and neutral_score >= conflict_score:
        confidence = min(0.70 + 0.06 * neutral_score, 0.99)
        return 0, round(confidence, 3), f"strong_neutral:{','.join(neutral_hits)}"

    # Слишком близко — лучше не гадать.
    # Чем больше общий сигнал и чем меньше разница, тем ниже уверенность.
    confidence = max(0.15, min(0.65, 0.35 + 0.08 * total - 0.10 * margin))
    return -1, round(confidence, 3), f"ambiguous:c={conflict_score},n={neutral_score}"


def load_raw(path: str) -> list[dict]:
    items: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if isinstance(obj, dict):
                items.append(obj)
    return items


def label_items(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Возвращает:
        labeled_items — уверенно размеченные
        uncertain_items — то, что лучше проверить отдельно
    """
    labeled: list[dict] = []
    uncertain: list[dict] = []

    for item in items:
        text = build_search_text(item)
        label, confidence, reason = auto_label(text)

        prepared = dict(item)
        prepared["text"] = item.get("text", "")  # гарантируем наличие поля
        prepared["label"] = label
        prepared["confidence"] = confidence
        prepared["reason"] = reason

        if label == -1:
            uncertain.append(prepared)
        else:
            labeled.append(prepared)

    return labeled, uncertain


def save_csv(items: list[dict], output_path: str, *, include_reason: bool = False) -> None:
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["text", "label", "source", "confidence"]
    if include_reason:
        fieldnames.append("reason")

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for item in items:
            row = {
                "text": item.get("text", ""),
                "label": item.get("label", ""),
                "source": item.get("source", "wikipedia"),
                "confidence": item.get("confidence", ""),
            }
            if include_reason:
                row["reason"] = item.get("reason", "")
            writer.writerow(row)


def print_stats(labeled: list[dict], uncertain: list[dict]) -> None:
    total = len(labeled) + len(uncertain)
    conflict = sum(1 for x in labeled if x.get("label") == 1)
    neutral = sum(1 for x in labeled if x.get("label") == 0)

    print("\n=== Разметка завершена ===")
    print(f"Всего строк:        {total}")
    print(f"Размечено уверенно:  {len(labeled)}")
    print(f"  - конфликт:        {conflict}")
    print(f"  - нейтральные:     {neutral}")
    print(f"Сомнительные:       {len(uncertain)}")
    if total:
        print(f"Coverage:           {len(labeled) / total:.1%}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Разметка сырых текстов ContextWatch")
    parser.add_argument("input", help="Путь к data/raw/*.jsonl")
    parser.add_argument("--output", default="data/labeled/dataset.csv", help="Путь для размеченного CSV")
    parser.add_argument(
        "--uncertain-output",
        default="data/labeled/uncertain.csv",
        help="Путь для сомнительных примеров",
    )
    args = parser.parse_args()

    raw_items = load_raw(args.input)
    print(f"Загружено {len(raw_items)} сырых записей из {args.input}")

    labeled, uncertain = label_items(raw_items)
    save_csv(labeled, args.output, include_reason=False)
    save_csv(uncertain, args.uncertain_output, include_reason=True)

    print_stats(labeled, uncertain)
    print(f"Размеченные строки сохранены в: {args.output}")
    print(f"Сомнительные строки сохранены в: {args.uncertain_output}")


if __name__ == "__main__":
    main()
