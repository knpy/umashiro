"""収集データ + 統計スコア + X予想をまとめてレポート出力する（API不要）"""

from scraper import RaceInfo
from predictor import HorseScore, scores_to_text
from grok_client import grok_result_to_text
from typing import Optional


def build_report(
    race: RaceInfo,
    stat_scores: Optional[list[HorseScore]] = None,
    grok_result: Optional[dict] = None,
) -> str:
    """全情報を統合したMarkdownレポートを生成する"""
    sections = []

    # ヘッダー
    sections.append(f"# {race.race_number}R {race.race_name}")
    sections.append("")
    sections.append(f"| 項目 | 内容 |")
    sections.append(f"|------|------|")
    course_info = race.course_info.replace("\n", " ").replace("\r", " ").strip()
    sections.append(f"| コース | {course_info} |")
    sections.append(f"| 発走 | {race.start_time} |")
    sections.append(f"| 出走 | {race.head_count}頭 |")
    sections.append("")
    sections.append("---")

    # Layer 1: 統計スコア
    if stat_scores:
        sections.append("")
        sections.append(scores_to_text(stat_scores))

    # Layer 2: X予想
    if grok_result and "error" not in grok_result:
        sections.append("")
        sections.append(grok_result_to_text(grok_result))

    # Layer 3: 生データ
    sections.append("")
    sections.append("---")
    sections.append("")
    sections.append("## 出馬表・過去成績")
    sections.append("")
    for entry in race.entries:
        sections.append(f"### {entry.horse_number}番 {entry.horse_name}")
        sections.append("")
        sections.append(f"| 枠 | 性齢 | 斤量 | 騎手 | 調教師 | オッズ | 人気 | 馬体重 |")
        sections.append(f"|:--:|:----:|:----:|:----:|:------:|:------:|:----:|:------:|")
        jockey_extra = ""
        if entry.jockey_stats:
            js = entry.jockey_stats
            jockey_extra = f" ({js.get('starts',0)}走 勝率{js.get('win_rate',0):.1%})"
        sections.append(
            f"| {entry.frame_number} | {entry.sex_age} | {entry.weight_carried} "
            f"| {entry.jockey}{jockey_extra} | {entry.trainer} "
            f"| {entry.odds or '-'} | {entry.popularity or '-'} | {entry.horse_weight or '-'} |"
        )
        sections.append("")

        if entry.history:
            sections.append("**近走成績**")
            sections.append("")
            sections.append("| 日付 | 会場 | レース名 | 距離/馬場 | 頭数 | 着順 | タイム | 上がり3F | 通過 | 体重 | 騎手 |")
            sections.append("|------|------|----------|:---------:|:----:|:----:|:------:|:--------:|:----:|:----:|:----:|")
            for h in entry.history:
                sections.append(
                    f"| {h.date} | {h.venue} | {h.race_name} "
                    f"| {h.distance}{h.track_condition} "
                    f"| {h.head_count} | {h.finish_position} "
                    f"| {h.time} | {h.last_3f} "
                    f"| {h.passing} | {h.horse_weight} "
                    f"| {h.jockey} |"
                )
        else:
            sections.append("**近走成績**: データなし")
        sections.append("")

    return "\n".join(sections)
