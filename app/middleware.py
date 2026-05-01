from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.config import Config
from app.db import Database
from app.i18n import get_event_lang
from app.services.avatars import AvatarCache
from app.services.stickers import StickerCache


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
        return await handler(event, data)

