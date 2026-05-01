from __future__ import annotations

from typing import Dict, List, Tuple

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def kb_start(no_chips: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if no_chips:
        b.button(text="Выбрать любимые стикеры", callback_data="setup")
        b.button(text="Использовать стикеры по умолчанию", callback_data="setup_default")
    else:
        b.button(text="Коллекция", callback_data="collection")
        b.button(text="Схватка с другом", callback_data="pvp")
    b.adjust(1)
    return b.as_markup()


def kb_collection_only() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Коллекция", callback_data="collection")
    b.adjust(1)
    return b.as_markup()


def kb_result_actions() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Реванш", callback_data="pvp")
    b.button(text="Коллекция", callback_data="collection")
    b.adjust(2)
    return b.as_markup()


def kb_duel_result_actions(opponent_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Реванш", callback_data=f"duel_rematch:{int(opponent_id)}")
    b.button(text="Коллекция", callback_data="collection")
    b.adjust(2)
    return b.as_markup()


def kb_profile_actions(energy: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if energy > 0:
        b.button(text=f"Ежедневная энергия: ⚡️ {energy}/3 • Потратить", callback_data="e")
    else:
        b.button(text="Ежедневная энергия: ⚡️ 0/3", callback_data="e")
    b.button(text="Коллекция", callback_data="collection")
    b.button(text="Схватка с другом", callback_data="pvp")
    b.adjust(1)
    return b.as_markup()


def kb_no_chips(energy: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if energy > 0:
        b.button(text=f"Ежедневная энергия: ⚡️ {energy}/3 • Потратить", callback_data="e")
    else:
        b.button(text="Ежедневная энергия: ⚡️ 0/3", callback_data="e")
    b.button(text="Коллекция", callback_data="collection")
    b.adjust(1)
    return b.as_markup()


def kb_duel_pick(inv_items: List[Tuple[str, int]], picked: Dict[str, int]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    total_energy = 0
    for idx, (file_id, total) in enumerate(inv_items):
        cur = 1 if int(picked.get(file_id, 0)) > 0 else 0
        if cur:
            total_energy += int(total)
        mark = " ✅" if cur else ""
        b.button(text=f"№{idx+1} · ⚡️{total}{mark}", callback_data=f"duel_pick_toggle:{idx}")
    b.adjust(3)
    b.row(InlineKeyboardButton(text=f"Создать вызов (⚡️{total_energy})", callback_data="duel_create"))
    b.row(InlineKeyboardButton(text="Отмена", callback_data="duel_cancel"))
    return b.as_markup()


def kb_duel_offer(duel_id: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Принять", callback_data=f"duel_accept:{duel_id}")
    b.button(text="Отказаться", callback_data=f"duel_decline:{duel_id}")
    b.adjust(1)
    return b.as_markup()


def kb_share_duel(invite_text: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Переслать ссылку на бой", switch_inline_query=invite_text))
    b.row(InlineKeyboardButton(text="Отмена", callback_data="duel_share_cancel"))
    return b.as_markup()


def kb_duel_accept_pick(inv_items: List[Tuple[str, int]], picked: Dict[str, int], target_energy: int, duel_id: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    total_energy = 0
    for idx, (file_id, total) in enumerate(inv_items):
        cur = 1 if int(picked.get(file_id, 0)) > 0 else 0
        if cur:
            total_energy += int(total)
        mark = " ✅" if cur else ""
        b.button(text=f"№{idx+1} · ⚡️{total}{mark}", callback_data=f"duel2_pick_toggle:{idx}")
    b.adjust(3)
    can_accept = (total_energy == int(target_energy))
    b.row(InlineKeyboardButton(text=f"Принять бой ({total_energy}/{target_energy})", callback_data=(f"duel_accept_go:{duel_id}" if can_accept else "noop")))
    b.row(InlineKeyboardButton(text="Отмена", callback_data=f"duel_accept_cancel:{duel_id}"))
    return b.as_markup()


def kb_setup_confirm(can_confirm: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Готово", callback_data=("setup_done" if can_confirm else "setup_done_disabled"))
    b.button(text="Отмена", callback_data="setup_cancel")
    b.adjust(1)
    return b.as_markup()


def kb_battle_pick(inv_items: List[Tuple[str, int]], picked: Dict[str, int], required: int = 3) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    total_energy = 0
    for idx, (file_id, total) in enumerate(inv_items):
        cur = 1 if int(picked.get(file_id, 0)) > 0 else 0
        if cur:
            total_energy += int(total)
        mark = " ✅" if cur else ""
        b.button(text=f"№{idx+1} · ⚡️{total}{mark}", callback_data=f"pick_toggle:{idx}")
    b.adjust(3)
    b.row(InlineKeyboardButton(text=f"Начать схватку (⚡️{total_energy})", callback_data="battle_go"))
    b.row(InlineKeyboardButton(text="Отмена", callback_data="battle_cancel"))
    return b.as_markup()


def kb_energy_menu(energy: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=f"⚡️ {energy}/3", callback_data="noop")
    b.button(text="Прокачать существующие фишки", callback_data="eu")
    b.button(text="Добавить новую фишку", callback_data="ea")
    b.button(text="Назад", callback_data="collection")
    b.adjust(1)
    return b.as_markup()


def kb_energy_upgrade(inv_items: List[Tuple[str, int]], spend: Dict[str, int], energy: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    used = sum(int(x) for x in spend.values())
    for idx, (file_id, total) in enumerate(inv_items):
        add = int(spend.get(file_id, 0))
        mark = f" +{add}" if add > 0 else ""
        b.button(text=f"№{idx+1} · ⚡{total}{mark} ＋", callback_data=f"eu+:{idx}")
    b.adjust(3)
    b.row(InlineKeyboardButton(text=f"Применить ({used}/{energy})", callback_data="eu_go"))
    b.row(InlineKeyboardButton(text="Отмена", callback_data="eu_cancel"))
    return b.as_markup()


def kb_reset_confirm() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Да, сбросить", callback_data="reset_ok")
    b.button(text="Отмена", callback_data="reset_no")
    b.adjust(1)
    return b.as_markup()

