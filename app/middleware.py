from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.cleanup import flush as _flush_msgs
from app.config import Config
from app.db import Database
from app.i18n import get_event_lang
from app.services.avatars import AvatarCache
from app.services.stickers import StickerCache

_SKIP_FLUSH: tuple[str, ...] = (
    "noop",
    "pick_toggle:",
    "mm_pick_toggle:",
    "duel_pick_toggle:",
    "duel2_pick_toggle:",
    "duel_pick_all",
    "pick_all",
    "mm_pick_all",
    "eu+:",
    "setup_done_disabled",
    "duel_decline:",
)


class DI(BaseMiddleware):
    def __init__(self, *, db: Database, cache: StickerCache, avatars: AvatarCache, cfg: Config):
        self._db = db
        self._cache = cache
        self._avatars = avatars
        self._cfg = cfg

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        from_user = getattr(event, "from_user", None)
        lang = get_event_lang(event)
        if from_user is not None:
            await self._db.get_or_create_user(int(from_user.id), ui_language=lang)
        data["db"] = self._db
        data["cache"] = self._cache
        data["avatars"] = self._avatars
        data["cfg"] = self._cfg
        data["lang"] = lang

        bot = data.get("bot")
        if bot and from_user is not None:
            cb_data = getattr(event, "data", None)
            should_flush = True
            if cb_data:
                for prefix in _SKIP_FLUSH:
                    if cb_data == prefix or cb_data.startswith(prefix):
                        should_flush = False
                        break
            if should_flush:
                await _flush_msgs(bot, int(from_user.id))

        return await handler(event, data)
