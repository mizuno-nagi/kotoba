import json
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path


SOURCE_URL_PATTERN = re.compile(r"\[原文链接\]\(([^)]+)\)")
PUB_DATE_PATTERN = re.compile(r"🕐\s*([^\s|]+)")
FAILURE_MARKER = "⚠️ 注释生成失败"
LEGACY_FAILURE_TEXT = "本次注释生成失败"


def first_title(raw):
    for line in (raw or "").splitlines():
        if line.startswith("# "):
            return re.sub(r"^\d+\.\s+", "", line[2:].strip())
    return ""


def first_summary(raw):
    lines = (raw or "").splitlines()
    started = False
    collected = []
    for line in lines:
        stripped = line.strip()
        if stripped == "## 原文":
            started = True
            continue
        if started:
            if stripped.startswith("#"):
                break
            if stripped.startswith("![") or stripped.startswith("- !["):
                continue
            if stripped:
                collected.append(stripped)
            elif collected:
                break
    return " ".join(" ".join(collected).split())[:140]


def parse_article(date, path, raw, source_info, region=None, period=None):
    source_id = source_info.get("id", "custom")
    markers = (
        ("## 翻译", "翻译"),
        ("四级翻译", "翻译"),
        ("六级翻译", "翻译"),
        ("重点词汇", "词汇"),
        ("难句解析", "难句"),
        ("背景补充", "背景"),
    )
    tags = [label for marker, label in markers if marker in raw]
    match = SOURCE_URL_PATTERN.search(raw)
    pub_match = PUB_DATE_PATTERN.search(raw)
    status = "error" if (FAILURE_MARKER in raw or LEGACY_FAILURE_TEXT in raw) else "ok"
    return {
        "date": date,
        "path": Path(path),
        "title": first_title(raw),
        "summary": first_summary(raw),
        "tags": tags,
        "raw": raw,
        "source_url": match.group(1) if match else "",
        "pub_date": pub_match.group(1) if pub_match else date,
        "source": source_id,
        "source_name": source_info.get("name") or source_id,
        "source_config": {
            "id": source_id,
            "name": source_info.get("name") or source_id,
            "region": region or source_info.get("region", "news"),
            "period": period or source_info.get("period", "daily"),
        },
        "region": region or source_info.get("region", "news"),
        "period": period or source_info.get("period", "daily"),
        "status": status,
        "error": "注释生成失败" if status == "error" else "",
    }


class ArticleIndex:
    def __init__(self, db_path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self):
        with self._lock:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS articles (
                    path TEXT PRIMARY KEY,
                    date TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    region TEXT NOT NULL,
                    period TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    pub_date TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ok',
                    error TEXT NOT NULL DEFAULT '',
                    raw TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_articles_region_date ON articles(region, date)"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_articles_source_date ON articles(source_id, date)"
            )
            self.conn.commit()

    def _article_row(self, article):
        updated_at = article.get("updated_at")
        if not updated_at:
            updated_at = datetime.now().isoformat(timespec="seconds")
        return (
            str(Path(article["path"]).resolve()),
            article.get("date", ""),
            article.get("title", ""),
            article.get("summary", ""),
            article.get("source", article.get("source_id", "")),
            article.get("source_name", ""),
            article.get("region", "news"),
            article.get("period", "daily"),
            article.get("source_url", ""),
            article.get("pub_date", article.get("date", "")),
            json.dumps(article.get("tags", []), ensure_ascii=False),
            article.get("status", "ok"),
            article.get("error", ""),
            article.get("raw", ""),
            updated_at,
        )

    def upsert(self, article):
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO articles (
                    path, date, title, summary, source_id, source_name, region, period,
                    source_url, pub_date, tags, status, error, raw, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    date=excluded.date,
                    title=excluded.title,
                    summary=excluded.summary,
                    source_id=excluded.source_id,
                    source_name=excluded.source_name,
                    region=excluded.region,
                    period=excluded.period,
                    source_url=excluded.source_url,
                    pub_date=excluded.pub_date,
                    tags=excluded.tags,
                    status=excluded.status,
                    error=excluded.error,
                    raw=excluded.raw,
                    updated_at=excluded.updated_at
                """,
                self._article_row(article),
            )
            self.conn.commit()

    def remove(self, path):
        with self._lock:
            self.conn.execute(
                "DELETE FROM articles WHERE path = ?",
                (str(Path(path).resolve()),),
            )
            self.conn.commit()

    def remove_region(self, region):
        with self._lock:
            self.conn.execute(
                "DELETE FROM articles WHERE region = ?",
                (region,),
            )
            self.conn.commit()

    def list_articles(self, include_raw=True):
        select_sql = (
            "SELECT * FROM articles"
            if include_raw
            else "SELECT path, date, title, summary, source_id, source_name, region, period, source_url, pub_date, tags, status, error, '' AS raw, updated_at FROM articles"
        )
        with self._lock:
            rows = self.conn.execute(
                select_sql + " ORDER BY region, updated_at DESC, path"
            ).fetchall()
        articles = []
        for row in rows:
            item = dict(row)
            item["path"] = Path(item["path"])
            item["tags"] = json.loads(item["tags"] or "[]")
            source_id = item.pop("source_id")
            source_name = item["source_name"]
            region = item["region"]
            period = item["period"]
            item["source"] = source_id
            item["source_config"] = {
                "id": source_id,
                "name": source_name,
                "region": region,
                "period": period,
            }
            articles.append(item)
        return articles

    def get_raw(self, path):
        with self._lock:
            row = self.conn.execute(
                "SELECT raw FROM articles WHERE path = ?",
                (str(Path(path).resolve()),),
            ).fetchone()
        return row["raw"] if row else ""

    def sync_from_disk(self, output_dir, config_sources=None):
        output_dir = Path(output_dir)
        source_map = {}
        for source in config_sources or []:
            if isinstance(source, dict) and source.get("id"):
                source_map[source["id"]] = source

        if not output_dir.is_dir():
            return 0

        seen = set()
        count = 0

        def parse_file(path, date, source_info, region, period):
            nonlocal count
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return
            normalized = str(path.resolve())
            if normalized in seen:
                return
            seen.add(normalized)
            article = parse_article(date, path, raw, source_info, region, period)
            try:
                article["updated_at"] = datetime.fromtimestamp(
                    path.stat().st_mtime
                ).isoformat(timespec="seconds")
            except OSError:
                pass
            self.upsert(article)
            count += 1

        for root in sorted(output_dir.iterdir()):
            if root.is_file():
                continue
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", root.name):
                source_info = source_map.get(
                    "nhk",
                    {"id": "nhk", "name": "NHK WORLD", "region": "news", "period": "daily"},
                )
                for path in sorted(root.glob("*.md")):
                    if path.name != "index.md":
                        parse_file(path, root.name, source_info, "news", "daily")
                continue
            if root.name == "custom":
                source_info = {
                    "id": "custom",
                    "name": "自定义网址",
                    "region": "news",
                    "period": "custom",
                }
                for day_dir in sorted(root.iterdir()):
                    if not day_dir.is_dir() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day_dir.name):
                        continue
                    for path in sorted(day_dir.glob("*.md")):
                        if path.name != "index.md":
                            parse_file(path, day_dir.name, source_info, "news", "custom")
                continue
            region = root.name
            if region not in ("news", "food", "culture"):
                continue
            for source_dir in sorted(root.iterdir()):
                if not source_dir.is_dir():
                    continue
                source_info = source_map.get(
                    source_dir.name,
                    {"id": source_dir.name, "name": source_dir.name, "region": region, "period": "daily"},
                )
                for period_dir in sorted(source_dir.iterdir()):
                    if not period_dir.is_dir():
                        continue
                    for day_dir in sorted(period_dir.iterdir()):
                        if not day_dir.is_dir() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day_dir.name):
                            continue
                        for path in sorted(day_dir.glob("*.md")):
                            if path.name != "index.md":
                                parse_file(path, day_dir.name, source_info, region, period_dir.name)
        return count

    def close(self):
        with self._lock:
            self.conn.close()
