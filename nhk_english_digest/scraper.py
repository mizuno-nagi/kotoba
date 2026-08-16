import re
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from firecrawl_client import FirecrawlClient


_NOISE_LABEL_PATTERNS = (
    r"read more",
    r"leave a reply",
    r"follow the series",
    r"related news",
    r"related articles",
    r"related stories",
    r"related posts?",
    r"related",
    r"you may also like",
    r"recommended for you",
    r"\*{0,2}recommended",
    r"digital editor",
    r"contributor",
    r"more news",
    r"latest news",
    r"popular on time out",
    r"advertising",
    r"copy link",
    r"share this",
    r"share on",
    r"this page in",
    r"japan forward on facebook",
    r"follow us on twitter",
    r"share",
    r"share on",
    r"share on (?:facebook|twitter|line|weibo|whatsapp|pinterest|email|x)",
    r"このページを ?日本語 ?で読む",
    r"関連記事",
    r"関連ニュース",
    r"おすすめ",
)
_NOISE_LINE_PATTERN = re.compile(
    r"^\s*(?:"
    + "|".join(f"(?:{pattern})" for pattern in _NOISE_LABEL_PATTERNS)
    + r")\s*(?:(?::|→|»|>|#|\||[,;]|[-–—])[^\w\s]*.*)?$",
    flags=re.IGNORECASE,
)
_TIME_AGO_PATTERN = re.compile(r"^\d+\s+(?:hours?|minutes?|days?|weeks?)\s+ago$")
_DATE_LINE_PATTERN = re.compile(
    r"^(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"\s+\d{1,2}\s+\w+\s+\d{4}$",
    flags=re.IGNORECASE,
)
_BYLINE_PATTERN = re.compile(
    r"^(?:written|posted|edited|contributed)\s+by\s+"
    r"[A-Z][\w'.-]*(?:\s+[A-Z][\w'.-]*)*$",
    flags=re.IGNORECASE,
)
_BYLINE_LINK_PATTERN = re.compile(
    r"^(?:written|posted|edited|contributed)\s+by\s+"
    r"\[[^\]\n]+\]\(https?://[^)\s]+\)$",
    flags=re.IGNORECASE,
)
_PURE_LINK_LINE_PATTERN = re.compile(
    r"^(?:-\s*)?(?:(?:!?\[[^\]\n]*\]\([^)\s]+\)|\[!\[[^\]\n]*\]\([^)\s]+\)\]\([^)\s]+\))\s*\\*)+$"
)
_PHOTO_CAPTION_PATTERN = re.compile(
    r"^photo:\s*[^\]\n]+\]\(https?://[^)\s]+\)$",
    flags=re.IGNORECASE,
)
_CGTN_TIME_LINE_PATTERN = re.compile(
    r"^\d{1,2}:\d{2},\s*\d{1,2}-(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)-\d{4}$",
    flags=re.IGNORECASE,
)
_CGTN_BRAND_PATTERN = re.compile(r"^(?:cgtn|copied|china)$", flags=re.IGNORECASE)

_ASSET_SUFFIXES = (
    ".gif",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".svg",
    ".ico",
    ".css",
    ".js",
    ".mp4",
    ".webm",
    ".mp3",
    ".wav",
    ".zip",
    ".woff",
    ".woff2",
    ".ttf",
    ".pdf",
)

_NON_ARTICLE_HINTS = (
    "category",
    "tag",
    "author",
    "archive",
    "month",
    "about",
    "contact",
    "privacy",
    "terms",
    "cookie",
    "feed",
    "login",
    "signup",
    "search",
    "sitemap",
    "wp-content",
    "wp-json",
    "mailto:",
    "javascript:",
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "youtube.com",
    "/hub/",
    "/tag/",
    "/topics/",
    "/topic/",
    "/category/",
    "/section/",
    "/author/",
    "/profile/",
    "/podcasts/",
    "/podcast/",
)

_VIDEO_PATH_HINTS = ("/video/", "/videos/", "/av/")

_NAV_LABELS = {
    "home",
    "world",
    "politics",
    "business",
    "health",
    "video",
    "videos",
    "live",
    "tv",
    "china",
    "subscribe",
    "newsletters",
    "more",
    "watch",
    "latest",
    "latest news",
    "view all",
    "read more",
}

_SECTION_PATHS = {
    "/world",
    "/world-news",
    "/us-news",
    "/politics",
    "/business",
    "/sports",
    "/health",
    "/china",
    "/sci-tech",
    "/asia",
    "/europe",
    "/africa",
    "/middle-east",
    "/latin-america",
    "/americas",
    "/uk-news",
    "/australia",
}


class Scraper:
    """Fetch real NHK WORLD-JAPAN English news from the official JSON API."""

    OFFLINE_SAMPLES = [
        {
            "title": "Kyoto Temple Hosts Solar-Powered Lantern Festival",
            "url": "https://www3.nhk.or.jp/nhkworld/en/news/offline-sample-1/",
            "pub_date": "2026-08-15",
            "content_text": (
                "Every summer, thousands of visitors walk through the old streets of Kyoto to see the "
                "Lantern Festival. This year, the event has a new highlight: the temple's traditional "
                "lanterns are now powered by solar panels installed on its roof. Organizers say the "
                "change cuts electricity costs and reduces carbon emissions.\n\n"
                "The temple has used paper lanterns for more than 400 years. In the past, volunteers "
                "lit each lantern with candles and checked them one by one. That process took hours "
                "and required careful attention. Now, small LED bulbs inside the lanterns receive "
                "energy from batteries charged during the day. The panels produce enough electricity "
                "to keep the lights on from dusk until midnight.\n\n"
                '"We wanted to respect tradition while finding a smarter way to operate," said a '
                'temple official. "Solar power lets us keep the festival beautiful without wasting '
                'energy."\n\n'
                "Local residents supported the project from the beginning. A nearby university helped "
                "measure the amount of sunlight and suggested the best position for the panels. "
                "Students also created a mobile app that monitors the battery level and reports any "
                "problems. If one light stops working, the app sends an alert to the maintenance team.\n\n"
                "The festival will continue until the end of August. Organizers hope the solar system "
                "will inspire other historic sites to consider clean energy. They also plan to share "
                "the project's data with schools, so young people can learn how modern technology can "
                "protect cultural traditions."
            ),
        },
        {
            "title": "Japanese Students Win International Robotics Contest",
            "url": "https://www3.nhk.or.jp/nhkworld/en/news/offline-sample-2/",
            "pub_date": "2026-08-15",
            "content_text": (
                "Six high school students from Osaka won first prize at the International Robotics "
                "Contest held in Singapore. Their robot completed a rescue mission in 12 minutes, "
                "faster than any other team. The contest asked students to design a machine that "
                "could find people in a damaged building, carry small supplies, and send messages "
                "to a control center.\n\n"
                "The team began working on the robot eight months ago. They spent weekends testing "
                "motors, sensors, and software in their school laboratory. Several early versions "
                "failed during trials, but the students recorded every mistake and adjusted the "
                "design. Their final robot uses cameras to identify colors on walls and a mechanical "
                "arm to move objects.\n\n"
                '"The hardest part was making the robot work in uneven spaces," said the team leader. '
                '"We practiced on floors covered with wood and bricks to imitate a real disaster site."\n\n'
                "The judges praised the students for their clear communication and careful planning. "
                "Each member had a specific role, such as programming, wiring, or navigation. The team "
                "also wrote a manual that explains how to operate the robot, so emergency workers "
                "could use it without special training.\n\n"
                "After the contest, the students returned to Osaka with a gold medal and a trophy. "
                "They hope to continue improving the robot and eventually share their design with "
                "rescue organizations. Their teacher said the victory shows that young people can "
                "solve real-world problems through science and teamwork."
            ),
        },
    ]

    LIST_URL = "https://www3.nhk.or.jp/nhkworld/data/en/news/all.json"
    DETAIL_URL = "https://www3.nhk.or.jp/nhkworld/data/en/news/{news_id}.json"
    PAGE_BASE = "https://www3.nhk.or.jp"

    def __init__(self, config):
        self.timeout = int(config.get("request_timeout", 30))
        self.max_articles = int(config.get("max_articles", 5))
        self.scrape_mode = str(config.get("scrape_mode", "auto")).lower()
        self.firecrawl = FirecrawlClient(
            api_key=config.get("firecrawl_api_key", ""),
            timeout=self.timeout,
        )
        self._firecrawl_cooldown_until = 0.0
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0 Safari/537.36"
                )
            }
        )

    def _firecrawl_ready(self):
        """Whether Firecrawl should be attempted right now.

        Firecrawl is useful for JavaScript-heavy pages, but a rate-limited
        CLI/API makes every article wait for a doomed request before falling
        back to direct HTML. After a rate-limit error, back off briefly so the
        remaining list/article fetches use the direct path immediately.
        """
        return self.firecrawl.available() and time.time() >= self._firecrawl_cooldown_until

    def _note_firecrawl_failure(self, exc):
        message = str(exc).lower()
        if "rate limit" in message or "too many requests" in message or "429" in message:
            self._firecrawl_cooldown_until = time.time() + 60

    def fetch_today_news(self, limit=None):
        """Fetch today's NHK WORLD English news; raises on network failure."""
        articles = self._fetch_from_official_api(limit=limit)
        if not articles:
            raise RuntimeError("NHK WORLD 官方 API 未返回任何文章")
        print(f"[Scraper] 从 NHK WORLD 官方英文 API 获取到 {len(articles)} 篇文章")
        return articles

    def fetch_source(self, source, limit=None):
        """Dispatch to the adapter configured for a source."""
        adapter = str(source.get("adapter", "list_page")).lower()
        fetch_limit = int(limit or source.get("limit") or self.max_articles)
        if adapter == "nhk_json":
            return self._fetch_from_official_api(limit=fetch_limit)
        if adapter == "list_page":
            return self._fetch_list_page_articles(source, fetch_limit)
        if adapter == "single_url":
            article = self.fetch_url(
                str(source.get("url", "")).strip(), source_config=source
            )
            return [article] if article else []
        raise ValueError(f"未知抓取适配器：{adapter}")

    def _fetch_list_page_articles(self, source, limit):
        list_url = str(source.get("url", "")).strip()
        if not re.match(r"^https?://", list_url, flags=re.IGNORECASE):
            raise ValueError("来源列表页必须是以 http:// 或 https:// 开头的有效网址")
        links = self._fetch_list_links(list_url)
        if not links:
            raise ValueError(f"未能从列表页提取文章链接：{list_url}")
        print(f"[Scraper] 列表页提取到 {len(links)} 个候选链接，取前 {limit} 个")

        articles = []
        for url in links[:limit]:
            try:
                article = self.fetch_url(url, source_config=source)
            except Exception as exc:
                print(f"[Scraper] 文章抓取失败，跳过 {url}：{exc}")
                continue
            if article.get("title") and article.get("content_text"):
                text = article.get("content_text", "").strip()
                title = article.get("title", "").strip()
                if len(text.split()) < 30 or title.lower().startswith("http"):
                    print(f"[Scraper] 非文章内容，跳过 {url}")
                    continue
                articles.append(article)
            if len(articles) >= limit:
                break
        return articles

    def _fetch_list_links(self, list_url):
        links = []
        if self._firecrawl_ready():
            try:
                markdown = self.firecrawl.scrape_markdown(list_url)
                links = self._markdown_links(markdown, list_url)
            except Exception as exc:
                self._note_firecrawl_failure(exc)
                print(f"[Scraper] 列表页 Firecrawl 抓取失败，尝试直连：{exc}")
        if not links:
            links = self._direct_list_links(list_url)
        return links

    def _direct_list_links(self, list_url):
        response = self.session.get(list_url, timeout=self.timeout)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding
        soup = BeautifulSoup(response.text, "html.parser")
        candidates = self._article_link_candidates(soup, list_url)
        return self._filter_links(candidates, list_url)

    @staticmethod
    def _looks_like_article_url(url):
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        path = parsed.path.lower()
        if not path or path == "/":
            return False
        if path.endswith(_ASSET_SUFFIXES):
            return False
        if any(hint in path for hint in ("/static/", "/assets/", "/img/", "/images/", "/media/", "/uploads/")):
            return False
        if any(hint in path for hint in _VIDEO_PATH_HINTS):
            return False
        if re.search(r"/(?:article|story|news|posts?)/", path):
            return True
        if re.search(r"/20\d{2}[/-]\d{1,2}(?:[/-]\d{1,2})?", path):
            return True
        if re.search(
            r"/20\d{2}/(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)/\d{1,2}/",
            path,
        ):
            return True
        return False

    @staticmethod
    def _anchor_text(anchor):
        return " ".join(anchor.get_text(" ", strip=True).split())

    @staticmethod
    def _best_anchor_per_url(anchors, list_url):
        best_by_url = {}
        for anchor in anchors:
            try:
                absolute = urljoin(list_url or "", anchor.get("href", ""))
            except (TypeError, ValueError):
                continue
            key = absolute.rstrip("/")
            if not key:
                continue
            text = Scraper._anchor_text(anchor)
            previous = best_by_url.get(key)
            if previous is None or len(text) > len(Scraper._anchor_text(previous)):
                best_by_url[key] = anchor
        return list(best_by_url.values())

    @staticmethod
    def _article_link_candidates(soup, list_url=None):
        anchors = [
            anchor
            for anchor in soup.find_all("a", href=True)
            if Scraper._anchor_text(anchor)
        ]
        if not anchors:
            return []

        article_anchors = []
        for anchor in anchors:
            try:
                absolute = urljoin(list_url or "", anchor.get("href", ""))
            except (TypeError, ValueError):
                continue
            if not Scraper._looks_like_article_url(absolute):
                continue
            label = Scraper._anchor_text(anchor).lower()
            if len(label) < 6 and label in _NAV_LABELS:
                continue
            article_anchors.append(anchor)

        if article_anchors:
            return Scraper._best_anchor_per_url(article_anchors, list_url)

        articles = soup.find_all("article")
        if articles:
            candidates = []
            for article in articles:
                article_anchors = [
                    anchor
                    for anchor in article.find_all("a", href=True)
                    if Scraper._anchor_text(anchor)
                ]
                if not article_anchors:
                    continue
                candidates.append(
                    max(article_anchors, key=lambda anchor: len(Scraper._anchor_text(anchor)))
                )
            if candidates:
                return candidates

        selectors = (
            "h1 a[href]",
            "h2 a[href]",
            "h3 a[href]",
            ".entry-title a",
            ".post-title a",
            ".card a[href]",
            "[class*=title] a[href]",
        )
        for selector in selectors:
            nodes = [
                node
                for node in soup.select(selector)
                if node.get("href") and Scraper._anchor_text(node)
            ]
            if nodes:
                return nodes
        return anchors

    @staticmethod
    def _markdown_links(markdown, list_url):
        pattern = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
        candidates = []
        for match in pattern.finditer(markdown or ""):
            label = " ".join(match.group(1).split())
            candidates.append((label, match.group(2)))
        return Scraper._filter_links(candidates, list_url)

    @staticmethod
    def _base_domain(netloc):
        parts = (netloc or "").lower().split(".")
        if len(parts) <= 2:
            return ".".join(parts)
        return ".".join(parts[-2:])

    @staticmethod
    def _article_url_score(url, label):
        parsed = urlparse(url)
        path = parsed.path.lower()
        lowered = url.lower()
        score = 0
        if Scraper._looks_like_article_url(url):
            score += 20
        if path.endswith((".html", ".htm")):
            score += 4
        if label and len(label) >= 15:
            score += 2
        if label.lower() in _NAV_LABELS:
            score -= 20
        if any(hint in lowered for hint in _NON_ARTICLE_HINTS):
            score -= 30
        bare_path = path.rstrip("/")
        if bare_path in _SECTION_PATHS:
            score -= 20
        return score

    @staticmethod
    def _filter_links(candidates, list_url):
        base_netloc = urlparse(list_url).netloc.lower()
        base_domain = Scraper._base_domain(base_netloc)
        base_path = urlparse(list_url).path.rstrip("/") or "/"
        links = []
        seen = set()
        for candidate in candidates:
            if isinstance(candidate, str):
                raw_url = candidate
                label = ""
            elif isinstance(candidate, tuple):
                label, raw_url = candidate
            else:
                raw_url = candidate.get("href", "")
                label = " ".join(candidate.get_text(" ", strip=True).split())
            try:
                url = urljoin(list_url, raw_url)
            except (TypeError, ValueError):
                continue
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                continue
            if Scraper._base_domain(parsed.netloc.lower()) != base_domain:
                continue
            path = parsed.path.rstrip("/") or "/"
            if path == base_path:
                continue
            if parsed.path.lower().endswith(_ASSET_SUFFIXES):
                continue
            lowered_path = parsed.path.lower()
            if any(
                segment in lowered_path
                for segment in (
                    "/static/",
                    "/assets/",
                    "/img/",
                    "/images/",
                    "/media/",
                    "/uploads/",
                )
            ):
                continue
            if any(hint in lowered_path for hint in _VIDEO_PATH_HINTS):
                continue
            lowered = url.lower()
            if "loading_icon" in lowered or "placeholder" in lowered:
                continue
            if any(hint in lowered for hint in _NON_ARTICLE_HINTS):
                continue
            if re.search(r"/page/\d+/", path):
                continue
            if re.fullmatch(r"/\d{4}/\d{2}/?", path):
                continue
            if len(label) <= 4 and label.lower() in {
                "read more",
                "更多",
                "阅读全文",
                "首页",
                "home",
                "latest",
                "最新",
                "skip to content",
                "跳过内容",
            }:
                continue
            if re.fullmatch(
                r"(?:[A-Za-z]+ \d{1,2},? \d{4}|[A-Za-z]+ \d{4}|"
                r"\d{4}年\d{1,2}月)",
                label,
            ):
                continue
            normalized = f"{parsed.netloc.lower()}{path}"
            if normalized in seen:
                continue
            seen.add(normalized)
            links.append((Scraper._article_url_score(url, label), url))
        links.sort(key=lambda item: item[0], reverse=True)
        return [url for _score, url in links]

    @staticmethod
    def clean_content_text(text, source_config=None, html=False):
        source_config = source_config or {}
        if html:
            soup = BeautifulSoup(text or "", "html.parser")
            for selector in source_config.get("drop_selectors", []) or []:
                for node in soup.select(str(selector)):
                    node.decompose()
            return Scraper.clean_content_text(
                Scraper._html_to_text(str(soup)), source_config
            )

        lines = []
        previous = None
        for raw_line in (text or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            line = re.sub(r"!\[[^\]]*\]\([^)\s]+\)", "", line).strip()
            if not line:
                continue
            if Scraper._is_noise_line(line):
                continue
            link_match = re.fullmatch(
                r"\[([^\]]+)\]\((https?://[^)\s]+)\)", line
            )
            if link_match:
                continue
            if line == previous:
                continue
            lines.append(line)
            previous = line
        return "\n\n".join(lines)

    @staticmethod
    def _is_noise_line(line):
        stripped = line.strip()
        if not stripped:
            return True
        if _PURE_LINK_LINE_PATTERN.fullmatch(stripped):
            return True
        if _PHOTO_CAPTION_PATTERN.fullmatch(stripped):
            return True
        if stripped.startswith("![") or stripped.startswith("- !["):
            return True
        if re.fullmatch(r"[\[\]\\]+", stripped):
            return True
        if re.match(r"^[^\[\]\n]*\]\(https?://[^)\s]+\)$", stripped):
            return True
        if any(marker in stripped for marker in ("\\image\\", "\\title\\", "\\category\\")):
            return True
        if _NOISE_LINE_PATTERN.fullmatch(stripped):
            return True
        if _BYLINE_LINK_PATTERN.fullmatch(stripped):
            return True
        if _CGTN_TIME_LINE_PATTERN.fullmatch(stripped):
            return True
        if _CGTN_BRAND_PATTERN.fullmatch(stripped):
            return True
        if len(line) > 80:
            return False
        if re.fullmatch(r"\\+", stripped):
            return True
        if _TIME_AGO_PATTERN.fullmatch(stripped):
            return True
        if _DATE_LINE_PATTERN.fullmatch(stripped):
            return True
        if _BYLINE_PATTERN.fullmatch(stripped):
            return True
        if re.fullmatch(r"[-—–_=*#]{3,}", stripped):
            return True
        return False

    @staticmethod
    def _is_noise_label(label):
        lowered = (label or "").lower().strip()
        if not lowered:
            return True
        return _NOISE_LINE_PATTERN.fullmatch(lowered) or "このページを" in label

    def fetch_url(self, url, source_config=None):
        """Fetch a single arbitrary article URL and return the standard article dict."""
        url = (url or "").strip()
        if not re.match(r"^https?://", url, flags=re.IGNORECASE):
            raise ValueError("请输入以 http:// 或 https:// 开头的有效网址")

        collect_images = (source_config or {}).get("region") == "food"
        content_text = ""
        title = ""
        pub_date = datetime.now().strftime("%Y-%m-%d")
        last_error = None
        images = []
        image_positions = []

        prefer_direct = bool((source_config or {}).get("content_selector"))
        if self._firecrawl_ready() and not prefer_direct:
            try:
                markdown = self.firecrawl.scrape_markdown(url)
                title, content_text, images, image_positions = self._markdown_title_and_text(
                    markdown, source_config, collect_images=collect_images, base_url=url
                )
            except Exception as exc:
                self._note_firecrawl_failure(exc)
                last_error = exc
                print(f"[Scraper] 自定义网址 Firecrawl 抓取失败：{exc}，尝试直连")

        if not content_text:
            try:
                title, content_text, pub_date, images, image_positions = self._fetch_direct_article(
                    url, source_config, collect_images=collect_images
                )
            except Exception as exc:
                last_error = exc
                print(f"[Scraper] 自定义网址直连抓取失败：{exc}")

        if not content_text:
            detail = f"（{last_error}）" if last_error else ""
            raise ValueError(f"未能提取正文：{url}{detail}")

        return {
            "title": title or _clean_text(url),
            "url": url,
            "pub_date": pub_date,
            "content_text": content_text,
            "images": images,
            "image_positions": image_positions,
        }

    @staticmethod
    def _markdown_title_and_text(markdown, source_config=None, collect_images=False, base_url=None):
        title = ""
        for line in (markdown or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                title = _clean_text(stripped.lstrip("#"))
                break
        images = []
        image_positions = []
        if collect_images:
            title, content_text, images, image_positions = Scraper._markdown_text_images_positions(
                markdown, source_config, base_url=base_url
            )
            return title, content_text, images, image_positions
        return (
            title,
            Scraper.clean_content_text(
                Scraper._firecrawl_to_text(markdown), source_config
            ),
            images,
            image_positions,
        )

    @staticmethod
    def _markdown_text_images_positions(markdown, source_config=None, base_url=None):
        title = ""
        started = False
        paragraphs = []
        images = []
        positions = []
        seen = set()
        image_pattern = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
        skip_prefixes = ("![", "Video Player", "Share", "Facebook", "X ", "LINE")

        for raw_line in (markdown or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("# "):
                if not title:
                    title = _clean_text(line.lstrip("# "))
                started = True
                continue
            if not started:
                continue
            if line.startswith("- !["):
                line = line[2:].strip()
            if line.startswith("!["):
                match = image_pattern.match(line)
                if match:
                    raw_url = match.group(2)
                    url = urljoin(base_url or "", raw_url)
                    parsed = urlparse(url)
                    if parsed.scheme not in ("http", "https"):
                        continue
                    normalized = url.rstrip("/")
                    if normalized in seen:
                        continue
                    seen.add(normalized)
                    image_index = len(images)
                    images.append({"url": url, "alt": " ".join(match.group(1).split())})
                    positions.append(
                        {"image_index": image_index, "after_paragraph": len(paragraphs) - 1}
                    )
                continue
            if line.startswith("#") or line.startswith(skip_prefixes):
                continue
            if re.fullmatch(r"\d+ (hours|minutes|days) ago", line, flags=re.I):
                continue
            cleaned_line = Scraper.clean_content_text(line, source_config).strip()
            if cleaned_line:
                paragraphs.append(cleaned_line)

        return title, "\n\n".join(paragraphs), images, positions

    def _fetch_direct_article(self, url, source_config=None, collect_images=False):
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding
        soup = BeautifulSoup(response.text, "html.parser")
        node = self._direct_content_node(soup, source_config, url)
        for selector in (source_config or {}).get("drop_selectors", []) or []:
            for tag in node.select(str(selector)):
                tag.decompose()
        for tag in node.find_all(
            ["script", "style", "nav", "footer", "aside", "form", "noscript"]
        ):
            tag.decompose()
        images = []
        image_positions = []
        if collect_images:
            content_text, images, image_positions = Scraper._direct_content_with_images(
                node or soup, url, source_config
            )
        else:
            content_text = (
                Scraper.clean_content_text(self._html_to_text(str(node)), source_config)
                if node
                else ""
            )
        return (
            self._direct_title(soup),
            content_text,
            self._direct_pub_date(soup),
            images,
            image_positions,
        )

    @staticmethod
    def _direct_content_with_images(node, base_url, source_config=None):
        if node is None:
            return "", [], []
        soup = BeautifulSoup(str(node), "html.parser")
        images = []
        seen = set()
        for img in soup.find_all("img"):
            raw_src = (
                img.get("src")
                or img.get("data-src")
                or img.get("data-original")
            )
            srcset = img.get("srcset") or img.get("data-srcset")
            if not raw_src and srcset:
                first = srcset.split(",")[0].strip()
                raw_src = first.split(" ")[0] if first else ""
            if not raw_src:
                img.decompose()
                continue
            url = urljoin(base_url, raw_src)
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                img.decompose()
                continue
            lowered = url.lower()
            if "loading_icon" in lowered or "placeholder" in lowered or "/spacer" in lowered:
                img.decompose()
                continue
            normalized = parsed.netloc.lower() + parsed.path
            if normalized in seen:
                img.decompose()
                continue
            seen.add(normalized)
            image_index = len(images)
            images.append(
                {"url": url, "alt": " ".join(img.get("alt", "").split())}
            )
            img.replace_with(f"[[JP_IMAGE_{image_index}]]")

        raw_text = Scraper._html_to_text(str(soup))
        paragraphs = []
        positions = []
        marker_pattern = re.compile(r"^\[\[JP_IMAGE_(\d+)\]\]$")
        for line in raw_text.splitlines():
            stripped = line.strip()
            match = marker_pattern.match(stripped)
            if match:
                positions.append(
                    {
                        "image_index": int(match.group(1)),
                        "after_paragraph": len(paragraphs) - 1,
                    }
                )
                continue
            if not Scraper.clean_content_text(stripped, source_config).strip():
                continue
            paragraphs.append(stripped)
        return "\n\n".join(paragraphs), images, positions

    @staticmethod
    def _extract_markdown_images(markdown, base_url=None):
        images = []
        seen = set()
        pattern = re.compile(r"!\[([^\]]*)\]\((https?://[^)\s]+)\)")
        for match in pattern.finditer(markdown or ""):
            url = match.group(2)
            normalized = url.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            images.append({"url": url, "alt": " ".join(match.group(1).split())})
        return images

    @staticmethod
    def _extract_html_images(node, base_url):
        images = []
        seen = set()
        for img in node.find_all("img"):
            raw_src = (
                img.get("src")
                or img.get("data-src")
                or img.get("data-original")
            )
            srcset = img.get("srcset") or img.get("data-srcset")
            if not raw_src and srcset:
                first = srcset.split(",")[0].strip()
                raw_src = first.split(" ")[0] if first else ""
            if not raw_src:
                continue
            url = urljoin(base_url, raw_src)
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                continue
            lowered = url.lower()
            if "loading_icon" in lowered or "placeholder" in lowered or "/spacer" in lowered:
                continue
            normalized = parsed.netloc.lower() + parsed.path
            if normalized in seen:
                continue
            seen.add(normalized)
            images.append(
                {"url": url, "alt": " ".join(img.get("alt", "").split())}
            )
        return images

    @staticmethod
    def _direct_title(soup):
        h1 = soup.find("h1")
        if h1:
            title = _clean_text(h1.get_text(" "))
            if title:
                return title
        og_title = soup.find("meta", attrs={"property": "og:title"})
        if og_title and og_title.get("content"):
            return _clean_text(og_title["content"])
        if soup.title and soup.title.get_text(strip=True):
            return _clean_text(soup.title.get_text(" "))
        return ""

    @staticmethod
    def _direct_content_node(soup, source_config=None, url=None):
        def wrap_nodes(nodes):
            if not nodes:
                return None
            if len(nodes) == 1:
                return nodes[0]
            wrapper = soup.new_tag("div")
            for node in nodes:
                wrapper.append(node)
            return wrapper

        content_selector = (source_config or {}).get("content_selector", "")
        if content_selector:
            for selector in str(content_selector).split(","):
                selector = selector.strip()
                if not selector:
                    continue
                node = wrap_nodes(soup.select(selector))
                if node is not None:
                    return node
        if url:
            netloc = urlparse(url).netloc.lower()
            if netloc == "bbc.com" or netloc.endswith(".bbc.com") or netloc == "bbc.co.uk" or netloc.endswith(".bbc.co.uk"):
                node = wrap_nodes(soup.select("div[data-component='text-block']"))
                if node is not None:
                    return node
        for selector in (
            "article",
            "main",
            "[role=main]",
            ".article-body",
            "#news_textbody",
            ".post-content",
            ".entry-content",
        ):
            node = soup.select_one(selector)
            if node is not None:
                return node
        return soup.body or soup

    @staticmethod
    def _direct_pub_date(soup):
        for selector in (
            "meta[property='article:published_time']",
            "meta[name='date']",
            "time[datetime]",
        ):
            node = soup.select_one(selector)
            if node is not None:
                value = node.get("content") or node.get("datetime") or ""
                match = re.search(r"\d{4}-\d{2}-\d{2}", value)
                if match:
                    return match.group(0)
        return datetime.now().strftime("%Y-%m-%d")

    def _fetch_from_official_api(self, limit=None):
        fetch_limit = int(limit or self.max_articles)
        response = self.session.get(self.LIST_URL, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", []) if isinstance(payload, dict) else payload
        if not isinstance(data, list):
            return []

        today_compact = datetime.now().strftime("%Y%m%d")
        candidates = [
            item for item in data
            if str(item.get("id", "")).startswith(today_compact + "_")
        ]
        if not candidates:
            candidates = sorted(
                data,
                key=lambda item: int(item.get("updated_at") or 0),
                reverse=True,
            )

        articles = []
        for item in candidates:
            news_id = str(item.get("id", ""))
            title = _clean_text(item.get("title", ""))
            page_url = item.get("page_url", "")
            if not news_id or not title or not page_url:
                continue

            url = page_url if page_url.startswith("http") else self.PAGE_BASE + page_url
            content_text = ""
            if self.scrape_mode == "firecrawl":
                try:
                    content_text = self._fetch_firecrawl_text(url)
                except Exception as exc:
                    print(f"[Scraper] 文章 {title} Firecrawl 抓取失败：{exc}")
                if not content_text:
                    try:
                        content_text = self._fetch_detail_text(news_id)
                    except Exception as exc:
                        print(f"[Scraper] 文章 {title} 详情抓取失败：{exc}")
            else:
                try:
                    content_text = self._fetch_detail_text(news_id)
                except Exception as exc:
                    print(f"[Scraper] 文章 {title} 详情抓取失败：{exc}")
                    if self.scrape_mode == "auto":
                        try:
                            content_text = self._fetch_firecrawl_text(url)
                        except Exception as fire_exc:
                            print(f"[Scraper] 文章 {title} Firecrawl 兜底抓取失败：{fire_exc}")

            if not content_text:
                content_text = _clean_text(item.get("description", ""))
            if not content_text:
                print(f"[Scraper] 文章 {title} 没有可用正文，跳过")
                continue

            articles.append(
                {
                    "title": title,
                    "url": url,
                    "pub_date": _pub_date(item, news_id),
                    "content_text": content_text,
                    "images": [],
                }
            )
            if len(articles) >= fetch_limit:
                break
        return articles

    def _fetch_detail_text(self, news_id):
        response = self.session.get(
            self.DETAIL_URL.format(news_id=news_id),
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", payload) if isinstance(payload, dict) else payload
        if not isinstance(data, dict):
            return ""
        detail_html = data.get("detail", "")
        return self._html_to_text(detail_html) if detail_html else ""

    @staticmethod
    def _html_to_text(html_text):
        soup = BeautifulSoup(html_text or "", "html.parser")
        for br in soup.find_all("br"):
            br.replace_with("\n")
        raw_lines = soup.get_text("\n").splitlines()
        lines = [
            re.sub(r"\s+", " ", line).strip()
            for line in raw_lines
            if line.strip()
        ]
        return "\n\n".join(lines)

    def _fetch_firecrawl_text(self, url):
        if not self._firecrawl_ready():
            return ""
        markdown = self.firecrawl.scrape_markdown(url)
        return self._firecrawl_to_text(markdown)

    @staticmethod
    def _firecrawl_to_text(markdown):
        lines = []
        started = False
        skip_prefixes = ("![", "Video Player", "Share", "Facebook", "X ", "LINE")
        for raw_line in (markdown or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("# "):
                started = True
                continue
            if not started:
                continue
            if line.startswith("- ![") or line.startswith(("- Share", "- Facebook", "- X", "- LINE")):
                continue
            if line.startswith("#") or line.startswith(skip_prefixes):
                continue
            if re.fullmatch(r"\d+ (hours|minutes|days) ago", line, flags=re.I):
                continue
            lines.append(line)
        return "\n\n".join(lines)

def _clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def _pub_date(item, news_id):
    compact_date = str(news_id)[:8]
    if len(compact_date) == 8 and compact_date.isdigit():
        return (
            f"{compact_date[:4]}-{compact_date[4:6]}-{compact_date[6:8]}"
        )
    updated_at = item.get("updated_at", "")
    try:
        return datetime.fromtimestamp(int(updated_at) / 1000).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return datetime.now().strftime("%Y-%m-%d")
