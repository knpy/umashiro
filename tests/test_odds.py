"""オッズ取得機能のテスト

SP版APIからのオッズ取得、およびRaceInfoへの注入が正しく動作することを検証する。
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper import NetkeibaScraper, HorseEntry, RaceInfo


class TestGetOdds(unittest.TestCase):
    """get_odds メソッドのテスト"""

    def _make_scraper(self):
        """delayを0にしたスクレイパーを生成"""
        return NetkeibaScraper(delay=0)

    def test_get_odds_returns_dict(self):
        """正常なAPIレスポンスからオッズ辞書を返す"""
        scraper = self._make_scraper()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = (
            '{"status":"result","data":{"official_datetime":"2026-04-25 09:52:39",'
            '"odds":{"1":{"01":["220.4","0.0","15"],"02":["9.4","0.0","5"],'
            '"03":["50.3","0.0","8"],"05":["3.9","0.0","1"]},"2":{}}}}'
        )
        with patch.object(scraper.session, "get", return_value=mock_resp):
            odds = scraper.get_odds("202603010501")

        self.assertIsInstance(odds, dict)
        self.assertEqual(odds["01"]["odds"], "220.4")
        self.assertEqual(odds["01"]["popularity"], "15")
        self.assertEqual(odds["05"]["odds"], "3.9")
        self.assertEqual(odds["05"]["popularity"], "1")
        self.assertEqual(len(odds), 4)

    def test_get_odds_error_status(self):
        """APIが400を返した場合は空辞書"""
        scraper = self._make_scraper()
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = ""
        with patch.object(scraper.session, "get", return_value=mock_resp):
            odds = scraper.get_odds("202603010501")

        self.assertEqual(odds, {})

    def test_get_odds_invalid_json(self):
        """不正なJSONの場合は空辞書"""
        scraper = self._make_scraper()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "not json"
        with patch.object(scraper.session, "get", return_value=mock_resp):
            odds = scraper.get_odds("202603010501")

        self.assertEqual(odds, {})

    def test_get_odds_no_result_status(self):
        """status != result の場合は空辞書"""
        scraper = self._make_scraper()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"status":"error","data":{}}'
        with patch.object(scraper.session, "get", return_value=mock_resp):
            odds = scraper.get_odds("202603010501")

        self.assertEqual(odds, {})


class TestInjectOdds(unittest.TestCase):
    """inject_odds メソッドのテスト"""

    def _make_race_info(self, with_odds=False):
        """テスト用RaceInfoを生成"""
        entries = [
            HorseEntry(horse_number="01", horse_name="テスト馬A",
                       odds="3.5" if with_odds else ""),
            HorseEntry(horse_number="05", horse_name="テスト馬B", odds=""),
            HorseEntry(horse_number="10", horse_name="テスト馬C", odds=""),
        ]
        return RaceInfo(race_id="202603010501", entries=entries, head_count=3)

    def test_inject_odds_fills_empty(self):
        """オッズ未取得のエントリーにオッズを注入する（ゼロパディング対応）"""
        scraper = NetkeibaScraper(delay=0)
        race = self._make_race_info(with_odds=False)

        # APIはゼロパディングされたキーを返す
        mock_odds = {
            "01": {"odds": "220.4", "popularity": "15"},
            "05": {"odds": "3.9", "popularity": "1"},
            "10": {"odds": "5.6", "popularity": "3"},
        }
        with patch.object(scraper, "get_odds", return_value=mock_odds):
            scraper.inject_odds(race)

        # エントリー側の馬番 "01", "05", "10" がAPIキーとマッチすること
        self.assertEqual(race.entries[0].odds, "220.4")
        self.assertEqual(race.entries[0].popularity, "15")
        self.assertEqual(race.entries[1].odds, "3.9")
        self.assertEqual(race.entries[1].popularity, "1")
        self.assertEqual(race.entries[2].odds, "5.6")

    def test_inject_odds_zero_padding_match(self):
        """馬番がパディングなし("1")でもAPIキー("01")にマッチする"""
        scraper = NetkeibaScraper(delay=0)
        entries = [
            HorseEntry(horse_number="1", horse_name="テスト馬A", odds=""),
            HorseEntry(horse_number="5", horse_name="テスト馬B", odds=""),
        ]
        race = RaceInfo(race_id="test", entries=entries, head_count=2)

        mock_odds = {
            "01": {"odds": "3.5", "popularity": "1"},
            "05": {"odds": "10.0", "popularity": "3"},
        }
        with patch.object(scraper, "get_odds", return_value=mock_odds):
            scraper.inject_odds(race)

        self.assertEqual(race.entries[0].odds, "3.5")
        self.assertEqual(race.entries[1].odds, "10.0")

    def test_inject_odds_skips_if_already_present(self):
        """既にオッズがある場合はスキップする"""
        scraper = NetkeibaScraper(delay=0)
        race = self._make_race_info(with_odds=True)

        with patch.object(scraper, "get_odds") as mock_get:
            scraper.inject_odds(race)
            mock_get.assert_not_called()

        self.assertEqual(race.entries[0].odds, "3.5")

    def test_inject_odds_handles_empty_response(self):
        """APIが空を返してもクラッシュしない"""
        scraper = NetkeibaScraper(delay=0)
        race = self._make_race_info(with_odds=False)

        with patch.object(scraper, "get_odds", return_value={}):
            scraper.inject_odds(race)

        self.assertEqual(race.entries[0].odds, "")


class TestGetOddsIntegration(unittest.TestCase):
    """SP版APIへの実アクセスによる統合テスト (ネットワーク依存)"""

    @unittest.skipUnless(
        __name__ == "__main__" or "integration" in sys.argv,
        "Integration test: run with 'python -m pytest tests/test_odds.py -k integration' or directly",
    )
    def test_get_odds_real_api(self):
        """実際のSP版APIからオッズが取得できる"""
        scraper = NetkeibaScraper(delay=1.0)
        # 過去の確定レースを使用
        odds = scraper.get_odds("202603010501")
        self.assertGreater(len(odds), 0, "オッズが1件以上取得できること")
        for umaban, data in odds.items():
            self.assertIn("odds", data)
            self.assertIn("popularity", data)
            self.assertRegex(data["odds"], r"\d+\.\d+", f"馬番{umaban}のオッズが数値であること")


if __name__ == "__main__":
    unittest.main()
