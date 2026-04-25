#!/usr/bin/env python3
"""BET/PASS閾値バックテストスクリプト

使い方:
  python3 scripts/run_threshold_test.py
  python3 scripts/run_threshold_test.py --year 2025
"""

import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.database import HistoryDB
from backtest.threshold_backtest import grid_search, simulate_strategy
from backtest.base_time_calc import load_base_times
from strategy import DEFAULT_STRATEGY


def main():
    parser = argparse.ArgumentParser(description="BET/PASS閾値バックテスト")
    parser.add_argument("--year", "-y", type=int, default=2025)
    parser.add_argument("--db", type=str, default=None)
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    db = HistoryDB(args.db)
    n = db.race_count(args.year)
    if n == 0:
        print(f"{args.year}年のデータがありません。")
        return

    print(f"=== BET/PASS閾値バックテスト ===")
    print(f"対象: {args.year}年 ({n:,} レース)\n")

    races = db.iter_races(year=args.year)
    base_times_data = load_base_times()

    print("--- 現行設定 ---")
    current = simulate_strategy(db, races, DEFAULT_STRATEGY, base_times_data=base_times_data)
    print(f"  BET: {current['bet_races']}/{current['total_races']}")
    print(f"  投資: {current['total_invested']:,}円 → 払戻: {current['total_returned']:,}円")
    print(f"  ROI: {current['roi']:+.1%} / 的中率: {current['hit_rate']:.1%}\n")

    print("--- グリッドサーチ ---")
    results = grid_search(db, races, base_times_data=base_times_data)

    valid = [r for r in results if r["bet_races"] >= 10]
    valid.sort(key=lambda x: x["roi"], reverse=True)

    print(f"\n=== ROI上位{args.top} ===\n")
    print(f"{'#':>3} {'ROI':>8} {'的中率':>6} {'BET':>5} {'投資':>10} {'損益':>10} "
          f"{'conf':>4} {'p_ev':>5} {'t3_ev':>5} {'d12A':>5} {'d13B':>5}")
    print("-" * 85)
    for i, r in enumerate(valid[:args.top], 1):
        c = r["config"]
        print(f"{i:>3} {r['roi']:>+7.1%} {r['hit_rate']:>5.1%} "
              f"{r['bet_races']:>5} {r['total_invested']:>9,} {r['profit']:>+9,} "
              f"{c['min_confidence']:>4} {c['min_primary_ev']:>5.1f} "
              f"{c['min_top3_ev']:>5.1f} {c['score_diff_1_2_for_A']:>5.1f} "
              f"{c['score_diff_1_3_for_B']:>5.1f}")

    report_dir = Path(__file__).parent.parent / "reports"
    report_dir.mkdir(exist_ok=True)
    report_path = report_dir / f"threshold_backtest_{datetime.now().strftime('%Y%m%d')}.json"
    report = {"date": datetime.now().strftime("%Y-%m-%d"), "year": args.year,
              "current_settings": current, "top_results": valid[:20]}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nレポート保存: {report_path}")


if __name__ == "__main__":
    main()
