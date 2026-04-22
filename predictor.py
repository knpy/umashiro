"""統計ベースのスコアリングエンジン - 過去成績から各馬のスコアを算出する"""

import re
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from scraper import RaceInfo, HorseEntry, HorseResult


@dataclass
class HorseScore:
    """各馬の統計スコア"""
    horse_number: str = ""
    horse_name: str = ""
    total_score: float = 0.0
    time_index: float = 0.0        # タイム指数
    last_3f_index: float = 0.0     # 上がり3F指数
    stability_index: float = 0.0   # 安定性指数
    course_fitness: float = 0.0    # コース適性
    pace_advantage: float = 0.0    # 展開利
    class_score: float = 0.0       # クラス補正
    form_cycle: float = 0.0        # 調子サイクル
    weight_score: float = 0.0      # 馬体重スコア
    odds_score: float = 0.0        # オッズ評価
    rest_days_score: float = 0.0   # 休養日数スコア
    gate_bias_score: float = 0.0   # 枠順バイアス
    jockey_score: float = 0.0      # 騎手スコア
    running_style: str = ""        # 脚質
    odds: str = ""                 # オッズ（表示用）
    win_prob: float = 0.0          # 推定勝率
    expected_value: float = 0.0    # 期待値
    comment: str = ""              # スコアリングコメント


# ============================================================================
# 基準タイム (距離別・芝/ダート別) - 中山コース基準
# 実際のデータに基づく概算値（秒）
# ============================================================================
BASE_TIMES = {
    "芝": {
        1200: 69.5, 1400: 82.0, 1600: 94.5, 1800: 107.5,
        2000: 120.0, 2200: 133.0, 2400: 146.0, 2500: 152.0, 3600: 222.0,
    },
    "ダ": {
        1200: 72.5, 1400: 85.0, 1600: 97.5, 1700: 104.0, 1800: 111.0,
        1900: 118.5, 2000: 126.0, 2100: 133.5, 2400: 157.0, 2500: 164.0,
    },
}

# 馬場状態補正（秒）
TRACK_CONDITION_ADJUST = {
    "良": 0.0,
    "稍": 0.5,   # 稍重
    "稍重": 0.5,
    "重": 1.5,
    "不": 3.0,   # 不良
    "不良": 3.0,
}

# 頭数補正: 少頭数は速くなりやすい
HEAD_COUNT_ADJUST = {
    range(1, 9): 0.5,
    range(9, 13): 0.0,
    range(13, 15): -0.3,
    range(15, 19): -0.5,
}


def _parse_time(time_str: str):
    """走破タイム文字列を秒に変換 (例: "1:34.2" -> 94.2)"""
    if not time_str or time_str == "":
        return None
    m = re.match(r"(\d+):(\d+)\.(\d+)", time_str)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3)) * 0.1
    m = re.match(r"(\d+)\.(\d+)", time_str)
    if m:
        return int(m.group(1)) + int(m.group(2)) * 0.1
    return None


def _parse_distance(dist_str: str) -> tuple[str, int]:
    """距離文字列をパース (例: "芝1600" -> ("芝", 1600))"""
    m = re.match(r"(芝|ダ)(\d+)", dist_str)
    if m:
        return m.group(1), int(m.group(2))
    return "", 0


def _parse_float(s: str) -> float:
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


# JRA中央競馬の会場リスト
JRA_VENUES = {"札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"}


def _is_obstacle_race(h: HorseResult) -> bool:
    """障害レースかどうかを判定"""
    if "障" in h.distance:
        return True
    if "障害" in h.race_name:
        return True
    return False


def _is_jra_flat_race(h: HorseResult) -> bool:
    """JRA中央の平地レースかどうかを判定"""
    if _is_obstacle_race(h):
        return False
    if h.venue in JRA_VENUES:
        return True
    return False


def _filter_jra_flat(history: list[HorseResult]) -> list[HorseResult]:
    """JRA平地レースのみにフィルタ（タイム比較用）"""
    return [h for h in history if _is_jra_flat_race(h)]


def _filter_flat(history: list[HorseResult]) -> list[HorseResult]:
    """平地レースのみにフィルタ（地方込み、脚質判定等で使用）"""
    return [h for h in history if not _is_obstacle_race(h)]


def _parse_int(s: str) -> int:
    m = re.search(r"(\d+)", str(s))
    return int(m.group(1)) if m else 0


def _get_base_time(surface: str, distance: int) -> float:
    """基準タイムを取得（近い距離で補間）"""
    times = BASE_TIMES.get(surface, BASE_TIMES["芝"])
    if distance in times:
        return times[distance]
    # 補間
    dists = sorted(times.keys())
    if distance <= dists[0]:
        return times[dists[0]]
    if distance >= dists[-1]:
        return times[dists[-1]]
    for i in range(len(dists) - 1):
        if dists[i] <= distance <= dists[i + 1]:
            ratio = (distance - dists[i]) / (dists[i + 1] - dists[i])
            return times[dists[i]] + ratio * (times[dists[i + 1]] - times[dists[i]])
    return 120.0


def _classify_running_style(history: list[HorseResult]) -> str:
    """過去の通過順位から脚質を判定（平地レースのみ）"""
    history = _filter_flat(history)
    if not history:
        return "不明"

    early_positions = []
    for h in history:
        if h.passing:
            positions = re.findall(r"\d+", h.passing)
            if positions:
                early_positions.append(int(positions[0]))

    if not early_positions:
        return "不明"

    avg_pos = sum(early_positions) / len(early_positions)
    if avg_pos <= 3:
        return "逃げ"
    elif avg_pos <= 6:
        return "先行"
    elif avg_pos <= 10:
        return "差し"
    else:
        return "追込"


# ============================================================================
# スコアリング関数
# ============================================================================

def calc_time_index(history: list[HorseResult]) -> float:
    """
    タイム指数: 走破タイムを基準タイムと比較してスコア化
    基準=50点、1秒速いごとに+5点
    直近ほど重み大 (最新1.0, 2走前0.8, 3走前0.6...)
    ※ JRA平地レースのみ対象（障害・地方は除外）
    """
    history = _filter_jra_flat(history)
    if not history:
        return 50.0

    scores = []
    weights = [1.0, 0.8, 0.6, 0.4, 0.3]

    for i, h in enumerate(history):
        time_sec = _parse_time(h.time)
        if time_sec is None:
            continue

        surface, distance = _parse_distance(h.distance)
        if not surface or not distance:
            continue

        base = _get_base_time(surface, distance)

        # 馬場補正
        cond_key = h.track_condition[:1] if h.track_condition else "良"
        cond_adjust = TRACK_CONDITION_ADJUST.get(cond_key, 0.0)

        # 頭数補正
        head_count = _parse_int(h.head_count)
        head_adjust = 0.0
        for r, adj in HEAD_COUNT_ADJUST.items():
            if head_count in r:
                head_adjust = adj
                break

        adjusted_base = base + cond_adjust + head_adjust
        diff = adjusted_base - time_sec  # プラスなら基準より速い

        score = 50.0 + diff * 5.0
        w = weights[i] if i < len(weights) else 0.2
        scores.append((score, w))

    if not scores:
        return 50.0

    total_w = sum(w for _, w in scores)
    return sum(s * w for s, w in scores) / total_w


def calc_last_3f_index(history: list[HorseResult]) -> float:
    """
    上がり3F指数: 末脚の切れ味を評価
    基準=50点、33.0秒を基準に0.1秒速いごとに+1点
    ※ JRA平地レースのみ対象（障害の上がり14秒台等を除外）
    """
    history = _filter_jra_flat(history)
    if not history:
        return 50.0

    scores = []
    weights = [1.0, 0.8, 0.6, 0.4, 0.3]
    BASE_3F = 33.5  # 基準上がり3F

    for i, h in enumerate(history):
        last_3f = _parse_float(h.last_3f)
        if last_3f <= 0:
            continue

        diff = BASE_3F - last_3f  # プラスなら速い
        score = 50.0 + diff * 10.0
        w = weights[i] if i < len(weights) else 0.2
        scores.append((score, w))

    if not scores:
        return 50.0

    total_w = sum(w for _, w in scores)
    return sum(s * w for s, w in scores) / total_w


def calc_stability_index(history: list[HorseResult]) -> float:
    """
    安定性指数: 着順のばらつきが少ないほど高スコア
    着順の標準偏差で評価
    ※ 平地レースのみ対象（障害は除外、地方は含む）
    """
    history = _filter_flat(history)
    if not history:
        return 50.0

    positions = []
    for h in history:
        pos = _parse_int(h.finish_position)
        if pos > 0:
            positions.append(pos)

    if len(positions) < 2:
        return 50.0

    avg = sum(positions) / len(positions)
    variance = sum((p - avg) ** 2 for p in positions) / len(positions)
    std = variance ** 0.5

    # 平均着順が良いほど + ばらつきが少ないほど高スコア
    position_score = max(0, 70 - avg * 5)  # 1着平均=65, 5着平均=45
    stability_bonus = max(0, 20 - std * 5)  # std=0で+20, std=4で0

    return position_score + stability_bonus


def calc_course_fitness(history: list[HorseResult], target_venue: str = "中山",
                        target_distance_info: str = "") -> float:
    """
    コース適性: 同会場・同距離帯での過去成績を重視
    ※ 平地レースのみ対象
    """
    history = _filter_flat(history)
    if not history:
        return 50.0

    # ターゲット距離のパース
    target_surface, target_dist = "", 0
    if target_distance_info:
        target_surface, target_dist = _parse_distance(target_distance_info)

    venue_scores = []
    distance_scores = []

    for h in history:
        pos = _parse_int(h.finish_position)
        if pos <= 0:
            continue

        # 同会場ボーナス
        if target_venue and target_venue in h.venue:
            venue_scores.append(max(0, 80 - (pos - 1) * 10))

        # 同距離帯（±200m）
        surface, dist = _parse_distance(h.distance)
        if target_dist and abs(dist - target_dist) <= 200 and surface == target_surface:
            distance_scores.append(max(0, 80 - (pos - 1) * 10))

    score = 50.0
    if venue_scores:
        score += (sum(venue_scores) / len(venue_scores) - 50) * 0.4
    if distance_scores:
        score += (sum(distance_scores) / len(distance_scores) - 50) * 0.4
    # データ量ボーナス
    if len(venue_scores) >= 3:
        score += 3.0

    return score


def calc_form_cycle(history: list[HorseResult]) -> float:
    """
    調子サイクル: 着順の推移から上昇/下降トレンドを判定
    直近3走の着順推移を分析
    ※ 平地レースのみ対象
    """
    history = _filter_flat(history)
    if not history:
        return 50.0

    positions = []
    for h in history[:4]:
        pos = _parse_int(h.finish_position)
        if pos > 0:
            positions.append(pos)

    if len(positions) < 2:
        return 50.0

    # 直近に向かって着順が良くなっていれば上昇トレンド
    # positions[0]が最新
    score = 50.0
    for i in range(len(positions) - 1):
        diff = positions[i + 1] - positions[i]  # 前走より良くなってればプラス
        score += diff * 3.0

    # 最新走が好走なら追加ボーナス
    if positions[0] <= 3:
        score += 10.0
    elif positions[0] <= 5:
        score += 5.0

    return min(80, max(20, score))


def calc_weight_score(entry: HorseEntry) -> float:
    """
    馬体重スコア: 馬体重の変動を評価
    大幅増減はマイナス
    """
    if not entry.horse_weight:
        return 50.0

    # 馬体重文字列から変動を抽出 (例: "480(+4)" or "480(-2)")
    m = re.search(r"\(([+-]?\d+)\)", entry.horse_weight)
    if not m:
        return 50.0

    change = int(m.group(1))
    abs_change = abs(change)

    if abs_change <= 4:
        return 55.0  # 安定
    elif abs_change <= 8:
        return 48.0  # やや変動
    elif abs_change <= 14:
        return 40.0  # 要注意
    else:
        return 30.0  # 大幅変動は危険信号


def _normalize_race_name(name: str) -> str:
    """全角数字を半角に変換"""
    zen = "０１２３４５６７８９"
    han = "0123456789"
    for z, h in zip(zen, han):
        name = name.replace(z, h)
    return name


def _estimate_class_level(race_name: str) -> int:
    """
    レース名からクラスレベルを推定する
    0=不明, 1=新馬/未勝利, 2=1勝, 3=2勝, 4=3勝, 5=OP/L, 6=G3, 7=G2, 8=G1
    """
    if not race_name:
        return 0
    race_name = _normalize_race_name(race_name)
    # G1が最も先にチェック（"GI"が"GIII"に部分一致しないように）
    if any(k in race_name for k in ["GI", "G1"]) and not any(k in race_name for k in ["GII", "GIII", "G2", "G3"]):
        return 8
    if any(k in race_name for k in ["GII", "G2"]):
        return 7
    if any(k in race_name for k in ["GIII", "G3"]):
        return 6
    if any(k in race_name for k in ["オープン", "OP", "リステッド"]):
        return 5
    if "3勝" in race_name or "1600万" in race_name:
        return 4
    if "2勝" in race_name or "1000万" in race_name:
        return 3
    if "1勝" in race_name or "500万" in race_name:
        return 2
    if "新馬" in race_name or "未勝利" in race_name:
        return 1
    # 特別レース名でクラスが含まれない場合（下総S等）
    # "S"で終わるレースは通常3勝クラス
    if race_name.endswith("S") and len(race_name) <= 10:
        return 4
    return 0


def _detect_class_upgrade(history: list[HorseResult], current_race_name: str) -> bool:
    """
    昇級初戦かどうかを判定する
    過去走のクラスレベルの最大値 < 今走のクラスレベルなら昇級初戦
    """
    current_level = _estimate_class_level(current_race_name)
    if current_level == 0:
        return False

    history = _filter_flat(history)
    if not history:
        return False

    past_levels = [_estimate_class_level(h.race_name) for h in history]
    past_levels = [l for l in past_levels if l > 0]

    if not past_levels:
        return False

    max_past = max(past_levels)
    return current_level > max_past


def calc_class_score(history: list[HorseResult], entry: HorseEntry) -> float:
    """
    クラス補正: 過去のレースのレベルと今回のクラスを比較
    重賞経験、オープン実績などを考慮
    ※ 平地レースのみ対象
    """
    history = _filter_flat(history)
    if not history:
        return 50.0

    score = 50.0

    # 過去のレース名からクラスを推定
    class_keywords_high = ["G1", "G2", "G3", "重賞", "オープン", "OP", "GI", "GII", "GIII"]
    class_keywords_mid = ["3勝", "1600万", "準オープン"]
    class_keywords_low = ["新馬", "未勝利", "1勝", "500万"]

    high_class_count = 0
    good_in_high_class = 0

    for h in history:
        race_name = h.race_name
        pos = _parse_int(h.finish_position)

        is_high = any(k in race_name for k in class_keywords_high)
        if is_high:
            high_class_count += 1
            if pos <= 5:
                good_in_high_class += 1

    # 高クラス経験ボーナス
    if high_class_count >= 2:
        score += 8.0
    if good_in_high_class >= 1:
        score += 10.0

    return min(80, score)


def calc_odds_score(entry: HorseEntry) -> float:
    """
    オッズスコア: 市場評価を反映
    人気馬ほど高スコアだが、過剰人気は抑制
    """
    odds = _parse_float(entry.odds)
    if odds <= 0:
        return 50.0

    # オッズが低い（人気）ほど高スコア、ただし対数スケールで抑制
    import math
    # 1.5倍→65, 3倍→58, 5倍→53, 10倍→47, 30倍→38, 100倍→30
    score = 70 - math.log(odds) * 8
    return max(25, min(70, score))


def calc_rest_days_score(history: list[HorseResult]) -> float:
    """
    休養日数スコア: 直近出走からの間隔を評価
    中2-4週(14-28日)が好走帯、長期休養や連戦はマイナス
    ※ 平地レースの最新走から計算（障害レースは間隔計算に含めない）
    """
    history = _filter_flat(history)
    if not history:
        return 50.0

    # 最新走の日付をパース
    date_str = history[0].date
    if not date_str:
        return 50.0

    # 日付フォーマット: "YYYY/MM/DD" or "YYYY.MM.DD" etc
    m = re.search(r"(\d{4})\D?(\d{1,2})\D?(\d{1,2})", date_str)
    if not m:
        return 50.0

    try:
        last_race = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        today = datetime.now()
        rest_days = (today - last_race).days

        if rest_days < 0:
            return 50.0
        elif rest_days <= 7:
            return 40.0   # 連闘・連戦は消耗
        elif rest_days <= 14:
            return 50.0   # 中1週
        elif rest_days <= 35:
            return 58.0   # 中2-4週：ベストゾーン
        elif rest_days <= 56:
            return 53.0   # 中5-8週：まずまず
        elif rest_days <= 90:
            return 48.0   # 中9-12週：やや不安
        elif rest_days <= 180:
            return 42.0   # 半年以内の休み明け
        else:
            return 35.0   # 長期休養明け
    except (ValueError, TypeError):
        return 50.0


# 枠順バイアス定数（コース×距離帯別）
# 正の値=内枠有利、負の値=外枠有利
GATE_BIAS = {
    # (会場, 馬場, 距離帯): {枠番: 補正値}
    # 中山芝: 内回り中心、内枠有利
    ("中山", "芝", "短"): {1: 5, 2: 4, 3: 3, 4: 1, 5: 0, 6: -1, 7: -3, 8: -4},
    ("中山", "芝", "中"): {1: 4, 2: 3, 3: 2, 4: 1, 5: 0, 6: -1, 7: -2, 8: -3},
    ("中山", "芝", "長"): {1: 2, 2: 2, 3: 1, 4: 0, 5: 0, 6: -1, 7: -1, 8: -2},
    ("中山", "ダ", "短"): {1: 3, 2: 2, 3: 1, 4: 0, 5: 0, 6: -1, 7: -2, 8: -3},
    ("中山", "ダ", "中"): {1: 2, 2: 1, 3: 1, 4: 0, 5: 0, 6: 0, 7: -1, 8: -2},
    # 東京: 直線長い、外枠でも差しが届く
    ("東京", "芝", "短"): {1: 3, 2: 2, 3: 1, 4: 0, 5: 0, 6: -1, 7: -2, 8: -2},
    ("東京", "芝", "中"): {1: 1, 2: 1, 3: 0, 4: 0, 5: 0, 6: 0, 7: -1, 8: -1},
    ("東京", "芝", "長"): {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0},
    ("東京", "ダ", "短"): {1: 4, 2: 3, 3: 2, 4: 1, 5: 0, 6: -1, 7: -2, 8: -3},
    ("東京", "ダ", "中"): {1: 2, 2: 1, 3: 1, 4: 0, 5: 0, 6: 0, 7: -1, 8: -2},
    # 阪神: 内回りは内有利、外回りはフラット寄り
    ("阪神", "芝", "短"): {1: 4, 2: 3, 3: 2, 4: 1, 5: 0, 6: -1, 7: -2, 8: -3},
    ("阪神", "芝", "中"): {1: 2, 2: 1, 3: 1, 4: 0, 5: 0, 6: 0, 7: -1, 8: -2},
    ("阪神", "芝", "長"): {1: 1, 2: 1, 3: 0, 4: 0, 5: 0, 6: 0, 7: -1, 8: -1},
    ("阪神", "ダ", "短"): {1: 3, 2: 2, 3: 1, 4: 0, 5: 0, 6: -1, 7: -2, 8: -3},
    ("阪神", "ダ", "中"): {1: 2, 2: 1, 3: 0, 4: 0, 5: 0, 6: 0, 7: -1, 8: -2},
    # 京都
    ("京都", "芝", "短"): {1: 3, 2: 2, 3: 1, 4: 0, 5: 0, 6: -1, 7: -2, 8: -3},
    ("京都", "芝", "中"): {1: 1, 2: 1, 3: 0, 4: 0, 5: 0, 6: 0, 7: -1, 8: -1},
    ("京都", "芝", "長"): {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0},
    ("京都", "ダ", "短"): {1: 3, 2: 2, 3: 1, 4: 0, 5: 0, 6: -1, 7: -2, 8: -3},
    ("京都", "ダ", "中"): {1: 2, 2: 1, 3: 0, 4: 0, 5: 0, 6: 0, 7: -1, 8: -2},
}

# デフォルト（定義がない会場用）
GATE_BIAS_DEFAULT = {1: 2, 2: 1, 3: 1, 4: 0, 5: 0, 6: 0, 7: -1, 8: -2}


def _distance_category(distance: int) -> str:
    """距離をカテゴリ化"""
    if distance <= 1400:
        return "短"
    elif distance <= 2200:
        return "中"
    else:
        return "長"


def calc_gate_bias_score(entry: HorseEntry, venue: str, surface: str, distance: int) -> float:
    """
    枠順バイアススコア: 枠番とコース特性から有利不利を算出
    """
    frame = _parse_int(entry.frame_number)
    if frame <= 0 or frame > 8:
        return 50.0

    dist_cat = _distance_category(distance)
    key = (venue, surface, dist_cat)
    bias = GATE_BIAS.get(key, GATE_BIAS_DEFAULT)

    return 50.0 + bias.get(frame, 0)


def calc_jockey_score(entry: HorseEntry) -> float:
    """
    騎手スコア: 騎手の今年の勝率・複勝率 + 同馬コンビ実績
    """
    score = 50.0

    # 騎手の年間成績（スクレイピング済みの場合）
    stats = entry.jockey_stats if hasattr(entry, 'jockey_stats') else {}
    if stats:
        win_rate = stats.get("win_rate", 0)
        place_rate = stats.get("place_rate", 0)
        # 勝率10%→55, 15%→60, 20%→65
        score = 45 + win_rate * 100
        # 複勝率ボーナス
        if place_rate >= 0.30:
            score += 5
        score = min(75, score)

    # 同馬コンビ実績（過去走データから）
    if entry.history and entry.jockey:
        same_jockey_results = []
        for h in entry.history:
            if entry.jockey in h.jockey:
                pos = _parse_int(h.finish_position)
                if pos > 0:
                    same_jockey_results.append(pos)

        if same_jockey_results:
            avg_pos = sum(same_jockey_results) / len(same_jockey_results)
            combo_score = 65 - (avg_pos - 1) * 3
            # コンビ実績を30%、年間成績を70%で混合
            if stats:
                score = score * 0.7 + combo_score * 0.3
            else:
                score = combo_score
            # コンビ継続ボーナス
            if len(same_jockey_results) >= 2:
                score += 3.0

    return max(30, min(75, score))


# ============================================================================
# メインスコアリング
# ============================================================================

DEFAULT_WEIGHTS = {
    "time_index": 0.22,
    "last_3f_index": 0.16,
    "stability_index": 0.08,
    "course_fitness": 0.13,
    "pace_advantage": 0.09,
    "form_cycle": 0.08,
    "weight_score": 0.03,
    "class_score": 0.05,
    "rest_days_score": 0.05,
    "gate_bias_score": 0.05,
    "jockey_score": 0.06,
}


def load_model_config(path: str = None) -> dict:
    """モデルコンフィグJSONを読み込む。Noneならデフォルト配点を返す"""
    default = {"name": "default", "version": "v1.0", "weights": DEFAULT_WEIGHTS}
    if path is None:
        return default
    import json
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return default
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return default
        if "weights" in data:
            if not isinstance(data["weights"], dict):
                return default
            # 未知のキーや不正な値を排除
            for k, v in data["weights"].items():
                if k not in DEFAULT_WEIGHTS or not isinstance(v, (int, float)):
                    return default
        return data
    except (json.JSONDecodeError, UnicodeDecodeError):
        return default


def calculate_scores(race: RaceInfo, model_config: dict = None) -> list[HorseScore]:
    """
    レースの全馬のスコアを計算する

    model_config: モデルコンフィグ辞書。Noneならデフォルト配点を使用。
    weights キーで各指標の配点を変更可能。

    ※ オッズスコアはtotal_scoreに含めない（循環参照を防止）
    ※ EVは実力ベースの推定勝率×単勝オッズで算出
    """
    w = DEFAULT_WEIGHTS.copy()
    if model_config and "weights" in model_config:
        w.update(model_config["weights"])
    # コース情報の抽出
    course_info = race.course_info or ""
    distance_match = re.search(r"(芝|ダ)\d+", course_info)
    target_distance_info = distance_match.group(0) if distance_match else ""

    # 馬場種別と距離を抽出
    target_surface, target_distance = "", 0
    if target_distance_info:
        target_surface, target_distance = _parse_distance(target_distance_info)

    # 全馬の脚質を判定（ペース予測用）
    running_styles = {}
    for entry in race.entries:
        style = _classify_running_style(entry.history)
        running_styles[entry.horse_number] = style

    # ペース予測
    style_counts = {}
    for s in running_styles.values():
        style_counts[s] = style_counts.get(s, 0) + 1

    escape_count = style_counts.get("逃げ", 0)
    lead_count = style_counts.get("先行", 0)
    front_pressure = escape_count + lead_count * 0.5

    is_high_pace = front_pressure >= 4
    is_slow_pace = front_pressure <= 2

    scores = []
    for entry in race.entries:
        hs = HorseScore(
            horse_number=entry.horse_number,
            horse_name=entry.horse_name,
        )

        hs.time_index = calc_time_index(entry.history)
        hs.last_3f_index = calc_last_3f_index(entry.history)
        hs.stability_index = calc_stability_index(entry.history)
        hs.course_fitness = calc_course_fitness(
            entry.history, target_venue=race.venue or "", target_distance_info=target_distance_info
        )
        hs.form_cycle = calc_form_cycle(entry.history)
        hs.weight_score = calc_weight_score(entry)
        hs.class_score = calc_class_score(entry.history, entry)
        hs.running_style = running_styles.get(entry.horse_number, "不明")

        # クラス昇級初戦の補正:
        # 下位クラスでの安定性・好調子がそのまま通用するとは限らない
        is_upgrade = _detect_class_upgrade(entry.history, race.race_name)
        if is_upgrade:
            hs.stability_index = hs.stability_index * 0.7 + 50.0 * 0.3  # 50点方向に30%寄せる
            hs.form_cycle = hs.form_cycle * 0.7 + 50.0 * 0.3

        # 新スコア
        hs.odds = entry.odds or ""
        hs.odds_score = calc_odds_score(entry)
        hs.rest_days_score = calc_rest_days_score(entry.history)
        hs.gate_bias_score = calc_gate_bias_score(
            entry, race.venue or "", target_surface, target_distance
        )
        hs.jockey_score = calc_jockey_score(entry)

        # 展開利の計算
        style = hs.running_style
        if is_high_pace:
            pace_bonus = {"追込": 8, "差し": 5, "先行": -3, "逃げ": -8}.get(style, 0)
        elif is_slow_pace:
            pace_bonus = {"逃げ": 8, "先行": 5, "差し": -3, "追込": -8}.get(style, 0)
        else:
            pace_bonus = {"先行": 3, "逃げ": 1, "差し": 0, "追込": -2}.get(style, 0)

        # 騎手ペース制御力補正:
        # ハイペース時でも騎手力が高い逃げ・先行馬はペナルティを軽減
        # （腕のある騎手はペースを制御して逃げ粘れる）
        if is_high_pace and style in ("逃げ", "先行") and hs.jockey_score >= 55:
            jockey_mitigation = (hs.jockey_score - 50) * 0.3  # 騎手60点→+3, 65点→+4.5
            pace_bonus += jockey_mitigation

        hs.pace_advantage = 50.0 + pace_bonus

        # 総合スコア (加重平均) - オッズ非依存の実力スコア
        hs.total_score = (
            hs.time_index * w["time_index"] +
            hs.last_3f_index * w["last_3f_index"] +
            hs.stability_index * w["stability_index"] +
            hs.course_fitness * w["course_fitness"] +
            hs.pace_advantage * w["pace_advantage"] +
            hs.form_cycle * w["form_cycle"] +
            hs.weight_score * w["weight_score"] +
            hs.class_score * w["class_score"] +
            hs.rest_days_score * w["rest_days_score"] +
            hs.gate_bias_score * w["gate_bias_score"] +
            hs.jockey_score * w["jockey_score"]
        )

        # コメント生成
        comments = []
        if hs.time_index >= 60:
            comments.append("時計優秀")
        if hs.last_3f_index >= 60:
            comments.append("末脚鋭い")
        if hs.course_fitness >= 60:
            comments.append("コース巧者")
        if hs.form_cycle >= 60:
            comments.append("上昇中")
        elif hs.form_cycle <= 40:
            comments.append("下降気味")
        if pace_bonus >= 5:
            comments.append("展開利あり")
        elif pace_bonus <= -5:
            comments.append("展開不利")
        if hs.rest_days_score >= 55:
            comments.append("好間隔")
        elif hs.rest_days_score <= 40:
            comments.append("間隔注意")
        if hs.gate_bias_score >= 55:
            comments.append("枠有利")
        elif hs.gate_bias_score <= 45:
            comments.append("枠不利")
        if is_upgrade:
            comments.append("昇級初戦")

        pace_desc = "ハイペース予想" if is_high_pace else ("スローペース予想" if is_slow_pace else "平均ペース予想")
        comments.insert(0, f"[{pace_desc}] 脚質:{style}")
        hs.comment = " / ".join(comments)

        scores.append(hs)

    # スコア順でソート
    scores.sort(key=lambda x: x.total_score, reverse=True)

    # 推定勝率と期待値を計算
    _calculate_win_prob_and_ev(scores)

    return scores


def _calculate_win_prob_and_ev(scores: list[HorseScore]):
    """
    スコアからソフトマックスで推定勝率を算出し、オッズとの乖離で期待値を計算
    """
    import math

    # ソフトマックスで勝率推定（温度パラメータで分布の鋭さを調整）
    # 温度5.0: 頭数による影響を緩和し、上位集中を抑える
    n = len(scores)
    temperature = 5.0 if n >= 10 else 4.0 if n >= 6 else 3.0
    max_score = max(s.total_score for s in scores) if scores else 50.0

    exp_scores = []
    for s in scores:
        exp_scores.append(math.exp((s.total_score - max_score) / temperature))

    total_exp = sum(exp_scores)

    # 勝率の上限キャップ: 単勝の上限は現実的に50%程度
    MAX_WIN_PROB = 0.50

    for i, s in enumerate(scores):
        raw_prob = exp_scores[i] / total_exp if total_exp > 0 else 0.0
        s.win_prob = min(raw_prob, MAX_WIN_PROB)

        # 期待値 = 推定勝率 × オッズ
        odds = _parse_float(s.odds)
        if odds > 0:
            s.expected_value = s.win_prob * odds
        else:
            s.expected_value = 0.0

    # キャップ適用後に勝率を再正規化（合計100%に）
    total_prob = sum(s.win_prob for s in scores)
    if total_prob > 0:
        for s in scores:
            s.win_prob = s.win_prob / total_prob
            odds = _parse_float(s.odds)
            if odds > 0:
                s.expected_value = s.win_prob * odds


def scores_to_text(scores: list[HorseScore]) -> str:
    """スコア結果をテキスト形式に変換（Claude分析用）"""
    lines = ["## 統計スコアリング結果\n"]

    for i, s in enumerate(scores, 1):
        ev_mark = ""
        if s.expected_value >= 1.5:
            ev_mark = " ★★★妙味大"
        elif s.expected_value >= 1.2:
            ev_mark = " ★★妙味あり"
        elif s.expected_value >= 1.0:
            ev_mark = " ★適正"

        lines.append(f"### {i}位: {s.horse_number}番 {s.horse_name} (総合: {s.total_score:.1f})")
        lines.append(
            f"  タイム指数:{s.time_index:.1f} / 上がり3F:{s.last_3f_index:.1f} / "
            f"安定性:{s.stability_index:.1f} / コース適性:{s.course_fitness:.1f}"
        )
        lines.append(
            f"  展開利:{s.pace_advantage:.1f} / 調子:{s.form_cycle:.1f} / "
            f"馬体重:{s.weight_score:.1f} / クラス:{s.class_score:.1f}"
        )
        lines.append(
            f"  オッズ:{s.odds_score:.1f} / 休養:{s.rest_days_score:.1f} / "
            f"枠順:{s.gate_bias_score:.1f} / 騎手:{s.jockey_score:.1f}"
        )
        lines.append(
            f"  推定勝率:{s.win_prob:.1%} / オッズ:{s.odds} / "
            f"期待値:{s.expected_value:.2f}{ev_mark}"
        )
        lines.append(f"  → {s.comment}")
        lines.append("")

    # 期待値ランキング（バリューベット候補）
    ev_sorted = sorted([s for s in scores if s.expected_value > 0], key=lambda x: x.expected_value, reverse=True)
    if ev_sorted:
        lines.append("## バリューベット候補（期待値順）\n")
        for s in ev_sorted[:5]:
            flag = "🔥" if s.expected_value >= 1.5 else ("⭐" if s.expected_value >= 1.0 else "")
            lines.append(
                f"- {s.horse_number}番 {s.horse_name}: "
                f"EV={s.expected_value:.2f} (勝率{s.win_prob:.1%} × オッズ{s.odds}) {flag}"
            )
        lines.append("")

    return "\n".join(lines)
