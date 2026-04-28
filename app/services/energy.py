from __future__ import annotations

import time

from app.db import Database, User


MAX_ENERGY = 3


def utc_midnight_ts(ts: int) -> int:
    return int(ts) - (int(ts) % (60 * 60 * 24))


def seconds_until_next_utc_midnight(now: int | None = None) -> int:
    if now is None:
        now = int(time.time())
    next_midnight = utc_midnight_ts(now) + (60 * 60 * 24)
    return max(0, int(next_midnight) - int(now))


async def get_user_with_regen(db: Database, user_id: int) -> User:
    user = await db.get_or_create_user(user_id)
    now = int(time.time())
    last_midnight = utc_midnight_ts(now)
    if int(user.energy_updated_at) < int(last_midnight):
        await db.update_energy(user_id, MAX_ENERGY, updated_at=last_midnight)
        return User(user_id=user.user_id, energy=MAX_ENERGY, energy_updated_at=last_midnight, setup_done=user.setup_done, created_at=user.created_at)
    return user

