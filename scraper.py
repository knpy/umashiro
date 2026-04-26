"""netkeiba.comからレース情報・出馬表・馬の過去成績をスクレイピングする"""

import re
import time
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup


@dataclass
class HorseResult:
    """過去のレース結果"""
    date: str = ""
    venue: str = ""
    race_name: str = ""
    head_count: str = ""
    frame_number: str = ""
    horse_number: str = ""
    odds: str = ""
    popularity: str = ""
    finish_position: str = ""
    jockey: str = ""
    weight_carried: str = ""
    distance: str = ""
    track_condition: str = ""
    time: str = ""
    margin: str = ""
    passing: str = ""
    last_3f: str = ""
    horse_weight: str = ""
    winner: str = ""


@dataclass
class HorseEntry:
    """出馬表の1頭分"""
    frame_number: str = ""
    horse_number: str = ""
    horse_name: str = ""
    horse_id: str = ""
    sex_age: str = ""
    weight_carried: str = ""
    jockey: str = ""
    jockey_id: str = ""
    trainer: str = ""
    trainer_id: str = ""
    odds: str = ""
    popularity: str = ""
    horse_weight: str = ""
    history: list = field(default_factory=list)
    jockey_stats: dict = field(default_factory=dict)


@dataclass
class RaceInfo:
    """レース情報"""
    race_id: str = ""
    race_number: int = 0
    race_name: str = ""
    course_info: str = ""
    start_time: str = ""
    head_count: int = 0
    venue: str = ""
    entries: list = field(default_factory=list)


def _safe_int(s: str) -> int:
    """文字列から数値を抽出"""
    m = re.search(r"(\d+)", s.replace(",", ""))
    return int(m.group(1)) if m else 0


class NetkeibaScraper:
    RACE_LIST_URL = "https://race.netkeiba.com/top/race_list.html"
    SHUTUBA_URL = "https://race.netkeiba.com/race/shutuba.html"
    SHUTUBA_SP_URL = "https://race.sp.netkeiba.com/race/shutuba.html"
    ODDS_SP_API_URL = "https://race.sp.netkeiba.com/"
    HORSE_URL = "https://db.netkeiba.com/horse"

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ja,en;q=0.9",
    }

    SP_HEADERS = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                      "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                      "Version/17.0 Mobile/15E148 Safari/604.1",
        "Accept-Language": "ja,en;q=0.9",
    }

    def __init__(self, delay: float = 1.0):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.delay = delay

    def _get(self, url: str, params: dict = None, encoding: str = None) -> BeautifulSoup:
        time.sleep(self.delay)
        resp = self.session.get(url, params=params, timeout=30)
        # netkeiba は基本的にEUC-JP
        if encoding:
            resp.encoding = encoding
        else:
            resp.encoding = "euc-jp"
        return BeautifulSoup(resp.text, "html.parser")

    def _get_sp(self, url: str, params: dict = None) -> BeautifulSoup:
        """SP版(スマホ版)にアクセスする"""
        time.sleep(self.delay)
        resp = self.session.get(
            url, params=params, timeout=30,
            headers=self.SP_HEADERS,
        )
        resp.encoding = "euc-jp"
        return BeautifulSoup(resp.text, "html.parser")

    # =========================================================================
    # レース一覧取得
    # =========================================================================
    def get_race_list(self, date: str, venue_filter: str = "") -> list[dict]:
        """
        指定日のレース一覧を取得する。
        date: "YYYYMMDD" 形式
        venue_filter: "中山" などで絞り込み（空なら全会場）
        """
        soup = self._get(self.RACE_LIST_URL, {"kaisai_date": date})
        races = []

        # 各開催場のブロックを走査
        race_list_items = soup.select("li.RaceList_DataItem")
        for item in race_list_items:
            link = item.select_one("a")
            if not link:
                continue

            href = link.get("href", "")
            race_id_match = re.search(r"race_id=(\w+)", href)
            if not race_id_match:
                continue

            race_id = race_id_match.group(1)
            race_num_el = item.select_one(".Race_Num")
            race_name_el = item.select_one(".ItemTitle")
            time_el = item.select_one(".RaceList_ItemLong .RaceData01 span") or item.select_one(".RaceList_ItemLong span")

            race_num = race_num_el.get_text(strip=True) if race_num_el else ""
            race_name = race_name_el.get_text(strip=True) if race_name_el else ""
            start_time = time_el.get_text(strip=True) if time_el else ""

            races.append({
                "race_id": race_id,
                "race_number": race_num,
                "race_name": race_name,
                "start_time": start_time,
            })

        # venue_filterがある場合、race_idのvenueコードで絞り込む
        if venue_filter:
            races = self._filter_by_venue(races, venue_filter)

        return races

    def _filter_by_venue(self, races: list[dict], venue_name: str) -> list[dict]:
        """
        会場名でフィルタリングする。
        race_id の5-6桁目が会場コード:
        01=札幌, 02=函館, 03=福島, 04=新潟, 05=東京, 06=中山, 07=中京, 08=京都, 09=阪神, 10=小倉
        """
        venue_codes = {
            "札幌": "01", "函館": "02", "福島": "03", "新潟": "04",
            "東京": "05", "中山": "06", "中京": "07", "京都": "08",
            "阪神": "09", "小倉": "10",
        }
        code = venue_codes.get(venue_name, "")
        if not code:
            return races
        return [r for r in races if len(r["race_id"]) >= 6 and r["race_id"][4:6] == code]

    # =========================================================================
    # 出馬表取得
    # =========================================================================
    def get_race_entries(self, race_id: str) -> RaceInfo:
        """出馬表ページからレース情報と全馬のエントリーを取得

        PC版を試し、取得できない場合はSP版にフォールバックする。
        """
        soup = self._get(self.SHUTUBA_URL, {"race_id": race_id})
        rows = soup.select(".HorseList")

        if rows:
            return self._parse_pc_shutuba(soup, rows, race_id)

        # PC版が取得できない場合、SP版にフォールバック
        soup = self._get_sp(self.SHUTUBA_SP_URL, {"race_id": race_id})
        rows = soup.select(".HorseList")
        return self._parse_sp_shutuba(soup, rows, race_id)

    def _parse_pc_shutuba(self, soup, rows, race_id: str) -> RaceInfo:
        """PC版出馬表をパースする"""
        info = RaceInfo(race_id=race_id)
        info.venue = self._venue_from_race_id(race_id)

        race_name_el = soup.select_one(".RaceName")
        if race_name_el:
            info.race_name = race_name_el.get_text(strip=True)

        race_num_el = soup.select_one(".RaceNum")
        if race_num_el:
            num_text = re.search(r"(\d+)", race_num_el.get_text(strip=True))
            info.race_number = int(num_text.group(1)) if num_text else 0

        race_data1 = soup.select_one(".RaceData01")
        if race_data1:
            info.course_info = race_data1.get_text(" ", strip=True)

        time_el = soup.select_one(".RaceData01 span")
        if time_el:
            info.start_time = time_el.get_text(strip=True)

        for row in rows:
            entry = self._parse_entry_row(row)
            if entry and entry.horse_name:
                info.entries.append(entry)

        info.head_count = len(info.entries)
        return info

    def _parse_sp_shutuba(self, soup, rows, race_id: str) -> RaceInfo:
        """SP版出馬表をパースする"""
        info = RaceInfo(race_id=race_id)
        info.venue = self._venue_from_race_id(race_id)

        # SP版のレース名・番号・コース情報
        race_name_el = soup.select_one(".Race_Name")
        if race_name_el:
            info.race_name = race_name_el.get_text(strip=True)

        race_num_el = soup.select_one(".RaceList_Item01")
        if race_num_el:
            num_text = re.search(r"(\d+)", race_num_el.get_text(strip=True))
            info.race_number = int(num_text.group(1)) if num_text else 0

        race_data_el = soup.select_one(".RaceList_Item02")
        if race_data_el:
            info.course_info = race_data_el.get_text(" ", strip=True)

        for row in rows:
            entry = self._parse_entry_row_sp(row)
            if entry and entry.horse_name:
                info.entries.append(entry)

        info.head_count = len(info.entries)
        return info

    def _venue_from_race_id(self, race_id: str) -> str:
        venue_code_map = {
            "01": "札幌", "02": "函館", "03": "福島", "04": "新潟",
            "05": "東京", "06": "中山", "07": "中京", "08": "京都",
            "09": "阪神", "10": "小倉",
        }
        if len(race_id) >= 6:
            return venue_code_map.get(race_id[4:6], "")
        return ""

    def _parse_entry_row_sp(self, row) -> Optional[HorseEntry]:
        """SP版出馬表の1行をパースする"""
        entry = HorseEntry()

        # 枠番 - td.Waku* のテキスト
        frame_el = row.select_one("td[class*='Waku']")
        if frame_el:
            entry.frame_number = frame_el.get_text(strip=True)

        # 馬番 - input[value] の "_" 前が馬番 (例: "1_98" → 馬番1)
        input_el = row.select_one(".Horse_Select input[name]")
        if input_el:
            value = input_el.get("value", "")
            if "_" in value:
                entry.horse_number = value.split("_")[0]
            else:
                entry.horse_number = input_el.get("name", "")

        # 馬名 - .Horse a or .HorseLink a
        horse_el = row.select_one(".Horse a, .HorseLink a")
        if horse_el:
            entry.horse_name = horse_el.get_text(strip=True)
            href = horse_el.get("href", "")
            horse_id_match = re.search(r"horse_id=(\w+)", href)
            if horse_id_match:
                entry.horse_id = horse_id_match.group(1)

        # 性齢 - .Age
        age_el = row.select_one(".Age")
        if age_el:
            # 最初のテキストノードだけ (例: "牝4")
            age_text = age_el.get_text(strip=True)
            sex_age_m = re.match(r"([牡牝セ]\d+)", age_text)
            if sex_age_m:
                entry.sex_age = sex_age_m.group(1)

        # 騎手・斤量 - .Jockey a (テキストが "騎手名 斤量")
        jockey_el = row.select_one(".Jockey a")
        if jockey_el:
            jockey_text = jockey_el.get_text(strip=True)
            # "騎手名54.0" → 分離
            wt_m = re.search(r"(\d+\.?\d*)$", jockey_text)
            if wt_m:
                entry.weight_carried = wt_m.group(1)
                entry.jockey = jockey_text[:wt_m.start()]
            else:
                entry.jockey = jockey_text
            href = jockey_el.get("href", "")
            jid = re.search(r"/jockey/(?:result/recent/)?(\w+)", href)
            if jid:
                entry.jockey_id = jid.group(1)

        # 馬体重
        weight_el = row.select_one("td.Weight, .Weight")
        if weight_el:
            entry.horse_weight = weight_el.get_text(strip=True)

        return entry

    def _parse_entry_row(self, row) -> Optional[HorseEntry]:
        """出馬表の1行をパースする"""
        entry = HorseEntry()
        tds = row.select("td")

        # 枠番 - td[0] class="Waku1" etc.
        frame_el = row.select_one("td[class*='Waku']")
        if frame_el:
            entry.frame_number = frame_el.get_text(strip=True)

        # 馬番 - td[1] class="Umaban1" etc.
        umaban_el = row.select_one("td[class*='Umaban']")
        if umaban_el:
            entry.horse_number = umaban_el.get_text(strip=True)

        # 馬名
        horse_name_el = row.select_one(".HorseInfo a, .HorseName a")
        if horse_name_el:
            entry.horse_name = horse_name_el.get_text(strip=True)
            href = horse_name_el.get("href", "")
            horse_id_match = re.search(r"/horse/(\w+)", href)
            if horse_id_match:
                entry.horse_id = horse_id_match.group(1)

        # 性齢
        barei_el = row.select_one(".Barei")
        if barei_el:
            entry.sex_age = barei_el.get_text(strip=True)

        # 斤量 - Bareiの次のTxt_C
        for td in tds:
            classes = td.get("class", [])
            if "Txt_C" in classes and "Barei" not in classes and "Waku" not in " ".join(classes) and "Umaban" not in " ".join(classes):
                text = td.get_text(strip=True)
                if re.match(r"\d+\.?\d*$", text):
                    entry.weight_carried = text
                    break

        # 騎手
        jockey_el = row.select_one(".Jockey a")
        if jockey_el:
            entry.jockey = jockey_el.get_text(strip=True)
            href = jockey_el.get("href", "")
            jid = re.search(r"/jockey/(?:result/recent/)?(\w+)", href)
            if jid:
                entry.jockey_id = jid.group(1)

        # 調教師
        trainer_el = row.select_one(".Trainer a")
        if trainer_el:
            entry.trainer = trainer_el.get_text(strip=True)
            href = trainer_el.get("href", "")
            tid = re.search(r"/trainer/(?:result/recent/)?(\w+)", href)
            if tid:
                entry.trainer_id = tid.group(1)

        # オッズ - td.Popular内のテキストまたはspan
        odds_el = row.select_one("td.Popular span.Odds, td.Txt_R.Popular")
        if odds_el:
            odds_text = odds_el.get_text(strip=True)
            # "---.-" 等は無視
            if re.search(r"\d+\.\d+", odds_text):
                m = re.search(r"(\d+\.\d+)", odds_text)
                if m:
                    entry.odds = m.group(1)

        # 人気
        pop_el = row.select_one("td.Popular_Ninki, td.Popular span.OddsPeople, .OddsPeople")
        if pop_el:
            pop_text = pop_el.get_text(strip=True)
            if re.search(r"\d+", pop_text):
                entry.popularity = re.search(r"(\d+)", pop_text).group(1)

        # 馬体重
        weight_el = row.select_one("td.Weight, .Weight")
        if weight_el:
            entry.horse_weight = weight_el.get_text(strip=True)

        return entry

    # =========================================================================
    # オッズ取得 (SP版APIを使用)
    # =========================================================================
    def get_odds(self, race_id: str) -> dict:
        """SP版APIから単勝オッズと人気を取得する

        Returns:
            {馬番(str): {"odds": str, "popularity": str}, ...}
        """
        import json as _json
        time.sleep(self.delay)
        resp = self.session.get(
            self.ODDS_SP_API_URL,
            params={
                "pid": "api_get_jra_odds",
                "race_id": race_id,
                "type": "1",
                "output": "json",
            },
            headers=self.SP_HEADERS,
            timeout=30,
        )
        result = {}
        if resp.status_code != 200:
            return result
        try:
            data = _json.loads(resp.text)
        except _json.JSONDecodeError:
            return result

        if data.get("status") != "result":
            return result

        # data.data.odds.1 = 単勝: {馬番: [オッズ, 前回オッズ, 人気], ...}
        tan_odds = data.get("data", {}).get("odds", {}).get("1", {})
        for umaban, values in tan_odds.items():
            if isinstance(values, list) and len(values) >= 3:
                odds_val = values[0]  # "3.9"
                pop_val = values[2]   # "1"
                if re.search(r"\d+\.\d+", str(odds_val)):
                    result[umaban] = {
                        "odds": str(odds_val),
                        "popularity": str(pop_val),
                    }
        return result

    def inject_odds(self, race_info: 'RaceInfo') -> None:
        """RaceInfoのエントリーにオッズと人気を注入する"""
        if not race_info.entries:
            return
        # 既にオッズが入っている場合はスキップ
        if any(e.odds for e in race_info.entries):
            return
        odds_data = self.get_odds(race_info.race_id)
        if not odds_data:
            return
        for entry in race_info.entries:
            # APIキーはゼロパディング("01")、エントリーは("1")の場合がある
            key = entry.horse_number.zfill(2)
            if key not in odds_data:
                key = entry.horse_number  # パディングなしでも試す
            if key in odds_data:
                entry.odds = odds_data[key]["odds"]
                if not entry.popularity:
                    entry.popularity = odds_data[key]["popularity"]

    # =========================================================================
    # 馬の過去成績取得 (SP版を使用 - PC版はJS動的読み込みのため)
    # =========================================================================
    HORSE_SP_URL = "https://db.sp.netkeiba.com/horse"

    def get_horse_history(self, horse_id: str, limit: int = 5) -> list[HorseResult]:
        """馬の過去成績を取得する（SP版から取得）"""
        if not re.match(r'^[a-zA-Z0-9]+$', horse_id):
            return []
        url = f"{self.HORSE_SP_URL}/{horse_id}/"
        soup = self._get(url)

        results = []

        # SP版: ヘッダに「レース名,映像,人気,着順,...」を持つテーブルを探す
        target_table = None
        for table in soup.select("table"):
            ths = table.select("tr th")
            headers = [th.get_text(strip=True) for th in ths]
            if "着順" in headers and "騎手" in headers:
                target_table = table
                break

        if not target_table:
            return results

        rows = target_table.select("tr")[1:]  # ヘッダ行をスキップ
        for row in rows[:limit]:
            cells = row.select("td")
            if len(cells) < 25:
                continue

            # [0]レース名(日付+会場+レース名), [2]人気, [3]着順, [4]騎手
            # [5]斤量, [6]オッズ, [7]頭数, [8]枠番, [9]馬番, [10]距離
            # [12]馬場, [14]タイム, [15]着差, [21]通過, [23]上り, [24]馬体重
            # [27]勝ち馬
            race_info = cells[0].get_text(strip=True)

            # "25/12/21 阪神 11R朝日フューチュリティGI" をパース
            date_str, venue, race_name = "", "", ""
            m = re.match(r"(\d{2}/\d{2}/\d{2})\s*(\S+)\s*\d+R(.*)", race_info)
            if m:
                yy = m.group(1)
                # YY/MM/DD -> YYYY/MM/DD
                date_str = "20" + yy
                venue = m.group(2)
                race_name = m.group(3).strip()
            else:
                # フォールバック
                m2 = re.match(r"(\d{2}/\d{2}/\d{2})\s*(\S+)\s*(.*)", race_info)
                if m2:
                    date_str = "20" + m2.group(1)
                    venue = m2.group(2)
                    race_name = m2.group(3).strip()

            result = HorseResult(
                date=date_str,
                venue=venue,
                race_name=race_name,
                head_count=cells[7].get_text(strip=True),
                frame_number=cells[8].get_text(strip=True),
                horse_number=cells[9].get_text(strip=True),
                odds=cells[6].get_text(strip=True),
                popularity=cells[2].get_text(strip=True),
                finish_position=cells[3].get_text(strip=True),
                jockey=cells[4].get_text(strip=True),
                weight_carried=cells[5].get_text(strip=True),
                distance=cells[10].get_text(strip=True),
                track_condition=cells[12].get_text(strip=True),
                time=cells[14].get_text(strip=True),
                margin=cells[15].get_text(strip=True),
                passing=cells[21].get_text(strip=True),
                last_3f=cells[23].get_text(strip=True),
                horse_weight=cells[24].get_text(strip=True),
                winner=cells[27].get_text(strip=True) if len(cells) > 27 else "",
            )
            results.append(result)

        return results

    # =========================================================================
    # 騎手成績取得
    # =========================================================================
    def get_jockey_stats(self, jockey_id: str) -> dict:
        """
        騎手の今年の成績を取得する。
        Returns: {"wins": int, "seconds": int, "thirds": int, "starts": int, "win_rate": float, "place_rate": float}
        """
        if not jockey_id or not re.match(r'^[a-zA-Z0-9]+$', jockey_id):
            return {}

        url = f"https://db.netkeiba.com/jockey/result/recent/{jockey_id}/"
        try:
            soup = self._get(url, encoding="euc-jp")

            # 成績テーブルから今年の成績を取得
            tables = soup.select("table.nk_tb_common")
            for table in tables:
                header = table.select_one("tr th")
                if not header:
                    continue
                rows = table.select("tbody tr")
                if not rows:
                    continue
                # 最初の行が最新年の成績
                cells = rows[0].select("td")
                if len(cells) >= 7:
                    starts = _safe_int(cells[1].get_text(strip=True))
                    wins = _safe_int(cells[2].get_text(strip=True))
                    seconds = _safe_int(cells[3].get_text(strip=True))
                    thirds = _safe_int(cells[4].get_text(strip=True))
                    if starts > 0:
                        return {
                            "wins": wins,
                            "seconds": seconds,
                            "thirds": thirds,
                            "starts": starts,
                            "win_rate": wins / starts,
                            "place_rate": (wins + seconds + thirds) / starts,
                        }
        except Exception:
            pass

        return {}

    # =========================================================================
    # レース結果取得（バックテスト用）
    # =========================================================================
    RESULT_URL = "https://race.netkeiba.com/race/result.html"

    def get_race_result(self, race_id: str) -> Optional[dict]:
        """レース結果ページから構造化データを取得する。存在しないレースは None。"""
        if not re.match(r'^[a-zA-Z0-9]+$', race_id):
            return None
        try:
            soup = self._get(self.RESULT_URL, {"race_id": race_id})
        except Exception:
            return None

        horse_rows = soup.select(".HorseList")
        if not horse_rows:
            return None

        venue_code_map = {
            "01": "札幌", "02": "函館", "03": "福島", "04": "新潟",
            "05": "東京", "06": "中山", "07": "中京", "08": "京都",
            "09": "阪神", "10": "小倉",
        }
        venue = venue_code_map.get(race_id[4:6], "") if len(race_id) >= 6 else ""

        race_name = ""
        el = soup.select_one(".RaceName")
        if el:
            race_name = el.get_text(strip=True)

        race_number = 0
        el = soup.select_one(".RaceNum")
        if el:
            m = re.search(r"(\d+)", el.get_text(strip=True))
            if m:
                race_number = int(m.group(1))

        surface, distance, track_condition = "", 0, ""
        el = soup.select_one(".RaceData01")
        if el:
            text = el.get_text(" ", strip=True)
            m = re.search(r"(芝|ダ).*?(\d{4})", text)
            if m:
                surface = m.group(1)
                distance = int(m.group(2))

        el = soup.select_one(".RaceData02")
        if el:
            m = re.search(r"(良|稍重|重|不良)", el.get_text(" ", strip=True))
            if m:
                track_condition = m.group(1)

        date_str = ""
        header_text = soup.get_text()
        m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", header_text)
        if m:
            date_str = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

        horses = []
        for row in horse_rows:
            tds = row.select("td")
            if len(tds) < 10:
                continue

            rank_text = tds[0].get_text(strip=True)
            rank_m = re.search(r"\d+", rank_text)
            finish_position = int(rank_m.group()) if rank_m else 0

            frame_el = row.select_one("td[class*='Waku']")
            frame_number = frame_el.get_text(strip=True) if frame_el else ""

            # 馬番: 結果ページでは class="Num Txt_C"、出馬表では class*="Umaban"
            umaban_el = row.select_one("td[class*='Umaban']")
            if not umaban_el:
                umaban_el = row.select_one("td.Num.Txt_C")
            horse_number = umaban_el.get_text(strip=True) if umaban_el else ""

            horse_name, horse_id = "", ""
            horse_el = row.select_one(".Horse_Info a, .HorseInfo a, .HorseName a, .Horse_Name a")
            if horse_el:
                horse_name = horse_el.get_text(strip=True)
                href = horse_el.get("href", "")
                hid_m = re.search(r"/horse/(\w+)", href)
                if hid_m:
                    horse_id = hid_m.group(1)

            jockey = ""
            jockey_el = row.select_one(".Jockey a")
            if jockey_el:
                jockey = jockey_el.get_text(strip=True)

            all_text = [td.get_text(strip=True) for td in tds]
            odds_val, time_str, time_sec, last_3f = None, "", None, None
            weight_carried, horse_weight = "", ""

            for t in all_text:
                if re.match(r"^\d:\d\d\.\d$", t):
                    time_str = t
                    parts = t.split(":")
                    sec_parts = parts[1].split(".")
                    time_sec = int(parts[0]) * 60 + int(sec_parts[0]) + int(sec_parts[1]) * 0.1

            # オッズは後半の列から探す（前半の斤量 56.0 等との誤検知を防ぐ）
            for t in reversed(all_text):
                if re.match(r"^\d+\.\d+$", t):
                    val = float(t)
                    if val >= 1.0 and val < 1000.0:
                        odds_val = val
                        break

            for td in tds[-10:]:
                t = td.get_text(strip=True)
                if re.match(r"^3\d\.\d$", t):
                    last_3f = float(t)
                    break

            passing = ""
            for td in tds:
                t = td.get_text(strip=True)
                if re.match(r"^\d+-\d+", t):
                    passing = t
                    break

            weight_el = row.select_one("td.Weight, .Weight")
            if weight_el:
                horse_weight = weight_el.get_text(strip=True)

            pop_el = row.select_one(".Popular_Ninki, .OddsPeople")
            popularity = None
            if pop_el:
                pop_m = re.search(r"(\d+)", pop_el.get_text(strip=True))
                if pop_m:
                    popularity = int(pop_m.group(1))

            horses.append({
                "horse_id": horse_id, "horse_name": horse_name,
                "horse_number": horse_number, "frame_number": frame_number,
                "finish_position": finish_position, "time_str": time_str,
                "time_sec": time_sec, "last_3f": last_3f, "passing": passing,
                "odds": odds_val, "popularity": popularity, "jockey": jockey,
                "weight_carried": weight_carried, "horse_weight": horse_weight,
            })

        if not horses:
            return None

        payouts = {}
        for table in soup.select("table"):
            text = table.get_text(strip=True)
            if "単勝" not in text and "馬連" not in text and "三連" not in text:
                continue
            for tr in table.select("tr"):
                cells = tr.select("th, td")
                if len(cells) >= 3:
                    bt = cells[0].get_text(strip=True)
                    sel = cells[1].get_text(strip=True)
                    pt = cells[2].get_text(strip=True)
                    pm = re.search(r"([\d,]+)円", pt)
                    if pm and bt in ("単勝", "複勝", "馬連", "馬単", "ワイド", "3連複", "3連単"):
                        normalized = bt.replace("3連複", "三連複").replace("3連単", "三連単")
                        payouts[normalized] = {"selections": sel, "payout": int(pm.group(1).replace(",", ""))}

        return {
            "race_id": race_id, "date": date_str, "venue": venue,
            "race_name": race_name, "race_number": race_number,
            "surface": surface, "distance": distance,
            "track_condition": track_condition, "head_count": len(horses),
            "horses": horses, "payouts": payouts,
        }

    # =========================================================================
    # まとめて取得
    # =========================================================================
    def fetch_full_race_data(self, race_id: str, history_limit: int = 5,
                             progress_callback=None) -> RaceInfo:
        """
        レースの全情報（出馬表＋各馬の過去成績）をまとめて取得する。
        """
        race = self.get_race_entries(race_id)

        for i, entry in enumerate(race.entries):
            if progress_callback:
                progress_callback(i + 1, len(race.entries), entry.horse_name)
            if entry.horse_id:
                entry.history = self.get_horse_history(entry.horse_id, limit=history_limit)

        return race
