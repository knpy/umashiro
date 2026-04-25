---
name: cycle
description: 予想サイクルのナビゲーター。現在の状態を確認し、次にやるべきステップを案内・実行する。
---

# /cycle — 予想サイクル ナビゲーター

あなたは競馬予想サイクルのナビゲーターとして、現在の状態を確認し、次に実行すべきステップをユーザーに案内する。

## サイクルの全体像

```
/predict   → 予想生成（土日AM）
/collect   → 結果照合・精算（土日PM、レース終了後）
/review    → 週次振り返り分析（日曜夜）
/knowledge → 仮説検証・モデル反映（月初）
```

## 実行手順

### 1. 状態確認

以下のコマンドで現在の状態を把握する:

```bash
# 今日の日付
date "+%Y-%m-%d (%a)"

# 直近の予想ファイル
ls -lt data/predictions/ 2>/dev/null | head -10

# 直近の結果ファイル
ls -lt data/results/ 2>/dev/null | head -10

# 直近の週次レビュー
ls -lt data/reviews/ 2>/dev/null | head -5

# 現在のバンクロール状態
python3 -c "from bankroll import format_status; print(format_status())" 2>/dev/null

# 仮説パイプライン状態
python3 -c "
import json; from pathlib import Path
h = Path('data/hypotheses.json')
if h.exists():
    data = json.loads(h.read_text())
    by_status = {}
    for x in data:
        by_status.setdefault(x['status'], []).append(x['id'])
    for s, ids in by_status.items():
        print(f\"  {s}: {len(ids)}件 ({', '.join(ids)})\")
else:
    print('  hypotheses.json未作成')
" 2>/dev/null
```

### 2. 判定ロジック

確認した状態に基づいて、以下の優先順で次のアクションを案内する:

1. **開催日で、今日の予想がまだない**（`data/predictions/` に今日の日付のファイルがない）→ `/predict` を案内
2. **今日の予想はあるが、結果がまだない**（`data/results/` に対応ファイルがない、かつ16:30以降）→ `/collect` を案内
3. **直近のcollectが完了していて、該当週の週次レビューがまだない** → `/review` を案内
4. **月末（25日以降）で、今月の週次レビューが2件以上ある** → `/knowledge` を案内
5. **すべて最新** → 現在の状態サマリーを表示して終了

### 3. 出力フォーマット

```
## サイクル状態

| ステップ | 最終実行 | 状態 |
|----------|----------|------|
| predict  | YYYY-MM-DD | OK / 未実行 |
| collect  | YYYY-MM-DD | OK / 未実行 |
| review   | YYYY-WNN   | OK / 未実行 |
| knowledge| YYYY-MM    | OK / 未実行 |

## 次のアクション

→ `/collect` を実行してください（理由: 本日の予想は完了済み、レース終了後です）
```

### 4. ユーザーが「実行して」と言った場合

該当するスキル（/predict, /collect, /review, /knowledge）を呼び出す。
