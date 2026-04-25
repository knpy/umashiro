"""過去レースデータからスコアを再構築する"""

from scraper import RaceInfo, HorseEntry, HorseResult
from predictor import calculate_scores, HorseScore
from backtest.database import HistoryDB


def _row_to_horse_result(row: dict) -> HorseResult:
    """DB の race_horses 行を HorseResult に変換する"""
    return HorseResult(
        date=row.get("date", ""),
        venue=row.get("venue", ""),
        race_name=row.get("race_name", ""),
        head_count=str(row.get("head_count", "")),
        frame_number=row.get("frame_number", ""),
        horse_number=row.get("horse_number", ""),
        odds=str(row.get("odds", "")),
        popularity=str(row.get("popularity", "")),
        finish_position=str(row.get("finish_position", "")),
        jockey=row.get("jockey", ""),
        weight_carried=row.get("weight_carried", ""),
        distance=f"{row.get('surface', '')}{row.get('distance', '')}",
        track_condition=row.get("track_condition", ""),
        time=row.get("time_str", ""),
        margin="",
        passing=row.get("passing", ""),
        last_3f=str(row.get("last_3f", "")),
        horse_weight=row.get("horse_weight", ""),
        winner="",
    )


def build_pseudo_entries(db: HistoryDB, race_data: dict) -> list[HorseEntry]:
    """1レース分のDB行から HorseEntry リスト（疑似ヒストリー付き）を構築する。"""
    race_date = race_data["date"]
    entries = []
    for h in race_data.get("horses", []):
        entry = HorseEntry(
            frame_number=h.get("frame_number", ""),
            horse_number=h.get("horse_number", ""),
            horse_name=h.get("horse_name", ""),
            horse_id=h.get("horse_id", ""),
            odds=str(h.get("odds", "")) if h.get("odds") is not None else "",
            popularity=str(h.get("popularity", "")) if h.get("popularity") is not None else "",
            horse_weight=h.get("horse_weight", ""),
            jockey=h.get("jockey", ""),
            weight_carried=h.get("weight_carried", ""),
        )
        if entry.horse_id:
            history_rows = db.get_horse_history(entry.horse_id, before_date=race_date, limit=5)
            entry.history = [_row_to_horse_result(r) for r in history_rows]
        else:
            entry.history = []
        entries.append(entry)
    return entries


def build_race_info(race_data: dict, entries: list[HorseEntry]) -> RaceInfo:
    surface = race_data.get("surface", "")
    distance = race_data.get("distance", 0)
    course_info = f"{surface}{distance}" if surface and distance else ""
    return RaceInfo(
        race_id=race_data["race_id"],
        race_number=race_data.get("race_number", 0),
        race_name=race_data.get("race_name", ""),
        course_info=course_info,
        venue=race_data.get("venue", ""),
        head_count=race_data.get("head_count", 0),
        entries=entries,
    )


def reconstruct_scores(db: HistoryDB, race_data: dict,
                       model_config: dict = None,
                       base_times_data: dict = None) -> list[HorseScore]:
    entries = build_pseudo_entries(db, race_data)
    race_info = build_race_info(race_data, entries)
    return calculate_scores(race_info, model_config=model_config,
                           base_times_data=base_times_data)


def get_actual_ranking(race_data: dict) -> dict[str, int]:
    return {
        h["horse_number"]: h["finish_position"]
        for h in race_data.get("horses", [])
        if h.get("finish_position") and h.get("horse_number")
    }
