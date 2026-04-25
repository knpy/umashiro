"""馬券判定ユーティリティ（backtest / run_collect 共用）"""


def check_bet_result(bet, payouts, finishing_order):
    """1つの馬券が的中したか判定

    Args:
        bet: {"type": str, "selections": str, "amount": int}
        payouts: {"単勝": {"selections": str, "payout": int}, ...}
        finishing_order: [{"num": str, "rank": int, ...}, ...] 着順ソート済み

    Returns: (result, payout, profit)
        result: "win" or "lose"
        payout: 払戻金額
        profit: 損益
    """
    bt = bet["type"]
    sel = bet["selections"]

    top3 = [f["num"] for f in finishing_order[:3]]
    top2 = top3[:2]
    top1 = top3[:1]

    sel_nums = sorted(sel.split("-"))

    if bt == "単勝":
        hit = sel_nums == sorted(top1)
    elif bt == "馬連":
        hit = sorted(sel_nums) == sorted(top2)
    elif bt == "ワイド":
        hit = all(n in top3 for n in sel_nums)
    elif bt == "三連複":
        hit = sorted(sel_nums) == sorted(top3)
    elif bt == "馬単":
        hit = sel_nums == top2
    else:
        hit = False

    if hit:
        payout_info = payouts.get(bt, {})
        payout_per_100 = payout_info.get("payout", 0)
        amount = bet["amount"]
        payout = payout_per_100 * amount // 100
        return "win", payout, payout - amount
    else:
        return "lose", 0, -bet["amount"]
