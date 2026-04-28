from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.config import Config
from app.db import Database
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
        data["db"] = self._db
        data["cache"] = self._cache
        data["avatars"] = self._avatars
        data["cfg"] = self._cfg
        return await handler(event, data)

