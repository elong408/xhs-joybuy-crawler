# 小红书 Joybuy 每日内容采集与分析

这是一个本地运行的低频采集工具，用于在你本人已登录的小红书网页中搜索 Joybuy 相关内容，并生成每日数据表和分析总结。

## 合规说明

- 不保存账号密码。
- 不绕过登录、验证码、安全验证、付费墙或风控。
- 只采集浏览器页面中你可以正常看到的内容。
- 如果出现验证码、登录过期或访问异常，脚本会停止，需要你手动处理后再运行。
- 建议低频使用，不要高频批量采集。

## 安装

```bash
npm install
npm run install-browser
```

## 首次登录

运行采集脚本：

```bash
npm run crawl
```

脚本会打开一个 Chromium 浏览器窗口。如果提示登录，请你在浏览器里手动登录小红书。登录完成后，回到终端按 Enter 继续。

登录状态保存在本地目录：`.browser-profile/xhs`。该目录已加入 `.gitignore`。

## 每日采集

```bash
npm run crawl
```

默认搜索关键词在 `config/joybuy_crawler.json`：

- `joybuy`
- `Joybuy`
- `京东 joybuy`
- `京东国际 joybuy`
- `JD joybuy`

采集结果保存到：

```text
output/YYYY-MM-DD/raw_notes.csv
output/YYYY-MM-DD/raw_notes.json
```

## 分析总结

采集完成后运行：

```bash
npm run analyze
```

输出文件：

```text
output/YYYY-MM-DD/analyzed_notes.csv
output/YYYY-MM-DD/analyzed_notes.json
output/YYYY-MM-DD/daily_report.md
output/YYYY-MM-DD/daily_report.html
```

分析内容包括：

- 每日头部内容 Top 10
- 主题分类
- 情绪分类
- 风险点识别
- 用户诉求总结
- 初步运营建议

## 配置

编辑 `config/joybuy_crawler.json`：

```json
{
  "keywords": ["joybuy", "京东国际 joybuy"],
  "max_notes_per_keyword": 20,
  "open_detail_top_n": 10,
  "scroll_rounds": 6,
  "min_delay_seconds": 3,
  "max_delay_seconds": 8,
  "always_wait_for_login": true,
  "headless": false,
  "output_dir": "output",
  "profile_dir": ".browser-profile/xhs"
}
```

## 注意事项

小红书页面结构可能变化。如果采集结果为空，请先确认：

1. 浏览器是否已经登录。
2. 搜索结果页是否能正常看到笔记卡片。
3. 是否出现验证码或安全验证。
4. 关键词是否有足够结果。

如果页面结构变化导致字段缺失，可以保留 `raw_text`，再调整解析规则。

## 用户洞察看板

生成本地 HTML 看板：

```bash
npm run dashboard
```

默认读取最新日期目录中的 `output/YYYY-MM-DD/analyzed_notes.csv`；如果没有分析文件，则读取最新日期目录中的 `output/YYYY-MM-DD/raw_notes.csv`。

也可以指定输入文件：

```bash
python3 scripts/build_dashboard.py output/2026-06-18/analyzed_notes.csv
```

输出文件：

```text
dashboard/dashboard_data.json
dashboard/index.html
```

直接用浏览器打开 `dashboard/index.html` 即可查看。看板包含：

- 核心指标：内容量、痛点占比、爽点占比、负向占比、总互动分
- 爽点概览：价格、物流、正品信任、商品体验、购买便利
- 痛点归类：产品体验、商品质量、物流履约、售后服务、价格促销、品牌信任
- 体验提升机会：每类痛点对应的原因、代表内容和行动建议
- 明细表：支持按关键词、痛点分类、情绪筛选
