from __future__ import annotations

import os

import httpx
from aiogram import Bot


class AvatarCache:
    def __init__(self, base_dir: str):
        self.base_dir = os.path.join(base_dir, "avatar_cache")
        os.makedirs(self.base_dir, exist_ok=True)

    def _path_for(self, user_id: int, file_unique_id: str, ext: str) -> str:
        safe = "".join(ch for ch in file_unique_id if ch.isalnum() or ch in ("-", "_"))
        return os.path.join(self.base_dir, f"{user_id}_{safe}.{ext}")

    async def _download_file(self, bot: Bot, user_id: int, file_id: str, file_unique_id: str) -> str | None:
        tg_file = await bot.get_file(file_id)
        if not tg_file.file_path:
            return None
        ext = os.path.splitext(tg_file.file_path)[1].lstrip(".").lower() or "jpg"
        local = self._path_for(user_id, file_unique_id, ext)
        if os.path.exists(local) and os.path.getsize(local) > 0:
            return local
        url = f"https://api.telegram.org/file/bot{bot.token}/{tg_file.file_path}"
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url)
            r.raise_for_status()
            with open(local, "wb") as f:
                f.write(r.content)
        return local

    async def get_avatar_path(self, bot: Bot, user_id: int) -> str | None:
        try:
            photos = await bot.get_user_profile_photos(user_id=user_id, limit=1)
            if photos.photos:
                best = photos.photos[0][-1]
                return await self._download_file(bot, user_id, best.file_id, best.file_unique_id)
        except Exception:
            pass
        try:
            chat = await bot.get_chat(user_id)
            if chat.photo:
                return await self._download_file(bot, user_id, chat.photo.small_file_id, chat.photo.small_file_unique_id)
        except Exception:
            pass
        return None

