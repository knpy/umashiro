"""過去データからベースタイムを統計的に算出する"""

import json
import statistics
from pathlib import Path
from backtest.database import HistoryDB


def compute_base_times(db: HistoryDB, min_samples: int = 5) -> dict:
    """
    DB内の勝ち馬タイムから、会場×馬場×距離×馬場状態ごとの基準タイムを算出する。
    """
    stats = db.get_base_time_stats()

    raw = {}
    for row in stats:
        key = (row["venue"], row["surface"], row["distance"], row["track_condition"])
        raw[key] = {"avg": row["avg_time"], "count": row["sample_count"]}

    # 会場別ベースタイム（良馬場基準）
    per_venue = {}
    sample_counts = {}
    for (venue, surface, distance, condition), info in raw.items():
        if condition not in ("良", ""):
            continue
        if info["count"] < min_samples:
            continue
        per_venue.setdefault(venue, {}).setdefault(surface, {})[distance] = round(info["avg"], 1)
        sample_counts[f"{venue}_{surface}_{distance}_良"] = info["count"]

    # グローバルベースタイム（全会場平均）
    global_times = {}
    for (venue, surface, distance, condition), info in raw.items():
        if condition not in ("良", "") or info["count"] < min_samples:
            continue
        global_times.setdefault((surface, distance), []).append(info["avg"])

    global_base = {}
    for (surface, distance), times in global_times.items():
        global_base.setdefault(surface, {})[distance] = round(statistics.mean(times), 1)

    # 馬場状態補正値（会場別）
    condition_adjust = {}
    for venue in per_venue:
        condition_adjust[venue] = {}
        for surface in per_venue[venue]:
            condition_adjust[venue][surface] = {"良": 0.0}
            good_times = per_venue[venue][surface]
            for cond_short in ("稍", "重", "不"):
                deltas = []
                for distance, good_time in good_times.items():
                    for cond_try in (cond_short, cond_short + "重" if cond_short == "稍" else cond_short + "良"):
                        key = (venue, surface, distance, cond_try)
                        if key in raw and raw[key]["count"] >= 3:
                            deltas.append(raw[key]["avg"] - good_time)
                            break
                if deltas:
                    condition_adjust[venue][surface][cond_short] = round(statistics.mean(deltas), 1)

    # グローバル馬場補正値
    global_condition_adjust = {}
    for surface in global_base:
        global_condition_adjust[surface] = {"良": 0.0}
        for cond_short in ("稍", "重", "不"):
            all_deltas = []
            for venue in condition_adjust:
                if surface in condition_adjust[venue] and cond_short in condition_adjust[venue][surface]:
                    all_deltas.append(condition_adjust[venue][surface][cond_short])
            if all_deltas:
                global_condition_adjust[surface][cond_short] = round(statistics.mean(all_deltas), 1)

    return {
        "per_venue": per_venue,
        "global": global_base,
        "condition_adjust": condition_adjust,
        "global_condition_adjust": global_condition_adjust,
        "sample_counts": sample_counts,
    }


def save_base_times(data: dict, path: str = None):
    if path is None:
        path = Path(__file__).parent.parent / "models" / "base_times.json"
    else:
        path = Path(path)
    path.write_text(json.dumps(_convert_keys(data), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_base_times(path: str = None) -> dict:
    if path is None:
        path = Path(__file__).parent.parent / "models" / "base_times.json"
    else:
        path = Path(path)
    if not path.exists():
        return None
    return _restore_keys(json.loads(path.read_text(encoding="utf-8")))


def _convert_keys(obj):
    if isinstance(obj, dict):
        return {str(k): _convert_keys(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_convert_keys(v) for v in obj]
    return obj


def _restore_keys(obj):
    if isinstance(obj, dict):
        restored = {}
        for k, v in obj.items():
            try:
                restored[int(k)] = _restore_keys(v)
            except (ValueError, TypeError):
                restored[k] = _restore_keys(v)
        return restored
    if isinstance(obj, list):
        return [_restore_keys(v) for v in obj]
    return obj
