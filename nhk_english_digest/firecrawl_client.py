import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests


SCRAPE_ENDPOINT = "https://api.firecrawl.dev/v1/scrape"


class FirecrawlError(RuntimeError):
    pass


class FirecrawlClient:
    """Minimal Firecrawl client that supports both API key and local CLI auth."""

    def __init__(self, api_key="", timeout=60):
        self.api_key = (api_key or "").strip()
        self.timeout = int(timeout or 60)
        self.cli_path = self._find_cli_path()

    def available(self):
        return bool(self.api_key or self.cli_path)

    def scrape_markdown(self, url, only_main_content=True):
        if self.api_key:
            return self._scrape_via_api(url, only_main_content)
        if self.cli_path:
            return self._scrape_via_cli(url, only_main_content)
        raise FirecrawlError(
            "Firecrawl 不可用：未配置 firecrawl_api_key，也未找到已登录的 Firecrawl CLI"
        )

    def _scrape_via_api(self, url, only_main_content):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "url": url,
            "formats": ["markdown"],
            "onlyMainContent": only_main_content,
        }
        response = requests.post(
            SCRAPE_ENDPOINT,
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = (response.json() or {}).get("data") or {}
        markdown = (data.get("markdown") or "").strip()
        if not markdown:
            raise FirecrawlError(f"Firecrawl API 未返回正文内容：{url}")
        return markdown

    def _scrape_via_cli(self, url, only_main_content):
        fd, tmp_name = tempfile.mkstemp(suffix=".md")
        os.close(fd)
        output_path = Path(tmp_name)
        cmd = [self.cli_path, "scrape", url]
        if only_main_content:
            cmd.append("--only-main-content")
        cmd.extend(["-o", str(output_path)])
        if os.name == "nt" and self.cli_path.lower().endswith((".cmd", ".bat")):
            cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/c"] + cmd
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout + 30,
            )
            if proc.returncode != 0:
                raise FirecrawlError(
                    f"Firecrawl CLI 抓取失败：{proc.stderr.strip() or proc.stdout.strip()}"
                )
            markdown = output_path.read_text(encoding="utf-8").strip()
            if not markdown:
                raise FirecrawlError(f"Firecrawl CLI 未返回正文内容：{url}")
            return markdown
        except FirecrawlError:
            raise
        except Exception as exc:
            raise FirecrawlError(f"Firecrawl CLI 调用失败：{exc}") from exc
        finally:
            output_path.unlink(missing_ok=True)

    @staticmethod
    def _find_cli_path():
        for name in ("firecrawl", "firecrawl.cmd", "firecrawl.exe"):
            found = shutil.which(name)
            if found:
                return found
        if os.name == "nt":
            appdata = os.environ.get("APPDATA", "")
            if appdata:
                candidate = Path(appdata) / "npm" / "firecrawl.cmd"
                if candidate.exists():
                    return str(candidate)
        return ""
