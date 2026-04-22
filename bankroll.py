"""資金管理 - 残高追跡、ポジションサイズ計算、リスク制御"""

import json
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict

LEDGER_PATH = Path(__file__).parent / "data" / "ledger.json"
INITIAL_BANKROLL = 1_000_000

# リスク管理パラメータ（凍結、月次レビューで更新）
MAX_PER_RACE_PCT = 0.03       # 1レース上限: 3%
MAX_PER_DAY_PCT = 0.10        # 1日上限: 10%
DRAWDOWN_THRESHOLD = 0.20     # 月次損失20%で賭け額半減
DRAWDOWN_SCALE = 0.5          # 半減係数


@dataclass
class LedgerEntry:
    """収支台帳の1エントリ"""
    date: str                  # YYYY-MM-DD
    race_id: str
    race_name: str
    bet_type: str              # 単勝/馬連/ワイド/三連複
    selections: str            # "7" or "7-12"
    amount: int                # 賭け金
    result: str                # "win" / "lose" / "refund"
    payout: int = 0            # 払い戻し (0=ハズレ)
    profit: int = 0            # 損益 (payout - amount)
    note: str = ""


def load_ledger() -> list[dict]:
    """台帳を読み込む"""
    if LEDGER_PATH.exists():
        return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    return []


def save_ledger(entries: list[dict]):
    """台帳を保存する"""
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_PATH.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_entry(entry: LedgerEntry):
    """台帳にエントリを追加"""
    entries = load_ledger()
    entries.append(asdict(entry))
    save_ledger(entries)


def add_entries(new_entries: list[LedgerEntry]):
    """台帳に複数エントリを一括追加"""
    entries = load_ledger()
    for e in new_entries:
        entries.append(asdict(e))
    save_ledger(entries)


def get_current_bankroll() -> int:
    """現在の残高を計算"""
    entries = load_ledger()
    balance = INITIAL_BANKROLL
    for e in entries:
        balance += e.get("profit", 0)
    return balance


def get_today_spent(date: str = None) -> int:
    """今日の合計賭け金を取得"""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    entries = load_ledger()
    return sum(e["amount"] for e in entries if e["date"] == date)


def get_month_pnl(year_month: str = None) -> dict:
    """
    月次損益を計算

    Returns: {
        "total_bet": int, "total_payout": int, "profit": int,
        "roi": float, "win_count": int, "lose_count": int,
        "win_rate": float, "race_count": int
    }
    """
    if year_month is None:
        year_month = datetime.now().strftime("%Y-%m")

    entries = load_ledger()
    month_entries = [e for e in entries if e["date"].startswith(year_month)]

    total_bet = sum(e["amount"] for e in month_entries)
    total_payout = sum(e["payout"] for e in month_entries)
    profit = total_payout - total_bet
    win_count = sum(1 for e in month_entries if e["result"] == "win")
    total_count = len(month_entries)

    # レース数（ユニークなrace_id数）
    race_ids = {e["race_id"] for e in month_entries}

    return {
        "year_month": year_month,
        "total_bet": total_bet,
        "total_payout": total_payout,
        "profit": profit,
        "roi": total_payout / total_bet if total_bet > 0 else 0.0,
        "win_count": win_count,
        "lose_count": total_count - win_count,
        "win_rate": win_count / total_count if total_count > 0 else 0.0,
        "bet_count": total_count,
        "race_count": len(race_ids),
    }


def calc_position_size(bankroll: int = None) -> dict:
    """
    現在のバンクロールに基づいてポジションサイズを計算

    Returns: {"max_per_race": int, "max_per_day": int, "scale": float, "note": str}
    """
    if bankroll is None:
        bankroll = get_current_bankroll()

    # 月次ドローダウンチェック
    month_pnl = get_month_pnl()
    month_loss = -month_pnl["profit"] if month_pnl["profit"] < 0 else 0

    scale = 1.0
    note = ""

    if month_loss >= INITIAL_BANKROLL * DRAWDOWN_THRESHOLD:
        scale = DRAWDOWN_SCALE
        note = f"月次損失{month_loss:,}円 >= {DRAWDOWN_THRESHOLD:.0%} → 賭け額{DRAWDOWN_SCALE:.0%}に縮小"

    max_per_race = int(bankroll * MAX_PER_RACE_PCT * scale)
    max_per_day = int(bankroll * MAX_PER_DAY_PCT * scale)

    # 今日の残り枠
    today_spent = get_today_spent()
    remaining_today = max(0, max_per_day - today_spent)

    return {
        "bankroll": bankroll,
        "max_per_race": max_per_race,
        "max_per_day": max_per_day,
        "today_spent": today_spent,
        "remaining_today": remaining_today,
        "scale": scale,
        "note": note,
    }


def format_status() -> str:
    """現在の資金状況を表示用テキストに変換"""
    bankroll = get_current_bankroll()
    pos = calc_position_size(bankroll)
    month = get_month_pnl()

    lines = []
    lines.append(f"残高: {bankroll:>10,}円 (初期: {INITIAL_BANKROLL:,}円)")
    lines.append(f"月次損益: {month['profit']:>+8,}円 (回収率: {month['roi']:.1%})")
    lines.append(f"月次成績: {month['win_count']}勝{month['lose_count']}敗"
                 f" ({month['bet_count']}点/{month['race_count']}レース)")
    lines.append(f"1レース上限: {pos['max_per_race']:>7,}円")
    lines.append(f"本日残り枠:  {pos['remaining_today']:>7,}円"
                 f" (使用済: {pos['today_spent']:,}円)")
    if pos["note"]:
        lines.append(f"[注意] {pos['note']}")

    return "\n".join(lines)
