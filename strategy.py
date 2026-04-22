"""賭ける/見送りの判断ルールとベットプラン生成"""

from dataclasses import dataclass, field
from predictor import HorseScore


@dataclass
class BetDecision:
    """1レースの賭け判断"""
    race_id: str = ""
    race_name: str = ""
    verdict: str = ""          # "BET" or "PASS"
    confidence: str = ""       # A/B/C/D
    reason: str = ""           # 判断理由
    bets: list = field(default_factory=list)  # BetPlanのリスト
    total_amount: int = 0


@dataclass
class BetPlan:
    """個別の馬券プラン"""
    bet_type: str = ""         # 単勝/馬連/ワイド/三連複/三連単
    selections: str = ""       # "7" or "7-12" or "7-12-13"
    amount: int = 0            # 金額
    ev: float = 0.0            # 主軸のEV
    reason: str = ""


# ============================================================================
# 判断基準（凍結して運用、月次レビューで更新）
# ============================================================================

# 賭けるための最低条件
MIN_CONFIDENCE = "B"           # C, D は見送り
MIN_PRIMARY_EV = 1.3           # 主軸馬のEV閾値
MIN_HISTORY_RACES = 3          # 各馬の最低過去走数
MIN_SCORED_HORSES = 8          # スコアリング可能な最低頭数

# 自信度判定の閾値
CONFIDENCE_THRESHOLDS = {
    "A": {"score_diff_1_2": 5.0, "primary_ev_min": 1.0},
    "B": {"score_diff_1_3": 5.0},
    "C": {"score_diff_1_5_max": 8.0},
    # D: 上記いずれにも該当しない
}


def assess_confidence(scores: list[HorseScore]) -> str:
    """
    自信度を判定する

    A(堅い): 1位と2位のスコア差>5点、かつ1位のEV>=1.0
    B(やや自信): 1位と3位のスコア差>5点
    C(混戦): 1位と5位のスコア差<8点
    D(難解): それ以外
    """
    if len(scores) < 5:
        return "D"

    diff_1_2 = scores[0].total_score - scores[1].total_score
    diff_1_3 = scores[0].total_score - scores[2].total_score
    diff_1_5 = scores[0].total_score - scores[4].total_score

    if diff_1_2 > 5.0 and scores[0].expected_value >= 1.0:
        return "A"
    if diff_1_3 > 5.0:
        return "B"
    if diff_1_5 < 8.0:
        return "C"
    return "D"


def check_data_quality(scores: list[HorseScore], entries) -> tuple[bool, str]:
    """
    データ品質チェック
    Returns: (OK?, 理由)
    """
    if len(scores) < MIN_SCORED_HORSES:
        return False, f"スコアリング可能馬が{len(scores)}頭 (最低{MIN_SCORED_HORSES}頭)"

    # 過去走データが不足している馬の数
    low_data = 0
    for entry in entries:
        if len(entry.history) < MIN_HISTORY_RACES:
            low_data += 1

    # 上位5頭にデータ不足馬がいたら厳しい
    top5_numbers = {s.horse_number for s in scores[:5]}
    top5_low = sum(1 for e in entries
                   if e.horse_number in top5_numbers
                   and len(e.history) < MIN_HISTORY_RACES)

    if top5_low >= 2:
        return False, f"上位5頭中{top5_low}頭がデータ不足"

    return True, "OK"


def decide(scores: list[HorseScore], entries, race_id: str = "",
           race_name: str = "") -> BetDecision:
    """
    スコアリング結果から賭ける/見送りを判断する

    Returns: BetDecision
    """
    decision = BetDecision(race_id=race_id, race_name=race_name)

    # 1. 自信度判定
    confidence = assess_confidence(scores)
    decision.confidence = confidence

    # 2. データ品質チェック
    data_ok, data_reason = check_data_quality(scores, entries)

    # 3. 主軸馬のEV確認
    primary = scores[0]
    primary_ev = primary.expected_value

    # 4. 判断
    reasons = []

    if confidence in ("C", "D"):
        decision.verdict = "PASS"
        reasons.append(f"自信度{confidence}(閾値: {MIN_CONFIDENCE}以上)")

    if not data_ok:
        decision.verdict = "PASS"
        reasons.append(data_reason)

    if primary_ev > 0 and primary_ev < MIN_PRIMARY_EV:
        decision.verdict = "PASS"
        reasons.append(f"主軸EV={primary_ev:.2f}(閾値: {MIN_PRIMARY_EV}以上)")

    if primary_ev == 0:
        # オッズデータなし → EVが計算できない → 判断保留
        reasons.append("オッズ未取得のためEV判定不可")

    if not reasons:
        decision.verdict = "BET"
        reasons.append(f"自信度{confidence}, 主軸EV={primary_ev:.2f}")

    decision.reason = " / ".join(reasons)

    # 5. BETの場合、買い目を生成
    if decision.verdict == "BET":
        decision.bets = generate_bet_plan(scores, confidence)
        decision.total_amount = sum(b.amount for b in decision.bets)

    return decision


def generate_bet_plan(scores: list[HorseScore], confidence: str,
                      bankroll: int = 1_000_000) -> list[BetPlan]:
    """
    スコアとEVに基づいて買い目を生成する

    ルール:
    - 1レース上限: bankrollの3%
    - 軸: スコア1位かつEV>=1.0
    - 相手: EV>=0.8かつスコア上位8位以内
    """
    max_per_race = int(bankroll * 0.03)
    bets = []

    primary = scores[0]

    # EV>=1.0の馬をバリュー馬として抽出
    value_horses = [s for s in scores if s.expected_value >= 1.0]
    # スコア上位8位かつEV>=0.8の馬を相手候補
    partners = [s for s in scores[:8] if s.expected_value >= 0.8
                and s.horse_number != primary.horse_number]

    # --- 単勝 ---
    if primary.expected_value >= 1.5:
        amount = min(int(max_per_race * 0.25), 7000)
        bets.append(BetPlan(
            bet_type="単勝",
            selections=primary.horse_number,
            amount=amount,
            ev=primary.expected_value,
            reason=f"EV={primary.expected_value:.2f}",
        ))
    elif primary.expected_value >= 1.3:
        amount = min(int(max_per_race * 0.15), 5000)
        bets.append(BetPlan(
            bet_type="単勝",
            selections=primary.horse_number,
            amount=amount,
            ev=primary.expected_value,
            reason=f"EV={primary.expected_value:.2f}",
        ))

    # --- 馬連 (軸-相手) ---
    for p in partners[:3]:
        amount = min(int(max_per_race * 0.12), 4000)
        bets.append(BetPlan(
            bet_type="馬連",
            selections=f"{primary.horse_number}-{p.horse_number}",
            amount=amount,
            ev=primary.expected_value,
            reason=f"軸EV={primary.expected_value:.2f}, 相手EV={p.expected_value:.2f}",
        ))

    # --- ワイド (バリュー馬絡み) ---
    # EV>=1.2の穴馬（人気7番以下）がいれば
    value_longshots = [s for s in value_horses
                       if s.horse_number != primary.horse_number
                       and _parse_int(s.odds) >= 10.0]
    for vl in value_longshots[:2]:
        amount = min(int(max_per_race * 0.08), 3000)
        bets.append(BetPlan(
            bet_type="ワイド",
            selections=f"{primary.horse_number}-{vl.horse_number}",
            amount=amount,
            ev=vl.expected_value,
            reason=f"穴馬EV={vl.expected_value:.2f}",
        ))

    # --- 三連複 (軸1頭流し) ---
    if len(partners) >= 2:
        # 相手上位から組み合わせ（最大6点）
        tri_partners = partners[:4]
        tri_count = 0
        for i in range(len(tri_partners)):
            for j in range(i + 1, len(tri_partners)):
                if tri_count >= 6:
                    break
                nums = sorted([primary.horse_number,
                               tri_partners[i].horse_number,
                               tri_partners[j].horse_number])
                amount = min(int(max_per_race * 0.06), 2000)
                bets.append(BetPlan(
                    bet_type="三連複",
                    selections="-".join(nums),
                    amount=amount,
                    ev=primary.expected_value,
                    reason=f"軸{primary.horse_number}流し",
                ))
                tri_count += 1

    # 合計金額がmax_per_raceを超えたら按分で縮小
    total = sum(b.amount for b in bets)
    if total > max_per_race:
        ratio = max_per_race / total
        for b in bets:
            b.amount = max(100, int(b.amount * ratio / 100) * 100)

    return bets


def _parse_int(s) -> float:
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def format_decision(decision: BetDecision) -> str:
    """判断結果を表示用テキストに変換"""
    lines = []
    lines.append(f"{'=' * 50}")

    if decision.verdict == "BET":
        lines.append(f"  判定: BET (自信度: {decision.confidence})")
    else:
        lines.append(f"  判定: PASS (自信度: {decision.confidence})")

    lines.append(f"  理由: {decision.reason}")

    if decision.bets:
        lines.append(f"")
        lines.append(f"  買い目 ({len(decision.bets)}点, 合計{decision.total_amount:,}円):")
        lines.append(f"  {'券種':<6} {'買い目':<12} {'金額':>8} {'理由'}")
        lines.append(f"  {'-' * 50}")
        for b in decision.bets:
            lines.append(
                f"  {b.bet_type:<6} {b.selections:<12} {b.amount:>7,}円  {b.reason}"
            )

    lines.append(f"{'=' * 50}")
    return "\n".join(lines)
