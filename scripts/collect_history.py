#!/usr/bin/env python3
"""過去レース結果の一括収集スクリプト

使い方:
  python3 scripts/collect_history.py --year 2025
  python3 scripts/collect_history.py --year 2025 --months 1-3
  python3 scripts/collect_history.py --stats
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper import NetkeibaScraper
from backtest.database import HistoryDB

VENUE_CODES = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟",
    "05": "東京", "06": "中山", "07": "中京", "08": "京都",
    "09": "阪神", "10": "小倉",
}


def generate_race_ids(year, venue_codes=None):
    if venue_codes is None:
        venue_codes = list(VENUE_CODES.keys())
    ids = []
    for venue in venue_codes:
        for kai in range(1, 7):
            for day in range(1, 14):
                for race in range(1, 13):
                    ids.append(f"{year}{venue}{kai:02d}{day:02d}{race:02d}")
    return ids


def parse_months(s):
    if "-" in s:
        parts = s.split("-")
        return range(int(parts[0]), int(parts[1]) + 1)
    return range(int(s), int(s) + 1)


def main():
    parser = argparse.ArgumentParser(description="過去レースデータ一括収集")
    parser.add_argument("--year", "-y", type=int)
    parser.add_argument("--months", "-m", type=str, default=None)
    parser.add_argument("--venue", "-v", type=str, default=None)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--db", type=str, default=None)
    args = parser.parse_args()

    db = HistoryDB(args.db)

    if args.stats:
        s = db.stats()
        print("=== DB 統計 ===")
        if s["date_range"]:
            print(f"期間: {s['date_range']['from']} ~ {s['date_range']['to']}")
        print(f"レース数: {s['total_races']:,}")
        print(f"ユニーク馬数: {s['unique_horses']:,}")
        print(f"延べ出走数: {s['total_entries']:,}")
        if s["venues"]:
            print("\n会場別:")
            for venue, n in s["venues"].items():
                print(f"  {venue}: {n:,}")
        return

    if not args.year:
        parser.error("--year は必須です (--stats 以外)")

    venue_codes = None
    if args.venue:
        code = next((k for k, v in VENUE_CODES.items() if v == args.venue), None)
        if not code:
            parser.error(f"不明な会場: {args.venue}")
        venue_codes = [code]

    print(f"=== 過去データ収集: {args.year}年 ===")
    if args.venue:
        print(f"会場: {args.venue}")
    print(f"リクエスト間隔: {args.delay}秒")
    print()

    existing_ids = set(db.iter_race_ids(args.year))
    print(f"収集済み: {len(existing_ids)} レース")

    all_ids = generate_race_ids(args.year, venue_codes=venue_codes)
    target_ids = [rid for rid in all_ids if rid not in existing_ids]
    print(f"候補: {len(all_ids)} → 未収集: {len(target_ids)}")
    print()

    scraper = NetkeibaScraper(delay=args.delay)
    collected = 0
    skipped = 0
    errors = 0
    not_found = 0
    consecutive_404 = 0

    for i, race_id in enumerate(target_ids):
        venue_name = VENUE_CODES.get(race_id[4:6], "??")
        kai = int(race_id[6:8])
        day = int(race_id[8:10])
        race_num = int(race_id[10:12])

        print(f"\r[{i+1}/{len(target_ids)}] {venue_name} {kai}回{day}日 {race_num}R "
              f"(収集:{collected} スキップ:{not_found} エラー:{errors})", end="", flush=True)

        try:
            result = scraper.get_race_result(race_id)
            if result is None:
                not_found += 1
                consecutive_404 += 1
                if consecutive_404 >= 36:
                    skip_prefix = race_id[:8]
                    while i + 1 < len(target_ids) and target_ids[i + 1].startswith(skip_prefix):
                        i += 1
                        skipped += 1
                    consecutive_404 = 0
                continue

            consecutive_404 = 0

            if args.months and result.get("date"):
                month = int(result["date"].split("-")[1])
                if month not in parse_months(args.months):
                    skipped += 1
                    continue

            if not result.get("surface") or not result.get("distance"):
                skipped += 1
                continue

            db.insert_race(result)
            collected += 1

        except KeyboardInterrupt:
            print("\n\n中断されました。次回は続きから再開できます。")
            break
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"\n  [ERROR] {race_id}: {e}")

    print(f"\n\n=== 完了 ===")
    print(f"収集: {collected} / 未発見: {not_found} / スキップ: {skipped} / エラー: {errors}")
    s = db.stats()
    print(f"DB合計: {s['total_races']:,} レース / {s['unique_horses']:,} 馬")


if __name__ == "__main__":
    main()
