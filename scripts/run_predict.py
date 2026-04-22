#!/usr/bin/env python3
"""自動予想スクリプト - 指定日の全レースをスコアリングしてBET/PASS判定する

使い方:
  python3 scripts/run_predict.py                        # 今日の全開催
  python3 scripts/run_predict.py --date 20260425        # 日付指定
  python3 scripts/run_predict.py --venue 東京           # 会場指定
  python3 scripts/run_predict.py --model models/exp_h001_front_bias.json  # モデル指定
"""

import sys
import os
import json
import argparse
from datetime import datetime
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper import NetkeibaScraper
from predictor import calculate_scores, load_model_config, scores_to_text
from strategy import decide, format_decision
from tracker import PredictionRecord, save_prediction
from bankroll import format_status, calc_position_size


def find_race_ids(scraper, date, venue_filter=""):
    """指定日のレース一覧をrace_list_subから取得"""
    import requests
    from bs4 import BeautifulSoup
    import re

    resp = scraper.session.get(
        "https://race.netkeiba.com/top/race_list_sub.html",
        params={"kaisai_date": date},
        timeout=30,
    )
    resp.encoding = "euc-jp"
    soup = BeautifulSoup(resp.text, "html.parser")

    venue_codes = {
        "札幌": "01", "函館": "02", "福島": "03", "新潟": "04",
        "東京": "05", "中山": "06", "中京": "07", "京都": "08",
        "阪神": "09", "小倉": "10",
    }
    venue_code = venue_codes.get(venue_filter, "")

    races = []
    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        # shutuba（未確定）と result（確定済み）の両方を取得
        if "shutuba" not in href and "result" not in href:
            continue
        rid_m = re.search(r"race_id=(\w+)", href)
        if not rid_m:
            continue
        rid = rid_m.group(1)
        text = link.get_text(strip=True)

        # 会場フィルタ
        if venue_code and len(rid) >= 6 and rid[4:6] != venue_code:
            continue

        # レース番号を抽出
        race_num_m = re.search(r"(\d+)R", text)
        race_num = int(race_num_m.group(1)) if race_num_m else 0

        # 重複除去（result と shutuba で同じrace_idが出る）
        if not any(r["race_id"] == rid for r in races):
            races.append({
                "race_id": rid,
                "race_number": race_num,
                "text": text,
            })

    return sorted(races, key=lambda r: r["race_id"])


def inject_odds_from_shutuba(scraper, race):
    """出馬表ページからオッズを取得して注入（スクレイパーで取れない場合の補完）"""
    # scraper.get_race_entries で既にオッズが入っている場合はスキップ
    has_odds = any(e.odds for e in race.entries)
    if has_odds:
        return


def run_prediction(scraper, race_id, date, model_config, model_name):
    """1レースの予想を実行"""
    # 出馬表取得
    race = scraper.get_race_entries(race_id)
    if not race.entries:
        return None

    # 過去成績取得
    for entry in race.entries:
        if entry.horse_id:
            entry.history = scraper.get_horse_history(entry.horse_id, limit=5)

    # 騎手成績取得
    jockey_cache = {}
    jockey_ids = {e.jockey_id for e in race.entries if e.jockey_id}
    for jid in jockey_ids:
        stats = scraper.get_jockey_stats(jid)
        if stats:
            jockey_cache[jid] = stats
    for entry in race.entries:
        if entry.jockey_id in jockey_cache:
            entry.jockey_stats = jockey_cache[entry.jockey_id]

    # スコアリング
    scores = calculate_scores(race, model_config=model_config)

    # BET/PASS判定
    decision = decide(scores, race.entries, race_id=race_id, race_name=race.race_name)

    # 予想記録
    record = PredictionRecord(
        date=datetime.strptime(date, "%Y%m%d").strftime("%Y-%m-%d"),
        race_id=race_id,
        race_name=race.race_name or "",
        venue=race.venue or "",
        course_info=race.course_info or "",
        head_count=race.head_count,
        verdict=decision.verdict,
        confidence=decision.confidence,
        verdict_reason=decision.reason,
        model_version=model_config.get("version", "v1.0"),
        rankings=[
            {
                "rank": i + 1,
                "num": s.horse_number,
                "name": s.horse_name,
                "score": round(s.total_score, 1),
                "ev": round(s.expected_value, 2),
                "style": s.running_style,
            }
            for i, s in enumerate(scores)
        ],
        bets=[
            {
                "type": b.bet_type,
                "selections": b.selections,
                "amount": b.amount,
                "reason": b.reason,
            }
            for b in decision.bets
        ],
    )

    # モデル名をファイル名に含めて保存（実験モデルは別ファイル）
    if model_name != "official":
        from pathlib import Path
        from tracker import PREDICTIONS_DIR, _ensure_dirs
        _ensure_dirs()
        path = PREDICTIONS_DIR / f"{record.date}_{race_id}_{model_name}.json"
        from dataclasses import asdict
        path.write_text(
            json.dumps(asdict(record), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    else:
        save_prediction(record)

    return {
        "race_id": race_id,
        "race_name": race.race_name,
        "venue": race.venue,
        "head_count": race.head_count,
        "verdict": decision.verdict,
        "confidence": decision.confidence,
        "reason": decision.reason,
        "top3": [(s.horse_number, s.horse_name, s.total_score) for s in scores[:3]],
        "bet_count": len(decision.bets),
        "total_amount": decision.total_amount,
        "model": model_name,
    }


def main():
    parser = argparse.ArgumentParser(description="自動予想スクリプト")
    parser.add_argument("--date", "-d", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--venue", "-v", default="", help="会場フィルタ (空=全会場)")
    parser.add_argument("--model", "-m", default=None,
                        help="モデルコンフィグJSONパス (デフォルト: 全モデル実行)")
    parser.add_argument("--official-only", action="store_true",
                        help="正モデルのみ実行")
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent
    models_dir = project_root / "models"

    # モデル一覧を取得
    if args.model:
        model_path = Path(args.model).resolve()
        if not str(model_path).startswith(str(models_dir.resolve())):
            print(f"[ERROR] Model path must be within models/ directory")
            sys.exit(1)
        model_files = [model_path]
    elif args.official_only:
        model_files = [models_dir / "official.json"]
    else:
        model_files = sorted(models_dir.glob("*.json"))

    models = []
    for mf in model_files:
        mc = load_model_config(str(mf))
        models.append((mf.stem, mc))

    print(f"=== 予想実行: {args.date} ===")
    print(f"モデル数: {len(models)} ({', '.join(n for n, _ in models)})")
    print(f"会場: {args.venue or '全会場'}")
    print()

    # 資金状況
    print(format_status())
    print()

    scraper = NetkeibaScraper(delay=args.delay)

    # レース一覧取得
    races = find_race_ids(scraper, args.date, args.venue)
    print(f"対象レース: {len(races)}レース")
    print()

    # 各レースを各モデルで予想
    summary = []
    for race_info in races:
        rid = race_info["race_id"]
        print(f"--- {race_info['text']} ({rid}) ---")

        for model_name, model_config in models:
            result = run_prediction(scraper, rid, args.date, model_config, model_name)
            if result:
                tag = "[OFFICIAL]" if model_config.get("is_official") else "[EXP]"
                verdict_mark = "BET" if result["verdict"] == "BET" else "PASS"
                print(
                    f"  {tag} {model_name}: {verdict_mark} "
                    f"({result['confidence']}) "
                    f"TOP: {result['top3'][0][1]}({result['top3'][0][2]:.1f})"
                )
                if result["verdict"] == "BET":
                    print(f"    → {result['bet_count']}点 {result['total_amount']:,}円")
                summary.append(result)

        print()

    # サマリー
    print("=" * 50)
    print("サマリー")
    print("=" * 50)
    official_bets = [s for s in summary
                     if s["model"] == "official" and s["verdict"] == "BET"]
    official_passes = [s for s in summary
                       if s["model"] == "official" and s["verdict"] == "PASS"]
    print(f"正モデル: BET {len(official_bets)}レース / PASS {len(official_passes)}レース")
    total_invest = sum(s["total_amount"] for s in official_bets)
    print(f"合計投資予定: {total_invest:,}円")

    for s in official_bets:
        print(f"  {s['venue']} {s['race_name']}: {s['bet_count']}点 {s['total_amount']:,}円")

    # 実験モデルとの差分
    for model_name, _ in models:
        if model_name == "official":
            continue
        exp_bets = [s for s in summary
                    if s["model"] == model_name and s["verdict"] == "BET"]
        if exp_bets:
            print(f"\n実験モデル [{model_name}]: BET {len(exp_bets)}レース")

    return summary


if __name__ == "__main__":
    main()
