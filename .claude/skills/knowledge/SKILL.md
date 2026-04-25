---
name: knowledge
description: 仮説の検証・昇格・棄却とモデルへの反映。週次レビューを元に知識を蓄積する。
argument-hint: [--month YYYY-MM]
---

# /knowledge — ナレッジ化

週次レビューの蓄積から仮説を検証・昇格・棄却し、モデルにフィードバックする。

## 前提条件

- 対象月の `/review` が少なくとも2週分完了していること
- `data/reviews/` に週次レビューJSONが存在すること
- `knowledge/hypotheses.md` に仮説が記載されていること

## 実行手順

### 1. 現在の仮説状態を確認

```bash
cat knowledge/hypotheses.md
```

`data/hypotheses.json` がある場合はそちらも確認:
```bash
python3 -c "
import json; from pathlib import Path
h = Path('data/hypotheses.json')
if h.exists():
    for x in json.loads(h.read_text()):
        print(f\"{x['id']}: {x['title']} [{x['status']}] {x['support_count']}/{x['total_samples']}サンプル ({x.get('support_rate', 0):.0%})\")
"
```

### 2. スクリプト実行（存在する場合）

```bash
python3 scripts/run_knowledge.py --month YYYY-MM
```

スクリプトが未作成の場合は、以下の手動プロセスを行う。

### 3. 手動プロセス（スクリプト未作成時）

#### 3a. 週次レビューからエビデンス集約

対象月の `data/reviews/YYYY-WNN_weekly_review.json` を読み込み:
- `hypothesis_evidence` からサンプルを仮説ごとに集計
- `pattern_signals` から新しい仮説候補を抽出

#### 3b. 仮説のサンプル更新

各仮説について:
- total_samples を更新
- support_count / refute_count を更新
- support_rate を再計算

#### 3c. 仮説の評価

| 条件 | アクション |
|------|------------|
| total_samples >= 30 かつ support_rate >= 70% | **昇格** → validated.mdに追記 |
| total_samples >= 30 かつ support_rate < 70% | **棄却** → hypotheses.mdでステータス更新 |
| それ以外 | 検証継続 |

#### 3d. 新仮説の生成

pattern_signalsのうち、既存仮説にマッチしないものについて:
1. 次のH-NNN番号を採番
2. 仮説のフォーマットに沿って記述
3. knowledge/hypotheses.md に追記
4. data/hypotheses.json にも追加（存在する場合）

#### 3e. モデル反映（昇格時のみ）

仮説が昇格した場合:
1. 昇格した仮説の内容に基づき、models/official.json のウェイト調整を**提案**する
2. **ユーザーに確認を取ってから**実際にウェイトを変更する
3. knowledge/changelog.md にバージョンアップを記録

### 4. ファイル更新

更新対象:
- `data/hypotheses.json` — サンプル数・ステータス更新
- `knowledge/hypotheses.md` — JSONから再同期（または手動更新）
- `knowledge/validated.md` — 昇格した仮説を追記
- `knowledge/changelog.md` — モデル変更があれば記録
- `models/official.json` — ウェイト変更があれば更新（要確認）

### 5. 報告フォーマット

```
## ナレッジ更新: YYYY-MM

### 仮説パイプライン

| ID | タイトル | ステータス | サンプル | 支持率 | 変化 |
|----|----------|-----------|---------|--------|------|
| H-001 | ダ短距離×先行×騎手 | 検証中 | 8/30 | 75% | +3 |
| H-002 | 上がり3F馬場補正 | 検証中 | 12/30 | 67% | +5 |
| H-008 | (新規) 差し馬過小評価 | 未検証 | 0/30 | - | new |

### 昇格した仮説
（なし / あれば詳細とモデル変更提案）

### 棄却した仮説
（なし / あれば理由）

### 新規仮説
- H-008: ダ1200m以下での差し馬過小評価（review W17のpattern_signalから）

### モデル変更
（なし / あればchangelog記載内容）
```

### 6. Claudeの役割

- 新仮説の自然言語での記述（pattern_signalから人間が読める仮説文へ）
- 昇格仮説に基づくウェイト調整幅の提案（例: pace_advantage 0.09 → 0.07）
- 棄却理由の解釈（なぜ仮説が支持されなかったか）
- 仮説間の関連性の指摘（H-001とH-006は同じ根本原因では？等）
