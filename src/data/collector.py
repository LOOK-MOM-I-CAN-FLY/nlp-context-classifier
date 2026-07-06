"""
Сбор сырых текстов из нескольких источников для датасета ContextWatch.

Источники:
  - NewsAPI   (https://newsapi.org/, нужен API-ключ, free tier: 100 запросов/день)
  - Reddit    (через PRAW, нужны client_id/client_secret: https://www.reddit.com/prefs/apps)
  - Wikipedia (без ключа, через REST API extracts)

Все источники сохраняют в одинаковый формат:
    {"text": "...", "source": "newsapi" | "reddit" | "wikipedia", ...}

Как пользоваться:
    python -m src.data.collector wikipedia
    python -m src.data.collector newsapi --api-key YOUR_KEY
    python -m src.data.collector reddit --client-id ID --client-secret SECRET

Подробное объяснение техник скрапинга/парсинга — в docs/guides/scraping_guide.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

import requests

RAW_DIR = Path("data/raw")


def load_env_file(path: str = ".env") -> None:
    """
    Читает .env (строки вида KEY=VALUE) в переменные окружения.
    Уже заданные переменные не перезаписываем. Нужен, чтобы не передавать
    ключи руками через --api-key: положил NEWS_API_KEY=... в .env и запустил.
    """
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

USER_AGENT = "ContextWatch-DataCollector/1.0 (educational NLP project)"

NEWSAPI_URL = "https://newsapi.org/v2/everything"

# Ключевые слова для класса 1 (политизированный/военный контекст)
CONFLICT_QUERIES = [
    "Russia Ukraine war",
    "missile strike Ukraine",
    "Russian invasion",
    "Ukraine sanctions",
    "front line Ukraine",
]

# Ключевые слова для класса 0 (нейтральный контекст)
NEUTRAL_QUERIES = [
    "Ukrainian cuisine",
    "Russia geography",
    "Kyiv tourism",
    "Ukrainian culture",
    "Russian literature",
]


def fetch_newsapi(query: str, api_key: str, max_articles: int = 100) -> list[dict]:
    """
    Тянет статьи NewsAPI по поисковому запросу.

    Возвращает список {"text": ..., "source": "newsapi", "query": query, "url": ...}.
    "text" собирается из title + description, т.к. полный текст статьи
    NewsAPI free tier не отдаёт.
    """
    items: list[dict] = []
    page_size = min(max_articles, 100)  # лимит NewsAPI на страницу

    params = {
        "q": query,
        "language": "en",
        "sortBy": "relevancy",
        "pageSize": page_size,
        "apiKey": api_key,
    }

    for attempt in range(3):
        try:
            response = requests.get(NEWSAPI_URL, params=params, timeout=30)
        except requests.exceptions.Timeout:
            if attempt < 2:
                time.sleep(3 * (attempt + 1))  # медленный ответ — ждём и пробуем снова
                continue
            raise
        if response.status_code == 429:
            time.sleep(5 * (attempt + 1))  # backoff при 429 Too Many Requests
            continue
        response.raise_for_status()
        break
    else:
        response.raise_for_status()

    data = response.json()
    if data.get("status") == "error":
        # NewsAPI отдаёт ошибки как JSON: неверный ключ, превышен лимит и т.п.
        raise RuntimeError(f"NewsAPI error [{data.get('code')}]: {data.get('message')}")
