---
name: collect
description: レース結果を収集し、予想と照合して精算する。的中/不的中の判定とレジャー更新。
argument-hint: [--date YYYY-MM-DD]
---

# /collect — 結果照合・精算

レース終了後に結果を取得し、予想と突き合わせて精算する。

## 前提条件

- 対象日の `/predict` が完了していること
- 全レースが終了していること（通常16:30以降）
- netkeiba.comに結果が反映されていること

## 実行手順

### 1. 予想ファイルの存在確認

```bash
ls data/predictions/ | grep "$(date +%Y-%m-%d)" | head -5
```

予想ファイルがない場合は「先に /predict を実行してください」と案内する。

### 2. 結果収集・精算

```bash
python3 scripts/run_collect.py --date YYYY-MM-DD
```

### 3. 結果確認

```bash
# 生成された結果ファイル
ls data/results/ | grep "$(date +%Y-%m-%d)" | grep -v review

# レビューファイル
ls data/results/ | grep "$(date +%Y-%m-%d)" | grep review

# 本日の収支
python3 -c "
from bankroll import load_ledger, get_current_bankroll
ledger = load_ledger()
today = [e for e in ledger if e['date'] == '$(date +%Y-%m-%d)']
bet = sum(e['amount'] for e in today)
payout = sum(e['payout'] for e in today)
print(f'本日投資: ¥{bet:,}')
print(f'本日回収: ¥{payout:,}')
print(f'本日収支: ¥{payout - bet:,}')
print(f'残高: ¥{get_current_bankroll():,}')
"
```

### 4. 報告フォーマット

```
## 結果照合完了: YYYY-MM-DD

| レース | 判定 | 投資 | 回収 | 収支 | 的中 |
|--------|------|------|------|------|------|
| 5R 葛飾特別 | BET-B | ¥20,000 | ¥35,100 | +¥15,100 | 単勝○ 馬連○ |
| 8R 春風S | BET-A | ¥25,000 | ¥0 | -¥25,000 | 全滅 |

**本日計: 投資¥XX,XXX / 回収¥XX,XXX / 収支¥XX,XXX**
**残高: ¥XXX,XXX (ROI: XX.X%)**
```

### 5. 大外しの記録

BETしたレースで全滅した場合、簡潔にどこが外れたかを報告する:
- モデル1位の実着順
- 実際の1着馬のモデル順位
- 考えられる要因（データから読み取れる範囲で）

これは `/review` での詳細分析の素材になる。
