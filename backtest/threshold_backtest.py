"""BET/PASS 閾値のバックテスト"""

from itertools import product

from backtest.database import HistoryDB
from backtest.score_reconstructor import reconstruct_scores, build_pseudo_entries
from backtest.bet_utils import check_bet_result
from strategy import StrategyConfig, decide


def simulate_strategy(db, races, config, model_config=None, base_times_data=None):
    total_races = 0
    bet_races = 0
    pass_races = 0
    total_invested = 0
    total_returned = 0
    bet_type_stats = {}

    for race_data in races:
        if len(race_data.get("horses", [])) < 5:
            continue
        total_races += 1

        scores = reconstruct_scores(db, race_data, model_config=model_config,
                                    base_times_data=base_times_data)
        if not scores:
            pass_races += 1
            continue

        entries = build_pseudo_entries(db, race_data)
        decision = decide(scores, entries, race_id=race_data["race_id"],
                         race_name=race_data.get("race_name", ""), config=config)

        if decision.verdict == "PASS":
            pass_races += 1
            continue

        bet_races += 1
        finishing_order = sorted(
            [{"num": h["horse_number"], "name": h.get("horse_name", ""),
              "rank": h["finish_position"], "odds": h.get("odds", 0)}
             for h in race_data["horses"] if h.get("finish_position")],
            key=lambda x: x["rank"],
        )
        payouts = race_data.get("payouts", {})
        if not payouts:
            payouts = db.get_payouts(race_data["race_id"])

        for bet in decision.bets:
            bet_dict = {"type": bet.bet_type, "selections": bet.selections, "amount": bet.amount}
            result, payout, profit = check_bet_result(bet_dict, payouts, finishing_order)
            total_invested += bet.amount
            total_returned += payout
            stats = bet_type_stats.setdefault(bet.bet_type, {"count": 0, "invested": 0, "returned": 0, "hits": 0})
            stats["count"] += 1
            stats["invested"] += bet.amount
            stats["returned"] += payout
            if result == "win":
                stats["hits"] += 1

    roi = (total_returned / total_invested - 1) if total_invested > 0 else 0.0
    hit_count = sum(s["hits"] for s in bet_type_stats.values())
    total_bets = sum(s["count"] for s in bet_type_stats.values())

    return {
        "total_races": total_races, "bet_races": bet_races, "pass_races": pass_races,
        "total_invested": total_invested, "total_returned": total_returned,
        "profit": total_returned - total_invested, "roi": roi,
        "hit_rate": hit_count / total_bets if total_bets > 0 else 0.0,
        "total_bets": total_bets,
        "bet_type_breakdown": {
            bt: {**s, "roi": (s["returned"] / s["invested"] - 1) if s["invested"] > 0 else 0.0,
                 "hit_rate": s["hits"] / s["count"] if s["count"] > 0 else 0.0}
            for bt, s in bet_type_stats.items()
        },
        "config": {
            "min_confidence": config.min_confidence, "min_primary_ev": config.min_primary_ev,
            "min_top3_ev": config.min_top3_ev, "score_diff_1_2_for_A": config.score_diff_1_2_for_A,
            "score_diff_1_3_for_B": config.score_diff_1_3_for_B,
        },
    }


DEFAULT_GRID = {
    "min_primary_ev": [0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5],
    "min_top3_ev": [1.0, 1.3, 1.5],
    "min_confidence": ["A", "B", "C"],
    "score_diff_1_2_for_A": [3.0, 5.0, 7.0],
    "score_diff_1_3_for_B": [3.0, 5.0, 7.0],
}


def grid_search(db, races, grid=None, model_config=None, base_times_data=None):
    if grid is None:
        grid = DEFAULT_GRID
    keys = list(grid.keys())
    values = [grid[k] for k in keys]
    combinations = list(product(*values))
    print(f"グリッドサーチ: {len(combinations)} 組み合わせ")
    results = []
    for i, combo in enumerate(combinations):
        params = dict(zip(keys, combo))
        config = StrategyConfig(**params)
        if (i + 1) % 10 == 0:
            print(f"\r  [{i+1}/{len(combinations)}]", end="", flush=True)
        result = simulate_strategy(db, races, config, model_config=model_config,
                                   base_times_data=base_times_data)
        results.append(result)
    print()
    return results
