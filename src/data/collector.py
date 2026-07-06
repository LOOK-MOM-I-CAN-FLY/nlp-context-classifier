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
