from __future__ import annotations

from typing import Dict, List

from aiogram import Bot

_to_delete: Dict[int, List[int]] = {}


def track(user_id: int, msg: object | None) -> None:
    if msg is None:
        return
    mid = getattr(msg, "message_id", None)
    if mid is not None:
        _to_delete.setdefault(int(user_id), []).append(int(mid))


async def flush(bot: Bot, user_id: int) -> None:
    ids = _to_delete.pop(int(user_id), [])
    for mid in ids:
        try:
            await bot.delete_message(chat_id=int(user_id), message_id=mid)
        except Exception:
            pass
