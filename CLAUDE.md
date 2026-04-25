# keiba-0418 — 競馬予想エージェント

## プロジェクト概要

中央競馬の自動予想・収支管理システム。netkeiba.comからデータを取得し、11要素のマルチファクタースコアリングで予想を生成する。Python 3 + requests + BeautifulSoup + Rich。DBレス設計（JSON + Markdown）。

## コマンド

```bash
# 予想実行（メインエントリポイント）
python3 main.py -v 東京 -n 11          # 東京11Rを分析
python3 main.py -v 中山 -a             # 中山全レース
python3 main.py -r 202606030811        # race_id直接指定
python3 main.py --no-grok              # Grok連携なし

# スクリプト経由
python3 scripts/run_predict.py         # 全開催の予想
python3 scripts/run_collect.py         # 結果収集

# バックテスト用
python3 scripts/collect_history.py     # 過去データ収集 → data/history.db
python3 scripts/run_base_time.py       # ベースタイム算出

# 依存インストール
pip install -r requirements.txt
```

## 主要モジュールの役割

| ファイル | 役割 |
|---------|------|
| `main.py` | CLI + マルチステップClaude分析（展開→期待値→最終予想） |
| `scraper.py` | netkeiba.comスクレイピング（出馬表・過去成績・騎手成績） |
| `predictor.py` | 11要素スコアリングエンジン（`HorseScore`を返す） |
| `strategy.py` | BET/PASS判定 + 買い目生成（`BetDecision`を返す） |
| `bankroll.py` | 資金管理・ポジションサイジング |
| `analyzer.py` | レポート生成（`build_report()`） |
| `grok_client.py` | Grok API経由のX予想収集 |
| `tracker.py` | 予想/結果/振り返りの記録管理 |

## 重要な設計判断

- **スコアリングウェイトは `models/official.json` で管理**。コード内にハードコードしない
- **仮説検証は `knowledge/` ディレクトリで管理**。hypotheses.md → validated.md → changelog.md の流れ
- **実験モデルは `models/exp_*.json`** で管理。30サンプル+70%支持率で正モデルへ昇格
- **Grok連携はオプショナル**。XAI_API_KEY未設定時はスキップされる

## 環境変数

- `XAI_API_KEY` — Grok API用（任意。未設定時はX予想収集をスキップ）
- `.env` ファイルで管理。NEVER commit `.env`

## データの扱い

- `data/` 配下は gitignore対象（収支・馬券記録は機密）
- `reports/` 配下も gitignore対象
- `models/` と `knowledge/` はgit管理対象

## Git ワークフロー

- ブランチ命名: `feature/`, `security/`, `bugfix/` プレフィックス
- mainブランチへの直接コミット禁止
- コミットメッセージ: Conventional Commits形式

## よくあるハマりどころ

- scraper.pyのdelay引数（デフォルト1.0秒）を短くしすぎるとnetkeiba.comからブロックされる
- race_idは12桁の数値文字列（例: `202506030811`）。形式を間違えるとスクレイピングが空データを返す
- `main.py` の Claude分析（`_call_claude`）は `claude -p` をサブプロセスで呼ぶため、claude CLIがPATHに必要
