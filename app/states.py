from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class SetupChips(StatesGroup):
    waiting_stickers = State()


class BattlePick(StatesGroup):
    picking = State()


class DuelCreate(StatesGroup):
    picking = State()


class DuelAccept(StatesGroup):
    picking = State()


class MatchmakingPick(StatesGroup):
    picking = State()


class EnergySpend(StatesGroup):
    menu = State()
    upgrade = State()
    add_sticker = State()

