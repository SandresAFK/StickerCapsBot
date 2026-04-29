from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Dict

import json

import aiosqlite


@dataclass(frozen=True)
class User:
    user_id: int
    energy: int
    energy_updated_at: int
    setup_done: int
    created_at: int


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    def connect(self) -> aiosqlite.Connection:
        return aiosqlite.connect(self.db_path)

    async def _configure(self, db: aiosqlite.Connection) -> None:
        await db.execute("PRAGMA foreign_keys = ON;")
        db.row_factory = aiosqlite.Row

    async def _fetchone(self, db: aiosqlite.Connection, sql: str, params: tuple) -> aiosqlite.Row | None:
        cur = await db.execute(sql, params)
        try:
            return await cur.fetchone()
        finally:
            await cur.close()

    async def _fetchall(self, db: aiosqlite.Connection, sql: str, params: tuple) -> list[aiosqlite.Row]:
        cur = await db.execute(sql, params)
        try:
            return list(await cur.fetchall())
        finally:
            await cur.close()

    async def init(self) -> None:
        async with self.connect() as db:
            await self._configure(db)
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    energy INTEGER NOT NULL,
                    energy_updated_at INTEGER NOT NULL,
                    notify_energy_reset INTEGER NOT NULL DEFAULT 0,
                    setup_done INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS inventory (
                    user_id INTEGER NOT NULL,
                    sticker_file_id TEXT NOT NULL,
                    count INTEGER NOT NULL,
                    PRIMARY KEY (user_id, sticker_file_id),
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS duels (
                    duel_id TEXT PRIMARY KEY,
                    creator_id INTEGER NOT NULL,
                    creator_pick TEXT NOT NULL,
                    target_energy INTEGER NOT NULL,
                    opponent_id INTEGER,
                    opponent_pick TEXT,
                    status TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    completed_at INTEGER,
                    FOREIGN KEY (creator_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    FOREIGN KEY (opponent_id) REFERENCES users(user_id) ON DELETE SET NULL
                );
                """
            )
            # migrations for older DBs
            try:
                await db.execute("ALTER TABLE users ADD COLUMN notify_energy_reset INTEGER NOT NULL DEFAULT 0")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE users ADD COLUMN setup_done INTEGER NOT NULL DEFAULT 0")
            except Exception:
                pass
            await db.commit()

    async def create_duel(self, duel_id: str, creator_id: int, creator_pick: list[str], target_energy: int) -> None:
        now = int(time.time())
        async with self.connect() as db:
            await self._configure(db)
            await db.execute(
                "INSERT INTO duels(duel_id, creator_id, creator_pick, target_energy, status, created_at) VALUES(?,?,?,?,?,?)",
                (duel_id, int(creator_id), json.dumps(list(creator_pick)), int(target_energy), "open", now),
            )
            await db.commit()

    async def get_duel(self, duel_id: str) -> dict | None:
        async with self.connect() as db:
            await self._configure(db)
            row = await self._fetchone(
                db,
                "SELECT duel_id, creator_id, creator_pick, target_energy, opponent_id, opponent_pick, status, created_at, completed_at FROM duels WHERE duel_id=?",
                (duel_id,),
            )
            if not row:
                return None
            d = dict(row)
            try:
                d["creator_pick"] = json.loads(d["creator_pick"]) if d.get("creator_pick") else []
            except Exception:
                d["creator_pick"] = []
            try:
                d["opponent_pick"] = json.loads(d["opponent_pick"]) if d.get("opponent_pick") else []
            except Exception:
                d["opponent_pick"] = []
            return d

    async def accept_duel(self, duel_id: str, opponent_id: int) -> bool:
        async with self.connect() as db:
            await self._configure(db)
            row = await self._fetchone(db, "SELECT status, opponent_id FROM duels WHERE duel_id=?", (duel_id,))
            if not row or str(row["status"]) != "open":
                return False
            if row["opponent_id"] is not None:
                return False
            await db.execute(
                "UPDATE duels SET opponent_id=?, status=? WHERE duel_id=? AND status='open' AND opponent_id IS NULL",
                (int(opponent_id), "picking", duel_id),
            )
            await db.commit()
            return True

    async def set_opponent_pick(self, duel_id: str, opponent_pick: list[str]) -> None:
        async with self.connect() as db:
            await self._configure(db)
            await db.execute(
                "UPDATE duels SET opponent_pick=? WHERE duel_id=?",
                (json.dumps(list(opponent_pick)), duel_id),
            )
            await db.commit()

    async def complete_duel(self, duel_id: str) -> None:
        now = int(time.time())
        async with self.connect() as db:
            await self._configure(db)
            await db.execute(
                "UPDATE duels SET status=?, completed_at=? WHERE duel_id=?",
                ("done", now, duel_id),
            )
            await db.commit()

    async def get_or_create_user(self, user_id: int) -> User:
        now = int(time.time())
        async with self.connect() as db:
            await self._configure(db)
            row = await self._fetchone(
                db,
                "SELECT user_id, energy, energy_updated_at, setup_done, created_at FROM users WHERE user_id=?",
                (user_id,),
            )
            if row:
                return User(**dict(row))
            await db.execute(
                "INSERT INTO users(user_id, energy, energy_updated_at, notify_energy_reset, setup_done, created_at) VALUES(?,?,?,?,?,?)",
                (user_id, 3, now, 0, 0, now),
            )
            await db.commit()
            return User(user_id=user_id, energy=3, energy_updated_at=now, setup_done=0, created_at=now)

    async def set_setup_done(self, user_id: int, value: int) -> None:
        async with self.connect() as db:
            await self._configure(db)
            await db.execute(
                "UPDATE users SET setup_done=? WHERE user_id=?",
                (1 if int(value) else 0, int(user_id)),
            )
            await db.commit()

    async def set_notify_energy_reset(self, user_id: int, value: int) -> None:
        async with self.connect() as db:
            await self._configure(db)
            await db.execute(
                "UPDATE users SET notify_energy_reset=? WHERE user_id=?",
                (1 if int(value) else 0, int(user_id)),
            )
            await db.commit()

    async def get_users_to_notify_energy_reset(self) -> list[int]:
        async with self.connect() as db:
            await self._configure(db)
            rows = await self._fetchall(db, "SELECT user_id FROM users WHERE notify_energy_reset=1", ())
            return [int(r["user_id"]) for r in rows]

    async def get_all_user_ids(self) -> list[int]:
        async with self.connect() as db:
            await self._configure(db)
            rows = await self._fetchall(db, "SELECT user_id FROM users", ())
            return [int(r["user_id"]) for r in rows]

    async def clear_notify_energy_reset(self, user_ids: list[int]) -> None:
        if not user_ids:
            return
        async with self.connect() as db:
            await self._configure(db)
            q = ",".join(["?"] * len(user_ids))
            await db.execute(f"UPDATE users SET notify_energy_reset=0 WHERE user_id IN ({q})", tuple(int(x) for x in user_ids))
            await db.commit()

    async def reset_energy_for_all(self, energy: int, updated_at: int) -> None:
        async with self.connect() as db:
            await self._configure(db)
            await db.execute("UPDATE users SET energy=?, energy_updated_at=?", (int(energy), int(updated_at)))
            await db.commit()

    async def update_energy(self, user_id: int, energy: int, updated_at: int | None = None) -> None:
        if updated_at is None:
            updated_at = int(time.time())
        async with self.connect() as db:
            await self._configure(db)
            await db.execute(
                "UPDATE users SET energy=?, energy_updated_at=? WHERE user_id=?",
                (int(energy), int(updated_at), user_id),
            )
            await db.commit()

    async def get_inventory(self, user_id: int) -> Dict[str, int]:
        async with self.connect() as db:
            await self._configure(db)
            rows = await self._fetchall(
                db,
                "SELECT sticker_file_id, count FROM inventory WHERE user_id=? ORDER BY sticker_file_id",
                (user_id,),
            )
            return {r["sticker_file_id"]: int(r["count"]) for r in rows}

    async def set_inventory_exact(self, user_id: int, counts: Dict[str, int]) -> None:
        async with self.connect() as db:
            await self._configure(db)
            await db.execute("DELETE FROM inventory WHERE user_id=?", (user_id,))
            for file_id, cnt in counts.items():
                if int(cnt) <= 0:
                    continue
                await db.execute(
                    "INSERT INTO inventory(user_id, sticker_file_id, count) VALUES(?,?,?)",
                    (user_id, file_id, int(cnt)),
                )
            await db.commit()

    async def get_user_duels_count(self, user_id: int) -> int:
        async with self.connect() as db:
            await self._configure(db)
            row = await self._fetchone(
                db,
                "SELECT COUNT(*) as cnt FROM duels WHERE status='done' AND (creator_id=? OR opponent_id=?)",
                (user_id, user_id),
            )
            return int(row["cnt"]) if row else 0

    async def get_all_users_stats(self) -> list[dict]:
        async with self.connect() as db:
            await self._configure(db)
            rows = await self._fetchall(
                db,
                """
                SELECT u.user_id, u.energy, u.setup_done, u.created_at,
                       COUNT(DISTINCT i.sticker_file_id) as chips_count,
                       COALESCE(SUM(i.count), 0) as total_nominal,
                       (SELECT COUNT(*) FROM duels d WHERE d.status='done' AND (d.creator_id=u.user_id OR d.opponent_id=u.user_id)) as duels_count
                FROM users u
                LEFT JOIN inventory i ON i.user_id = u.user_id
                GROUP BY u.user_id
                ORDER BY u.created_at DESC
                """,
                (),
            )
            return [dict(r) for r in rows]

    async def add_inventory(self, user_id: int, delta: Dict[str, int]) -> None:
        async with self.connect() as db:
            await self._configure(db)
            for file_id, d in delta.items():
                d = int(d)
                if d == 0:
                    continue
                row = await self._fetchone(
                    db,
                    "SELECT count FROM inventory WHERE user_id=? AND sticker_file_id=?",
                    (user_id, file_id),
                )
                if row is None:
                    if d > 0:
                        await db.execute(
                            "INSERT INTO inventory(user_id, sticker_file_id, count) VALUES(?,?,?)",
                            (user_id, file_id, d),
                        )
                else:
                    new_count = int(row["count"]) + d
                    if new_count > 0:
                        await db.execute(
                            "UPDATE inventory SET count=? WHERE user_id=? AND sticker_file_id=?",
                            (new_count, user_id, file_id),
                        )
                    else:
                        await db.execute(
                            "DELETE FROM inventory WHERE user_id=? AND sticker_file_id=?",
                            (user_id, file_id),
                        )
            await db.commit()

