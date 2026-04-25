"""過去レースデータを格納する SQLite データベース"""

import json
import sqlite3
from pathlib import Path
from contextlib import contextmanager


DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "history.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS races (
    race_id         TEXT PRIMARY KEY,
    date            TEXT NOT NULL,
    venue           TEXT NOT NULL,
    race_name       TEXT,
    race_number     INTEGER,
    surface         TEXT NOT NULL,
    distance        INTEGER NOT NULL,
    track_condition TEXT,
    head_count      INTEGER
);

CREATE TABLE IF NOT EXISTS race_horses (
    race_id         TEXT NOT NULL,
    horse_id        TEXT NOT NULL,
    horse_name      TEXT,
    horse_number    TEXT,
    frame_number    TEXT,
    finish_position INTEGER,
    time_str        TEXT,
    time_sec        REAL,
    last_3f         REAL,
    passing         TEXT,
    odds            REAL,
    popularity      INTEGER,
    jockey          TEXT,
    weight_carried  TEXT,
    horse_weight    TEXT,
    race_name       TEXT,
    PRIMARY KEY (race_id, horse_id),
    FOREIGN KEY (race_id) REFERENCES races(race_id)
);

CREATE TABLE IF NOT EXISTS payouts (
    race_id    TEXT NOT NULL,
    bet_type   TEXT NOT NULL,
    seq        INTEGER NOT NULL DEFAULT 0,
    selections TEXT,
    payout     INTEGER,
    PRIMARY KEY (race_id, bet_type, seq),
    FOREIGN KEY (race_id) REFERENCES races(race_id)
);

CREATE INDEX IF NOT EXISTS idx_horse_date
    ON race_horses(horse_id, race_id);

CREATE INDEX IF NOT EXISTS idx_race_condition
    ON races(venue, surface, distance, track_condition);

CREATE INDEX IF NOT EXISTS idx_race_date
    ON races(date);
"""


class HistoryDB:
    """過去レースデータの読み書きを行う SQLite ラッパー

    接続を保持して再利用する。Optuna の大量クエリでも効率的。
    """

    def __init__(self, db_path=None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = None
        self._init_schema()

    def _get_conn(self):
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    @contextmanager
    def _transaction(self):
        conn = self._get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def _init_schema(self):
        with self._transaction() as conn:
            conn.executescript(SCHEMA_SQL)

    # =========================================================================
    # 書き込み
    # =========================================================================

    def insert_race(self, race_data: dict):
        """1レース分のデータを挿入する（既存なら無視）"""
        with self._transaction() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO races
                   (race_id, date, venue, race_name, race_number,
                    surface, distance, track_condition, head_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    race_data["race_id"],
                    race_data["date"],
                    race_data["venue"],
                    race_data.get("race_name", ""),
                    race_data.get("race_number", 0),
                    race_data["surface"],
                    race_data["distance"],
                    race_data.get("track_condition", ""),
                    race_data.get("head_count", 0),
                ),
            )

            for h in race_data.get("horses", []):
                conn.execute(
                    """INSERT OR IGNORE INTO race_horses
                       (race_id, horse_id, horse_name, horse_number,
                        frame_number, finish_position, time_str, time_sec,
                        last_3f, passing, odds, popularity, jockey,
                        weight_carried, horse_weight, race_name)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        race_data["race_id"],
                        h.get("horse_id", ""),
                        h.get("horse_name", ""),
                        h.get("horse_number", ""),
                        h.get("frame_number", ""),
                        h.get("finish_position", 0),
                        h.get("time_str", ""),
                        h.get("time_sec"),
                        h.get("last_3f"),
                        h.get("passing", ""),
                        h.get("odds"),
                        h.get("popularity"),
                        h.get("jockey", ""),
                        h.get("weight_carried", ""),
                        h.get("horse_weight", ""),
                        race_data.get("race_name", ""),
                    ),
                )

            for bet_type, info in race_data.get("payouts", {}).items():
                if isinstance(info, list):
                    for seq, item in enumerate(info):
                        conn.execute(
                            """INSERT OR IGNORE INTO payouts
                               (race_id, bet_type, seq, selections, payout)
                               VALUES (?, ?, ?, ?, ?)""",
                            (race_data["race_id"], bet_type, seq,
                             item.get("selections", ""), item.get("payout", 0)),
                        )
                else:
                    conn.execute(
                        """INSERT OR IGNORE INTO payouts
                           (race_id, bet_type, seq, selections, payout)
                           VALUES (?, ?, 0, ?, ?)""",
                        (race_data["race_id"], bet_type,
                         info.get("selections", ""), info.get("payout", 0)),
                    )

    # =========================================================================
    # 読み出し: 疑似ヒストリー（最重要）
    # =========================================================================

    def get_horse_history(self, horse_id: str, before_date: str,
                         limit: int = 5) -> list[dict]:
        """指定日より前の出走記録を直近から返す。"""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT rh.*, r.date, r.venue, r.surface, r.distance,
                      r.track_condition, r.head_count
               FROM race_horses rh
               JOIN races r ON rh.race_id = r.race_id
               WHERE rh.horse_id = ? AND r.date < ?
               ORDER BY r.date DESC
               LIMIT ?""",
            (horse_id, before_date, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # =========================================================================
    # 読み出し: レースイテレーション
    # =========================================================================

    def iter_races(self, year: int = None, venue: str = None,
                   surface: str = None) -> list[dict]:
        """条件付きでレース一覧を返す"""
        conn = self._get_conn()
        conditions = []
        params = []

        if year:
            conditions.append("r.date LIKE ?")
            params.append(f"{year}-%")
        if venue:
            conditions.append("r.venue = ?")
            params.append(venue)
        if surface:
            conditions.append("r.surface = ?")
            params.append(surface)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        races = conn.execute(
            f"""SELECT r.*,
                (SELECT json_group_array(
                    json_object(
                        'horse_id', rh.horse_id,
                        'horse_name', rh.horse_name,
                        'horse_number', rh.horse_number,
                        'frame_number', rh.frame_number,
                        'finish_position', rh.finish_position,
                        'time_str', rh.time_str,
                        'time_sec', rh.time_sec,
                        'last_3f', rh.last_3f,
                        'passing', rh.passing,
                        'odds', rh.odds,
                        'popularity', rh.popularity,
                        'jockey', rh.jockey,
                        'weight_carried', rh.weight_carried,
                        'horse_weight', rh.horse_weight
                    )
                ) FROM race_horses rh WHERE rh.race_id = r.race_id
                ) as horses_json
                FROM races r {where}
                ORDER BY r.date, r.race_id""",
            params,
        ).fetchall()

        result = []
        for race in races:
            d = dict(race)
            d["horses"] = json.loads(d.pop("horses_json"))
            result.append(d)
        return result

    def iter_race_ids(self, year: int = None) -> list[str]:
        """収集済みの race_id 一覧を返す（高速）"""
        conn = self._get_conn()
        if year:
            rows = conn.execute(
                "SELECT race_id FROM races WHERE date LIKE ? ORDER BY race_id",
                (f"{year}-%",),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT race_id FROM races ORDER BY race_id"
            ).fetchall()
        return [r["race_id"] for r in rows]

    # =========================================================================
    # 読み出し: ベースタイム統計
    # =========================================================================

    def get_base_time_stats(self) -> list[dict]:
        """会場×馬場×距離×馬場状態ごとの勝ち馬タイム統計を返す"""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT r.venue, r.surface, r.distance, r.track_condition,
                      COUNT(*) as sample_count,
                      AVG(rh.time_sec) as avg_time,
                      MIN(rh.time_sec) as min_time,
                      MAX(rh.time_sec) as max_time
               FROM races r
               JOIN race_horses rh ON r.race_id = rh.race_id
               WHERE rh.finish_position = 1 AND rh.time_sec IS NOT NULL
               GROUP BY r.venue, r.surface, r.distance, r.track_condition
               HAVING COUNT(*) >= 3
               ORDER BY r.venue, r.surface, r.distance""",
        ).fetchall()
        return [dict(r) for r in rows]

    # =========================================================================
    # 読み出し: 払い戻し
    # =========================================================================

    def get_payouts(self, race_id: str) -> dict:
        """レースの払い戻し情報を返す"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT bet_type, selections, payout FROM payouts WHERE race_id = ?",
            (race_id,),
        ).fetchall()
        return {r["bet_type"]: {"selections": r["selections"], "payout": r["payout"]}
                for r in rows}

    # =========================================================================
    # ユーティリティ
    # =========================================================================

    def race_exists(self, race_id: str) -> bool:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT 1 FROM races WHERE race_id = ?", (race_id,)
        ).fetchone()
        return row is not None

    def race_count(self, year: int = None) -> int:
        conn = self._get_conn()
        if year:
            row = conn.execute(
                "SELECT COUNT(*) as n FROM races WHERE date LIKE ?",
                (f"{year}-%",),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) as n FROM races").fetchone()
        return row["n"]

    def stats(self) -> dict:
        conn = self._get_conn()
        race_n = conn.execute("SELECT COUNT(*) as n FROM races").fetchone()["n"]
        horse_n = conn.execute(
            "SELECT COUNT(DISTINCT horse_id) as n FROM race_horses"
        ).fetchone()["n"]
        entry_n = conn.execute("SELECT COUNT(*) as n FROM race_horses").fetchone()["n"]
        date_range = conn.execute(
            "SELECT MIN(date) as min_d, MAX(date) as max_d FROM races"
        ).fetchone()
        venues = conn.execute(
            "SELECT venue, COUNT(*) as n FROM races GROUP BY venue ORDER BY n DESC"
        ).fetchall()
        return {
            "total_races": race_n,
            "unique_horses": horse_n,
            "total_entries": entry_n,
            "date_range": {
                "from": date_range["min_d"],
                "to": date_range["max_d"],
            } if date_range["min_d"] else None,
            "venues": {r["venue"]: r["n"] for r in venues},
        }
