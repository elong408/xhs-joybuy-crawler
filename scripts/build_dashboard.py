#!/usr/bin/env python3
import csv
import html
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path.cwd()
OUTPUT_ROOT = ROOT / 'output'
DASHBOARD_DIR = ROOT / 'dashboard'

PAIN_RULES = [
    ('产品体验', ['搜索', '页面', '打不开', '404', '登录', '支付', '下单', '流程', '入口', 'bug', '卡顿', '体验差', '不好用'], '优化核心路径和页面可用性，减少用户完成购买和查找信息的摩擦。'),
    ('商品质量', ['假货', '真假', '正品', '破损', '临期', '质量', '包装', '漏', '坏', '瑕疵', '不符', '鉴别'], '加强商品准入、质检、包装和正品信任表达，降低质量不确定性。'),
    ('物流履约', ['物流', '配送', '快递', '清关', '延迟', '慢', '丢件', '没到', '到货', '时效', '仓', '保税'], '提升履约时效透明度，补齐异常物流预警、解释和补偿机制。'),
    ('售后服务', ['售后', '客服', '退款', '退货', '换货', '不退', '拒绝', '投诉', '联系不上', '处理'], '提升客服响应、退换货规则清晰度和售后闭环效率。'),
    ('价格促销', ['价格', '优惠', '券', '补贴', '涨价', '比价', '贵', '便宜', '活动', '折扣', '虚假'], '优化促销解释、价格保护和优惠使用体验，减少用户对价格机制的不信任。'),
    ('品牌信任', ['靠谱吗', '可靠', '信任', '平台', '京东', 'Joybuy', 'JD', '避雷', '踩雷', '翻车', '曝光'], '强化平台背书、用户证据链和负面舆情响应，提升品牌可信度。')
]

NEGATIVE_SIGNAL_WORDS = ['避雷', '踩雷', '投诉', '差评', '失败', '不退', '拒绝', '失望', '翻车', '坑', '慢', '贵', '假货', '打不开', '404', '联系不上', '退款', '破损', '延迟']

ACTION_MAP = {
    '产品体验': ['排查搜索到详情页链路', '优化页面错误提示与重试', '减少下单关键路径步骤'],
    '商品质量': ['补充正品/质检证明', '加强包装与发货前检查', '建立质量问题快速赔付机制'],
    '物流履约': ['展示预计到达和清关节点', '异常物流主动通知', '建立延迟补偿或安抚方案'],
    '售后服务': ['明确退换货规则', '缩短客服首次响应时间', '建立退款进度可视化'],
    '价格促销': ['解释优惠叠加规则', '上线价格保护说明', '减少券不可用的用户困惑'],
    '品牌信任': ['沉淀真实用户案例', '统一负面问题回应口径', '强化 Joybuy 与京东背书关系']
}


def normalize_count(value):
    text = str(value or '').strip().replace(',', '')
    match = re.search(r'(\d+(?:\.\d+)?)(万|k|K)?', text)
    if not match:
        return 0
    number = float(match.group(1))
    if match.group(2) == '万':
        number *= 10000
    elif match.group(2) in ('k', 'K'):
        number *= 1000
    return int(number)


def find_latest_input():
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    date_dir_pattern = re.compile(r'\d{4}-\d{2}-\d{2}$')
    raw = sorted(
        (path for path in OUTPUT_ROOT.glob('*/raw_notes.csv') if date_dir_pattern.search(path.parent.name)),
        reverse=True
    )
    if raw:
        return raw
    analyzed = sorted(
        (path for path in OUTPUT_ROOT.glob('*/analyzed_notes.csv') if date_dir_pattern.search(path.parent.name)),
        reverse=True
    )
    if raw:
        return raw[0]
    if analyzed:
        return analyzed[0]
    raise FileNotFoundError('找不到 output/*/analyzed_notes.csv 或 output/*/raw_notes.csv')


def source_label(source):
    if isinstance(source, list):
        return '、'.join(str(path) for path in source)
    return str(source)


def read_rows(source):
    paths = source if isinstance(source, list) else [source]
    rows = []
    for path in paths:
        with path.open('r', encoding='utf-8-sig', newline='') as file:
            for row in csv.DictReader(file):
                row['_source_file'] = str(path)
                row['_date_dir'] = path.parent.name
                rows.append(normalize_row(row))
    return dedupe_rows(rows)


def dedupe_rows(rows):
    deduped = {}
    keyword_map = defaultdict(list)
    for row in rows:
        key = row.get('note_id') or normalize_url_key(row.get('url')) or f"{row.get('date')}::{row.get('display_title')}::{row.get('author')}"
        keyword = row.get('keyword') or ''
        if keyword and keyword not in keyword_map[key]:
            keyword_map[key].append(keyword)
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = row
            continue
        if row_quality_score(row) > row_quality_score(existing):
            deduped[key] = row
    result = []
    for key, row in deduped.items():
        keywords = keyword_map.get(key) or [row.get('keyword', '')]
        merged = {**row, 'keyword': ' / '.join(k for k in keywords if k), 'matched_keywords': keywords, 'duplicate_count': len(keywords)}
        result.append(merged)
    return sorted(result, key=lambda row: (row.get('date', ''), int(row.get('rank') or 999999)), reverse=True)


def normalize_url_key(url):
    if not url:
        return ''
    return re.sub(r'[?&]xsec_token=[^&]+', '', url).split('&xsec_source=')[0]


def row_quality_score(row):
    score = 0
    title = str(row.get('display_title') or '')
    bad_titles = {'首页', '历史记录', '发现', '小红书'}
    if title in bad_titles:
        score -= 10
    if title and not title.startswith('Joybuy 相关内容') and title not in bad_titles:
        score += 5
    if row.get('display_summary'):
        score += min(len(str(row.get('display_summary'))), 200) / 100
    score += int(row.get('engagement_score') or 0) / 1000
    return score


def normalize_row(row):
    display_title = infer_display_title(row)
    display_summary = infer_display_summary(row, display_title)
    text = meaningful_text(row, display_title, display_summary)
    like = normalize_count(row.get('like_count'))
    comment = normalize_count(row.get('comment_count'))
    collect = normalize_count(row.get('collect_count'))
    score = int(row.get('engagement_score') or 0) or like + comment * 3 + collect * 2
    pain_category, pain_evidence = classify_pain(text)
    negative_signal = classify_negative_signal(text, pain_category)
    return {
        **row,
        'date': row.get('crawl_date') or row.get('_date_dir') or '',
        'display_title': display_title,
        'display_summary': display_summary,
        'like_count_norm': like,
        'comment_count_norm': comment,
        'collect_count_norm': collect,
        'engagement_score': score,
        'negative_signal': negative_signal,
        'pain_category': pain_category,
        'pain_evidence': pain_evidence,
        'summary': row.get('summary') or display_summary,
        'owner_action': '；'.join(ACTION_MAP.get(pain_category, ['持续观察用户反馈']))
    }


def infer_display_title(row):
    title = str(row.get('title') or '').strip()
    author = str(row.get('author') or '').strip()
    publish_time = str(row.get('publish_time') or '').strip()
    if title and title not in {'首页', '发现', '小红书'}:
        return title
    if publish_time and not looks_like_time_only(publish_time):
        return publish_time[:80]
    if author:
        return f'{author} 的 Joybuy 相关内容'
    note_id = str(row.get('note_id') or '').strip()
    return f'Joybuy 相关内容 {note_id[:8]}' if note_id else 'Joybuy 相关内容'


def infer_display_summary(row, display_title):
    content = str(row.get('content') or '').strip()
    raw_text = str(row.get('raw_text') or '').strip()
    publish_time = str(row.get('publish_time') or '').strip()
    author = str(row.get('author') or '').strip()
    if content and not is_homepage_shell_text(content):
        return re.sub(r'\s+', ' ', content)[:180]
    if raw_text and not is_homepage_shell_text(raw_text):
        return re.sub(r'\s+', ' ', raw_text)[:180]
    pieces = []
    if author:
        pieces.append(f'作者：{author}')
    if publish_time and publish_time != display_title:
        pieces.append(f'卡片信息：{publish_time}')
    if row.get('keyword'):
        pieces.append(f'关键词：{row.get("keyword")}')
    return '；'.join(pieces) or display_title


def looks_like_time_only(value):
    text = value.strip()
    return bool(re.fullmatch(r'(今天|昨天)?\s*\d{1,2}:\d{2}(\s*[^\s]+)?|\d{1,2}-\d{1,2}|\d{4}-\d{1,2}-\d{1,2}|\d+\s*(分钟前|小时前|天前)', text))


def is_homepage_shell_text(value):
    text = value or ''
    return text.startswith('首页\n') or '沪ICP备13030189号' in text or '营业执照' in text


def meaningful_text(row, display_title, display_summary):
    parts = [display_title, display_summary]
    content = str(row.get('content') or '')
    summary = str(row.get('summary') or '')
    if content and not is_homepage_shell_text(content):
        parts.append(content)
    if summary and not is_homepage_shell_text(summary):
        parts.append(summary)
    raw = str(row.get('raw_text') or '')
    if raw and not is_homepage_shell_text(raw):
        parts.append(raw)
    return '\n'.join(parts)


def classify_pain(text):
    lowered = text.lower()
    for category, keywords, _ in PAIN_RULES:
        hit = [word for word in keywords if word.lower() in lowered]
        if hit:
            return category, '、'.join(hit[:5])
    return '无明显痛点', ''


def classify_negative_signal(text, pain_category):
    hit = [word for word in NEGATIVE_SIGNAL_WORDS if word in text]
    if hit:
        return '明确负向：' + '、'.join(hit[:5])
    if pain_category != '无明显痛点':
        return '疑似痛点线索'
    return '未识别负向'


def summarize(row):
    title = str(row.get('title') or '').strip()
    content = re.sub(r'\s+', ' ', str(row.get('content') or row.get('raw_text') or '')).strip()
    return (f'{title}：{content}' if title and content else title or content)[:180]


def counter_items(counter):
    return [{'name': key, 'value': value} for key, value in counter.most_common()]


def pct(value, total):
    return 0 if total == 0 else round(value / total * 100, 1)


def build_data(rows, source_path):
    total = len(rows)
    pain_rows = [row for row in rows if row['pain_category'] != '无明显痛点']
    negative_rows = [row for row in rows if row['negative_signal'] != '未识别负向']

    pain_counter = Counter(row['pain_category'] for row in pain_rows)
    negative_counter = Counter(row['negative_signal'].split('：', 1)[0] for row in negative_rows)
    keyword_counter = Counter(row.get('keyword') or '未知' for row in rows)

    opportunities = []
    for category, count in pain_counter.most_common():
        examples = [row for row in pain_rows if row['pain_category'] == category]
        score_sum = sum(int(row['engagement_score']) for row in examples)
        rule = next((item for item in PAIN_RULES if item[0] == category), None)
        opportunities.append({
            'category': category,
            'count': count,
            'share': pct(count, total),
            'score_sum': score_sum,
            'why_it_matters': rule[2] if rule else '需要结合明细进一步判断。',
            'actions': ACTION_MAP.get(category, ['持续观察用户反馈']),
            'examples': compact_rows(sorted(examples, key=lambda row: row['engagement_score'], reverse=True)[:3])
        })

    return {
        'generated_at': date.today().isoformat(),
        'source_file': source_label(source_path),
        'kpis': {
            'total_notes': total,
            'pain_notes': len(pain_rows),
            'pain_rate': pct(len(pain_rows), total),
            'negative_notes': len(negative_rows),
            'negative_rate': pct(len(negative_rows), total),
            'total_engagement': sum(int(row['engagement_score']) for row in rows),
            'homepage_shell_notes': sum(1 for row in rows if is_homepage_shell_text(str(row.get('raw_text') or ''))),
            'valid_detail_notes': sum(1 for row in rows if not is_homepage_shell_text(str(row.get('raw_text') or '')))
        },
        'distributions': {
            'pain': counter_items(pain_counter),
            'negative_signal': counter_items(negative_counter),
            'keyword': counter_items(keyword_counter)
        },
        'daily': build_daily_aggregation(rows),
        'pain_groups': build_pain_groups(rows, pain_rows),
        'top_pains': compact_rows(sorted(pain_rows, key=lambda row: row['engagement_score'], reverse=True)[:12]),
        'top_notes': compact_rows(sorted(rows, key=lambda row: row['engagement_score'], reverse=True)[:20]),
        'opportunities': opportunities,
        'rows': compact_rows(rows)
}


def build_daily_aggregation(rows):
    daily = []
    for day, day_rows in sorted(group_by(rows, 'date').items()):
        total = len(day_rows)
        pain_rows = [row for row in day_rows if row['pain_category'] != '无明显痛点']
        negative_rows = [row for row in day_rows if row['negative_signal'] != '未识别负向']
        pain_counter = Counter(row['pain_category'] for row in pain_rows)
        daily.append({
            'date': day or '未知日期',
            'total_notes': total,
            'pain_notes': len(pain_rows),
            'pain_rate': pct(len(pain_rows), total),
            'negative_notes': len(negative_rows),
            'negative_rate': pct(len(negative_rows), total),
            'total_engagement': sum(int(row['engagement_score']) for row in day_rows),
            'top_pain': pain_counter.most_common(1)[0][0] if pain_counter else '无明显痛点',
        })
    return daily


def build_pain_groups(rows, pain_rows):
    total = len(rows)
    grouped = []
    for category, examples in group_by(pain_rows, 'pain_category').items():
        ordered = sorted(examples, key=lambda row: row['engagement_score'], reverse=True)
        rule = next((item for item in PAIN_RULES if item[0] == category), None)
        grouped.append({
            'category': category,
            'count': len(examples),
            'share': pct(len(examples), total),
            'score_sum': sum(int(row['engagement_score']) for row in examples),
            'why_it_matters': rule[2] if rule else '需要结合明细进一步判断。',
            'actions': ACTION_MAP.get(category, ['持续观察用户反馈']),
            'examples': compact_rows(ordered[:5])
        })
    return sorted(grouped, key=lambda item: (item['count'], item['score_sum']), reverse=True)


def group_by(rows, key):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get(key, '')].append(row)
    return grouped


def compact_rows(rows):
    fields = ['date', 'rank', 'note_id', 'title', 'display_title', 'author', 'keyword', 'matched_keywords', 'duplicate_count', 'url', 'publish_time', 'like_count', 'comment_count', 'collect_count', 'like_count_norm', 'comment_count_norm', 'collect_count_norm', 'engagement_score', 'negative_signal', 'pain_category', 'pain_evidence', 'summary', 'display_summary', 'owner_action']
    return [{field: row.get(field, '') for field in fields} for row in rows]


def render_dashboard(data):
    payload = json.dumps(data, ensure_ascii=False).replace('</', '<\\/')
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Joybuy 小红书痛点与负向反馈看板</title>
<style>
:root {{ --red:#1d4ed8; --green:#0ea5e9; --blue:#2563eb; --amber:#38bdf8; --bg:#eff6ff; --card:#fff; --text:#0f172a; --muted:#64748b; --line:#dbeafe; --deep:#1e3a8a; --soft:#e0f2fe; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",Arial,sans-serif; background:var(--bg); color:var(--text); }}
header {{ padding:28px 32px; background:linear-gradient(135deg,#0f172a,#1d4ed8,#0284c7); color:white; }}
header h1 {{ margin:0 0 8px; font-size:28px; }}
header p {{ margin:4px 0; opacity:.9; }}
main {{ padding:24px 32px 48px; max-width:1480px; margin:0 auto; }}
.grid {{ display:grid; gap:16px; }}
.kpis {{ grid-template-columns:repeat(5,minmax(150px,1fr)); }}
.two {{ grid-template-columns:1fr 1fr; }}
.three {{ grid-template-columns:repeat(3,1fr); }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:16px; padding:18px; box-shadow:0 8px 24px rgba(30,64,175,.06); }}
.kpi .label {{ color:var(--muted); font-size:13px; }}
.kpi .value {{ font-size:30px; font-weight:760; margin-top:6px; }}
.kpi .hint {{ color:var(--muted); font-size:12px; margin-top:6px; }}
h2 {{ margin:28px 0 12px; font-size:20px; color:var(--deep); }}
h3 {{ margin:0 0 12px; font-size:16px; }}
.bar {{ display:flex; align-items:center; gap:10px; margin:10px 0; }}
.bar-name {{ width:110px; font-size:13px; color:#344054; }}
.bar-track {{ flex:1; height:12px; background:#f2f4f7; border-radius:999px; overflow:hidden; }}
.bar-fill {{ height:100%; background:var(--red); border-radius:999px; }}
.bar-value {{ width:44px; text-align:right; color:var(--muted); font-size:12px; }}
.badge {{ display:inline-flex; align-items:center; padding:3px 8px; border-radius:999px; background:#f2f4f7; color:#344054; font-size:12px; margin:2px; }}
.badge.red {{ background:#dbeafe; color:#1e40af; }}
.badge.green {{ background:#e0f2fe; color:#0369a1; }}
.badge.blue {{ background:#eff6ff; color:#1d4ed8; }}
.badge.amber {{ background:#cffafe; color:#155e75; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th,td {{ padding:10px 9px; border-bottom:1px solid var(--line); vertical-align:top; text-align:left; }}
th {{ color:#1e3a8a; background:#eff6ff; position:sticky; top:0; }}
a {{ color:#2563eb; text-decoration:none; }}
.summary {{ line-height:1.7; color:#344054; }}
.actions {{ margin:8px 0 0; padding-left:18px; color:#344054; }}
.filter {{ display:flex; gap:10px; flex-wrap:wrap; margin:12px 0 16px; }}
select,input {{ border:1px solid #d0d5dd; border-radius:10px; padding:9px 10px; background:white; min-width:160px; }}
.small {{ color:var(--muted); font-size:12px; }}
.pain-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }}
.pain-card {{ border-left:5px solid #2563eb; background:linear-gradient(180deg,#fff,#f8fbff); }}
.pain-card h3 {{ display:flex; align-items:center; justify-content:space-between; gap:8px; }}
.example-list {{ margin:10px 0 0; padding:0; list-style:none; }}
.example-list li {{ padding:8px 0; border-top:1px dashed #bfdbfe; }}
.example-list a {{ font-weight:600; }}
@media (max-width:1000px) {{ .kpis,.two,.three,.pain-grid {{ grid-template-columns:1fr; }} main {{ padding:16px; }} }}
</style>
</head>
<body>
<header>
  <h1>Joybuy 小红书痛点与负向反馈看板</h1>
  <p>聚焦用户痛点和负向反馈，按产品体验、商品质量、物流履约、售后服务、价格促销、品牌信任归类沉淀改进线索。</p>
  <p class="small">生成日期：<span id="generatedAt"></span> ｜ 数据源：<span id="sourceFile"></span></p>
</header>
<main>
  <section class="grid kpis" id="kpis"></section>
  <section class="card" id="dataQuality"></section>

  <h2>按日期聚合</h2>
  <section class="card"><div id="dailyAggregation"></div></section>

  <h2>每日具体内容 Top</h2>
  <section class="card"><div id="dailyTopNotes"></div></section>

  <h2>核心结论</h2>
  <section class="grid two">
    <div class="card"><h3>痛点分类分布</h3><div id="painBars"></div></div>
    <div class="card"><h3>负向线索类型</h3><div id="negativeBars"></div></div>
  </section>

  <h2>体验提升机会</h2>
  <section class="grid three" id="opportunities"></section>

  <h2>痛点分类洞察</h2>
  <section class="pain-grid" id="painGroups"></section>

  <h2>头部痛点内容</h2>
  <section class="card"><div id="topPains"></div></section>

  <h2>内容明细</h2>
  <section class="card">
    <div class="filter">
      <input id="searchInput" placeholder="搜索标题/摘要/作者">
      <select id="painFilter"><option value="">全部痛点</option></select>
    </div>
    <div id="detailTable"></div>
  </section>
</main>
<script id="dashboard-data" type="application/json">{payload}</script>
<script>
const data = JSON.parse(document.getElementById('dashboard-data').textContent);
const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}}[c]));
const pct = value => `${{value}}%`;

document.getElementById('generatedAt').textContent = data.generated_at;
document.getElementById('sourceFile').textContent = data.source_file;

function renderKpis() {{
  const k = data.kpis;
  const items = [
    ['采集内容', k.total_notes, '条笔记/内容'],
    ['痛点占比', pct(k.pain_rate), `${{k.pain_notes}} 条痛点内容`],
    ['负向线索', pct(k.negative_rate), `${{k.negative_notes}} 条负向/痛点线索`],
    ['总互动分', k.total_engagement, '点赞+评论*3+收藏*2']
  ];
  document.getElementById('kpis').innerHTML = items.map(([label,value,hint]) => `<div class="card kpi"><div class="label">${{esc(label)}}</div><div class="value">${{esc(value)}}</div><div class="hint">${{esc(hint)}}</div></div>`).join('');
  document.getElementById('dataQuality').innerHTML = `<strong>数据质量提示</strong>：当前数据共 ${{k.total_notes}} 条，其中详情正文有效 ${{k.valid_detail_notes}} 条，详情页仍为小红书首页壳层 ${{k.homepage_shell_notes}} 条。当前看板按“卡片级数据模式”展示，优先使用搜索卡片上的作者、标题/摘要、发布时间和互动数据；痛点分类是基于卡片文本的初步归因，适合做线索筛查。`;
}}

function renderBars(id, items, color) {{
  const max = Math.max(1, ...items.map(x => x.value));
  document.getElementById(id).innerHTML = items.length ? items.map(item => `
    <div class="bar"><div class="bar-name">${{esc(item.name)}}</div><div class="bar-track"><div class="bar-fill" style="width:${{Math.round(item.value/max*100)}}%;background:${{color}}"></div></div><div class="bar-value">${{item.value}}</div></div>
  `).join('') : '<p class="small">暂无数据</p>';
}}

function renderDailyAggregation() {{
  const rows = data.daily || [];
  if (!rows.length) {{
    document.getElementById('dailyAggregation').innerHTML = '<p class="small">暂无日期聚合数据</p>';
    return;
  }}
  document.getElementById('dailyAggregation').innerHTML = `<table><thead><tr><th>日期</th><th>内容数</th><th>痛点数/占比</th><th>负向线索数/占比</th><th>总互动分</th><th>首要痛点</th></tr></thead><tbody>${{rows.map(row => `
    <tr>
      <td><strong>${{esc(row.date)}}</strong></td>
      <td>${{esc(row.total_notes)}}</td>
      <td>${{esc(row.pain_notes)}} / ${{esc(row.pain_rate)}}%</td>
      <td>${{esc(row.negative_notes)}} / ${{esc(row.negative_rate)}}%</td>
      <td>${{esc(row.total_engagement)}}</td>
      <td>${{badge(row.top_pain, 'red')}}</td>
    </tr>`).join('')}}</tbody></table>`;
}}

function renderDailyTopNotes() {{
  const byDate = new Map();
  for (const row of data.rows) {{
    if (!byDate.has(row.date)) byDate.set(row.date, []);
    byDate.get(row.date).push(row);
  }}
  const sections = [...byDate.entries()].sort((a,b) => String(b[0]).localeCompare(String(a[0]))).map(([day, rows]) => {{
    const top = rows.sort((a,b) => Number(b.engagement_score || 0) - Number(a.engagement_score || 0)).slice(0, 8);
    return `<h3>${{esc(day)}} Top 内容</h3>${{table(top)}}`;
  }});
  document.getElementById('dailyTopNotes').innerHTML = sections.join('') || '<p class="small">暂无每日明细</p>';
}}

function badge(text, type='') {{ return `<span class="badge ${{type}}">${{esc(text)}}</span>`; }}

function renderOpportunities() {{
  document.getElementById('opportunities').innerHTML = data.opportunities.length ? data.opportunities.map(item => `
    <div class="card">
      <h3>${{esc(item.category)}} ${{badge(item.count + '条', 'red')}} ${{badge(item.share + '%', 'amber')}}</h3>
      <p class="summary">${{esc(item.why_it_matters)}}</p>
      <ul class="actions">${{item.actions.map(action => `<li>${{esc(action)}}</li>`).join('')}}</ul>
      <p class="small">代表内容：${{item.examples.map(row => esc(row.display_title || row.title || row.summary || '未命名')).join(' / ')}}</p>
    </div>
  `).join('') : '<div class="card">暂无明显痛点机会。</div>';
}}

function renderPainGroups() {{
  document.getElementById('painGroups').innerHTML = data.pain_groups.length ? data.pain_groups.map(item => `
    <div class="card pain-card">
      <h3><span>${{esc(item.category)}}</span><span>${{badge(item.count + '条', 'red')}} ${{badge(item.share + '%', 'blue')}}</span></h3>
      <p class="summary">${{esc(item.why_it_matters)}}</p>
      <div>${{item.actions.map(action => badge(action, 'amber')).join('')}}</div>
      <ul class="example-list">
        ${{item.examples.map(row => `<li><a href="${{esc(row.url || '#')}}" target="_blank">${{esc(row.display_title || row.title || '未命名内容')}}</a><br><span class="small">${{esc(row.display_summary || row.summary || '')}}</span></li>`).join('')}}
      </ul>
    </div>
  `).join('') : '<div class="card pain-card">暂无明显痛点分类。</div>';
}}

function renderRows(id, rows) {{
  document.getElementById(id).innerHTML = table(rows, false);
}}

function table(rows, showFilters=true) {{
  if (!rows.length) return '<p class="small">暂无数据</p>';
  return `<table><thead><tr><th>日期/排名</th><th>标题</th><th>负向线索</th><th>痛点分类</th><th>互动明细</th><th>摘要/动作</th><th>链接</th></tr></thead><tbody>${{rows.map(row => `
    <tr>
      <td>${{esc(row.date || '')}}<br><span class="small">#${{esc(row.rank || '')}}</span></td>
      <td><strong>${{esc(row.display_title || row.title || '未命名')}}</strong><br><span class="small">${{esc(row.author || '')}}｜${{esc(row.keyword || '')}}</span></td>
      <td>${{badge(row.negative_signal || '未识别负向', row.negative_signal === '未识别负向' ? 'blue' : 'red')}}</td>
      <td>${{badge(row.pain_category || '无明显痛点', row.pain_category === '无明显痛点' ? 'blue' : 'red')}}<br><span class="small">${{esc(row.pain_evidence || '')}}</span></td>
      <td><strong>${{esc(row.engagement_score || 0)}}</strong><br><span class="small">赞 ${{esc(row.like_count || row.like_count_norm || 0)}}｜评 ${{esc(row.comment_count || row.comment_count_norm || 0)}}｜藏 ${{esc(row.collect_count || row.collect_count_norm || 0)}}</span></td>
      <td>${{esc(row.display_summary || row.summary || '')}}<br><span class="small">建议：${{esc(row.owner_action || '')}}</span></td>
      <td>${{row.url ? `<a href="${{esc(row.url)}}" target="_blank">打开</a>` : ''}}</td>
    </tr>`).join('')}}</tbody></table>`;
}}

function setupFilters() {{
  const dateOptions = [...new Set(data.rows.map(row => row.date).filter(Boolean))].sort().reverse();
  const painOptions = [...new Set(data.rows.map(row => row.pain_category).filter(Boolean))];
    const dateSelect = document.createElement('select');
  dateSelect.id = 'dateFilter';
  dateSelect.innerHTML = '<option value="">全部日期</option>' + dateOptions.map(x => `<option value="${{esc(x)}}">${{esc(x)}}</option>`).join('');
  document.querySelector('.filter').prepend(dateSelect);
  document.getElementById('painFilter').innerHTML += painOptions.map(x => `<option value="${{esc(x)}}">${{esc(x)}}</option>`).join('');
  for (const id of ['dateFilter', 'searchInput', 'painFilter']) document.getElementById(id).addEventListener('input', renderDetailTable);
}}

function renderDetailTable() {{
  const q = document.getElementById('searchInput').value.trim().toLowerCase();
  const date = document.getElementById('dateFilter').value;
  const pain = document.getElementById('painFilter').value;
  const rows = data.rows.filter(row => {{
    const text = `${{row.display_title}} ${{row.title}} ${{row.display_summary}} ${{row.summary}} ${{row.author}}`.toLowerCase();
    return (!date || row.date === date) && (!q || text.includes(q)) && (!pain || row.pain_category === pain);
  }}).slice(0, 200);
  document.getElementById('detailTable').innerHTML = table(rows);
}}

renderKpis();
renderDailyAggregation();
renderDailyTopNotes();
renderBars('negativeBars', data.distributions.negative_signal, 'var(--green)');
renderBars('painBars', data.distributions.pain, 'var(--red)');
renderOpportunities();
renderPainGroups();
renderRows('topPains', data.top_pains);
setupFilters();
renderDetailTable();
</script>
</body>
</html>'''


def main():
    source = find_latest_input()
    rows = read_rows(source)
    data = build_data(rows, source)
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    data_path = DASHBOARD_DIR / 'dashboard_data.json'
    html_path = DASHBOARD_DIR / 'index.html'
    data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    html_path.write_text(render_dashboard(data), encoding='utf-8')
    print(f'完成：{data_path}')
    print(f'完成：{html_path}')


if __name__ == '__main__':
    main()
