import re
from pathlib import Path
from urllib.parse import urlparse

import requests


SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}


def is_remote_url(url):
    return bool(re.match(r"^https?://", (url or "").strip(), flags=re.IGNORECASE))


def _safe_stem(value):
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", value or "image")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:60] or "image"


def _extension_for(url, content_type=""):
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in SUPPORTED_IMAGE_SUFFIXES:
        return suffix
    return CONTENT_TYPE_EXT.get((content_type or "").split(";")[0].strip().lower(), ".jpg")


def download_article_images(article, article_path, only_region="food"):
    if article.get("region", only_region) != only_region:
        return article
    images = article.get("images") or []
    if not images:
        return article

    article_path = Path(article_path)
    assets_dir = article_path.parent / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_stem(article_path.stem)

    local_images = []
    for index, image in enumerate(images, start=1):
        url = (image or {}).get("url", "") if isinstance(image, dict) else str(image)
        alt = (image or {}).get("alt", "") if isinstance(image, dict) else ""
        if not is_remote_url(url):
            local_images.append({"url": url, "alt": alt, "local": False})
            continue
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "japan-news-study/kotoba"},
                timeout=20,
                stream=True,
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if content_type and not content_type.lower().startswith("image/"):
                local_images.append({"url": url, "alt": alt, "local": False})
                continue
            extension = _extension_for(url, content_type)
            filename = f"{stem}_{index:02d}{extension}"
            target = assets_dir / filename
            with target.open("wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            local_images.append(
                {"url": f"assets/{filename}", "alt": alt, "local": True}
            )
        except Exception:
            local_images.append({"url": url, "alt": alt, "local": False})

    article = dict(article)
    article["images"] = local_images
    return article
