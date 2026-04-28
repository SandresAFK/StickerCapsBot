from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
from aiogram import Bot


@dataclass(frozen=True)
class StickerAsset:
    file_id: str
    local_path: str


class StickerCache:
    def __init__(self, base_dir: str):
        self.base_dir = os.path.join(base_dir, "sticker_cache")
        os.makedirs(self.base_dir, exist_ok=True)

    def _path_for(self, file_unique_id: str, ext: str) -> str:
        safe = "".join(ch for ch in file_unique_id if ch.isalnum() or ch in ("-", "_"))
        return os.path.join(self.base_dir, f"{safe}.{ext}")

    async def get_static_sticker_path(self, bot: Bot, file_id: str) -> StickerAsset:
        tg_file = await bot.get_file(file_id)
        if not tg_file.file_path:
            raise RuntimeError("Sticker file_path is empty")
        ext = os.path.splitext(tg_file.file_path)[1].lstrip(".").lower() or "bin"
        if ext in ("tgs", "webm"):
            raise RuntimeError("non-static sticker")

        local = self._path_for(tg_file.file_unique_id, ext)
        if os.path.exists(local) and os.path.getsize(local) > 0:
            return StickerAsset(file_id=file_id, local_path=local)

        url = f"https://api.telegram.org/file/bot{bot.token}/{tg_file.file_path}"
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url)
            r.raise_for_status()
            with open(local, "wb") as f:
                f.write(r.content)
        return StickerAsset(file_id=file_id, local_path=local)


async def pick_enemy_stickers(bot: Bot, sticker_set_name: str, n: int = 5) -> list[str]:
    import random

    st_set = await bot.get_sticker_set(sticker_set_name)
    candidates: list[str] = []
    for s in st_set.stickers:
        if (not s.is_animated and not s.is_video):
            candidates.append(s.file_id)
            continue
        thumb = getattr(s, "thumbnail", None)
        if thumb and getattr(thumb, "file_id", None):
            candidates.append(str(thumb.file_id))
    if not candidates:
        raise RuntimeError("Sticker set has no usable stickers")
    return [random.choice(candidates) for _ in range(n)]

