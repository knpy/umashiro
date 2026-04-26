#!/usr/bin/env python3
"""週次振り返りスクリプト - 予想と結果を集約分析してパターンを検出する

使い方:
  python3 scripts/run_review.py                    # 今週の振り返り
  python3 scripts/run_review.py --week 2026-W17    # 週番号指定
  python3 scripts/run_review.py --dates 2026-04-25,2026-04-26  # 日付直接指定
"""

import sys
import json
import argparse
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tracker import PREDICTIONS_DIR, RESULTS_DIR, _ensure_dirs

DATA_DIR = Path(__file__).parent.parent / "data"
REVIEWS_DIR = DATA_DIR / "reviews"


def get_week_dates(week_str: str) -> list[str]:
    """ISO週番号 (YYYY-WNN) から対象の土日日付リストを返す"""
    year, week_num = week_str.split("-W")
    # ISO week: 月曜=1, 日曜=7。土曜=6, 日曜=7
    monday = datetime.strptime(f"{year}-W{int(week_num):02d}-1", "%G-W%V-%u")
    saturday = monday + timedelta(days=5)
    sunday = monday + timedelta(days=6)
    return [saturday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")]


def current_week_str() -> str:
    """今日が属するISO週番号を返す"""
    now = datetime.now()
    return now.strftime("%G-W%V")


def load_predictions_for_dates(dates: list[str]) -> list[dict]:
    """指定日付の予想を読み込む（公式モデルのみ）"""
    _ensure_dirs()
    preds = []
    for f in sorted(PREDICTIONS_DIR.glob("*.json")):
        if any(x in f.stem for x in ["_exp_", "_exp-"]):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if data["date"] in dates:
            preds.append(data)
    return preds


def load_results_for_dates(dates: list[str]) -> list[dict]:
    """指定日付の結果を読み込む"""
    _ensure_dirs()
    results = []
    for f in sorted(RESULTS_DIR.glob("*.json")):
        if "_review" in f.name:
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if data["date"] in dates:
            results.append(data)
    return results


def load_reviews_for_dates(dates: list[str]) -> list[dict]:
    """指定日付のレビューを読み込む"""
    _ensure_dirs()
    reviews = []
    for f in sorted(RESULTS_DIR.glob("*_review.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        if data["date"] in dates:
            reviews.append(data)
    return reviews


def parse_course_info(course_info: str) -> dict:
    """course_infoから馬場・距離を抽出"""
    surface = "不明"
    distance = 0
    if "芝" in course_info:
        surface = "芝"
    elif "ダ" in course_info:
        surface = "ダ"
    m = re.search(r"(\d{3,4})m", course_info)
    if m:
        distance = int(m.group(1))
    return {"surface": surface, "distance": distance}


def distance_category(dist: int) -> str:
    """距離カテゴリを返す"""
    if dist <= 1400:
        return "短距離"
    elif dist <= 1800:
        return "マイル"
    elif dist <= 2200:
        return "中距離"
    else:
        return "長距離"


def compute_summary(preds: list[dict], results: list[dict], dates: list[str]) -> dict:
    """サマリー集計"""
    result_map = {r["race_id"]: r for r in results}

    total = len(preds)
    bet_count = sum(1 for p in preds if p["verdict"] == "BET")
    pass_count = total - bet_count

    total_bet = sum(r.get("total_bet", 0) for r in results)
    total_payout = sum(r.get("total_payout", 0) for r in results)

    # モデル1位の着順
    top1_hits = 0
    top1_place = 0
    top3_overlap_total = 0
    matched_count = 0

    for p in preds:
        r = result_map.get(p["race_id"])
        if not r or not r.get("finishing_order") or not p.get("rankings"):
            continue
        matched_count += 1

        # top1 的中
        top_num = p["rankings"][0]["num"]
        actual_1st = r["finishing_order"][0]["num"] if r["finishing_order"] else ""
        actual_top3 = {f["num"] for f in r["finishing_order"][:3]}
        if top_num == actual_1st:
            top1_hits += 1
        if top_num in actual_top3:
            top1_place += 1

        # top3 overlap
        pred_top3 = {h["num"] for h in p["rankings"][:3]}
        overlap = len(pred_top3 & actual_top3)
        top3_overlap_total += overlap

    return {
        "total_races": total,
        "bet_races": bet_count,
        "pass_races": pass_count,
        "total_bet": total_bet,
        "total_payout": total_payout,
        "profit": total_payout - total_bet,
        "roi": round(total_payout / total_bet, 3) if total_bet > 0 else 0,
        "top1_hit_rate": round(top1_hits / matched_count, 3) if matched_count > 0 else 0,
        "top1_place_rate": round(top1_place / matched_count, 3) if matched_count > 0 else 0,
        "top3_overlap_rate": round(top3_overlap_total / (matched_count * 3), 3) if matched_count > 0 else 0,
        "matched_races": matched_count,
    }


def analyze_factors(preds: list[dict], results: list[dict]) -> dict:
    """ファクター誤差分析: gap>=3の馬について、どのファクターが系統的に偏っているか"""
    result_map = {r["race_id"]: r for r in results}
    factor_errors = defaultdict(lambda: {"overrated": 0, "underrated": 0, "errors": []})

    for p in preds:
        r = result_map.get(p["race_id"])
        if not r or not r.get("finishing_order"):
            continue

        actual_rank_map = {f["num"]: f["rank"] for f in r["finishing_order"]}
        pred_rank_map = {h["num"]: h["rank"] for h in p.get("rankings", [])}

        for horse in p.get("rankings", []):
            num = horse["num"]
            pred_rank = horse["rank"]
            actual_rank = actual_rank_map.get(num)
            if actual_rank is None:
                continue

            gap = pred_rank - actual_rank  # 正=過大評価、負=過小評価
            if abs(gap) < 3:
                continue

            factors = horse.get("factors")
            if not factors:
                continue

            direction = "overrated" if gap > 0 else "underrated"
            for factor_name, factor_val in factors.items():
                # 50点が中央値。50から離れるほど高評価/低評価
                if factor_val > 55 and gap > 0:
                    factor_errors[factor_name]["overrated"] += 1
                elif factor_val < 45 and gap < 0:
                    factor_errors[factor_name]["underrated"] += 1

    return {
        name: {
            "overrated": data["overrated"],
            "underrated": data["underrated"],
            "total_errors": data["overrated"] + data["underrated"],
        }
        for name, data in factor_errors.items()
        if data["overrated"] + data["underrated"] > 0
    }


def detect_patterns(preds: list[dict], results: list[dict]) -> list[dict]:
    """パターン検出: (馬場, 距離カテゴリ, 脚質) でグルーピングしてエラー率を算出"""
    result_map = {r["race_id"]: r for r in results}
    category_stats = defaultdict(lambda: {"total": 0, "errors": 0, "races": []})

    for p in preds:
        r = result_map.get(p["race_id"])
        if not r or not r.get("finishing_order") or p["verdict"] != "BET":
            continue

        course = parse_course_info(p.get("course_info", ""))
        dist_cat = distance_category(course["distance"])
        actual_1st_num = r["finishing_order"][0]["num"] if r["finishing_order"] else ""
        pred_1st_num = p["rankings"][0]["num"] if p.get("rankings") else ""

        # カテゴリ: (馬場, 距離)
        cat_key = f"{course['surface']}_{dist_cat}"
        category_stats[cat_key]["total"] += 1
        if pred_1st_num != actual_1st_num:
            category_stats[cat_key]["errors"] += 1
            category_stats[cat_key]["races"].append(p["race_id"])

        # カテゴリ: (脚質)
        if p.get("rankings"):
            top_style = p["rankings"][0].get("style", "不明")
            style_key = f"本命脚質_{top_style}"
            category_stats[style_key]["total"] += 1
            if pred_1st_num != actual_1st_num:
                category_stats[style_key]["errors"] += 1
                category_stats[style_key]["races"].append(p["race_id"])

    signals = []
    for cat, stats in category_stats.items():
        if stats["total"] >= 3 and stats["errors"] / stats["total"] >= 0.6:
            signals.append({
                "pattern_id": cat,
                "description": f"{cat}: {stats['errors']}/{stats['total']}レースで本命外し",
                "affected_races": stats["races"],
                "occurrences": stats["errors"],
                "total_applicable": stats["total"],
                "confidence": round(stats["errors"] / stats["total"], 2),
            })

    return sorted(signals, key=lambda s: s["confidence"], reverse=True)


def find_big_misses(preds: list[dict], results: list[dict]) -> list[dict]:
    """大外し: pred_rank vs actual_rank の gap >= 4"""
    result_map = {r["race_id"]: r for r in results}
    misses = []

    for p in preds:
        r = result_map.get(p["race_id"])
        if not r or not r.get("finishing_order") or not p.get("rankings"):
            continue

        actual_rank_map = {f["num"]: f["rank"] for f in r["finishing_order"]}
        pred_rank_map = {h["num"]: h for h in p["rankings"]}

        for finish in r["finishing_order"][:3]:  # 実際の上位3頭
            num = finish["num"]
            actual_rank = finish["rank"]
            pred_horse = pred_rank_map.get(num)
            if not pred_horse:
                continue
            pred_rank = pred_horse["rank"]
            gap = pred_rank - actual_rank
            if gap >= 4:
                # どのファクターが最も寄与していたか
                dominant_error = ""
                factors = pred_horse.get("factors", {})
                if factors:
                    # 最も低いスコアのファクター = 過小評価の主因
                    dominant_error = min(factors, key=factors.get)

                misses.append({
                    "race_id": p["race_id"],
                    "race_name": p.get("race_name", ""),
                    "horse": finish["name"],
                    "num": num,
                    "pred_rank": pred_rank,
                    "actual_rank": actual_rank,
                    "gap": gap,
                    "course_info": p.get("course_info", ""),
                    "style": pred_horse.get("style", ""),
                    "dominant_factor_error": dominant_error,
                })

    return sorted(misses, key=lambda m: m["gap"], reverse=True)


def collect_hypothesis_evidence(preds: list[dict], results: list[dict]) -> list[dict]:
    """既存仮説へのエビデンス収集"""
    hypotheses_path = DATA_DIR / "hypotheses.json"
    if not hypotheses_path.exists():
        return []

    hypotheses = json.loads(hypotheses_path.read_text(encoding="utf-8"))
    result_map = {r["race_id"]: r for r in results}
    evidence = []

    for hyp in hypotheses:
        cond = hyp.get("condition", {})
        for p in preds:
            r = result_map.get(p["race_id"])
            if not r or not r.get("finishing_order"):
                continue

            course = parse_course_info(p.get("course_info", ""))

            # 条件マッチング
            if cond.get("surface") and course["surface"] != cond["surface"]:
                continue
            if cond.get("distance_max") and course["distance"] > cond["distance_max"]:
                continue
            if cond.get("distance_min") and course["distance"] < cond["distance_min"]:
                continue

            # 対象馬を特定（仮説の条件に合致する馬がいるか）
            actual_rank_map = {f["num"]: f["rank"] for f in r["finishing_order"]}
            for horse in p.get("rankings", []):
                # 脚質条件
                if cond.get("running_style") and horse.get("style") not in cond["running_style"]:
                    continue
                # 騎手スコア条件
                factors = horse.get("factors", {})
                if cond.get("jockey_score_min") and factors.get("jockey_score", 0) < cond["jockey_score_min"]:
                    continue

                actual_rank = actual_rank_map.get(horse["num"])
                if actual_rank is None:
                    continue

                gap = horse["rank"] - actual_rank
                # 支持 = 仮説通り過小評価されていた (gap > 0)
                supports = gap >= 2

                evidence.append({
                    "hypothesis_id": hyp["id"],
                    "race_id": p["race_id"],
                    "horse": horse["name"],
                    "pred_rank": horse["rank"],
                    "actual_rank": actual_rank,
                    "supports": supports,
                })
                break  # 1レース1エビデンス

    return evidence


def main():
    parser = argparse.ArgumentParser(description="週次振り返りスクリプト")
    parser.add_argument("--week", "-w", default=None, help="ISO週番号 (YYYY-WNN)")
    parser.add_argument("--dates", default=None, help="日付カンマ区切り (YYYY-MM-DD,YYYY-MM-DD)")
    args = parser.parse_args()

    # 対象日付を決定
    if args.dates:
        dates = [d.strip() for d in args.dates.split(",")]
        week_str = args.week or "custom"
    elif args.week:
        dates = get_week_dates(args.week)
        week_str = args.week
    else:
        week_str = current_week_str()
        dates = get_week_dates(week_str)

    print(f"=== 週次レビュー: {week_str} ({', '.join(dates)}) ===")
    print()

    # データ読み込み
    preds = load_predictions_for_dates(dates)
    results = load_results_for_dates(dates)
    reviews = load_reviews_for_dates(dates)

    if not preds:
        print("対象期間の予想データがありません")
        return

    print(f"予想: {len(preds)}件 / 結果: {len(results)}件 / レビュー: {len(reviews)}件")
    print()

    # 1. サマリー
    summary = compute_summary(preds, results, dates)
    print("--- サマリー ---")
    print(f"  分析: {summary['total_races']}レース (BET: {summary['bet_races']} / PASS: {summary['pass_races']})")
    print(f"  収支: {summary['profit']:+,}円 (投資{summary['total_bet']:,}円 / 回収{summary['total_payout']:,}円)")
    if summary["total_bet"] > 0:
        print(f"  ROI: {summary['roi']:.1%}")
    print(f"  top1的中率: {summary['top1_hit_rate']:.1%} / top1複勝率: {summary['top1_place_rate']:.1%}")
    print(f"  top3重複率: {summary['top3_overlap_rate']:.1%}")
    print()

    # 2. ファクター分析
    factor_analysis = analyze_factors(preds, results)
    if factor_analysis:
        print("--- ファクター誤差 ---")
        for name, data in sorted(factor_analysis.items(), key=lambda x: x[1]["total_errors"], reverse=True):
            print(f"  {name}: 過大{data['overrated']}件 / 過小{data['underrated']}件")
        print()

    # 3. パターン検出
    patterns = detect_patterns(preds, results)
    if patterns:
        print("--- 検出パターン ---")
        for p in patterns:
            print(f"  {p['description']} (信頼度{p['confidence']:.0%})")
        print()

    # 4. 大外し
    big_misses = find_big_misses(preds, results)
    if big_misses:
        print("--- 大外し (gap>=4) ---")
        for m in big_misses[:5]:
            print(f"  {m['race_name']}: {m['horse']} "
                  f"(予想{m['pred_rank']}位→実際{m['actual_rank']}着, gap={m['gap']})")
            if m["dominant_factor_error"]:
                print(f"    主因: {m['dominant_factor_error']}")
        print()

    # 5. 仮説エビデンス
    hyp_evidence = collect_hypothesis_evidence(preds, results)
    if hyp_evidence:
        print("--- 仮説エビデンス ---")
        by_hyp = defaultdict(list)
        for e in hyp_evidence:
            by_hyp[e["hypothesis_id"]].append(e)
        for hid, evs in by_hyp.items():
            supports = sum(1 for e in evs if e["supports"])
            refutes = len(evs) - supports
            print(f"  {hid}: +{supports}支持 / +{refutes}反証")
        print()

    # JSON出力
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    output = {
        "period": week_str,
        "dates": dates,
        "summary": summary,
        "factor_analysis": factor_analysis,
        "pattern_signals": patterns,
        "big_misses": big_misses,
        "hypothesis_evidence": hyp_evidence,
    }

    output_path = REVIEWS_DIR / f"{week_str}_weekly_review.json"
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"保存: {output_path}")


if __name__ == "__main__":
    main()
