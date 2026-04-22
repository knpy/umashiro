#!/usr/bin/env python3
"""オッズを手動注入して再分析するスクリプト"""

import os
import sys
from dotenv import load_dotenv
from rich.console import Console

from scraper import NetkeibaScraper
from predictor import calculate_scores
from analyzer import build_report
from main import display_scores_table, save_report, run_claude_analysis

load_dotenv()
console = Console()

# 手動オッズデータ: 馬番 -> (単勝オッズ, 人気)
ODDS_DATA = {
    "1":  ("26.7", "9"),
    "2":  ("24.3", "8"),
    "3":  ("59.9", "12"),
    "4":  ("5.9", "2"),
    "5":  ("5.9", "3"),
    "6":  ("66.1", "13"),
    "7":  ("29.0", "10"),
    "8":  ("12.5", "7"),
    "9":  ("3.3", "1"),
    "10": ("6.8", "4"),
    "11": ("9.6", "6"),
    "12": ("8.0", "5"),
    "13": ("57.5", "11"),
}

race_id = "202606030710"
date = "20260418"
use_grok = True

scraper = NetkeibaScraper(delay=1.0)

# Grokクライアント
grok_client = None
if use_grok:
    xai_key = os.environ.get("XAI_API_KEY")
    if xai_key:
        from grok_client import GrokClient
        grok_client = GrokClient(api_key=xai_key)

from rich.progress import Progress, SpinnerColumn, TextColumn

with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
    task = progress.add_task("出馬表を取得中...", total=None)
    race = scraper.get_race_entries(race_id)
    progress.update(task, description=f"[green]OK[/green] {race.race_name} ({race.head_count}頭)")
    progress.remove_task(task)

    # オッズ注入
    for entry in race.entries:
        if entry.horse_number in ODDS_DATA:
            entry.odds, entry.popularity = ODDS_DATA[entry.horse_number]

    # 過去成績取得
    task = progress.add_task("過去成績を取得中...", total=len(race.entries))
    for entry in race.entries:
        progress.update(task, description=f"取得中: {entry.horse_name}")
        if entry.horse_id:
            entry.history = scraper.get_horse_history(entry.horse_id, limit=5)
        progress.advance(task)
    progress.remove_task(task)

    # 騎手成績取得
    jockey_cache = {}
    jockey_ids = {e.jockey_id for e in race.entries if e.jockey_id}
    if jockey_ids:
        task = progress.add_task("騎手成績を取得中...", total=len(jockey_ids))
        for jid in jockey_ids:
            stats = scraper.get_jockey_stats(jid)
            if stats:
                jockey_cache[jid] = stats
            progress.advance(task)
        progress.remove_task(task)
        for entry in race.entries:
            if entry.jockey_id in jockey_cache:
                entry.jockey_stats = jockey_cache[entry.jockey_id]

    # スコアリング（オッズ込み）
    task = progress.add_task("スコアリング中...", total=None)
    scores = calculate_scores(race)
    progress.update(task, description="[green]OK[/green] スコアリング完了")
    progress.remove_task(task)

    # Grok X予想
    grok_result = None
    if grok_client:
        task = progress.add_task("X予想を収集中 (Grok)...", total=None)
        try:
            grok_result = grok_client.search_predictions(
                venue=race.venue or "中山", date=date, race_number=race.race_number
            )
            progress.update(task, description="[green]OK[/green] X予想収集完了")
        except Exception as e:
            progress.update(task, description=f"[yellow]SKIP[/yellow] Grok: {e}")
            grok_result = None
        progress.remove_task(task)

# スコア表示
console.print()
display_scores_table(scores)

# レポート生成 & 保存
report = build_report(race, stat_scores=scores, grok_result=grok_result)
path = save_report(report, race_id, date)
console.print(f"\n[dim]レポート保存: {path}[/dim]")

# Claude分析
run_claude_analysis(report)
