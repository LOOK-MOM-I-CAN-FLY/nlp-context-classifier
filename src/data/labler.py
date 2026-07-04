"""
Полуавтоматическая разметка сырых текстов из data/raw/*.jsonl.

Стратегия: сначала keyword matching (auto_label), потом ручная проверка
сомнительных случаев (confidence < 0.7) через CLI (review_uncertain).

Как пользоваться:
    python -m src.data.labeler data/raw/wikipedia.jsonl --output data/labeled/dataset.csv
    (низкоуверенные примеры уйдут в интерактивный обзор в терминале)
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

CONFLICT_KEYWORDS = [
    "war", "attack", "invasion", "missile", "troops", "military",
    "weapons", "sanctions", "bomb", "offensive", "casualties",
    "occupied", "shelling", "ceasefire", "NATO", "frontline",
    "front line", "soldiers", "battalion", "artillery", "strike",
]

NEUTRAL_KEYWORDS = [
    "cuisine", "culture", "tourism", "history", "language",
    "geography", "music", "art", "sport", "recipe", "landscape",
    "museum", "river", "mountains", "literature", "festival",
]


def _count_keyword_hits(text_lower: str, keywords: list[str]) -> int:
    """
    Считает совпадения по границам слов (\\b), а не по вхождению подстроки.
    Наивный `kw in text_lower` ловит "war" внутри "warrior"/"award"/"forward"
    и "art" внутри "part"/"artillery" — такие ложные срабатывания портят разметку.
    """
    return sum(
        1 for kw in keywords
        if re.search(r"\b" + re.escape(kw) + r"\b", text_lower)
    )


def auto_label(text: str) -> tuple[int, float]:
    """
    Возвращает (label, confidence).
    confidence < 0.7 -> нужна ручная проверка (label в этом случае = -1).
    """
    text_lower = text.lower()
    conflict_hits = _count_keyword_hits(text_lower, CONFLICT_KEYWORDS)
    neutral_hits = _count_keyword_hits(text_lower, NEUTRAL_KEYWORDS)

    if conflict_hits >= 2 and neutral_hits == 0:
        return 1, 0.9
    elif neutral_hits >= 2 and conflict_hits == 0:
        return 0, 0.9
    else:
        return -1, 0.0  


def review_uncertain(items: list[dict]) -> list[dict]:
    """
    CLI-интерфейс для ручной разметки сомнительных примеров.
    Показывает текст, ты вводишь 0/1/s (skip).

    Возвращает только те items, что получили лейбл (со skip не возвращаются).
    """
    reviewed: list[dict] = []
    total = len(items)

    for i, item in enumerate(items, start=1):
        print(f"\n[{i}/{total}] {item['text']}")
        choice = input("Класс? (0=нейтральный, 1=конфликт, s=пропустить): ").strip().lower()

        if choice == "1":
            item["label"] = 1
            item["confidence"] = 1.0
            reviewed.append(item)
        elif choice == "0":
            item["label"] = 0
            item["confidence"] = 1.0
            reviewed.append(item)


    return reviewed


def load_raw(path: str) -> list[dict]:
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def label_items(items: list[dict]) -> list[dict]:
    """Прогоняет auto_label по всем items, размечает уверенные, остальные — на ручной обзор."""
    labeled: list[dict] = []
    uncertain: list[dict] = []

    for item in items:
        label, confidence = auto_label(item["text"])
        if label == -1:
            uncertain.append(item)
        else:
            item["label"] = label
            item["confidence"] = confidence
            labeled.append(item)

    print(f"Авто-разметка: {len(labeled)} уверенных, {len(uncertain)} требуют ручной проверки")

    if uncertain:
        labeled.extend(review_uncertain(uncertain))

    return labeled


def save_labeled(items: list[dict], output_path: str) -> None:
    """Дописывает размеченные примеры в CSV (text,label,source,confidence). Дублирует по text не проверяет — это задача EDA-ноутбука."""
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    file_exists = output_file.exists()
    with open(output_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["text", "label", "source", "confidence"])
        for item in items:
            writer.writerow([item["text"], item["label"], item["source"], item["confidence"]])

    print(f"Записано {len(items)} строк в {output_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Разметка сырых текстов ContextWatch")
    parser.add_argument("input", help="Путь к data/raw/*.jsonl")
    parser.add_argument("--output", default="data/labeled/dataset.csv")
    args = parser.parse_args()

    raw_items = load_raw(args.input)
    print(f"Загружено {len(raw_items)} сырых записей из {args.input}")

    labeled = label_items(raw_items)
    save_labeled(labeled, args.output)


if __name__ == "__main__":
    main()
