import json
import re

import requests


SYSTEM_PROMPT = """你是一位资深英语教师兼翻译专家。请对以下英文文章进行深度解析，严格按照 JSON 格式输出，每个字段都必须存在：
{
"title": "原标题",
"translation": "英文原文第1段\\n对应中文翻译第1段\\n英文原文第2段\\n对应中文翻译第2段",
"vocabulary": [
{
"word": "单词",
"pos": "词性缩写",
"meaning_cn": "中文释义",
"level": "常见英语学习等级，如 CET4、CET6、TOEFL 或日常",
"example_sentence": "原文中包含该词的句子"
}
],
"difficult_sentences": [
{
"original": "原句",
"analysis": "语法结构解析",
"translation": "整句中文翻译"
}
],
"background": "与该新闻相关的背景知识补充（50字以内，若无则写'无需额外背景'）"
}
要求：
vocabulary 至少提取 5 个词汇，并标注合理的学习等级
difficult_sentences 至少解析 2 句
翻译需准确、通顺，符合中文表达习惯
translation 必须逐段对照：按原文段落顺序，每段先输出该段英文原文，再输出该段中文翻译；不同段落之间用空行分隔，不得漏段或合并段落，确保英文段落与中文段落一一对应
任何一句英文原文或中文翻译都不得连续重复出现，同一句话只输出一次
不要添加任何额外说明文字，只输出 JSON"""


class Annotator:
    def __init__(self, api_key, base_url, model):
        self.api_key = api_key or ""
        self.base_url = (base_url or "https://api.deepseek.com/v1").rstrip("/")
        self.model = model or "deepseek-chat"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "japan-news-study/3.0",
                "Content-Type": "application/json",
            }
        )

    def annotate(self, article_dict):
        if not self.api_key:
            raise RuntimeError(
                "未配置 DeepSeek API Key，请在 config.yaml 的 openai_api_key 填写后重试"
            )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"标题：{article_dict['title']}\n"
                        f"原文：\n{article_dict['content_text']}"
                    ),
                },
            ],
            "temperature": 0.2,
            "max_tokens": 8000,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_error = "未知错误"
        for attempt in (1, 2):
            try:
                print(f"[Annotator] 调用 {self.base_url} 第 {attempt} 次")
                response = self.session.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=60,
                )
                response.raise_for_status()
                raw = response.json()["choices"][0]["message"]["content"]
                annotation = _parse_json(raw, tolerate_truncation=True)
                return self._fill_defaults(annotation, article_dict)
            except Exception as exc:
                last_error = str(exc)
                print(f"[Annotator] 第 {attempt} 次调用或解析失败：{exc}")

        print("[Annotator] 调用失败，返回默认错误结构")
        return self._default_error(article_dict, error=last_error)

    def _fill_defaults(self, annotation, article):
        defaults = self._default_error(article)
        merged = dict(defaults)
        merged.update(annotation)
        merged["status"] = "ok"
        merged["error"] = ""
        merged["title"] = merged.get("title") or article.get("title") or defaults["title"]
        if not merged.get("translation"):
            merged["translation"] = annotation.get(
                "translation_cet4", annotation.get("translation_cet6", "")
            )
        if not isinstance(merged.get("vocabulary"), list):
            merged["vocabulary"] = defaults["vocabulary"]
        if not isinstance(merged.get("difficult_sentences"), list):
            merged["difficult_sentences"] = defaults["difficult_sentences"]
        return merged

    def _default_error(self, article, error=""):
        title = article.get("title", "未知标题")
        return {
            "title": title,
            "status": "error",
            "error": error or "注释生成失败",
            "translation": "本次注释生成失败，请检查 API 配置后重试。",
            "vocabulary": [
                {
                    "word": "network",
                    "pos": "n.",
                    "meaning_cn": "网络",
                    "level": "CET4",
                    "example_sentence": "The network request failed.",
                }
            ],
            "difficult_sentences": [
                {
                    "original": article.get("content_text", "")[:120],
                    "analysis": "注释服务暂时不可用，未能完成原句解析。",
                    "translation": "请稍后重试。",
                }
            ],
            "background": "无需额外背景",
        }


def _parse_json(text, tolerate_truncation=False):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1:
        raise ValueError("返回内容中未找到 JSON 对象")
    candidate = text[start:] if end == -1 else text[start : end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        if not tolerate_truncation:
            raise
        try:
            repaired = _repair_truncated_json(candidate)
        except ValueError:
            raise
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            raise


def _repair_truncated_json(text):
    """Salvage a JSON object cut off by the model's output limit."""
    containers = []
    closers = {"{": "}", "[": "]"}
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            containers.append(closers[char])
        elif char in "}]":
            if containers and containers[-1] == char:
                containers.pop()

    repaired = text
    if in_string:
        trailing_backslashes = len(repaired) - len(repaired.rstrip("\\"))
        if trailing_backslashes % 2 == 1:
            repaired += "\\"
        repaired += '"'
    while containers:
        repaired += containers.pop()
    return repaired
