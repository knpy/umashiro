#!/usr/bin/env python3
"""ナレッジ化スクリプト - 週次レビューから仮説を更新・昇格・棄却する

使い方:
  python3 scripts/run_knowledge.py                      # 今月
  python3 scripts/run_knowledge.py --month 2026-04      # 月指定
  python3 scripts/run_knowledge.py --status              # 仮説状態の表示のみ
"""

import sys
import json
import argparse
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DATA_DIR = Path(__file__).parent.parent / "data"
REVIEWS_DIR = DATA_DIR / "reviews"
HYPOTHESES_PATH = DATA_DIR / "hypotheses.json"
KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"

REQUIRED_SAMPLES = 30
PROMOTION_THRESHOLD = 0.70


def load_hypotheses() -> list[dict]:
    """仮説JSONを読み込む"""
    if HYPOTHESES_PATH.exists():
        return json.loads(HYPOTHESES_PATH.read_text(encoding="utf-8"))
    return []


def save_hypotheses(hypotheses: list[dict]):
    """仮説JSONを保存"""
    HYPOTHESES_PATH.parent.mkdir(parents=True, exist_ok=True)
    HYPOTHESES_PATH.write_text(
        json.dumps(hypotheses, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_weekly_reviews(month: str = None) -> list[dict]:
    """週次レビューを読み込む"""
    if not REVIEWS_DIR.exists():
        return []
    reviews = []
    for f in sorted(REVIEWS_DIR.glob("*_weekly_review.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        if month:
            # 対象月のレビューのみ
            dates = data.get("dates", [])
            if not any(d.startswith(month) for d in dates):
                continue
        reviews.append(data)
    return reviews


def update_samples(hypotheses: list[dict], reviews: list[dict]) -> dict:
    """週次レビューのhypothesis_evidenceからサンプルを更新"""
    changes = defaultdict(lambda: {"added": 0, "supports": 0, "refutes": 0})

    for review in reviews:
        for ev in review.get("hypothesis_evidence", []):
            hid = ev["hypothesis_id"]
            hyp = next((h for h in hypotheses if h["id"] == hid), None)
            if not hyp:
                continue

            # 重複チェック（同じrace_idのサンプルは追加しない）
            existing_races = {s["race_id"] for s in hyp.get("samples", [])}
            if ev["race_id"] in existing_races:
                continue

            hyp.setdefault("samples", []).append({
                "race_id": ev["race_id"],
                "date": review.get("dates", [""])[0],
                "horse": ev.get("horse", ""),
                "supports": ev["supports"],
            })
            hyp["total_samples"] = len(hyp["samples"])
            hyp["support_count"] = sum(1 for s in hyp["samples"] if s["supports"])
            hyp["support_rate"] = (
                round(hyp["support_count"] / hyp["total_samples"], 3)
                if hyp["total_samples"] > 0 else 0
            )

            changes[hid]["added"] += 1
            if ev["supports"]:
                changes[hid]["supports"] += 1
            else:
                changes[hid]["refutes"] += 1

    return dict(changes)


def evaluate_hypotheses(hypotheses: list[dict]) -> dict:
    """仮説を評価し、昇格/棄却を判定"""
    promotions = []
    rejections = []

    for hyp in hypotheses:
        if hyp["status"] in ("promoted", "rejected"):
            continue
        if hyp["total_samples"] < REQUIRED_SAMPLES:
            continue

        if hyp["support_rate"] >= PROMOTION_THRESHOLD:
            hyp["status"] = "promoted"
            promotions.append(hyp)
        else:
            hyp["status"] = "rejected"
            rejections.append(hyp)

    return {"promotions": promotions, "rejections": rejections}


def generate_candidates(reviews: list[dict], hypotheses: list[dict]) -> list[dict]:
    """週次レビューのpattern_signalsから新仮説候補を生成"""
    existing_patterns = {h.get("pattern_id", "") for h in hypotheses}
    next_id = max((int(h["id"].replace("H-", "")) for h in hypotheses), default=0) + 1

    candidates = []
    for review in reviews:
        for signal in review.get("pattern_signals", []):
            pid = signal.get("pattern_id", "")
            if pid in existing_patterns:
                continue
            existing_patterns.add(pid)

            candidate = {
                "id": f"H-{next_id:03d}",
                "title": signal.get("description", pid),
                "origin_date": review.get("dates", [""])[0],
                "origin_race": "",
                "content": signal.get("description", ""),
                "condition": {},
                "verification": f"パターン '{pid}' の再現性を追跡",
                "required_samples": REQUIRED_SAMPLES,
                "status": "testing",
                "samples": [],
                "total_samples": 0,
                "support_count": 0,
                "support_rate": 0,
                "pattern_id": pid,
            }
            candidates.append(candidate)
            next_id += 1

    return candidates


def sync_hypotheses_md(hypotheses: list[dict]):
    """hypotheses.json → knowledge/hypotheses.md を同期"""
    lines = [
        "# 仮説リスト",
        "",
        "未検証の仮説をここに蓄積する。月次レビューで統計検証し、有意なものを `validated.md` に昇格させる。",
        "",
        "## フォーマット",
        "",
        "```",
        "### H-001: 仮説タイトル",
        "- 起源: YYYY-MM-DD レース名での観察",
        "- 内容: 具体的な仮説",
        "- 検証方法: どうやって確かめるか",
        "- 必要サンプル数: N",
        "- 現在のデータ: X/N (支持/反証)",
        "- ステータス: 未検証 / 検証中 / 棄却 / 昇格",
        "```",
        "",
        "---",
        "",
    ]

    for hyp in hypotheses:
        status_map = {
            "testing": "検証中",
            "promoted": "昇格",
            "rejected": "棄却",
        }
        status = status_map.get(hyp["status"], hyp["status"])

        lines.append(f"### {hyp['id']}: {hyp['title']}")
        lines.append(f"- 起源: {hyp['origin_date']} {hyp.get('origin_race', '')}")
        lines.append(f"- 内容: {hyp['content']}")
        lines.append(f"- 検証方法: {hyp['verification']}")
        lines.append(f"- 必要サンプル数: {hyp['required_samples']}")
        lines.append(f"- 現在のデータ: {hyp['support_count']}/{hyp['total_samples']} "
                      f"(支持{hyp['support_count']})")
        lines.append(f"- ステータス: {status}")
        if hyp["total_samples"] > 0:
            lines.append(f"- 支持率: {hyp['support_rate']:.0%}")
        lines.append("")

    md_path = KNOWLEDGE_DIR / "hypotheses.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def append_validated(promotions: list[dict]):
    """昇格した仮説をvalidated.mdに追記"""
    validated_path = KNOWLEDGE_DIR / "validated.md"
    content = validated_path.read_text(encoding="utf-8") if validated_path.exists() else "# 検証済み仮説\n\n"

    for hyp in promotions:
        content += f"\n### {hyp['id']}: {hyp['title']}\n"
        content += f"- 昇格日: {datetime.now().strftime('%Y-%m-%d')}\n"
        content += f"- サンプル数: {hyp['total_samples']}\n"
        content += f"- 支持率: {hyp['support_rate']:.0%}\n"
        content += f"- 内容: {hyp['content']}\n"
        content += f"- 検証方法: {hyp['verification']}\n"
        content += "\n"

    validated_path.write_text(content, encoding="utf-8")
    return validated_path


def append_changelog(promotions: list[dict], rejections: list[dict]):
    """changelog.mdに記録"""
    changelog_path = KNOWLEDGE_DIR / "changelog.md"
    content = changelog_path.read_text(encoding="utf-8") if changelog_path.exists() else "# モデル変更履歴\n\n"

    today = datetime.now().strftime("%Y-%m-%d")
    entry = f"\n## {today} ナレッジ更新\n\n"
    if promotions:
        entry += "### 昇格\n"
        for h in promotions:
            entry += f"- {h['id']}: {h['title']} ({h['support_rate']:.0%}, n={h['total_samples']})\n"
        entry += "\n"
    if rejections:
        entry += "### 棄却\n"
        for h in rejections:
            entry += f"- {h['id']}: {h['title']} ({h['support_rate']:.0%}, n={h['total_samples']})\n"
        entry += "\n"

    content += entry
    changelog_path.write_text(content, encoding="utf-8")
    return changelog_path


def print_status(hypotheses: list[dict]):
    """仮説パイプラインの状態を表示"""
    print("=== 仮説パイプライン ===")
    print()
    print(f"{'ID':<8} {'タイトル':<40} {'ステータス':<10} {'サンプル':<10} {'支持率':<8}")
    print("-" * 80)

    for hyp in hypotheses:
        status_map = {"testing": "検証中", "promoted": "昇格", "rejected": "棄却"}
        status = status_map.get(hyp["status"], hyp["status"])
        rate = f"{hyp['support_rate']:.0%}" if hyp["total_samples"] > 0 else "-"
        print(f"{hyp['id']:<8} {hyp['title'][:38]:<40} {status:<10} "
              f"{hyp['support_count']}/{hyp['total_samples']:<7} {rate:<8}")

    print()
    testing = sum(1 for h in hypotheses if h["status"] == "testing")
    promoted = sum(1 for h in hypotheses if h["status"] == "promoted")
    rejected = sum(1 for h in hypotheses if h["status"] == "rejected")
    print(f"検証中: {testing} / 昇格: {promoted} / 棄却: {rejected}")


def main():
    parser = argparse.ArgumentParser(description="ナレッジ化スクリプト")
    parser.add_argument("--month", "-m", default=None,
                        help="対象月 (YYYY-MM, デフォルト: 今月)")
    parser.add_argument("--status", "-s", action="store_true",
                        help="仮説状態の表示のみ")
    args = parser.parse_args()

    month = args.month or datetime.now().strftime("%Y-%m")

    hypotheses = load_hypotheses()
    if not hypotheses:
        print("data/hypotheses.json が見つかりません")
        return

    # 状態表示のみ
    if args.status:
        print_status(hypotheses)
        return

    print(f"=== ナレッジ更新: {month} ===")
    print()

    # 1. 週次レビューを読み込み
    reviews = load_weekly_reviews(month)
    print(f"週次レビュー: {len(reviews)}件")

    # 2. サンプル更新
    changes = update_samples(hypotheses, reviews)
    if changes:
        print("\n--- サンプル更新 ---")
        for hid, ch in changes.items():
            print(f"  {hid}: +{ch['added']}件 (支持{ch['supports']} / 反証{ch['refutes']})")

    # 3. 仮説評価
    results = evaluate_hypotheses(hypotheses)
    if results["promotions"]:
        print("\n--- 昇格 ---")
        for h in results["promotions"]:
            print(f"  {h['id']}: {h['title']} ({h['support_rate']:.0%}, n={h['total_samples']})")
    if results["rejections"]:
        print("\n--- 棄却 ---")
        for h in results["rejections"]:
            print(f"  {h['id']}: {h['title']} ({h['support_rate']:.0%}, n={h['total_samples']})")

    # 4. 新仮説候補の生成
    candidates = generate_candidates(reviews, hypotheses)
    if candidates:
        print(f"\n--- 新仮説候補: {len(candidates)}件 ---")
        for c in candidates:
            print(f"  {c['id']}: {c['title']}")
        hypotheses.extend(candidates)

    # 5. 保存
    save_hypotheses(hypotheses)
    print(f"\n保存: {HYPOTHESES_PATH}")

    # 6. Markdown同期
    md_path = sync_hypotheses_md(hypotheses)
    print(f"同期: {md_path}")

    # 7. 昇格/棄却があれば追記
    if results["promotions"]:
        vpath = append_validated(results["promotions"])
        print(f"昇格記録: {vpath}")
    if results["promotions"] or results["rejections"]:
        cpath = append_changelog(results["promotions"], results["rejections"])
        print(f"変更履歴: {cpath}")

    # 8. 最終状態
    print()
    print_status(hypotheses)

    # 9. 昇格があればモデル変更の提案
    if results["promotions"]:
        print("\n" + "=" * 50)
        print("【要確認】昇格した仮説があります。")
        print("models/official.json のウェイト調整を検討してください。")
        print("/knowledge スキルで Claude に調整案を相談できます。")


if __name__ == "__main__":
    main()
