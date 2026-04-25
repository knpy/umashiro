#!/usr/bin/env python3
"""ベースタイム算出スクリプト

使い方:
  python3 scripts/run_base_time.py
  python3 scripts/run_base_time.py --compare
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.database import HistoryDB
from backtest.base_time_calc import compute_base_times, save_base_times
from predictor import BASE_TIMES, TRACK_CONDITION_ADJUST


def main():
    parser = argparse.ArgumentParser(description="ベースタイム算出")
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--db", type=str, default=None)
    parser.add_argument("--min-samples", type=int, default=5)
    args = parser.parse_args()

    db = HistoryDB(args.db)
    n = db.race_count()
    if n == 0:
        print("DB にデータがありません。先に collect_history.py を実行してください。")
        return

    print(f"DB: {n:,} レースから算出\n")
    data = compute_base_times(db, min_samples=args.min_samples)

    print("=== グローバルベースタイム (全会場平均・良馬場) ===")
    for surface in sorted(data["global"].keys()):
        print(f"\n  {surface}:")
        for dist in sorted(data["global"][surface].keys()):
            t = data["global"][surface][dist]
            print(f"    {dist}m: {t:.1f}秒")

    if args.compare:
        print("\n=== 現行ハードコード値との比較 ===")
        print(f"{'馬場':>4} {'距離':>6} {'現行':>8} {'データ':>8} {'差':>8}")
        print("-" * 40)
        for surface in ("芝", "ダ"):
            if surface not in BASE_TIMES or surface not in data["global"]:
                continue
            for dist in sorted(set(BASE_TIMES[surface].keys()) | set(data["global"].get(surface, {}).keys())):
                current = BASE_TIMES[surface].get(dist)
                computed = data["global"].get(surface, {}).get(dist)
                if current and computed:
                    print(f"{surface:>4} {dist:>5}m {current:>7.1f} {computed:>7.1f} {computed - current:>+7.1f}")

    out_path = save_base_times(data)
    print(f"\n保存: {out_path}")


if __name__ == "__main__":
    main()
