# 言叶

当前版本：4.9.0

一个 Windows 桌面应用：按区域抓取日本相关英文内容，使用 DeepSeek 生成中文学习注释（翻译、重点词汇、难句解析、背景补充），结果保存为本地 Markdown 文件。

内容仅供学习参考，请自行辨别信息真实度，作者不为爬取内容负责。

## 区域与周期

应用分为三个区域：

- 新闻：NHK WORLD（日刊）、Japan Forward（日刊）、自定义网址与设置中新增的来源
- 美食：Time Out Tokyo（月刊）
- 文化：预留区域，可在 `config.yaml` 的 `sources` 中添加来源

日刊刷新只处理列表页当前可见的最新条目并跳过已收录文章；月刊刷新在列表范围内按来源全部历史 URL 去重，未收录的文章会增量录入。

## 开发运行

```powershell
python -m venv .venv314
.venv314\Scripts\activate
pip install -r requirements.txt
python desktop_app.py
```

桌面界面基于 CustomTkinter，依赖已包含在 `requirements.txt` 中；打包脚本会通过 `--collect-all customtkinter` 一并收集所需资源。

首次打开应用后，在“设置”中填入：

- DeepSeek API Key（必填）
- Firecrawl API Key（可选，用于直连失败时兜底抓取）

点击“全局刷新”会刷新全部启用的来源；每个区域页内也有“仅刷新本区域”按钮。刷新时会显示当前来源的翻译进度，已有文章不会重复调用 API。

API Key 不会明文写入 `config.yaml`，会使用 Windows DPAPI 加密后保存在程序目录的 `secret_store.json`。

## 来源管理

“设置”中的“来源管理”区域可以启用或停用每个来源，并调整单次抓取上限。3.4 起可直接点击“新增来源”，填写显示名称、网址、区域、周期和来源类型；来源会参与全局刷新与每日定时任务。每行“删除”按钮只移除配置项，不会删除已抓取文章。

新增报刊也可以不改代码，在 `config.yaml` 的 `sources` 中复制一条 `list_page` 条目，修改 `id`、`name`、`region`、`period`、`url`、`limit` 即可。

- `region`：`news`（新闻）、`food`（美食）、`culture`（文化）
- `period`：`daily`（日刊）、`monthly`（月刊）
- `adapter`：`nhk_json`（NHK 官方 JSON API）、`list_page`（通用列表页抓取）或 `single_url`（固定单篇文章链接）
- `content_selector`：可选，正文 CSS 选择器；为空时使用内置的 `article` / `main` / `.article-body` 等回退链
- `drop_selectors`：可选，正文提取后需要丢弃的噪声节点 CSS 选择器列表

## 抓取任意网址并翻译

在顶部“网址”输入框粘贴一个 `http://` 或 `https://` 开头的文章链接，点击“抓取并翻译”，应用会抓取正文并用 DeepSeek 生成与日报相同的注释。

自定义网址文章保存在 `output/custom/YYYY-MM-DD/`，在新闻页的“自定义网址”分组中展示。同一天重复抓取同一个网址时会直接跳过，不重复调用 API。

抓取正文时优先使用 Firecrawl（API Key 或已登录的本机 CLI），失败或未配置时自动降级为 `requests + BeautifulSoup` 直连。

## 正文噪声清洗

3.1 起，列表页来源和自定义网址抓取得到的正文都会经过统一清洗：先按来源配置的 `drop_selectors` 删除噪声节点，再过滤图片行、纯链接行、`Read more`、`Leave a Reply`、相关文章、分享按钮、广告等短噪声行。NHK 官方 JSON API 返回的正文不经过此清洗，不受影响。

美食区会保留全部图片，下载到文章旁的 `assets/` 目录并在详情页显示；新闻、文化区域仍按原规则过滤图片。

已经收录的旧文章不会自动重写。在文章卡片或详情页点击“重新抓取”，应用会重新下载原文、重新调用 DeepSeek 翻译，并覆盖原文件（保留原序号和文件名，同时重建当天 `index.md`）。

## 输出目录

新结构为：

```text
output/
  news/nhk/daily/YYYY-MM-DD/
  news/japan_forward/daily/YYYY-MM-DD/
  food/timeout_tokyo/monthly/YYYY-MM-DD/
  custom/YYYY-MM-DD/
```

每个日期目录内包含文章 Markdown 与 `index.md`。删除文章后会自动重建对应日期的 `index.md`。

旧版 `output/YYYY-MM-DD/` 目录会在首次启动时自动迁移到 `output/news/nhk/daily/`，旧文件仍可正常阅读。

## 打包成可移动应用

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

打包结果在 `dist\言叶\`。把整个文件夹复制到其他 Windows 电脑，双击 `言叶.exe`，在设置页输入 DeepSeek API Key 即可使用。

打包后的应用不会内置真实 API Key；`config.yaml` 和 `output/` 都会生成在 exe 旁边，方便整体携带。

首次启动时，应用会把内置的 Tcl/Tk 运行库复制到 `C:\Users\Public\JapanNewsStudy`（纯 ASCII 路径），之后会自动复用，不影响使用。

## 抓取模式

`config.yaml` 中的 `scrape_mode` 支持三种：

- `auto`：直连优先，失败后用 Firecrawl 兜底
- `direct`：只用直连请求
- `firecrawl`：Firecrawl 优先，失败后直连

Firecrawl 支持两种使用方式：

1. 在设置中填写 `firecrawl_api_key`
2. 电脑上已安装并登录 Firecrawl CLI 时，程序会自动调用本机 CLI

## 命令行

```powershell
python main.py                # 全局刷新全部来源
python main.py --region news  # 只刷新新闻区域
python main.py --rebuild 路径 # 重新抓取并翻译一篇已收录的文章
python main.py --backfill-images food # 仅补全已有美食文章的图片
python scheduler.py           # 按 schedule_time 每天定时执行
```

勾选“每日定时”会在 Windows 任务计划程序中创建 `JapanNewsStudyDaily`，程序关闭后也能按点刷新。
