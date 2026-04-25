#!/usr/bin/env python3
"""Optuna 重み最適化スクリプト

使い方:
  python3 scripts/run_optimize.py
  python3 scripts/run_optimize.py --year 2025 --trials 200
"""

import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.database import HistoryDB
from backtest.optimizer import run_optimization, DEFAULT_WEIGHTS
from backtest.base_time_calc import load_base_times


def main():
    parser = argparse.ArgumentParser(description="Optuna 重み最適化")
    parser.add_argument("--year", "-y", type=int, default=2025)
    parser.add_argument("--trials", "-n", type=int, default=200)
    parser.add_argument("--metric", type=str, default="composite",
                        choices=["avg_spearman", "top1_hit_rate", "top3_hit_rate", "composite"])
    parser.add_argument("--train-months", type=str, default="1-9")
    parser.add_argument("--val-months", type=str, default="10-12")
    parser.add_argument("--db", type=str, default=None)
    parser.add_argument("--output", "-o", type=str, default=None)
    args = parser.parse_args()

    db = HistoryDB(args.db)
    n = db.race_count(args.year)
    if n == 0:
        print(f"{args.year}年のデータがありません。")
        return

    print(f"=== Optuna 重み最適化 ===")
    print(f"対象: {args.year}年 ({n:,} レース) / 指標: {args.metric} / トライアル: {args.trials}\n")

    base_times_data = load_base_times()
    print(f"データ駆動ベースタイム: {'あり' if base_times_data else 'なし'}\n")

    def parse_months(s):
        parts = s.split("-")
        return range(int(parts[0]), int(parts[1]) + 1) if len(parts) == 2 else range(int(parts[0]), int(parts[0]) + 1)

    result = run_optimization(db, n_trials=args.trials,
                              train_months=parse_months(args.train_months),
                              val_months=parse_months(args.val_months),
                              year=args.year, metric=args.metric,
                              base_times_data=base_times_data)

    print("\n=== 重み比較 ===")
    print(f"{'因子':<20} {'現行':>8} {'最適化':>8} {'差':>8}")
    print("-" * 50)
    for key in DEFAULT_WEIGHTS:
        current = DEFAULT_WEIGHTS[key]
        optimized = result["best_weights"][key]
        print(f"{key:<20} {current:>7.2%} {optimized:>7.2%} {optimized - current:>+7.2%}")

    output_path = args.output or str(Path(__file__).parent.parent / "models" / "optimized_v1.json")
    model_data = {
        "name": "optimized_v1", "version": "v1.0-optuna",
        "description": f"Optuna最適化 ({args.year}年, {args.trials}トライアル, {args.metric})",
        "created": datetime.now().strftime("%Y-%m-%d"), "is_official": False,
        "weights": result["best_weights"],
        "optimization": {"metric": args.metric, "best_value": round(result["best_value"], 4),
                         "n_trials": result["n_trials"], "year": args.year,
                         "train_metrics": result["train_metrics"], "val_metrics": result["val_metrics"]},
        "strategy": {"min_confidence": "B", "min_primary_ev": 1.3, "max_bet_points": 8,
                     "include_favorite_in_partners": True},
    }
    Path(output_path).write_text(json.dumps(model_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n保存: {output_path}")


if __name__ == "__main__":
    main()
