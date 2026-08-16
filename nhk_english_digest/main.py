import re
import sys
import argparse
import shutil
import logging
import threading
import unicodedata
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import yaml

from article_index import ArticleIndex, parse_article
from annotator import Annotator
from image_store import download_article_images
from scraper import Scraper
from secret_store import load_secrets, save_secrets


for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.yaml"
SECRET_STORE_PATH = BASE_DIR / "secret_store.json"
OUTPUT_DIR = BASE_DIR / "output"
CUSTOM_OUTPUT_DIR = OUTPUT_DIR / "custom"
ARTICLE_INDEX_PATH = OUTPUT_DIR / ".article_index.db"
SOURCE_URL_PATTERN = re.compile(r"\[原文链接\]\(([^)]+)\)")
PUB_DATE_PATTERN = re.compile(r"🕐\s*([^\s|]+)")
SECRET_KEYS = ("openai_api_key", "firecrawl_api_key")

REGION_NAMES = {"news": "新闻", "food": "美食", "culture": "文化"}
PERIOD_NAMES = {"daily": "日刊", "monthly": "月刊"}

DEFAULT_SOURCES = [
    {
        "id": "nhk",
        "name": "NHK WORLD",
        "region": "news",
        "period": "daily",
        "adapter": "nhk_json",
        "url": "https://www3.nhk.or.jp/nhkworld/data/en/news/all.json",
        "enabled": True,
        "limit": 5,
    },
    {
        "id": "japan_forward",
        "name": "Japan Forward",
        "region": "news",
        "period": "daily",
        "adapter": "list_page",
        "url": "https://japan-forward.com/news/",
        "enabled": True,
        "limit": 10,
        "content_selector": ".entry-content",
        "drop_selectors": [
            ".wpml-ls-statics-post_translations",
            "[class*='jf-in-article']",
            "[class*='related']",
            ".author-bio",
            ".post-navigation",
            ".entry-meta",
            ".post-meta",
            "#comments",
            ".comments-area",
        ],
    },
    {
        "id": "timeout_tokyo",
        "name": "Time Out Tokyo",
        "region": "food",
        "period": "monthly",
        "adapter": "list_page",
        "url": "https://www.timeout.com/tokyo/food-drink",
        "enabled": True,
        "limit": 20,
        "content_selector": ".zoneItems, .contentAnnotation, .zoneFirst",
        "drop_selectors": [
            "[class*='_secondary']",
            "[class*='_imageContainer']",
            ".tileImageLink",
            "[class*='share']",
            "[class*='social']",
            "[class*='newsletter']",
            "[class*='subscription']",
            "[class*='advert']",
            "nav",
            "aside",
            "footer",
            "form",
        ],
    },
]

DEFAULT_CONFIG = {
    "openai_base_url": "https://api.deepseek.com/v1",
    "openai_api_key": "",
    "model": "deepseek-chat",
    "firecrawl_api_key": "",
    "scrape_mode": "auto",
    "max_articles": 5,
    "request_timeout": 30,
    "schedule_time": "07:00",
    "auto_schedule": False,
    "sources": DEFAULT_SOURCES,
}


def load_config(path=CONFIG_PATH):
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    return _merge_secrets(config)


def save_config(config, path=CONFIG_PATH):
    config = dict(config)
    secrets = load_secrets(SECRET_STORE_PATH)
    for key in SECRET_KEYS:
        value = str(config.get(key) or "").strip()
        if value:
            secrets[key] = value
        else:
            secrets.pop(key, None)
        config[key] = ""
    save_secrets(secrets, SECRET_STORE_PATH)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)


def _merge_secrets(config):
    secrets = load_secrets(SECRET_STORE_PATH)
    for key in SECRET_KEYS:
        if secrets.get(key):
            config[key] = secrets[key]
    return config


def _ensure_sources_defaults(config):
    changed = False
    sources = config.get("sources")
    if not isinstance(sources, list):
        config["sources"] = deepcopy(DEFAULT_SOURCES)
        return True
    defaults_by_id = {
        item.get("id"): item for item in DEFAULT_SOURCES if item.get("id")
    }
    for index, source in enumerate(sources):
        defaults = {
            "id": f"source_{index + 1}",
            "name": f"来源 {index + 1}",
            "region": "news",
            "period": "daily",
            "adapter": "list_page",
            "url": "",
            "enabled": True,
            "limit": 5,
        }
        for key, value in defaults.items():
            if key not in source:
                source[key] = value
                changed = True
        source_default = defaults_by_id.get(source.get("id"))
        if source_default:
            for key, value in source_default.items():
                if key not in source:
                    source[key] = deepcopy(value)
                    changed = True
    return changed


def ensure_config(path=CONFIG_PATH):
    if not Path(path).exists():
        config = deepcopy(DEFAULT_CONFIG)
        save_config(config, path)
        return config
    config = load_config(path)
    has_plaintext_secrets = any(str(config.get(key, "")).strip() for key in SECRET_KEYS)
    changed = False
    for key, value in DEFAULT_CONFIG.items():
        if key not in config:
            config[key] = deepcopy(value)
            changed = True
    if _ensure_sources_defaults(config):
        changed = True
    if changed or has_plaintext_secrets:
        save_config(config, path)
    return config


def safe_title(title):
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", title or "untitled")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:80] or "untitled"


def normalize_title(title):
    """Normalize a title for deduplication within the same source."""
    value = unicodedata.normalize("NFKC", str(title or ""))
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"^\d+\.\s*", "", value)
    value = value.strip("\"'“”‘’[]（）()【】<>《》-–—_—:：;；,，.。!！?？")
    return value.lower()


def split_paragraphs(text):
    return [part.strip() for part in re.split(r"\n\s*\n", text or "") if part.strip()]


def _contains_english(text):
    return bool(re.search(r"[A-Za-z]{4,}", text or ""))


def interleave_translation(original_text, translation_text):
    original_paragraphs = split_paragraphs(original_text)
    translation_paragraphs = split_paragraphs(translation_text)
    if (
        original_paragraphs
        and len(original_paragraphs) == len(translation_paragraphs)
        and not all(_contains_english(part) for part in translation_paragraphs)
    ):
        paired = []
        for source, target in zip(original_paragraphs, translation_paragraphs):
            paired.append(source)
            paired.append(target)
        return "\n\n".join(paired)
    return translation_text


def dedupe_consecutive_lines(text):
    output = []
    previous = ""
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped and stripped == previous:
            continue
        output.append(line)
        previous = stripped
    return "\n".join(output)


def _index_article(path, raw, source_config, date_str=None):
    path = Path(path)
    date_str = date_str or path.parent.name
    source_config = source_config or {}
    region = source_config.get("region", "news")
    period = source_config.get("period", "daily")
    article = parse_article(
        date_str,
        path,
        raw,
        {
            "id": source_config.get("id", path.parent.name),
            "name": source_config.get("name", source_config.get("id", path.parent.name)),
            "region": region,
            "period": period,
        },
        region=region,
        period=period,
    )
    index = ArticleIndex(ARTICLE_INDEX_PATH)
    try:
        index.upsert(article)
    finally:
        index.close()


def _format_image_markdown(image):
    if isinstance(image, dict):
        image_url = image.get("url", "")
        image_alt = image.get("alt", "")
    else:
        image_url = str(image)
        image_alt = ""
    return f"![{image_alt}]({image_url})"


def _render_content_with_images(content_text, images, positions=None):
    images = images or []
    paragraphs = [part for part in (content_text or "").split("\n\n") if part.strip()]
    if not paragraphs and not images:
        return ""

    by_position = {}
    for position in positions or []:
        if not isinstance(position, dict):
            continue
        image_index = position.get("image_index")
        if image_index is None or not 0 <= int(image_index) < len(images):
            continue
        image_index = int(image_index)
        after_paragraph = position.get("after_paragraph", len(paragraphs) - 1)
        if after_paragraph is None:
            after_paragraph = len(paragraphs) - 1
        by_position.setdefault(int(after_paragraph), []).append(image_index)

    placed = set()
    output = []

    def emit_image(image_index):
        if image_index in placed:
            return
        placed.add(image_index)
        output.append(_format_image_markdown(images[image_index]))
        output.append("")

    for image_index in by_position.get(-1, []):
        emit_image(image_index)
    if output and paragraphs:
        output.append("")

    for paragraph_index, paragraph in enumerate(paragraphs):
        output.append(paragraph)
        output.append("")
        for image_index in by_position.get(paragraph_index, []):
            emit_image(image_index)

    for image_index in range(len(images)):
        emit_image(image_index)

    while output and not output[-1]:
        output.pop()
    return "\n".join(output)


def article_markdown(index, article, annotation):
    title = article.get("title", "未知标题")
    content_text = article.get("content_text", "")
    pub_date = article.get("pub_date", "")
    translation_raw = annotation.get(
        "translation",
        annotation.get(
            "translation_cet4", annotation.get("translation_cet6", "")
        ),
    )
    translation = dedupe_consecutive_lines(
        interleave_translation(content_text, translation_raw)
    )

    original_text = _render_content_with_images(
        content_text,
        article.get("images") or [],
        article.get("image_positions") or [],
    )

    lines = [
        f"# {index}. {title}",
        "",
        f"🔗 [原文链接]({article.get('url', '#')}) ｜ 🕐 {pub_date}",
        "",
        "## 原文",
        "",
        original_text,
        "",
    ]
    if annotation.get("status") == "error":
        error_text = annotation.get("error") or "注释生成失败"
        lines.extend([f"> ⚠️ 注释生成失败：{error_text}", ""])

    lines.extend([
        "## 翻译",
        "",
        translation,
        "",
        f"💡 背景补充：{annotation.get('background', '')}",
        "",
        "## 📚 重点词汇",
        "",
        "| 单词 | 词性 | 中文释义 | 等级 | 原文例句 |",
        "| --- | --- | --- | --- | --- |",
    ])
    for vocab in annotation.get("vocabulary", []):
        example = str(vocab.get("example_sentence", "")).replace("|", "\\|")
        lines.append(
            f"| {vocab.get('word', '')} | {vocab.get('pos', '')} | "
            f"{vocab.get('meaning_cn', '')} | {vocab.get('level', '')} | {example} |"
        )

    lines.extend(["", "## 🔍 难句解析", ""])
    for item in annotation.get("difficult_sentences", []):
        lines.extend(
            [
                f"**原文：** {item.get('original', '')}",
                "",
                f"**解析：** {item.get('analysis', '')}",
                "",
                f"**翻译：** {item.get('translation', '')}",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _image_markdown_lines(images):
    lines = ["## 🖼️ 图片", ""]
    for image in images or []:
        if isinstance(image, dict):
            image_url = image.get("url", "")
            image_alt = image.get("alt", "")
        else:
            image_url = str(image)
            image_alt = ""
        lines.append(f"![{image_alt}]({image_url})")
        lines.append("")
    return lines


def _remove_image_section(lines):
    image_heading = "## 🖼️ 图片"
    heading_index = next(
        (pos for pos, line in enumerate(lines) if line.strip() == image_heading),
        None,
    )
    if heading_index is None:
        return lines
    next_heading = next(
        (
            pos
            for pos in range(heading_index + 1, len(lines))
            if lines[pos].strip().startswith("## ")
        ),
        len(lines),
    )
    return lines[:heading_index] + lines[next_heading:]


def _insert_image_section(raw, images, positions=None, content_text=None):
    lines = (raw or "").rstrip().splitlines()
    lines = _remove_image_section(lines)
    original_heading = "## 原文"
    start = next(
        (pos for pos, line in enumerate(lines) if line.strip() == original_heading),
        None,
    )
    if start is None:
        return raw
    end = next(
        (
            pos
            for pos in range(start + 1, len(lines))
            if lines[pos].strip().startswith("## ")
        ),
        len(lines),
    )
    content_lines = lines[start + 1 : end]
    while content_lines and not content_lines[0].strip():
        content_lines.pop(0)
    while content_lines and not content_lines[-1].strip():
        content_lines.pop()
    source_text = (
        content_text
        if content_text is not None and content_text.strip()
        else "\n".join(content_lines)
    )
    rendered = _render_content_with_images(source_text, images, positions)
    rebuilt = lines[: start + 1]
    if rendered:
        rebuilt.extend(["", rendered])
    if end < len(lines):
        rebuilt.extend(["", *lines[end:]])
    return "\n".join(rebuilt).rstrip() + "\n"


def _strip_inline_image_markdown(raw):
    output = []
    for line in (raw or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("![") or stripped.startswith("- !["):
            output.append(line)
            continue
        if any(marker in line for marker in ("\\image\\", "\\title\\", "\\category\\")):
            continue
        output.append(re.sub(r"!\[[^\]]*\]\([^)\s]+\)", "", line).strip())
    return "\n".join(output)


def index_markdown(date_str, entries, source=None):
    label = ""
    if source:
        region = REGION_NAMES.get(source.get("region", ""), "")
        period = PERIOD_NAMES.get(source.get("period", ""), "")
        label = f"｜ {region}｜ {source.get('name', '')}｜ {period}"
    lines = [f"# {date_str}{label} 文章列表", ""]
    for entry in entries:
        lines.append(
            f"- [{entry['index']}. {entry['title']}]({entry['filename']}) "
            f"｜ {entry['pub_date']} ｜ {entry['summary']}"
        )
    return "\n".join(lines) + "\n"


def _markdown_title(raw):
    for line in (raw or "").splitlines():
        if line.startswith("# "):
            return re.sub(r"^\d+\.\s+", "", line[2:].strip())
    return ""


def _find_custom_article(day_dir, url):
    if not day_dir.is_dir():
        return None
    normalized = (url or "").rstrip("/")
    for path in sorted(day_dir.glob("*.md")):
        if path.name == "index.md":
            continue
        raw = path.read_text(encoding="utf-8", errors="replace")
        match = SOURCE_URL_PATTERN.search(raw)
        if match and match.group(1).strip().rstrip("/") == normalized:
            return path
    return None


def _custom_titles():
    titles = set()
    if not CUSTOM_OUTPUT_DIR.is_dir():
        return titles
    for day_dir in sorted(CUSTOM_OUTPUT_DIR.iterdir()):
        if not day_dir.is_dir() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day_dir.name):
            continue
        for path in day_dir.glob("*.md"):
            if path.name == "index.md":
                continue
            raw = path.read_text(encoding="utf-8", errors="replace")
            title = normalize_title(_markdown_title(raw))
            if title:
                titles.add(title)
    return titles


def _file_index(path):
    match = re.match(r"(\d+)", path.stem)
    return int(match.group(1)) if match else 0


def _markdown_summary(raw):
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
    return " ".join(" ".join(collected).split())[:120]


def _existing_daily_entries(day_dir):
    if not day_dir.is_dir():
        return []
    entries = []
    for path in sorted(day_dir.glob("*.md")):
        if path.name == "index.md":
            continue
        raw = path.read_text(encoding="utf-8", errors="replace")
        source_match = SOURCE_URL_PATTERN.search(raw)
        pub_match = PUB_DATE_PATTERN.search(raw)
        entries.append(
            {
                "index": _file_index(path),
                "title": _markdown_title(raw),
                "filename": path.name,
                "pub_date": pub_match.group(1) if pub_match else day_dir.name,
                "summary": _markdown_summary(raw),
                "source_url": source_match.group(1) if source_match else "",
            }
        )
    return sorted(entries, key=lambda entry: entry["index"])


def rebuild_day_index(day_dir, date_str=None, source=None):
    day_dir = Path(day_dir)
    date_str = date_str or day_dir.name
    entries = _existing_daily_entries(day_dir)
    index_path = day_dir / "index.md"
    if entries:
        index_path.write_text(
            index_markdown(date_str, entries, source=source),
            encoding="utf-8",
        )
    elif index_path.exists():
        index_path.unlink()
    return len(entries)


def source_root(source):
    return OUTPUT_DIR / source["region"] / source["id"] / source["period"]


def source_day_dir(source, date_str=None):
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    return source_root(source) / date_str


def migrate_legacy_output(output_dir=OUTPUT_DIR):
    """Move old output/YYYY-MM-DD NHK dailies into the news/nhk/daily tree."""
    output_dir = Path(output_dir)
    if not output_dir.is_dir():
        return 0
    moved = 0
    for path in sorted(output_dir.iterdir()):
        if not path.is_dir():
            continue
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.name):
            continue
        target = output_dir / "news" / "nhk" / "daily" / path.name
        target.mkdir(parents=True, exist_ok=True)
        for file_path in sorted(path.iterdir()):
            if not file_path.is_file():
                continue
            destination = target / file_path.name
            if destination.exists():
                continue
            shutil.move(str(file_path), str(destination))
            moved += 1
        if not any(path.iterdir()):
            path.rmdir()
    if moved:
        print(f"[Main] 已迁移旧输出 {moved} 个文件到新目录结构")
    return moved


def _all_source_urls(source):
    urls = set()
    root = source_root(source)
    if not root.is_dir():
        return urls
    for day_dir in sorted(root.iterdir()):
        if not day_dir.is_dir() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day_dir.name):
            continue
        for path in day_dir.glob("*.md"):
            if path.name == "index.md":
                continue
            raw = path.read_text(encoding="utf-8", errors="replace")
            match = SOURCE_URL_PATTERN.search(raw)
            if match:
                urls.add(match.group(1).strip().rstrip("/"))
    return urls


def _all_source_titles(source):
    titles = set()
    root = source_root(source)
    if not root.is_dir():
        return titles
    for day_dir in sorted(root.iterdir()):
        if not day_dir.is_dir() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day_dir.name):
            continue
        for path in day_dir.glob("*.md"):
            if path.name == "index.md":
                continue
            raw = path.read_text(encoding="utf-8", errors="replace")
            title = normalize_title(_markdown_title(raw))
            if title:
                titles.add(title)
    return titles


def run_source_job(
    source,
    config,
    scraper=None,
    annotator=None,
    force=False,
    progress=None,
    cancel_event=None,
):
    source = dict(source)
    date_str = datetime.now().strftime("%Y-%m-%d")
    day_dir = source_day_dir(source, date_str)
    day_dir.mkdir(parents=True, exist_ok=True)

    entries = [] if force else _existing_daily_entries(day_dir)
    if force:
        for path in day_dir.glob("*.md"):
            if path.name != "index.md":
                path.unlink()

    known_urls = set() if force else _all_source_urls(source)
    known_urls.update(
        str(entry.get("source_url", "")).rstrip("/")
        for entry in entries
        if entry.get("source_url")
    )
    known_titles = set() if force else _all_source_titles(source)
    known_titles.update(
        normalize_title(entry.get("title", ""))
        for entry in entries
        if normalize_title(entry.get("title", ""))
    )

    scraper = scraper or Scraper(config)
    annotator = annotator or Annotator(
        api_key=config.get("openai_api_key", ""),
        base_url=config.get("openai_base_url", "https://api.deepseek.com/v1"),
        model=config.get("model", "deepseek-chat"),
    )

    limit = int(source.get("limit") or config.get("max_articles", 5))
    articles = scraper.fetch_source(source, limit=limit)
    print(f"[Main] {source['name']} 获取到 {len(articles)} 篇候选文章")

    new_count = 0
    next_index = max((entry["index"] for entry in entries), default=0) + 1
    seen_titles = set()
    for position, article in enumerate(articles, start=1):
        if cancel_event and cancel_event.is_set():
            print(f"[Main] 来源 {source['name']} 已取消")
            break
        normalized_url = str(article.get("url", "")).rstrip("/")
        normalized_title = normalize_title(article.get("title", ""))
        if normalized_title and (
            normalized_title in known_titles or normalized_title in seen_titles
        ):
            print(f"[Main] 标题重复，跳过：{article.get('title', '')}")
            continue
        if normalized_url and normalized_url in known_urls:
            print(f"[Main] 已收录，跳过：{article.get('title', '')}")
            continue

        index = next_index
        if progress:
            try:
                progress(
                    source.get("name", ""),
                    position,
                    len(articles),
                    article.get("title", ""),
                )
            except Exception:
                pass
        print(f"[Main] 注释第 {index} 篇：{article['title']}")
        annotation = annotator.annotate(article)
        filename = f"{index:02d}_{safe_title(article['title'])}.md"
        article_path = day_dir / filename
        article["region"] = source.get("region", "news")
        article["period"] = source.get("period", "daily")
        article = download_article_images(article, article_path, only_region="food")
        markdown = article_markdown(index, article, annotation)
        article_path.write_text(markdown, encoding="utf-8")
        print(f"[Main] 已保存 {filename}")
        _index_article(article_path, markdown, source)
        entries.append(
            {
                "index": index,
                "title": article["title"],
                "filename": filename,
                "pub_date": article.get("pub_date", date_str),
                "summary": " ".join(article.get("content_text", "").split())[:120],
                "source_url": article.get("url", ""),
            }
        )
        if normalized_url:
            known_urls.add(normalized_url)
        if normalized_title:
            seen_titles.add(normalized_title)
            known_titles.add(normalized_title)
        new_count += 1
        next_index += 1

    entries = sorted(entries, key=lambda entry: entry["index"])
    rebuild_day_index(day_dir, date_str, source=source)
    print(f"[Main] 完成 {source['name']}：新增 {new_count} 篇，共 {len(entries)} 篇")
    return {
        "source_id": source["id"],
        "source_name": source["name"],
        "region": source["region"],
        "period": source["period"],
        "date": date_str,
        "count": new_count,
        "total": len(entries),
        "cancelled": bool(cancel_event and cancel_event.is_set()),
    }


def run_refresh_job(
    config_path=CONFIG_PATH,
    region=None,
    progress=None,
    cancel_event=None,
):
    config = ensure_config(config_path)
    if not config.get("openai_api_key", ""):
        print("[Main] 未配置 openai_api_key，请在应用设置中填写后重试")
        raise SystemExit("未配置 openai_api_key，请在应用设置中填写 DeepSeek API Key")

    migrate_legacy_output()
    sources = [
        source
        for source in config.get("sources", [])
        if source.get("enabled", True)
    ]
    if region:
        sources = [source for source in sources if source.get("region") == region]
    if not sources:
        print("[Main] 没有启用的来源")
        return {"count": 0, "total": 0, "sources": [], "region": region}

    print(f"[Main] 开始刷新，区域：{region or '全部'}")
    scraper = Scraper(config)
    annotator = Annotator(
        api_key=config.get("openai_api_key", ""),
        base_url=config.get("openai_base_url", "https://api.deepseek.com/v1"),
        model=config.get("model", "deepseek-chat"),
    )

    results = []
    total_new = 0
    total_all = 0
    for source in sources:
        if cancel_event and cancel_event.is_set():
            break
        try:
            result = run_source_job(
                source,
                config,
                scraper=scraper,
                annotator=annotator,
                progress=progress,
                cancel_event=cancel_event,
            )
        except Exception as exc:
            print(f"[Main] 来源 {source.get('name', '')} 刷新失败：{exc}")
            result = {
                "source_id": source.get("id", ""),
                "source_name": source.get("name", ""),
                "region": source.get("region", ""),
                "period": source.get("period", ""),
                "count": 0,
                "total": 0,
                "error": str(exc),
            }
        results.append(result)
        total_new += result.get("count", 0)
        total_all += result.get("total", 0)
        if result.get("cancelled"):
            break

    print(f"[Main] 全部完成：新增 {total_new} 篇，共 {total_all} 篇")
    return {
        "count": total_new,
        "total": total_all,
        "sources": results,
        "region": region,
        "cancelled": bool(cancel_event and cancel_event.is_set()),
    }


def run_daily_job(config_path=CONFIG_PATH, force=False):
    """Compatibility wrapper for the old NHK daily command."""
    config = ensure_config(config_path)
    sources = [
        source
        for source in config.get("sources", [])
        if source.get("id") == "nhk"
    ]
    if not sources:
        source = {
            "id": "nhk",
            "name": "NHK WORLD",
            "region": "news",
            "period": "daily",
            "adapter": "nhk_json",
            "url": DEFAULT_SOURCES[0]["url"],
            "enabled": True,
            "limit": int(config.get("max_articles", 5)),
        }
    else:
        source = sources[0]
    result = run_source_job(source, config, force=force)
    return {
        "skipped": False,
        "date": result["date"],
        "count": result["count"],
        "total": result["total"],
    }


def run_url_job(url, config_path=CONFIG_PATH, cancel_event=None):
    config = ensure_config(config_path)
    if not config.get("openai_api_key", ""):
        print("[Main] 未配置 openai_api_key，请在应用设置中填写后重试")
        raise SystemExit("未配置 openai_api_key，请在应用设置中填写 DeepSeek API Key")

    url = (url or "").strip()
    if cancel_event and cancel_event.is_set():
        return {"ok": False, "cancelled": True, "date": datetime.now().strftime("%Y-%m-%d")}
    date_str = datetime.now().strftime("%Y-%m-%d")
    day_dir = CUSTOM_OUTPUT_DIR / date_str
    day_dir.mkdir(parents=True, exist_ok=True)

    existing = _find_custom_article(day_dir, url)
    if existing:
        raw = existing.read_text(encoding="utf-8", errors="replace")
        print(f"[Main] 该网址今天已抓取：{existing.name}")
        return {
            "ok": True,
            "skipped": True,
            "path": existing,
            "title": _markdown_title(raw),
            "date": date_str,
        }

    scraper = Scraper(config)
    article = scraper.fetch_url(url)

    if cancel_event and cancel_event.is_set():
        return {"ok": False, "cancelled": True, "date": date_str}

    normalized_title = normalize_title(article.get("title", ""))
    if normalized_title and normalized_title in _custom_titles():
        print(f"[Main] 自定义网址标题重复，跳过：{article.get('title', '')}")
        return {
            "ok": True,
            "skipped": True,
            "path": None,
            "title": article.get("title", ""),
            "date": date_str,
        }

    annotator = Annotator(
        api_key=config.get("openai_api_key", ""),
        base_url=config.get("openai_base_url", "https://api.deepseek.com/v1"),
        model=config.get("model", "deepseek-chat"),
    )
    annotation = annotator.annotate(article)

    if cancel_event and cancel_event.is_set():
        return {"ok": False, "cancelled": True, "date": date_str}

    timestamp = datetime.now().strftime("%H%M%S")
    filename = f"{timestamp}_{safe_title(article['title'])}.md"
    article_path = day_dir / filename
    suffix = 2
    while article_path.exists():
        article_path = day_dir / f"{timestamp}_{safe_title(article['title'])}_{suffix}.md"
        suffix += 1

    article["region"] = "news"
    article["period"] = "custom"
    article = download_article_images(article, article_path, only_region="food")
    markdown = article_markdown(1, article, annotation)
    article_path.write_text(markdown, encoding="utf-8")
    print(f"[Main] 自定义网址注释完成：{article_path}")
    _index_article(
        article_path,
        markdown,
        {
            "id": "custom",
            "name": "自定义网址",
            "region": "news",
            "period": "custom",
        },
    )
    return {
        "ok": True,
        "skipped": False,
        "path": article_path,
        "title": article["title"],
        "date": date_str,
    }


def _source_config_for_path(path, config):
    try:
        relative = Path(path).resolve().relative_to(OUTPUT_DIR.resolve())
    except ValueError:
        return None, None
    parts = relative.parts
    if not parts:
        return None, None
    if parts[0] == "custom":
        return None, None
    if len(parts) >= 3 and parts[0] in REGION_NAMES:
        region, source_id, period = parts[0], parts[1], parts[2]
        for source in config.get("sources", []):
            if source.get("id") == source_id and source.get("region", region) == region:
                return source, source
        minimal = {
            "id": source_id,
            "name": source_id,
            "region": region,
            "period": period,
            "adapter": "list_page",
            "url": "",
            "enabled": True,
            "limit": 5,
        }
        return None, minimal
    if (
        len(parts) == 2
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[0])
        and parts[1].endswith(".md")
    ):
        source = next(
            (
                item
                for item in config.get("sources", [])
                if item.get("id") == "nhk"
            ),
            None,
        )
        if source:
            return source, source
        minimal = {
            "id": "nhk",
            "name": "NHK WORLD",
            "region": "news",
            "period": "daily",
            "adapter": "nhk_json",
            "url": DEFAULT_SOURCES[0]["url"],
            "enabled": True,
            "limit": 5,
        }
        return None, minimal
    return None, None


def run_rebuild_article(path, config_path=CONFIG_PATH):
    config = ensure_config(config_path)
    if not config.get("openai_api_key", ""):
        print("[Main] 未配置 openai_api_key，请在应用设置中填写后重试")
        raise SystemExit("未配置 openai_api_key，请在应用设置中填写 DeepSeek API Key")

    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"文章文件不存在：{path}")
    raw = path.read_text(encoding="utf-8", errors="replace")
    url_match = SOURCE_URL_PATTERN.search(raw)
    if not url_match:
        raise ValueError(f"无法从文章 Markdown 解析原文链接：{path.name}")
    url = url_match.group(1).strip()

    source_config, index_source = _source_config_for_path(path, config)
    scraper = Scraper(config)
    article = scraper.fetch_url(url, source_config=source_config)
    annotator = Annotator(
        api_key=config.get("openai_api_key", ""),
        base_url=config.get("openai_base_url", "https://api.deepseek.com/v1"),
        model=config.get("model", "deepseek-chat"),
    )
    annotation = annotator.annotate(article)
    index = _file_index(path) or 1
    article["region"] = (source_config or {}).get("region", "news")
    article["period"] = (source_config or {}).get("period", "daily")
    article = download_article_images(article, path, only_region="food")
    markdown = article_markdown(index, article, annotation)
    path.write_text(markdown, encoding="utf-8")
    _index_article(
        path,
        markdown,
        index_source or source_config or {"id": "custom", "name": "自定义网址", "region": "news", "period": "custom"},
    )

    date_str = path.parent.name
    if (
        re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str)
        and index_source
        and index_source.get("id") != "custom"
    ):
        rebuild_day_index(path.parent, date_str, source=index_source)

    print(f"[Main] 重新抓取完成：{path}")
    return {
        "ok": True,
        "path": path,
        "title": article["title"],
        "date": date_str,
        "overwritten": True,
    }


def run_image_backfill(
    config_path=CONFIG_PATH,
    region="food",
    progress=None,
    cancel_event=None,
):
    config = ensure_config(config_path)
    index = ArticleIndex(ARTICLE_INDEX_PATH)
    try:
        articles = index.list_articles()
    finally:
        index.close()

    source_map = {
        source.get("id"): source
        for source in config.get("sources", [])
        if isinstance(source, dict) and source.get("id")
    }
    targets = [
        article for article in articles if article.get("region") == region
    ]
    scraper = Scraper(config)
    updated = 0
    results = []
    for position, article in enumerate(targets, start=1):
        if cancel_event and cancel_event.is_set():
            break
        path = Path(article["path"])
        if progress:
            try:
                progress(
                    "美食图片补全",
                    position,
                    len(targets),
                    article.get("title", ""),
                )
            except Exception:
                pass
        raw = path.read_text(encoding="utf-8", errors="replace")
        url_match = SOURCE_URL_PATTERN.search(raw)
        if not url_match:
            results.append({"path": str(path), "ok": False, "error": "缺少原文链接"})
            continue
        source_config = source_map.get(article.get("source"))
        try:
            fetched = scraper.fetch_url(
                url_match.group(1).strip(), source_config=source_config
            )
            fetched["region"] = region
            fetched["period"] = article.get("period", "monthly")
            fetched = download_article_images(fetched, path, only_region="food")
            if not fetched.get("images"):
                results.append({"path": str(path), "ok": False, "error": "未提取到图片"})
                continue
            new_raw = _insert_image_section(
                raw,
                fetched["images"],
                fetched.get("image_positions") or [],
                content_text=fetched.get("content_text", ""),
            )
            new_raw = _strip_inline_image_markdown(new_raw)
            path.write_text(new_raw, encoding="utf-8")
            _index_article(
                path,
                new_raw,
                source_config or article.get("source_config", {}),
            )
            updated += 1
            results.append({"path": str(path), "ok": True})
        except Exception as exc:
            results.append({"path": str(path), "ok": False, "error": str(exc)})

    print(f"[Main] 图片补全完成：更新 {updated} 篇，共 {len(targets)} 篇")
    return {
        "updated": updated,
        "total": len(targets),
        "results": results,
        "cancelled": bool(cancel_event and cancel_event.is_set()),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="言叶：抓取、注释与刷新")
    parser.add_argument(
        "--force",
        action="store_true",
        help="重抓 NHK 日刊（兼容旧命令）",
    )
    parser.add_argument(
        "--rebuild",
        metavar="PATH",
        help="重新抓取并翻译指定的 Markdown 文章",
    )
    parser.add_argument(
        "--region",
        choices=("news", "food", "culture"),
        help="只刷新指定区域：news / food / culture",
    )
    parser.add_argument(
        "--backfill-images",
        choices=("food",),
        help="只补全已有文章的图片（不重新翻译）",
    )
    args = parser.parse_args()
    if args.rebuild:
        run_rebuild_article(args.rebuild)
    elif args.backfill_images:
        run_image_backfill(region=args.backfill_images)
    elif args.force:
        run_daily_job(force=True)
    else:
        run_refresh_job(region=args.region)
