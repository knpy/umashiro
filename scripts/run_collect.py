#!/usr/bin/env python3
"""結果収集スクリプト - 予想済みレースの結果を取得し収支を記録する

使い方:
  python3 scripts/run_collect.py                    # 今日の結果を収集
  python3 scripts/run_collect.py --date 2026-04-18  # 日付指定
"""

import sys
import os
import json
import re
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper import NetkeibaScraper
from tracker import (
    ResultRecord, save_result,
    generate_review, save_review,
    load_prediction, PREDICTIONS_DIR, _ensure_dirs,
)
from bankroll import LedgerEntry, add_entries, format_status
from backtest.bet_utils import check_bet_result


def fetch_result(scraper, race_id):
    """レース結果と払い戻しをスクレイピング"""
    import requests
    from bs4 import BeautifulSoup

    resp = scraper.session.get(
        "https://race.netkeiba.com/race/result.html",
        params={"race_id": race_id},
        timeout=30,
    )
    resp.encoding = "euc-jp"
    soup = BeautifulSoup(resp.text, "html.parser")

    # 着順テーブル
    finishing_order = []
    rows = soup.select(".HorseList")
    for row in rows:
        tds = row.select("td")
        if len(tds) < 10:
            continue

        rank_text = tds[0].get_text(strip=True)
        rank = int(re.search(r"\d+", rank_text).group()) if re.search(r"\d+", rank_text) else 0

        umaban_el = row.select_one("td[class*='Umaban']")
        umaban = umaban_el.get_text(strip=True) if umaban_el else ""

        horse_el = row.select_one(".HorseInfo a, .HorseName a, .Horse_Name a")
        horse_name = horse_el.get_text(strip=True) if horse_el else ""

        # 全テキストから人気・オッズ・タイムを取得
        all_text = [td.get_text(strip=True) for td in tds]

        # 人気とオッズを探す
        pop, odds, time_str = 0, 0.0, ""
        for t in all_text:
            odds_m = re.match(r"(\d+\.\d+)$", t)
            if odds_m and odds == 0.0:
                odds = float(odds_m.group(1))
            time_m = re.match(r"\d:\d\d\.\d$", t)
            if time_m:
                time_str = t

        finishing_order.append({
            "rank": rank,
            "num": umaban,
            "name": horse_name,
            "pop": 0,  # 後で解析
            "odds": odds,
            "time": time_str,
        })

    # 払い戻し
    payouts = {}
    for table in soup.select("table"):
        text = table.get_text(strip=True)
        if "単勝" not in text and "馬連" not in text and "三連" not in text:
            continue
        for tr in table.select("tr"):
            cells = tr.select("th, td")
            if len(cells) >= 3:
                bet_type = cells[0].get_text(strip=True)
                selections = cells[1].get_text(strip=True)
                payout_text = cells[2].get_text(strip=True)
                payout_m = re.search(r"([\d,]+)円", payout_text)
                if payout_m and bet_type in ("単勝", "複勝", "馬連", "馬単", "ワイド", "3連複", "3連単"):
                    normalized_type = bet_type.replace("3連複", "三連複").replace("3連単", "三連単")
                    payout_val = int(payout_m.group(1).replace(",", ""))
                    payouts[normalized_type] = {
                        "selections": selections,
                        "payout": payout_val,
                    }

    return finishing_order, payouts


def main():
    parser = argparse.ArgumentParser(description="結果収集スクリプト")
    parser.add_argument("--date", "-d", default=datetime.now().strftime("%Y-%m-%d"))
    args = parser.parse_args()

    date = args.date
    # YYYYMMDD形式にも対応
    if len(date) == 8 and date.isdigit():
        date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"

    print(f"=== 結果収集: {date} ===")
    print()

    _ensure_dirs()
    scraper = NetkeibaScraper(delay=1.0)

    # この日付の予想ファイルを検索
    pred_files = sorted(PREDICTIONS_DIR.glob(f"{date}_*.json"))
    # 実験モデルのファイルは除外（officialのみ収支計上）
    official_preds = [f for f in pred_files
                      if not any(x in f.stem for x in ["_exp_", "_exp-"])]

    if not official_preds:
        print(f"{date} の予想データがありません")
        return

    print(f"予想ファイル: {len(official_preds)}レース")
    print()

    ledger_entries = []
    total_bet = 0
    total_payout = 0

    for pred_file in official_preds:
        pred = json.loads(pred_file.read_text(encoding="utf-8"))
        race_id = pred["race_id"]
        race_name = pred.get("race_name", "")

        print(f"--- {race_name} ({race_id}) ---")
        print(f"  判定: {pred['verdict']} ({pred['confidence']})")

        # 結果取得
        finishing_order, payouts = fetch_result(scraper, race_id)
        if not finishing_order:
            print("  [SKIP] 結果未確定")
            continue

        print(f"  着順: {' → '.join(f['name'] for f in finishing_order[:3])}")

        # 馬券の照合
        bet_results = []
        race_bet = 0
        race_payout = 0

        if pred["verdict"] == "BET" and pred.get("bets"):
            for bet in pred["bets"]:
                result, payout, profit = check_bet_result(bet, payouts, finishing_order)
                bet_results.append({
                    "type": bet["type"],
                    "selections": bet["selections"],
                    "amount": bet["amount"],
                    "result": result,
                    "payout": payout,
                    "profit": profit,
                })

                # 収支台帳
                ledger_entries.append(LedgerEntry(
                    date=date,
                    race_id=race_id,
                    race_name=race_name,
                    bet_type=bet["type"],
                    selections=bet["selections"],
                    amount=bet["amount"],
                    result=result,
                    payout=payout,
                    profit=profit,
                ))

                mark = "O" if result == "win" else "X"
                race_bet += bet["amount"]
                race_payout += payout
                print(f"  [{mark}] {bet['type']} {bet['selections']}: "
                      f"{bet['amount']:,}円 → {payout:,}円")

            print(f"  小計: {race_bet:,}円 → {race_payout:,}円 ({race_payout - race_bet:+,}円)")

        # 結果を保存
        result_record = ResultRecord(
            date=date,
            race_id=race_id,
            race_name=race_name,
            finishing_order=finishing_order,
            payouts=payouts,
            bet_results=bet_results,
            total_bet=race_bet,
            total_payout=race_payout,
            profit=race_payout - race_bet,
        )
        save_result(result_record)

        # 振り返りを生成
        review = generate_review(pred, result_record)
        save_review(review)

        total_bet += race_bet
        total_payout += race_payout
        print()

    # 収支台帳に一括記録
    if ledger_entries:
        add_entries(ledger_entries)

    # サマリー
    print("=" * 50)
    print(f"日計: 投資{total_bet:,}円 → 払戻{total_payout:,}円 = {total_payout - total_bet:+,}円")
    print()
    print(format_status())


if __name__ == "__main__":
    main()
