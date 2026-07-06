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

    for article in data.get("articles", [])[:max_articles]:
        title = (article.get("title") or "").strip()
        description = (article.get("description") or "").strip()
        text = f"{title}. {description}".strip(". ").strip()

        if not text:
            continue

        items.append({
            "text": text,
            "source": "newsapi",
            "query": query,
            "url": article.get("url"),
        })

    return items


# ---------------------------------------------------------------------------
# Источник 2: Reddit (PRAW)
# ---------------------------------------------------------------------------

def fetch_reddit(
    subreddit: str,
    query: str,
    client_id: str,
    client_secret: str,
    limit: int = 100,
) -> list[dict]:
    """
    Тянет посты с Reddit через PRAW: заголовок + первые 2-3 предложения текста поста.

    Возвращает список {"text": ..., "source": "reddit", "subreddit": subreddit, "url": ...}.
    """
    import praw  # локальный импорт: библиотека нужна только для этого источника

    reddit = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=USER_AGENT,
    )

    items: list[dict] = []

    for submission in reddit.subreddit(subreddit).search(query, limit=limit):
        title = (submission.title or "").strip()
        body = (submission.selftext or "").strip()

        # Берём первые 2-3 предложения тела поста
        sentences = split_into_sentences(body)
        snippet = " ".join(sentences[:3])

        text = f"{title}. {snippet}".strip(". ").strip()
        if not text:
            continue

        items.append({
            "text": text,
            "source": "reddit",
            "subreddit": subreddit,
            "url": f"https://reddit.com{submission.permalink}",
        })

    return items


# ---------------------------------------------------------------------------
# Источник 3: Wikipedia
# ---------------------------------------------------------------------------

WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"

# Статьи класса 0 — география, культура, история без военной привязки
WIKIPEDIA_NEUTRAL_TITLES = [
    "Kyiv", "Lviv", "Odesa", "Black Sea", "Carpathian Mountains",
    "Volga River", "Ukrainian cuisine", "Russian cuisine",
    "Ukrainian language", "Russian language", "Saint Basil's Cathedral",
    "Hermitage Museum", "Ukrainian literature", "Russian literature",
    "Borscht", "Ukraine national football team",
    "Moscow", "Saint Petersburg", "Sevastopol", "Crimean Tatars",
    "Taras Shevchenko", "Alexander Pushkin", "Leo Tolstoy",
    "Fyodor Dostoevsky", "FC Shakhtar Donetsk", "FC Dynamo Kyiv",
    "Vyshyvanka", "Varenyky", "Ukrainian Orthodox Church",
    "Tourism in Russia", "Geography of Ukraine", "Geography of Russia",
    "Music of Ukraine", "Russian cinema",
]

# Статьи класса 1 — военный/политический конфликт
WIKIPEDIA_CONFLICT_TITLES = [
    "Russian invasion of Ukraine", "Russo-Ukrainian War",
    "Battle of Bakhmut", "Siege of Mariupol", "War in Donbas",
    "International sanctions during the Russo-Ukrainian War",
    "Battle of Avdiivka", "Wagner Group",
    "Timeline of the Russian invasion of Ukraine (2022)",
    "Casualties of the Russo-Ukrainian War",
    "Humanitarian impact of the Russian invasion of Ukraine",
    "War crimes in the Russian invasion of Ukraine",
    "Refugees of the Russian invasion of Ukraine",
    "Sanctions against Russia following the invasion of Ukraine",
    "Battle of Kherson (2022)", "Battle of Soledar",
    "Kharkiv counteroffensive", "Battle of Kyiv (2022)",
]


def split_into_sentences(text: str) -> list[str]:
    """Грубое разбиение текста на предложения по точке/!/? с учётом пробела после."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-ZА-Я])", text)
    return [s.strip() for s in sentences if s.strip()]


def fetch_wikipedia(title: str, expected_label_hint: str) -> list[dict]:
    """
    Тянет plaintext-экстракт статьи Wikipedia и режет на предложения.

    expected_label_hint: "conflict" или "neutral" — только для метаданных,
    финальный лейбл всё равно выставляет labeler.auto_label().

    Возвращает список {"text": ..., "source": "wikipedia", "title": title, "hint": ...}.
    """
    params = {
        "action": "query",
        "prop": "extracts",
        "explaintext": 1,
        "format": "json",
        "titles": title,
    }
    headers = {"User-Agent": USER_AGENT}

    for attempt in range(3):
        response = requests.get(WIKIPEDIA_API_URL, params=params, headers=headers, timeout=15)
        if response.status_code == 429:
            time.sleep(5 * (attempt + 1))  # backoff при 429 Too Many Requests
            continue
        response.raise_for_status()
        break
    else:
        response.raise_for_status()

    pages = response.json().get("query", {}).get("pages", {})

    items: list[dict] = []
    for page in pages.values():
        extract = page.get("extract", "")
        for sentence in split_into_sentences(extract):
            word_count = len(sentence.split())
            if 8 <= word_count <= 40 and "==" not in sentence:
                items.append({
                    "text": sentence,
                    "source": "wikipedia",
                    "title": title,
                    "hint": expected_label_hint,
                })

    return items


def collect_wikipedia_all() -> list[dict]:
    """Собирает предложения со всех сконфигурированных статей Wikipedia."""
    items: list[dict] = []
    for title in WIKIPEDIA_NEUTRAL_TITLES:
        items.extend(fetch_wikipedia(title, "neutral"))
        time.sleep(2.0)  # вежливая задержка между запросами к API
    for title in WIKIPEDIA_CONFLICT_TITLES:
        items.extend(fetch_wikipedia(title, "conflict"))
        time.sleep(2.0)
    return items


# ---------------------------------------------------------------------------
# Сохранение
# ---------------------------------------------------------------------------

def save_raw(items: list[dict], filename: str) -> None:
    """Сохраняет список словарей в data/raw/{filename}.jsonl (append не делает, перезаписывает)."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"{filename}.jsonl"

    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"Сохранено {len(items)} записей в {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Сбор сырых текстов для ContextWatch")
    sub = parser.add_subparsers(dest="source", required=True)

    p_wiki = sub.add_parser("wikipedia", help="Собрать предложения из статей Wikipedia (без ключа)")
    p_wiki.add_argument("--output", default="wikipedia", help="Имя выходного файла (без .jsonl)")

    p_news = sub.add_parser("newsapi", help="Собрать статьи NewsAPI")
    p_news.add_argument("--api-key", help="Ключ NewsAPI (по умолчанию берётся из NEWS_API_KEY в .env)")
    p_news.add_argument("--max-articles", type=int, default=100)
    p_news.add_argument("--output", default="newsapi")

    p_reddit = sub.add_parser("reddit", help="Собрать посты с Reddit")
    p_reddit.add_argument("--client-id", help="Reddit client_id (по умолчанию из REDDIT_CLIENT_ID в .env)")
    p_reddit.add_argument("--client-secret", help="Reddit client_secret (по умолчанию из REDDIT_CLIENT_SECRET в .env)")
    p_reddit.add_argument("--subreddits", nargs="+", default=["worldnews", "europe", "history", "travel"])
    p_reddit.add_argument("--query", default="Ukraine Russia")
    p_reddit.add_argument("--limit", type=int, default=100)
    p_reddit.add_argument("--output", default="reddit")

    args = parser.parse_args()
    load_env_file()  # подхватываем ключи из .env, если он есть

    if args.source == "wikipedia":
        items = collect_wikipedia_all()
        save_raw(items, args.output)

    elif args.source == "newsapi":
        api_key = args.api_key or os.getenv("NEWS_API_KEY")
        if not api_key:
            parser.error("нет ключа NewsAPI: передай --api-key или добавь NEWS_API_KEY=... в .env")

        items: list[dict] = []
        for query in CONFLICT_QUERIES + NEUTRAL_QUERIES:
            try:
                new_items = fetch_newsapi(query, api_key, args.max_articles)
                print(f"  '{query}': +{len(new_items)}")
                items.extend(new_items)
            except Exception as e:
                # один упавший запрос (таймаут/лимит) не должен ронять весь сбор
                print(f"  [warn] запрос '{query}' пропущен: {e}")
        save_raw(items, args.output)

    elif args.source == "reddit":
        client_id = args.client_id or os.getenv("REDDIT_CLIENT_ID")
        client_secret = args.client_secret or os.getenv("REDDIT_CLIENT_SECRET")
        if not client_id or not client_secret:
            parser.error("нет Reddit-кредов: передай --client-id/--client-secret или добавь "
                         "REDDIT_CLIENT_ID=... и REDDIT_CLIENT_SECRET=... в .env")

        items = []
        for subreddit in args.subreddits:
            items.extend(fetch_reddit(
                subreddit, args.query, client_id, client_secret, args.limit
            ))
        save_raw(items, args.output)


if __name__ == "__main__":
    main()
