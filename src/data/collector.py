import requests
import json
from pathlib import Path

RAW_DIR = Path("data/raw")

def fetch_newsapi(query: str, api_key: str, max_articles: int = 100) -> list[dict]:
    """Возвращает список {"text": ..., "source": "newsapi", "query": query}"""
    ...

def fetch_reddit(subreddit: str, query: str, limit: int = 100) -> list[dict]:
    """Возвращает список {"text": ..., "source": "reddit", "subreddit": subreddit}"""
    ...

def save_raw(items: list[dict], filename: str) -> None:
    """Сохраняет в data/raw/{filename}.jsonl"""
    ...
