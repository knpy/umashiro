#!/usr/bin/env python3
"""競馬予想エージェント - データ収集 + スコアリング + X予想収集

使い方:
  python3 main.py                     # 今日の中山全レース一覧
  python3 main.py -n 11               # 中山11Rを分析
  python3 main.py -a                   # 全レース分析
  python3 main.py -r 202606030811     # race_id直接指定
  python3 main.py --no-grok           # Grok連携なし
"""

import os
import sys
import subprocess
import argparse
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box

from scraper import NetkeibaScraper
from predictor import calculate_scores
from analyzer import build_report

load_dotenv()
console = Console()

OUTPUT_DIR = Path(__file__).parent / "reports"

# ============================================================================
# マルチステップ分析プロンプト（GALLOPIA方式）
# 短い専門プロンプトを複数回 > 1つの巨大プロンプト
# ============================================================================

STEP1_PACE_PROMPT = """\
あなたは競馬の展開予想の専門家です。以下のレースデータから展開分析だけを行ってください。

## 参照すべきデータ
- 各馬のスコアリング結果の「脚質」欄（逃げ/先行/差し/追込）
- 近走成績の「通過」欄（序盤のポジション取り傾向）
- コース情報（芝/ダート、距離、会場）
- 枠順バイアススコア（枠有利/枠不利のコメント）

## 分析項目
1. 逃げ馬・先行馬の頭数を数え、ペース予想（ハイ/ミドル/スロー）を判定
   - 逃げ2頭以上 or 先行4頭以上 → ハイペース寄り
   - 逃げ1頭のみ and 先行2頭以下 → スローペース寄り
2. 会場特性（中山=小回り内枠有利、東京=直線長く外差し届く等）と馬場状態から有利な脚質を判定
3. 枠順×脚質で展開利のある馬（3頭以内）を具体的に馬番・馬名で指摘
4. 展開不利になりそうな馬（3頭以内）を具体的に馬番・馬名で指摘

300字以内で簡潔に。

---
"""

STEP2_VALUE_PROMPT = """\
あなたは競馬の期待値分析の専門家です。以下のレースデータから期待値分析だけを行ってください。

## EV（期待値）の算出方法
EVは「実力ベースの推定勝率 × 単勝オッズ」で計算されています。
- 推定勝率: オッズを含まない実力スコア（タイム・上がり・適性等）からソフトマックスで算出
- EV>1.0: オッズに対して実力が過小評価されている（買い得）
- EV<1.0: オッズに対して実力が過大評価されている（買い損）

## 参照すべきデータ
- 「バリューベット候補（期待値順）」セクション
- 各馬のスコア詳細（総合スコア順位 vs 人気順位のギャップ）
- X予想のコンセンサス（支持されている馬）

## 分析項目
1. スコア上位5位以内かつ人気6番以下の馬（＝バリューベット候補）を最大3頭、EV値とともに指摘
2. 人気3番以内かつスコア順位6位以下の馬（＝危険な人気馬）を最大3頭指摘
3. EV>=1.5の馬があれば特に強調
4. X予想で支持されているがスコアが低い馬への警告

250字以内で簡潔に。

---
"""

STEP3_FINAL_PROMPT = """\
あなたは日本競馬の最強予想AIです。以下の専門分析結果とレースデータを統合して最終予想を出してください。

## ルール
- 展開分析と期待値分析の結果を重視しつつ、生データも確認して最終判断
- EVは「実力ベース推定勝率×単勝オッズ」で算出。オッズはスコアに含まれないため、EVが高い馬＝市場に過小評価されている馬
- EV>=1.0の馬を優先。EV>=1.5の馬は積極的に軸候補にする
- 統計スコアとX予想が一致する馬は信頼度が高い

## 混戦度の判断基準
- スコア1位と5位の差が8点未満 → 混戦（三連系の広め買い推奨、点数多めOK）
- スコア1位と2位の差が5点以上 かつ 1位が人気3番以内 → 堅い（馬連・馬単の厚め買い）
- 上記以外 → やや混戦（ワイド・馬連の中穴狙い）

## 自信度の判断基準
- A(堅い): 1位と2位のスコア差>5点、かつ1位のEV>=1.0
- B(やや自信): 1位と3位のスコア差>5点
- C(混戦): 1位と5位のスコア差<8点
- D(難解): 1位と5位のスコア差<5点、またはデータ不足の馬が3頭以上

## 買い目のルール
- 合計点数は最大15点を目安（回収率意識）
- 軸馬はスコア上位かつEV>=1.0の馬から選ぶ
- 相手はEV>=0.8かつスコア上位8位以内から選ぶ
- 三連複には必ず「穴馬枠」を1頭入れる（人気8番以下で、コース実績or展開利がある馬）。大穴はモデルで拾えないため運用でカバーする

## 注意すべきバイアス
- 「昇級初戦」コメントがある馬は下位クラスでの好走実績が過大評価されている可能性がある。割り引いて判断すること
- 逃げ馬でも騎手力が高い場合（リーディング上位騎手）はペース制御で粘れる可能性がある。一律に「逃げ不利」と切らないこと
- 左回り専門の馬が右回り初（またはその逆）の場合はリスク要因として明記すること

## 出力フォーマット

### レース展望
（ペース予想、馬場バイアス、有利な脚質を含めた展望 300字程度）

### 予想ランキング
| 印 | 馬番 | 馬名 | スコア | EV | 評価理由 | リスク |
（◎本命1頭、○対抗1頭、▲単穴1頭、△連下2-3頭、×穴馬枠1頭）

### おすすめ馬券
| 券種 | 買い目 | 点数 | 自信度(1-5) | 理由 |
（期待値ベースで推奨。軸馬のEV値を明記。三連複には穴馬枠を含めること）

### 注目の穴馬
（馬名、推す理由、オッズに対する妙味、EV値）

### 危険な人気馬
（馬名、スコア順位と人気順位のギャップ、人気ほど信頼できない理由。昇級初戦の馬は特に注意）

### 予想自信度: A / B / C / D（上記基準に基づき判定、根拠を1行で）

---
"""


def save_report(report: str, race_id: str, date: str):
    """レポートをファイルに保存"""
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"{date}_{race_id}.md"
    path.write_text(report, encoding="utf-8")
    return path


def display_scores_table(scores):
    """統計スコアをリッチテーブルで表示"""
    table = Table(
        title="統計スコアリング",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("順位", justify="center", width=4)
    table.add_column("馬番", justify="center", width=4)
    table.add_column("馬名", width=12)
    table.add_column("総合", justify="center", width=5)
    table.add_column("タイム", justify="center", width=5)
    table.add_column("上3F", justify="center", width=5)
    table.add_column("適性", justify="center", width=5)
    table.add_column("展開", justify="center", width=5)
    table.add_column("枠順", justify="center", width=5)
    table.add_column("騎手", justify="center", width=5)
    table.add_column("脚質", justify="center", width=4)
    table.add_column("勝率", justify="center", width=5)
    table.add_column("EV", justify="center", width=5)

    for i, s in enumerate(scores, 1):
        total = f"{s.total_score:.1f}"
        if s.total_score >= 60:
            total = f"[bold red]{total}[/bold red]"
        elif s.total_score >= 55:
            total = f"[yellow]{total}[/yellow]"

        ev = f"{s.expected_value:.2f}"
        if s.expected_value >= 1.5:
            ev = f"[bold red]{ev}[/bold red]"
        elif s.expected_value >= 1.0:
            ev = f"[green]{ev}[/green]"

        table.add_row(
            str(i), s.horse_number, s.horse_name,
            total,
            f"{s.time_index:.1f}", f"{s.last_3f_index:.1f}",
            f"{s.course_fitness:.1f}", f"{s.pace_advantage:.1f}",
            f"{s.gate_bias_score:.1f}", f"{s.jockey_score:.1f}",
            s.running_style,
            f"{s.win_prob:.0%}", ev,
        )

    console.print(table)


def run_single_race(scraper, race_id, date, use_grok=True):
    """1レースを分析してレポート出力"""
    grok_client = None
    if use_grok:
        xai_key = os.environ.get("XAI_API_KEY")
        if xai_key:
            from grok_client import GrokClient
            grok_client = GrokClient(api_key=xai_key)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        # 出馬表取得
        task = progress.add_task("出馬表を取得中...", total=None)
        race = scraper.get_race_entries(race_id)
        progress.update(task, description=f"[green]OK[/green] {race.race_name} ({race.head_count}頭)")
        progress.remove_task(task)

        if not race.entries:
            console.print("[red]出馬表が取得できませんでした。[/red]")
            return None, None

        # 各馬の過去成績取得
        task = progress.add_task("過去成績を取得中...", total=len(race.entries))
        for entry in race.entries:
            progress.update(task, description=f"取得中: {entry.horse_name}")
            if entry.horse_id:
                entry.history = scraper.get_horse_history(entry.horse_id, limit=5)
            progress.advance(task)
        progress.remove_task(task)

        # 騎手成績取得（ユニークな騎手のみ）
        jockey_cache = {}
        jockey_ids = {e.jockey_id for e in race.entries if e.jockey_id}
        if jockey_ids:
            task = progress.add_task("騎手成績を取得中...", total=len(jockey_ids))
            for jid in jockey_ids:
                stats = scraper.get_jockey_stats(jid)
                if stats:
                    jockey_cache[jid] = stats
                progress.advance(task)
            progress.remove_task(task)
            for entry in race.entries:
                if entry.jockey_id in jockey_cache:
                    entry.jockey_stats = jockey_cache[entry.jockey_id]

        # 統計スコアリング
        task = progress.add_task("スコアリング中...", total=None)
        scores = calculate_scores(race)
        progress.update(task, description="[green]OK[/green] スコアリング完了")
        progress.remove_task(task)

        # Grok X予想
        grok_result = None
        if grok_client:
            task = progress.add_task("X予想を収集中 (Grok)...", total=None)
            try:
                grok_result = grok_client.search_predictions(
                    venue="中山", date=date, race_number=race.race_number
                )
                progress.update(task, description="[green]OK[/green] X予想収集完了")
            except Exception as e:
                progress.update(task, description=f"[yellow]SKIP[/yellow] Grok: {e}")
                grok_result = None
            progress.remove_task(task)

    # スコア表示
    console.print()
    display_scores_table(scores)

    # レポート生成 & 保存
    report = build_report(race, stat_scores=scores, grok_result=grok_result)
    path = save_report(report, race_id, date)
    console.print(f"\n[dim]レポート保存: {path}[/dim]")

    return path, report


def _call_claude(prompt: str, timeout: int = 90):
    """claude -p を呼び出して結果を返す"""
    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def run_claude_analysis(report: str):
    """マルチステップでClaude分析を実行（GALLOPIA方式）"""
    console.print("\n[bold magenta]Claude Code で多段階分析中...[/bold magenta]")

    from concurrent.futures import ThreadPoolExecutor, as_completed

    analyses = []

    # Step 1 & 2: 展開分析と期待値分析を並列実行（相互依存なし）
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task1 = progress.add_task("Step 1/3: 展開分析中...", total=None)
        task2 = progress.add_task("Step 2/3: 期待値分析中...", total=None)

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_pace = executor.submit(_call_claude, STEP1_PACE_PROMPT + report)
            future_value = executor.submit(_call_claude, STEP2_VALUE_PROMPT + report)

            pace_result = future_pace.result()
            if pace_result:
                analyses.append(f"## 展開分析結果\n{pace_result}")
                progress.update(task1, description="[green]OK[/green] 展開分析完了")
            else:
                progress.update(task1, description="[yellow]SKIP[/yellow] 展開分析")
            progress.remove_task(task1)

            value_result = future_value.result()
            if value_result:
                analyses.append(f"## 期待値分析結果\n{value_result}")
                progress.update(task2, description="[green]OK[/green] 期待値分析完了")
            else:
                progress.update(task2, description="[yellow]SKIP[/yellow] 期待値分析")
            progress.remove_task(task2)

        # Step 3: 最終統合予想
        task3 = progress.add_task("Step 3/3: 最終予想生成中...", total=None)
        final_input = STEP3_FINAL_PROMPT
        if analyses:
            final_input += "以下は専門エージェントの分析結果です:\n\n"
            final_input += "\n\n".join(analyses)
            final_input += "\n\n---\n以下がレースの生データです:\n\n"
        final_input += report

        final_result = _call_claude(final_input, timeout=120)
        progress.remove_task(task3)

    if final_result:
        console.print(Panel(
            final_result,
            title="[bold green]AI 最終予想（3段階分析）[/bold green]",
            border_style="green",
            padding=(1, 2),
        ))
    else:
        console.print("[yellow]Claude Code の呼び出しに失敗しました。[/yellow]")
        console.print("[dim]レポートファイルを手動でClaude Codeに渡してください。[/dim]")


def main():
    parser = argparse.ArgumentParser(description="競馬予想エージェント")
    parser.add_argument("--date", "-d", default=datetime.now().strftime("%Y%m%d"),
                        help="対象日 (YYYYMMDD, デフォルト: 今日)")
    parser.add_argument("--venue", "-v", default="中山",
                        help="会場名 (デフォルト: 中山)")
    parser.add_argument("--race", "-r", type=str, default=None,
                        help="race_idを直接指定")
    parser.add_argument("--race-number", "-n", type=int, default=None,
                        help="レース番号 (例: 11)")
    parser.add_argument("--all", "-a", action="store_true",
                        help="全レースを分析")
    parser.add_argument("--no-grok", action="store_true",
                        help="Grok連携を無効にする")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="スクレイピング間隔(秒)")
    args = parser.parse_args()

    use_grok = not args.no_grok

    console.print(Panel(
        f"[bold]日付:[/bold] {args.date}\n"
        f"[bold]会場:[/bold] {args.venue}\n"
        f"[bold]Grok:[/bold] {'ON' if use_grok else 'OFF'}",
        title="[bold green]競馬予想エージェント[/bold green]",
        border_style="green",
    ))

    scraper = NetkeibaScraper(delay=args.delay)

    # race_id直接指定
    if args.race:
        path, report = run_single_race(scraper, args.race, args.date, use_grok)
        if report:
            run_claude_analysis(report)
        return

    # レース一覧取得
    console.print(f"\n[cyan]{args.date} {args.venue}のレース一覧を取得中...[/cyan]")
    races = scraper.get_race_list(args.date, venue_filter=args.venue)

    if not races:
        console.print(f"[red]{args.venue}のレースが見つかりません。日付・会場を確認してください。[/red]")
        sys.exit(1)

    # 一覧表示
    list_table = Table(title=f"{args.venue}競馬 レース一覧", box=box.SIMPLE)
    list_table.add_column("No.", justify="center", width=6)
    list_table.add_column("レース名", width=30)
    list_table.add_column("race_id", width=16)
    for r in races:
        list_table.add_row(r["race_number"], r["race_name"], r["race_id"])
    console.print(list_table)

    # レース番号指定
    if args.race_number:
        target = next(
            (r for r in races if r["race_number"].replace("R", "").strip() == str(args.race_number)),
            None,
        )
        if target:
            console.print(f"\n[bold cyan]>>> {target['race_number']} {target['race_name']}[/bold cyan]\n")
            path, report = run_single_race(scraper, target["race_id"], args.date, use_grok)
            if report:
                run_claude_analysis(report)
        else:
            console.print(f"[red]{args.race_number}Rが見つかりません。[/red]")
        return

    # 全レース
    if args.all:
        results = []
        for r in races:
            console.print(f"\n[bold cyan]{'='*50}[/bold cyan]")
            console.print(f"[bold cyan]>>> {r['race_number']} {r['race_name']}[/bold cyan]\n")
            path, report = run_single_race(scraper, r["race_id"], args.date, use_grok)
            if report:
                results.append((r, report))
        console.print(f"\n[green]全{len(results)}レースのデータ収集完了[/green]")
        for r, report in results:
            console.print(f"\n[bold cyan]{'='*50}[/bold cyan]")
            console.print(f"[bold cyan]>>> {r['race_number']} {r['race_name']} の最終予想[/bold cyan]\n")
            run_claude_analysis(report)
        return

    # インタラクティブ
    console.print("\n[dim]-n <番号> でレース指定、-a で全レース分析[/dim]")
    while True:
        try:
            choice = console.input("\n[bold]レース番号 (q=終了): [/bold]")
        except (EOFError, KeyboardInterrupt):
            break
        if choice.lower() in ("q", "quit", "exit"):
            break
        target = next(
            (r for r in races if r["race_number"].replace("R", "").strip() == choice.strip()),
            None,
        )
        if target:
            path, report = run_single_race(scraper, target["race_id"], args.date, use_grok)
            if report:
                run_claude_analysis(report)
        else:
            console.print("[red]該当レースなし[/red]")


if __name__ == "__main__":
    main()
