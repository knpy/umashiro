"""バックテスト用の評価指標"""


def spearman_correlation(predicted_ranks, actual_ranks):
    n = len(predicted_ranks)
    if n < 2:
        return 0.0
    d_squared = sum((p - a) ** 2 for p, a in zip(predicted_ranks, actual_ranks))
    return 1 - (6 * d_squared) / (n * (n ** 2 - 1))


def top_k_hit_rate(predicted_numbers, actual_ranking, k=1):
    if not predicted_numbers:
        return 0.0
    actual_pos = actual_ranking.get(predicted_numbers[0], 99)
    return 1.0 if actual_pos <= k else 0.0


def top3_coverage(predicted_numbers, actual_ranking):
    if len(predicted_numbers) < 3:
        return 0.0
    top3_predicted = set(predicted_numbers[:3])
    actual_top3 = {num for num, pos in actual_ranking.items() if pos <= 3}
    return len(top3_predicted & actual_top3) / 3.0


def evaluate_race(predicted_scores, actual_ranking):
    pred_numbers = [s.horse_number for s in predicted_scores]
    common = [num for num in pred_numbers if num in actual_ranking]
    if len(common) < 3:
        return None
    pred_ranks = [i + 1 for i, num in enumerate(pred_numbers) if num in actual_ranking]
    actual_ranks = [actual_ranking[num] for num in common]
    return {
        "spearman": spearman_correlation(pred_ranks, actual_ranks),
        "top1_hit": top_k_hit_rate(pred_numbers, actual_ranking, k=1),
        "top3_hit": top_k_hit_rate(pred_numbers, actual_ranking, k=3),
        "top3_coverage": top3_coverage(pred_numbers, actual_ranking),
        "n_horses": len(common),
    }


def aggregate_metrics(race_results):
    if not race_results:
        return {"avg_spearman": 0.0, "top1_hit_rate": 0.0, "top3_hit_rate": 0.0,
                "avg_top3_coverage": 0.0, "n_races": 0}
    n = len(race_results)
    return {
        "avg_spearman": sum(r["spearman"] for r in race_results) / n,
        "top1_hit_rate": sum(r["top1_hit"] for r in race_results) / n,
        "top3_hit_rate": sum(r["top3_hit"] for r in race_results) / n,
        "avg_top3_coverage": sum(r["top3_coverage"] for r in race_results) / n,
        "n_races": n,
    }
