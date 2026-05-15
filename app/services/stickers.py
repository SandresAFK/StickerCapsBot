from __future__ import annotations

import asyncio
import json
import os
import time
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
        self._map_path = os.path.join(self.base_dir, "_fileid_map.json")
        self._id_map: dict[str, str] = self._load_map()

    def _load_map(self) -> dict[str, str]:
        try:
            if os.path.exists(self._map_path):
                with open(self._map_path, encoding="utf-8") as f:
                    data = json.load(f)
                return {
                    fid: p for fid, p in data.items()
                    if isinstance(p, str) and os.path.exists(p) and os.path.getsize(p) > 0
                }
        except Exception:
            pass
        return {}

    def _save_map(self) -> None:
        try:
            with open(self._map_path, "w", encoding="utf-8") as f:
                json.dump(self._id_map, f)
        except Exception:
            pass

    def _path_for(self, file_unique_id: str, ext: str) -> str:
        safe = "".join(ch for ch in file_unique_id if ch.isalnum() or ch in ("-", "_"))
        return os.path.join(self.base_dir, f"{safe}.{ext}")

    async def get_static_sticker_path(self, bot: Bot, file_id: str) -> StickerAsset:
        # Fast path: skip bot.get_file() if already cached
        cached = self._id_map.get(file_id)
        if cached and os.path.exists(cached) and os.path.getsize(cached) > 0:
            return StickerAsset(file_id=file_id, local_path=cached)
        if cached:
            del self._id_map[file_id]

        tg_file = await bot.get_file(file_id)
        if not tg_file.file_path:
            raise RuntimeError("Sticker file_path is empty")
        ext = os.path.splitext(tg_file.file_path)[1].lstrip(".").lower() or "bin"
        if ext in ("tgs", "webm"):
            raise RuntimeError("non-static sticker")

        local = self._path_for(tg_file.file_unique_id, ext)
        if not (os.path.exists(local) and os.path.getsize(local) > 0):
            url = f"https://api.telegram.org/file/bot{bot.token}/{tg_file.file_path}"
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(url)
                r.raise_for_status()
                with open(local, "wb") as f:
                    f.write(r.content)

        self._id_map[file_id] = local
        self._save_map()
        return StickerAsset(file_id=file_id, local_path=local)

    async def get_paths_for_inv(self, bot: Bot, inv_items: list[tuple[str, int]]) -> dict[str, str]:
        """Resolve all file_ids in parallel. Returns {file_id: local_path} for successful ones."""
        results = await asyncio.gather(
            *(self.get_static_sticker_path(bot, fid) for fid, _ in inv_items),
            return_exceptions=True,
        )
        return {
            fid: r.local_path
            for (fid, _), r in zip(inv_items, results)
            if isinstance(r, StickerAsset)
        }

    async def get_paths_for_ids(self, bot: Bot, file_ids: list[str] | set[str]) -> dict[str, str]:
        """Resolve arbitrary file_ids in parallel. Returns {file_id: local_path} for successful ones."""
        fid_list = list(file_ids)
        results = await asyncio.gather(
            *(self.get_static_sticker_path(bot, fid) for fid in fid_list),
            return_exceptions=True,
        )
        return {
            fid: r.local_path
            for fid, r in zip(fid_list, results)
            if isinstance(r, StickerAsset)
        }


_sticker_set_cache: dict[str, tuple[float, list[str]]] = {}
_STICKER_SET_TTL = 600.0  # 10 minutes


async def pick_enemy_stickers(bot: Bot, sticker_set_name: str, n: int = 5) -> list[str]:
    import random

    now = time.time()
    cached = _sticker_set_cache.get(sticker_set_name)
    if cached:
        ts, candidates = cached
        if now - ts < _STICKER_SET_TTL and candidates:
            return [random.choice(candidates) for _ in range(n)]

    st_set = await bot.get_sticker_set(sticker_set_name)
    candidates: list[str] = []
    for s in st_set.stickers:
        if not s.is_animated and not s.is_video:
            candidates.append(s.file_id)
            continue
        thumb = getattr(s, "thumbnail", None)
        if thumb and getattr(thumb, "file_id", None):
            candidates.append(str(thumb.file_id))
    if not candidates:
        raise RuntimeError("Sticker set has no usable stickers")
    _sticker_set_cache[sticker_set_name] = (now, candidates)
    return [random.choice(candidates) for _ in range(n)]

