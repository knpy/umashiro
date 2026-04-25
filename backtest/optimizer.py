"""Optuna によるスコアリング重みの最適化"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.database import HistoryDB
from backtest.score_reconstructor import reconstruct_scores, get_actual_ranking
from backtest.metrics import evaluate_race, aggregate_metrics
from predictor import DEFAULT_WEIGHTS

try:
    import optuna
except ImportError:
    optuna = None

WEIGHT_KEYS = list(DEFAULT_WEIGHTS.keys())

WEIGHT_RANGES = {
    "time_index":       (0.05, 0.40),
    "last_3f_index":    (0.05, 0.30),
    "stability_index":  (0.02, 0.20),
    "course_fitness":   (0.02, 0.25),
    "pace_advantage":   (0.02, 0.20),
    "form_cycle":       (0.02, 0.20),
    "weight_score":     (0.01, 0.10),
    "class_score":      (0.02, 0.15),
    "rest_days_score":  (0.01, 0.15),
    "gate_bias_score":  (0.01, 0.15),
    "jockey_score":     (0.02, 0.20),
}


def _normalize_weights(raw):
    total = sum(raw.values())
    if total == 0:
        return {k: 1.0 / len(raw) for k in raw}
    return {k: v / total for k, v in raw.items()}


def evaluate_weights(weights, races, db, base_times_data=None):
    model_config = {"weights": weights}
    results = []
    for race_data in races:
        actual = get_actual_ranking(race_data)
        if len(actual) < 5:
            continue
        scores = reconstruct_scores(db, race_data, model_config=model_config,
                                    base_times_data=base_times_data)
        result = evaluate_race(scores, actual)
        if result:
            results.append(result)
    return aggregate_metrics(results)


def create_objective(train_races, db, base_times_data=None, metric="avg_spearman"):
    def objective(trial):
        raw_weights = {}
        for key in WEIGHT_KEYS:
            lo, hi = WEIGHT_RANGES.get(key, (0.02, 0.30))
            raw_weights[key] = trial.suggest_float(key, lo, hi)
        weights = _normalize_weights(raw_weights)
        metrics = evaluate_weights(weights, train_races, db, base_times_data=base_times_data)
        if metrics["n_races"] == 0:
            return 0.0
        if metric == "composite":
            return (metrics["avg_spearman"] * 0.5 +
                    metrics["top3_hit_rate"] * 0.3 +
                    metrics["avg_top3_coverage"] * 0.2)
        return metrics.get(metric, 0.0)
    return objective


def run_optimization(db, n_trials=200, train_months=None, val_months=None,
                     year=2025, metric="composite", base_times_data=None):
    if optuna is None:
        raise ImportError("optuna が必要です: pip install optuna")

    all_races = db.iter_races(year=year)
    if not all_races:
        raise ValueError(f"{year}年のデータがありません")

    if train_months is None:
        train_months = range(1, 10)
    if val_months is None:
        val_months = range(10, 13)

    train_races = [r for r in all_races if int(r["date"].split("-")[1]) in train_months]
    val_races = [r for r in all_races if int(r["date"].split("-")[1]) in val_months]

    print(f"学習データ: {len(train_races)} レース")
    print(f"検証データ: {len(val_races)} レース")

    if not train_races:
        raise ValueError("学習データがありません")

    current_metrics = evaluate_weights(DEFAULT_WEIGHTS, train_races, db, base_times_data)
    print(f"\n現行重み性能 (学習データ):")
    _print_metrics(current_metrics)

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="maximize")
    objective = create_objective(train_races, db, base_times_data, metric)

    print(f"\n最適化開始 ({n_trials} トライアル)...")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    best_raw = {k: study.best_params[k] for k in WEIGHT_KEYS}
    best_weights = _normalize_weights(best_raw)

    train_metrics = evaluate_weights(best_weights, train_races, db, base_times_data)
    print(f"\n最適化重み性能 (学習データ):")
    _print_metrics(train_metrics)

    val_metrics = None
    if val_races:
        val_metrics = evaluate_weights(best_weights, val_races, db, base_times_data)
        current_val = evaluate_weights(DEFAULT_WEIGHTS, val_races, db, base_times_data)
        print(f"\n現行重み性能 (検証データ):")
        _print_metrics(current_val)
        print(f"最適化重み性能 (検証データ):")
        _print_metrics(val_metrics)

    return {
        "best_weights": {k: round(v, 4) for k, v in best_weights.items()},
        "best_value": study.best_value,
        "train_metrics": train_metrics,
        "val_metrics": val_metrics,
        "current_metrics": current_metrics,
        "n_trials": n_trials,
    }


def _print_metrics(m):
    print(f"  Spearman相関: {m['avg_spearman']:.4f}")
    print(f"  Top1的中率:   {m['top1_hit_rate']:.2%}")
    print(f"  Top3的中率:   {m['top3_hit_rate']:.2%}")
    print(f"  Top3カバー率: {m['avg_top3_coverage']:.2%}")
    print(f"  評価レース数: {m['n_races']}")
