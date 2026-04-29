from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    default_sticker_set_name: str
    data_dir: str
    admin_id: int | None


def load_config() -> Config:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is missing in .env")

    sticker_set = os.getenv("DEFAULT_STICKER_SET_NAME", "").strip()
    if not sticker_set:
        raise RuntimeError("DEFAULT_STICKER_SET_NAME is missing in .env")

    data_dir = os.path.abspath(os.path.join(os.getcwd(), "data"))
    os.makedirs(data_dir, exist_ok=True)
    admin_id_str = os.getenv("ADMIN_ID", "").strip()
    admin_id: int | None = int(admin_id_str) if admin_id_str.lstrip("-").isdigit() else None
    return Config(bot_token=token, default_sticker_set_name=sticker_set, data_dir=data_dir, admin_id=admin_id)

