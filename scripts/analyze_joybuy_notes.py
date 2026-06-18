#!/usr/bin/env python3
import csv
import html
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path.cwd()
OUTPUT_ROOT = ROOT / 'output'
TODAY = date.today().isoformat()

RAW_COLUMNS = [
    'crawl_date', 'keyword', 'rank', 'note_id', 'url', 'title', 'author',
    'publish_time', 'like_count', 'comment_count', 'collect_count', 'note_type',
    'content', 'images_count', 'raw_text'
]
ANALYZED_COLUMNS = RAW_COLUMNS + [
    'engagement_score', 'primary_category', 'secondary_category', 'sentiment',
    'risk_type', 'user_need', 'summary'
]

CATEGORY_RULES = [
    ('购物体验', '物流/清关/售后', ['物流', '配送', '快递', '清关', '保税', '下单', '订单', '退货', '退款', '客服', '售后', '到货']),
    ('价格促销', '优惠/折扣/比价', ['优惠', '折扣', '便宜', '补贴', '券', '大促', '618', '双11', '黑五', '价格', '比价', '省钱']),
    ('商品品类', '商品/品类讨论', ['奶粉', '面霜', '护肤', '美妆', '保健', '维生素', '苹果', '手机', '数码', '食品', '生鲜', '香水', '包', '鞋']),
    ('真假信任', '正品/避雷/鉴别', ['真假', '假货', '正品', '鉴别', '授权', '避雷', '踩雷', '翻车', '靠谱吗', '可靠']),
    ('海外业务', '海外/本地履约', ['英国', '欧洲', '海外', '伦敦', 'Amazon', 'Temu', 'delivery', 'grocery', 'JD International', '国际']),
    ('品牌资讯', '平台/业务动态', ['Joybuy', 'joybuy', '京东', 'JD', '上线', '发布', '平台', '业务', '招聘'])
]

SENTIMENT_RULES = [
    ('负向', ['避雷', '踩雷', '投诉', '差评', '垃圾', '假货', '被骗', '失败', '慢', '延迟', '不退', '拒绝', '失望', '翻车', '坑']),
    ('正向', ['推荐', '好价', '划算', '便宜', '快', '靠谱', '正品', '满意', '复购', '不错', '好用', '省钱']),
]

RISK_RULES = [
    ('品控风险', ['假货', '真假', '破损', '临期', '质量', '鉴别', '正品']),
    ('履约风险', ['物流', '配送', '清关', '延迟', '丢件', '慢', '没到', '快递']),
    ('售后风险', ['售后', '客服', '退款', '退货', '不退', '拒绝', '投诉']),
    ('价格风险', ['价格', '优惠', '券', '补贴', '虚假', '涨价', '比价']),
    ('舆情风险', ['避雷', '踩雷', '翻车', '投诉', '差评', '曝光'])
]

NEED_RULES = [
    ('想确认是否靠谱/正品', ['真假', '假货', '正品', '靠谱吗', '可靠', '鉴别']),
    ('想获得低价/优惠', ['优惠', '折扣', '便宜', '券', '补贴', '好价', '省钱']),
    ('关注物流和到货速度', ['物流', '配送', '清关', '到货', '快递', '时效']),
    ('需要售后解决方案', ['售后', '客服', '退款', '退货', '投诉']),
    ('寻找商品购买建议', ['推荐', '好用', '测评', '清单', '买什么', '种草'])
]


def normalize_count(value):
    text = str(value or '').strip().replace(',', '')
    if not text:
        return 0
    match = re.search(r'(\d+(?:\.\d+)?)(万|k|K)?', text)
    if not match:
        return 0
    number = float(match.group(1))
    unit = match.group(2)
    if unit == '万':
        number *= 10000
    elif unit in ('k', 'K'):
        number *= 1000
    return int(number)


def row_text(row):
    return '\n'.join(str(row.get(key, '')) for key in ['title', 'content', 'raw_text', 'keyword'])


def classify(row):
    text = row_text(row)
    primary = '其他'
    secondary = '未归类'
    for candidate_primary, candidate_secondary, keywords in CATEGORY_RULES:
        if any(word.lower() in text.lower() for word in keywords):
            primary = candidate_primary
            secondary = candidate_secondary
            break

    sentiment = '中性'
    for candidate, keywords in SENTIMENT_RULES:
        if any(word.lower() in text.lower() for word in keywords):
            sentiment = candidate
            break

    risk = '无明显风险'
    for candidate, keywords in RISK_RULES:
        if any(word.lower() in text.lower() for word in keywords):
            risk = candidate
            break

    user_need = '信息了解/一般关注'
    for candidate, keywords in NEED_RULES:
        if any(word.lower() in text.lower() for word in keywords):
            user_need = candidate
            break

    return primary, secondary, sentiment, risk, user_need


def summarize(row):
    title = str(row.get('title') or '').strip()
    content = re.sub(r'\s+', ' ', str(row.get('content') or row.get('raw_text') or '')).strip()
    if title and content and title not in content[:80]:
        text = f'{title}：{content}'
    else:
        text = title or content
    return text[:180]


def find_input_path():
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    candidates = sorted(OUTPUT_ROOT.glob('*/raw_notes.csv'), reverse=True)
    if candidates:
        return candidates[0]
    today_path = OUTPUT_ROOT / TODAY / 'raw_notes.csv'
    return today_path


def read_rows(path):
    if not path.exists():
        raise FileNotFoundError(f'找不到输入文件：{path}')
    with path.open('r', encoding='utf-8-sig', newline='') as file:
        return list(csv.DictReader(file))


def analyze_rows(rows):
    analyzed = []
    for row in rows:
        normalized = {column: row.get(column, '') for column in RAW_COLUMNS}
        like = normalize_count(normalized['like_count'])
        comment = normalize_count(normalized['comment_count'])
        collect = normalize_count(normalized['collect_count'])
        score = like + comment * 3 + collect * 2
        primary, secondary, sentiment, risk, user_need = classify(normalized)
        normalized.update({
            'engagement_score': score,
            'primary_category': primary,
            'secondary_category': secondary,
            'sentiment': sentiment,
            'risk_type': risk,
            'user_need': user_need,
            'summary': summarize(normalized)
        })
        analyzed.append(normalized)
    analyzed.sort(key=lambda item: int(item.get('engagement_score') or 0), reverse=True)
    return analyzed


def write_csv(path, rows, columns):
    with path.open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def pct(count, total):
    return '0.0%' if total == 0 else f'{count / total * 100:.1f}%'


def md_table(headers, rows):
    lines = ['|' + '|'.join(headers) + '|', '|' + '|'.join(['---'] * len(headers)) + '|']
    for row in rows:
        lines.append('|' + '|'.join(str(cell).replace('\n', '<br>') for cell in row) + '|')
    return '\n'.join(lines)


def build_markdown(rows, output_dir):
    total = len(rows)
    categories = Counter(row['primary_category'] for row in rows)
    sentiments = Counter(row['sentiment'] for row in rows)
    risks = Counter(row['risk_type'] for row in rows if row['risk_type'] != '无明显风险')
    keywords = Counter(row['keyword'] for row in rows)
    top_rows = rows[:10]
    negative_rows = [row for row in rows if row['sentiment'] == '负向' or row['risk_type'] != '无明显风险'][:10]

    parts = [
        '# 小红书 Joybuy 每日内容分析',
        '',
        f'生成日期：{date.today().isoformat()}',
        f'数据目录：`{output_dir}`',
        '',
        '## 今日概览',
        '',
        f'- 采集笔记数：{total}',
        f'- 覆盖关键词：{", ".join(keywords.keys()) if keywords else "无"}',
        f'- 正向/中性/负向：{sentiments.get("正向", 0)} / {sentiments.get("中性", 0)} / {sentiments.get("负向", 0)}',
        '',
        '## 头部内容 Top 10',
        '',
        md_table(['排名', '分数', '标题', '作者', '分类', '情绪', '风险', '链接'], [
            [index + 1, row['engagement_score'], row['title'], row['author'], row['primary_category'], row['sentiment'], row['risk_type'], row['url']]
            for index, row in enumerate(top_rows)
        ]) if top_rows else '暂无有效笔记。',
        '',
        '## 主题分布',
        '',
        md_table(['分类', '数量', '占比'], [[key, value, pct(value, total)] for key, value in categories.most_common()]) if total else '暂无数据。',
        '',
        '## 情绪分布',
        '',
        md_table(['情绪', '数量', '占比'], [[key, value, pct(value, total)] for key, value in sentiments.most_common()]) if total else '暂无数据。',
        '',
        '## 风险内容',
        '',
        md_table(['标题', '风险', '情绪', '用户诉求', '摘要', '链接'], [
            [row['title'], row['risk_type'], row['sentiment'], row['user_need'], row['summary'], row['url']]
            for row in negative_rows
        ]) if negative_rows else '未识别到明显风险内容。',
        '',
        '## 初步总结',
        '',
        build_summary(total, categories, sentiments, risks),
        ''
    ]
    return '\n'.join(parts)


def build_summary(total, categories, sentiments, risks):
    if total == 0:
        return '本次没有采集到有效笔记，建议确认小红书登录状态和关键词结果页是否正常展示。'
    top_category = categories.most_common(1)[0][0] if categories else '未归类'
    top_sentiment = sentiments.most_common(1)[0][0] if sentiments else '中性'
    risk_text = '、'.join(key for key, _ in risks.most_common(3)) if risks else '暂无明显集中风险'
    return f'本次 Joybuy 相关内容以“{top_category}”为主，整体情绪偏“{top_sentiment}”。主要风险集中在：{risk_text}。建议重点跟进高互动内容评论区，并针对物流、正品、售后、优惠等高频诉求准备回应素材。'


def markdown_to_html(markdown):
    lines = markdown.splitlines()
    html_lines = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>Joybuy 小红书日报</title><style>body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",Arial,sans-serif;margin:32px;line-height:1.6;color:#222}table{border-collapse:collapse;width:100%;margin:12px 0}th,td{border:1px solid #ddd;padding:8px;vertical-align:top}th{background:#f7d7d7}code{background:#f3f4f6;padding:2px 4px;border-radius:4px}h1,h2{color:#a61b1b}</style></head><body>']
    in_table = False
    for line in lines:
        if line.startswith('# '):
            html_lines.append(f'<h1>{html.escape(line[2:])}</h1>')
        elif line.startswith('## '):
            if in_table:
                html_lines.append('</tbody></table>')
                in_table = False
            html_lines.append(f'<h2>{html.escape(line[3:])}</h2>')
        elif line.startswith('|') and line.endswith('|'):
            cells = [cell.strip() for cell in line.strip('|').split('|')]
            if all(cell == '---' for cell in cells):
                continue
            if not in_table:
                html_lines.append('<table><tbody>')
                in_table = True
                tag = 'th'
            else:
                tag = 'td'
            html_lines.append('<tr>' + ''.join(f'<{tag}>{html.escape(cell)}</{tag}>' for cell in cells) + '</tr>')
        else:
            if in_table:
                html_lines.append('</tbody></table>')
                in_table = False
            if line.startswith('- '):
                html_lines.append(f'<p>• {html.escape(line[2:])}</p>')
            elif line.strip():
                html_lines.append(f'<p>{html.escape(line)}</p>')
    if in_table:
        html_lines.append('</tbody></table>')
    html_lines.append('</body></html>')
    return '\n'.join(html_lines)


def main():
    input_path = find_input_path()
    rows = read_rows(input_path)
    analyzed = analyze_rows(rows)
    output_dir = input_path.parent
    analyzed_path = output_dir / 'analyzed_notes.csv'
    md_path = output_dir / 'daily_report.md'
    html_path = output_dir / 'daily_report.html'
    json_path = output_dir / 'analyzed_notes.json'

    write_csv(analyzed_path, analyzed, ANALYZED_COLUMNS)
    json_path.write_text(json.dumps(analyzed, ensure_ascii=False, indent=2), encoding='utf-8')
    markdown = build_markdown(analyzed, output_dir)
    md_path.write_text(markdown, encoding='utf-8')
    html_path.write_text(markdown_to_html(markdown), encoding='utf-8')

    print(f'完成：{analyzed_path}')
    print(f'完成：{md_path}')
    print(f'完成：{html_path}')


if __name__ == '__main__':
    main()
