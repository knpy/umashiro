"""予想・結果・振り返りの記録 - 全データを蓄積してナレッジ化に使う"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional

DATA_DIR = Path(__file__).parent / "data"
PREDICTIONS_DIR = DATA_DIR / "predictions"
RESULTS_DIR = DATA_DIR / "results"


def _ensure_dirs():
    PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# 予想記録
# ============================================================================

@dataclass
class PredictionRecord:
    """1レースの予想記録"""
    date: str                          # YYYY-MM-DD
    race_id: str
    race_name: str
    venue: str
    course_info: str                   # "ダ1200m" 等
    head_count: int
    verdict: str                       # BET / PASS
    confidence: str                    # A/B/C/D
    verdict_reason: str
    rankings: list = field(default_factory=list)  # [{rank, num, name, score, ev, style}]
    bets: list = field(default_factory=list)       # [{type, selections, amount, reason}]
    model_version: str = "v1.0"


def save_prediction(record: PredictionRecord):
    """予想を保存"""
    _ensure_dirs()
    path = PREDICTIONS_DIR / f"{record.date}_{record.race_id}.json"
    path.write_text(
        json.dumps(asdict(record), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_prediction(date: str, race_id: str) -> Optional[dict]:
    """予想を読み込む"""
    path = PREDICTIONS_DIR / f"{date}_{race_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


# ============================================================================
# 結果記録
# ============================================================================

@dataclass
class ResultRecord:
    """1レースの結果記録"""
    date: str
    race_id: str
    race_name: str
    finishing_order: list = field(default_factory=list)  # [{rank, num, name, pop, odds, time}]
    payouts: dict = field(default_factory=dict)          # {"単勝": {"selections": "7", "payout": 670}, ...}
    bet_results: list = field(default_factory=list)      # [{type, selections, amount, result, payout, profit}]
    total_bet: int = 0
    total_payout: int = 0
    profit: int = 0


def save_result(record: ResultRecord):
    """結果を保存"""
    _ensure_dirs()
    path = RESULTS_DIR / f"{record.date}_{record.race_id}.json"
    path.write_text(
        json.dumps(asdict(record), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


# ============================================================================
# 振り返り記録（予想と結果を突き合わせる）
# ============================================================================

@dataclass
class ReviewRecord:
    """振り返り"""
    date: str
    race_id: str
    prediction_rank_vs_actual: list = field(default_factory=list)  # [{num, name, pred_rank, actual_rank, gap}]
    hits: list = field(default_factory=list)           # 的中した判断
    misses: list = field(default_factory=list)         # 外した判断
    hypotheses: list = field(default_factory=list)     # この結果から生まれた仮説
    pass_was_correct: Optional[bool] = None             # PASS判定の場合、正しかったか


def generate_review(prediction: dict, result: ResultRecord) -> ReviewRecord:
    """予想と結果を突き合わせて振り返りを生成"""
    review = ReviewRecord(
        date=prediction["date"],
        race_id=prediction["race_id"],
    )

    # 予想順位 vs 実際の着順を比較
    pred_rankings = {r["num"]: r["rank"] for r in prediction.get("rankings", [])}

    for finish in result.finishing_order:
        num = finish["num"]
        actual_rank = finish["rank"]
        pred_rank = pred_rankings.get(num, 0)
        gap = pred_rank - actual_rank if pred_rank > 0 else None

        review.prediction_rank_vs_actual.append({
            "num": num,
            "name": finish["name"],
            "pred_rank": pred_rank,
            "actual_rank": actual_rank,
            "gap": gap,
        })

    # 的中/不的中の集計
    for br in result.bet_results:
        entry = {
            "type": br["type"],
            "selections": br["selections"],
            "amount": br["amount"],
            "payout": br.get("payout", 0),
        }
        if br["result"] == "win":
            review.hits.append(entry)
        else:
            review.misses.append(entry)

    # PASS判定の評価
    if prediction["verdict"] == "PASS":
        # 1番人気が1着の場合、PASSは正解だった可能性が高い（堅い結果=低配当）
        # 上位人気外の馬が来た場合も、混戦=PASS正解
        review.pass_was_correct = True  # デフォルトtrue、手動で修正可能

    return review


def save_review(review: ReviewRecord):
    """振り返りを保存"""
    _ensure_dirs()
    path = RESULTS_DIR / f"{review.date}_{review.race_id}_review.json"
    path.write_text(
        json.dumps(asdict(review), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


# ============================================================================
# 集計
# ============================================================================

def get_all_predictions(year_month: str = None) -> list[dict]:
    """全予想を取得"""
    _ensure_dirs()
    preds = []
    for f in sorted(PREDICTIONS_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        if year_month and not data["date"].startswith(year_month):
            continue
        preds.append(data)
    return preds


def get_all_results(year_month: str = None) -> list[dict]:
    """全結果を取得（振り返り除く）"""
    _ensure_dirs()
    results = []
    for f in sorted(RESULTS_DIR.glob("*.json")):
        if "_review" in f.name:
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if year_month and not data["date"].startswith(year_month):
            continue
        results.append(data)
    return results


def summary_stats(year_month: str = None) -> dict:
    """期間の統計サマリー"""
    preds = get_all_predictions(year_month)
    results = get_all_results(year_month)

    total_races_analyzed = len(preds)
    bet_races = sum(1 for p in preds if p["verdict"] == "BET")
    pass_races = sum(1 for p in preds if p["verdict"] == "PASS")
    pass_rate = pass_races / total_races_analyzed if total_races_analyzed > 0 else 0

    total_bet = sum(r.get("total_bet", 0) for r in results)
    total_payout = sum(r.get("total_payout", 0) for r in results)
    profit = total_payout - total_bet

    # スコア1位の着順分布
    rank1_finishes = []
    for p, r in _match_pred_result(preds, results):
        if p["rankings"]:
            top_num = p["rankings"][0]["num"]
            for f in r.get("finishing_order", []):
                if f["num"] == top_num:
                    rank1_finishes.append(f["rank"])

    rank1_win = sum(1 for r in rank1_finishes if r == 1)
    rank1_top3 = sum(1 for r in rank1_finishes if r <= 3)

    return {
        "total_races_analyzed": total_races_analyzed,
        "bet_races": bet_races,
        "pass_races": pass_races,
        "pass_rate": pass_rate,
        "total_bet": total_bet,
        "total_payout": total_payout,
        "profit": profit,
        "roi": total_payout / total_bet if total_bet > 0 else 0,
        "model_top1_win_rate": rank1_win / len(rank1_finishes) if rank1_finishes else 0,
        "model_top1_place_rate": rank1_top3 / len(rank1_finishes) if rank1_finishes else 0,
        "sample_size": len(rank1_finishes),
    }


def _match_pred_result(preds, results):
    """予想と結果をrace_idで突き合わせる"""
    result_map = {r["race_id"]: r for r in results}
    for p in preds:
        if p["race_id"] in result_map:
            yield p, result_map[p["race_id"]]
