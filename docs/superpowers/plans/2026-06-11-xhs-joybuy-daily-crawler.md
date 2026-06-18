# XHS Joybuy Daily Crawler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local, low-frequency, login-browser-based Xiaohongshu Joybuy content collector and daily analyzer.

**Architecture:** A Playwright collector opens a persistent browser profile so the user can log in manually, searches configured Joybuy keywords, reads visible result cards and selected detail pages, and writes raw CSV/JSON. A separate Python analyzer enriches collected rows with engagement score, rule-based category/sentiment/risk labels, and generates Markdown/HTML reports.

**Tech Stack:** Node.js + Playwright for visible browser collection; Python standard library for CSV/JSON analysis and report generation; JSON config.

---

### Task 1: Project Scaffold

**Files:**
- Create: `package.json`
- Create: `config/joybuy_crawler.json`
- Create: `.gitignore`

- [ ] Create Node package metadata with scripts: `npm run install-browser`, `npm run crawl`, `npm run analyze`.
- [ ] Create JSON config with keywords, limits, delays, and output directory.
- [ ] Ignore generated browser profile, screenshots, temporary files, and dependency folders.

### Task 2: Playwright Collector

**Files:**
- Create: `scripts/xhs_joybuy_crawler.mjs`

- [ ] Load config from `config/joybuy_crawler.json`.
- [ ] Launch Chromium persistent context at `.browser-profile/xhs` with `headless:false`.
- [ ] Navigate to Xiaohongshu and pause if login is needed.
- [ ] For each keyword, navigate to search URL and slowly scroll.
- [ ] Extract visible note cards using multiple selector fallbacks.
- [ ] Open top detail notes in new tabs and extract visible text/counts using conservative DOM text parsing.
- [ ] Write `raw_notes.csv` and `raw_notes.json` under `output/YYYY-MM-DD/`.
- [ ] Stop and warn if captcha/login/blocked text is detected.

### Task 3: Analyzer

**Files:**
- Create: `scripts/analyze_joybuy_notes.py`

- [ ] Read latest or specified `raw_notes.csv`.
- [ ] Normalize Chinese count strings such as `1.2万`.
- [ ] Compute engagement score.
- [ ] Apply keyword rules for category, sentiment, risk type, and user need.
- [ ] Write `analyzed_notes.csv`, `daily_report.md`, and `daily_report.html`.

### Task 4: Documentation

**Files:**
- Create: `README.md`

- [ ] Document login-safe usage: install browser, run crawl, manually log in, rerun crawl, run analyze.
- [ ] Explain that the script does not store passwords or bypass access controls.
- [ ] Document output files and config options.

### Task 5: Validation

**Files:**
- No new files.

- [ ] Run syntax checks for Node and Python.
- [ ] Run analyzer on a small sample CSV to verify report generation.
- [ ] Do not run live crawl unless the user is ready to log in interactively.
