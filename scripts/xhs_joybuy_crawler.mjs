import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const CONFIG_PATH = process.argv[2] || 'config/joybuy_crawler.json';
const TODAY = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit'
}).format(new Date());
const XHS_HOME = 'https://www.xiaohongshu.com/';

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function randomDelay(config) {
  const min = Number(config.min_delay_seconds || 3) * 1000;
  const max = Number(config.max_delay_seconds || 8) * 1000;
  return Math.floor(min + Math.random() * Math.max(0, max - min));
}

function csvEscape(value) {
  const text = value == null ? '' : String(value);
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

async function writeCsv(filePath, rows) {
  const columns = [
    'crawl_date',
    'keyword',
    'rank',
    'note_id',
    'url',
    'title',
    'author',
    'publish_time',
    'like_count',
    'comment_count',
    'collect_count',
    'note_type',
    'content',
    'images_count',
    'raw_text'
  ];
  const lines = [columns.join(',')];
  for (const row of rows) {
    lines.push(columns.map((column) => csvEscape(row[column])).join(','));
  }
  await fs.writeFile(filePath, `${lines.join('\n')}\n`, 'utf8');
}

async function readConfig() {
  const raw = await fs.readFile(CONFIG_PATH, 'utf8');
  return JSON.parse(raw);
}

function extractNoteId(url) {
  if (!url) return '';
  const match = url.match(/(?:explore|discovery\/item|search_result)\/([0-9a-fA-F]{16,32})/);
  return match ? match[1] : '';
}

function normalizeXhsNoteUrl(url) {
  const noteId = extractNoteId(url);
  if (!noteId) return '';
  try {
    const parsed = new URL(url, XHS_HOME);
    if (parsed.pathname.startsWith('/search_result/')) {
      parsed.pathname = `/explore/${noteId}`;
    }
    if (parsed.searchParams.has('xsec_token') && !parsed.searchParams.get('xsec_source')) {
      parsed.searchParams.set('xsec_source', 'pc_feed');
    }
    return parsed.toString();
  } catch {
    return url;
  }
}

function hasXsecToken(url) {
  return /[?&]xsec_token=/.test(url || '');
}

function toAbsoluteUrl(candidate) {
  if (!candidate) return '';
  try {
    return candidate.startsWith('http') ? candidate : new URL(candidate, XHS_HOME).toString();
  } catch {
    return '';
  }
}

function detectBlockedText(text) {
  return /验证码|安全验证|访问异常|操作频繁|登录后查看|请先登录|滑块|人机验证/.test(text || '');
}

async function ensureLoggedIn(page, config) {
  await page.goto(XHS_HOME, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(3000);
  const bodyText = await page.locator('body').innerText({ timeout: 10000 }).catch(() => '');
  const loginLikelyNeeded = /登录|手机号|验证码/.test(bodyText) && !/退出|消息|通知|创作中心/.test(bodyText);
  if (config.always_wait_for_login !== false || loginLikelyNeeded) {
    console.log('\n浏览器已打开：请在浏览器中确认小红书已登录。');
    console.log('如果未登录，请先手动登录；登录完成后回到终端按 Enter 开始采集。');
    console.log('脚本不会读取或保存你的账号、密码、验证码。');
    await waitForEnter();
  }
}

function waitForEnter() {
  return new Promise((resolve) => {
    process.stdin.resume();
    process.stdin.once('data', () => {
      process.stdin.pause();
      resolve();
    });
  });
}

function attachTokenSniffer(page) {
  const tokenMap = new Map();
  function ingest(node) {
    if (!node || typeof node !== 'object') return;
    if (Array.isArray(node)) {
      for (const child of node) ingest(child);
      return;
    }
    const id = node.id || node.note_id || node.noteId || (node.note && (node.note.id || node.note.note_id));
    const token = node.xsec_token || node.xsecToken || (node.note && (node.note.xsec_token || node.note.xsecToken));
    if (typeof id === 'string' && /^[0-9a-fA-F]{16,32}$/.test(id) && typeof token === 'string' && token) {
      if (!tokenMap.has(id)) tokenMap.set(id, token);
    }
    for (const key of Object.keys(node)) {
      const value = node[key];
      if (value && typeof value === 'object') ingest(value);
    }
  }
  const handler = async (response) => {
    try {
      const url = response.url();
      if (!/xiaohongshu\.com/.test(url)) return;
      if (!/\/api\/sns\/web\/v\d+\/search|\/api\/sns\/web\/.*\/feed|\/api\/sns\/web\/.*\/notes/.test(url)) return;
      const ct = (response.headers()['content-type'] || '').toLowerCase();
      if (!ct.includes('json')) return;
      const json = await response.json().catch(() => null);
      if (json) ingest(json);
    } catch {}
  };
  page.on('response', handler);
  return {
    tokenMap,
    detach() { page.off('response', handler); }
  };
}

async function collectCards(page, keyword, config, tokenMap) {
  const maxNotes = Number(config.max_notes_per_keyword || 20);
  const cards = [];
  const seen = new Set();

  for (let round = 0; round < Number(config.scroll_rounds || 6); round += 1) {
    const found = await page.evaluate(() => {
      function collectCandidateUrls(anchor) {
        const values = [];
        const nodes = [anchor, anchor.closest('section'), anchor.closest('article'), anchor.closest('div')].filter(Boolean);
        for (const node of nodes) {
          for (const attr of Array.from(node.attributes || [])) {
            if (/explore\//.test(attr.value) || /discovery\/item/.test(attr.value) || /xsec_token/.test(attr.value)) {
              values.push(attr.value);
            }
          }
          const dataset = node.dataset || {};
          for (const key of Object.keys(dataset)) {
            const value = dataset[key];
            if (/explore\//.test(value) || /discovery\/item/.test(value) || /xsec_token/.test(value)) {
              values.push(value);
            }
          }
        }
        values.unshift(anchor.href || '', anchor.getAttribute('href') || '');
        return Array.from(new Set(values.filter(Boolean)));
      }

      const anchors = Array.from(document.querySelectorAll('a.cover[href*="/search_result/"], a[href*="/search_result/"], a[href*="/explore/"], a[href*="/discovery/item/"]'));
      return anchors.map((anchor, anchorIndex) => {
        const container = anchor.closest('section, article, .note-item, .note-card, .cover, .footer, div[class*="note"], div[class*="card"]') || anchor;
        const text = (container.innerText || anchor.innerText || '').trim();
        const candidateUrls = collectCandidateUrls(anchor);
        const href = candidateUrls.find((value) => value.includes('xsec_token=')) || candidateUrls[0] || '';
        const imgCount = container.querySelectorAll('img').length;
        const cardIndex = Array.from(document.querySelectorAll('section, article, .note-item, .note-card, div[class*="note"], div[class*="card"]')).indexOf(container);
        return { href, candidateUrls, text, imgCount, anchorIndex, cardIndex };
      }).filter((item) => item.href);
    });

    for (const item of found) {
      const rawHref = toAbsoluteUrl(item.href);
      const rawUrl = item.candidateUrls
        .map((candidate) => toAbsoluteUrl(candidate))
        .find((candidate) => hasXsecToken(candidate) && extractNoteId(candidate)) || rawHref;
      const noteId = extractNoteId(rawUrl);
      const key = noteId || rawUrl;
      if (!noteId || seen.has(key)) continue;
      seen.add(key);
      const sniffedToken = tokenMap && tokenMap.get(noteId);
      const urlWithToken = sniffedToken && !hasXsecToken(rawUrl)
        ? `${XHS_HOME}explore/${noteId}?xsec_token=${encodeURIComponent(sniffedToken)}&xsec_source=pc_search`
        : rawUrl;
      const url = normalizeXhsNoteUrl(urlWithToken);
      const parsed = parseCardText(item.text);
      const tokenSource = sniffedToken ? 'xhr-sniff' : (hasXsecToken(rawUrl) ? 'dom' : 'none');
      const urlDebug = hasXsecToken(url) ? `[card_href:${tokenSource}] ${url}` : `[card_href_missing_xsec:${tokenSource}] ${url}`;
      cards.push({
        crawl_date: TODAY,
        keyword,
        rank: cards.length + 1,
        note_id: noteId,
        url,
        title: parsed.title || `笔记 ${noteId}`,
        author: parsed.author,
        publish_time: parsed.publish_time,
        like_count: parsed.like_count,
        comment_count: '',
        collect_count: '',
        note_type: /视频|播放/.test(item.text) ? '视频' : '未知',
        content: '',
        images_count: item.imgCount || '',
        raw_text: `${item.text || '[cover_without_text]'}\n\n${urlDebug}`,
        _anchorIndex: item.anchorIndex,
        _cardIndex: item.cardIndex
      });
      if (cards.length >= maxNotes) break;
    }

    if (cards.length >= maxNotes) break;
    await page.mouse.wheel(0, 1200);
    await sleep(randomDelay(config));
  }

  return cards;
}

function parseCardText(text) {
  const lines = String(text || '').split('\n').map((line) => line.trim()).filter(Boolean);
  const title = lines.find((line) => !/^赞|评论|收藏|\d+$/.test(line)) || lines[0] || '';
  const likeLine = lines.find((line) => /赞|like|喜欢|\d+(\.\d+)?万?$/.test(line));
  return {
    title,
    author: lines[1] && lines[1] !== title ? lines[1] : '',
    publish_time: lines.find((line) => /\d{4}-\d{1,2}-\d{1,2}|昨天|今天|小时前|分钟前|天前/.test(line)) || '',
    like_count: likeLine ? likeLine.replace(/[赞喜欢\s]/g, '') : ''
  };
}

async function enrichDetails(context, searchPage, rows, config) {
  const limit = Math.min(rows.length, Number(config.open_detail_top_n || 10));
  for (let index = 0; index < limit; index += 1) {
    const row = rows[index];
    if (!row.url) continue;
    const detailTarget = hasXsecToken(row.url)
      ? await openXsecDetailInNewPage(context, row)
      : await openDetailFromSearch(context, searchPage, row);
    const page = detailTarget?.page || await context.newPage();
    try {
      if (!detailTarget) {
        await page.goto(row.url, { waitUntil: 'domcontentloaded', timeout: 60000 });
      }
      await page.waitForTimeout(4000);
      const currentUrl = page.url();
      if (/404|notfound/i.test(currentUrl)) {
        row.raw_text = `${row.raw_text}\n\n[detail_404] ${currentUrl}\n[detail_404_reason] likely_missing_or_invalid_xsec_token`;
        continue;
      }
      const bodyText = await page.locator('body').innerText({ timeout: 15000 }).catch(() => '');
      if (isHomepageShell(bodyText, row.note_id, currentUrl)) {
        row.raw_text = `${row.raw_text}\n\n[detail_homepage_shell] ${currentUrl}\n${bodyText.slice(0, 1000)}`;
        continue;
      }
      if (detectBlockedText(bodyText)) {
        row.raw_text = `${row.raw_text}\n\n[detail_blocked_or_login_required]\n${bodyText.slice(0, 1000)}`;
        await page.close();
        break;
      }
      const detail = parseDetailText(bodyText);
      row.title = detail.title || row.title;
      row.author = detail.author || row.author;
      row.publish_time = detail.publish_time || row.publish_time;
      row.like_count = detail.like_count || row.like_count;
      row.comment_count = detail.comment_count || row.comment_count;
      row.collect_count = detail.collect_count || row.collect_count;
      row.content = detail.content || row.content;
      row.note_type = detail.note_type || row.note_type;
      row.raw_text = bodyText.slice(0, 5000);
    } catch (error) {
      row.raw_text = `${row.raw_text}\n\n[detail_error] ${error.message}`;
    } finally {
      if (detailTarget?.mode === 'same-page-modal') {
        await closeSamePageDetail(searchPage);
      } else if (page !== searchPage) {
        await page.close().catch(() => {});
      }
    }
    await sleep(randomDelay(config));
  }
}

async function openDetailFromSearch(context, searchPage, row) {
  const noteId = row.note_id;
  if (!noteId) return null;
  const selector = `a.cover[href*="${noteId}"], a[href*="/search_result/${noteId}"], a[href*="${noteId}"]`;
  const anchor = searchPage.locator(selector).first();
  if (!(await anchor.count().catch(() => 0))) return null;
  await anchor.scrollIntoViewIfNeeded().catch(() => {});
  const href = await anchor.evaluate((node) => {
    const values = [node.href || '', node.getAttribute('href') || ''];
    const parents = [node.closest('section'), node.closest('article'), node.closest('div')].filter(Boolean);
    for (const parent of parents) {
      for (const attr of Array.from(parent.attributes || [])) values.push(attr.value);
    }
    return values.find((value) => value && value.includes('xsec_token=')) || values.find(Boolean) || '';
  }).catch(() => '');
  if (href && extractNoteId(href)) {
    row.url = href.startsWith('http') ? href : new URL(href, XHS_HOME).toString();
    row.raw_text = `${row.raw_text}\n\n[detail_href] ${href}`;
  }

  const beforeUrl = searchPage.url();
  const beforeText = await searchPage.locator('body').innerText({ timeout: 5000 }).catch(() => '');
  await clickCardDomNode(searchPage, row, anchor);
  await searchPage.waitForTimeout(3500);
  const afterUrl = searchPage.url();
  const afterText = await searchPage.locator('body').innerText({ timeout: 10000 }).catch(() => '');
  row.raw_text = `${row.raw_text}\n\n[detail_click_url] before=${beforeUrl} after=${afterUrl}`;
  const samePageOpened = /\/explore\//.test(afterUrl) || /\/discovery\/item\//.test(afterUrl) || isLikelyDetailText(afterText, beforeText, noteId);
  if (samePageOpened && !isHomepageShell(afterText, noteId, afterUrl)) {
    row.url = afterUrl.includes(noteId) ? afterUrl : row.url;
    row.raw_text = `${row.raw_text}\n\n[detail_open_mode] same-page-modal-or-route`;
    return { page: searchPage, mode: 'same-page-modal' };
  }

  const pagePromise = context.waitForEvent('page', { timeout: 5000 }).catch(() => null);
  await anchor.evaluate((node) => window.open(node.href || node.getAttribute('href'), '_blank')).catch(async () => {
    await anchor.click({ button: 'left', modifiers: ['Meta'], timeout: 10000 }).catch(() => {});
  });
  const opened = await pagePromise;
  if (!opened) return null;
  await opened.waitForLoadState('domcontentloaded', { timeout: 30000 }).catch(() => {});
  return { page: opened, mode: 'new-page' };
}

async function openXsecDetailInNewPage(context, row) {
  const page = await context.newPage();
  await page.goto(row.url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(2500);
  row.raw_text = `${row.raw_text}\n\n[detail_open_mode] direct-xsec-url`;
  return { page, mode: 'new-page' };
}

async function clickCardDomNode(searchPage, row, anchor) {
  const clicked = await searchPage.evaluate(({ noteId }) => {
    const anchorNode = Array.from(document.querySelectorAll('a.cover[href*="/search_result/"], a[href*="/search_result/"], a[href*="/explore/"], a[href*="/discovery/item/"]'))
      .find((node) => (node.href || node.getAttribute('href') || '').includes(noteId));
    if (!anchorNode) return false;
    const candidates = [
      anchorNode.closest('section'),
      anchorNode.closest('article'),
      anchorNode.closest('.note-item'),
      anchorNode.closest('.note-card'),
      anchorNode.closest('div[class*="note"]'),
      anchorNode.closest('div[class*="card"]'),
      anchorNode
    ].filter(Boolean);
    const target = candidates.find((node) => {
      const rect = node.getBoundingClientRect();
      return rect.width > 80 && rect.height > 80;
    }) || anchorNode;
    target.scrollIntoView({ block: 'center', inline: 'center' });
    const rect = target.getBoundingClientRect();
    const x = rect.left + Math.min(rect.width / 2, 120);
    const y = rect.top + Math.min(rect.height / 2, 120);
    const eventOptions = { bubbles: true, cancelable: true, clientX: x, clientY: y, view: window };
    target.dispatchEvent(new MouseEvent('mouseover', eventOptions));
    target.dispatchEvent(new MouseEvent('mousedown', eventOptions));
    target.dispatchEvent(new MouseEvent('mouseup', eventOptions));
    target.dispatchEvent(new MouseEvent('click', eventOptions));
    return true;
  }, { noteId: row.note_id }).catch(() => false);

  if (!clicked) {
    await anchor.click({ timeout: 10000 }).catch(() => {});
  }
}

function isLikelyDetailText(afterText, beforeText, noteId) {
  const after = afterText || '';
  const before = beforeText || '';
  if (after.length > before.length + 300 && /赞|收藏|评论|发布于|展开/.test(after)) return true;
  if (noteId && after.includes(noteId) && /赞|收藏|评论/.test(after)) return true;
  return false;
}

async function closeSamePageDetail(page) {
  await page.keyboard.press('Escape').catch(() => {});
  await page.waitForTimeout(800);
  const canGoBack = /\/explore\//.test(page.url()) || /\/discovery\/item\//.test(page.url());
  if (canGoBack) {
    await page.goBack({ waitUntil: 'domcontentloaded', timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(1200);
  }
}

function isHomepageShell(text, noteId, currentUrl) {
  const body = text || '';
  if (noteId && currentUrl && !currentUrl.includes(noteId)) return true;
  const looksLikeHomepage = /^首页\s*\n/.test(body) || body.includes('沪ICP备13030189号');
  if (!looksLikeHomepage) return false;
  const hasNoteSignals = /发布于|展开|共\s*\d+\s*条评论|说点什么|分享笔记/.test(body);
  return !hasNoteSignals;
}

function parseDetailText(text) {
  const lines = String(text || '').split('\n').map((line) => line.trim()).filter(Boolean);
  const joined = lines.join('\n');
  const title = lines.find((line) => line.length >= 2 && line.length <= 80 && !/赞|收藏|评论|分享|关注/.test(line)) || '';
  const publish_time = lines.find((line) => /\d{4}-\d{1,2}-\d{1,2}|昨天|今天|小时前|分钟前|天前/.test(line)) || '';
  const like_count = extractCountNear(joined, ['赞', '喜欢', '点赞']);
  const comment_count = extractCountNear(joined, ['评论']);
  const collect_count = extractCountNear(joined, ['收藏']);
  const contentLines = lines.filter((line) => {
    if (line === title || line === publish_time) return false;
    return !/^(赞|评论|收藏|分享|关注|登录|打开小红书)/.test(line);
  });
  return {
    title,
    author: inferAuthor(lines, title),
    publish_time,
    like_count,
    comment_count,
    collect_count,
    note_type: /视频|播放/.test(joined) ? '视频' : '图文/未知',
    content: contentLines.slice(0, 30).join('\n').slice(0, 3000)
  };
}

function extractCountNear(text, labels) {
  for (const label of labels) {
    const patterns = [
      new RegExp(`${label}\\s*([0-9]+(?:\\.[0-9]+)?万?)`),
      new RegExp(`([0-9]+(?:\\.[0-9]+)?万?)\\s*${label}`)
    ];
    for (const pattern of patterns) {
      const match = text.match(pattern);
      if (match) return match[1];
    }
  }
  return '';
}

function inferAuthor(lines, title) {
  const index = lines.indexOf(title);
  if (index > 0) return lines[index - 1];
  return '';
}

async function main() {
  const config = await readConfig();
  const outputDir = path.join(config.output_dir || 'output', TODAY);
  await fs.mkdir(outputDir, { recursive: true });
  await fs.mkdir(path.dirname(config.profile_dir || '.browser-profile/xhs'), { recursive: true });

  const context = await chromium.launchPersistentContext(config.profile_dir || '.browser-profile/xhs', {
    headless: Boolean(config.headless),
    viewport: { width: 1440, height: 1000 },
    locale: 'zh-CN'
  });

  const page = context.pages()[0] || await context.newPage();
  const allRows = [];

  try {
    await ensureLoggedIn(page, config);
    for (const keyword of config.keywords || ['joybuy']) {
      console.log(`\n搜索关键词：${keyword}`);
      const sniffer = attachTokenSniffer(page);
      try {
        const url = `https://www.xiaohongshu.com/search_result?keyword=${encodeURIComponent(keyword)}`;
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
        await page.waitForTimeout(5000);
        const text = await page.locator('body').innerText({ timeout: 15000 }).catch(() => '');
        if (detectBlockedText(text)) {
          throw new Error(`页面需要人工处理：${text.slice(0, 200)}`);
        }
        const rows = await collectCards(page, keyword, config, sniffer.tokenMap);
        const withToken = rows.filter((row) => hasXsecToken(row.url)).length;
        console.log(`采集到 ${rows.length} 条搜索结果（${withToken} 条带 xsec_token，sniffer 抓到 ${sniffer.tokenMap.size} 个 token）`);
        await enrichDetails(context, page, rows, config);
        for (const row of rows) delete row._anchorIndex;
        allRows.push(...rows);
      } finally {
        sniffer.detach();
      }
      await sleep(randomDelay(config));
    }

    const jsonPath = path.join(outputDir, 'raw_notes.json');
    const csvPath = path.join(outputDir, 'raw_notes.csv');
    await fs.writeFile(jsonPath, JSON.stringify(allRows, null, 2), 'utf8');
    await writeCsv(csvPath, allRows);
    console.log(`\n完成：${csvPath}`);
    console.log(`完成：${jsonPath}`);
  } finally {
    await context.close();
  }
}

main().catch((error) => {
  console.error(`\n采集停止：${error.message}`);
  console.error('如果出现登录、验证码或安全验证，请在浏览器中手动处理后重新运行。');
  process.exit(1);
});
