# 言叶（KOTOBA）

一个基于 DeepSeek 的 Windows 英语阅读应用：抓取英文新闻、文化与生活内容，生成翻译、重点词汇、难句解析和背景补充，并以现代阅读界面展示。

详细安装、运行、来源配置与打包说明见：

- [nhk_english_digest/README.md](nhk_english_digest/README.md)

## 项目结构

```text
nhk_english_digest/
├── desktop_app.py        # CustomTkinter 桌面应用入口
├── main.py               # 命令行抓取、注释与刷新
├── scraper.py            # 新闻内容抓取
├── annotator.py          # DeepSeek AI 注释
├── ui_theme.py           # 设计系统
├── ui_components.py      # 复用 UI 组件
├── config.template.yaml  # 配置模板（真实 Key 不入库）
└── README.md             # 项目文档
```

## 隐私说明

- 真实 `config.yaml`、`secret_store.json`、`output/`、`logs/`、虚拟环境与打包产物均已被 `.gitignore` 忽略，不会提交到仓库。
- 运行前请在应用“设置”页自行填写 DeepSeek API Key；Firecrawl API Key 可选。

## 开发运行

```powershell
cd nhk_english_digest
python -m venv .venv314
.venv314\Scripts\activate
pip install -r requirements.txt
python desktop_app.py
```

## 打包

```powershell
cd nhk_english_digest
powershell -ExecutionPolicy Bypass -File build.ps1
```
