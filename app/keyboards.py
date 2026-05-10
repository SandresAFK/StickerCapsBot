from __future__ import annotations

from typing import Dict, List, Tuple

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.i18n import t


def kb_start(no_chips: bool, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if no_chips:
        b.button(text=t(lang, "use_favorite_stickers"), callback_data="setup")
        b.button(text=t(lang, "use_default_stickers"), callback_data="setup_default")
    else:
        b.button(text=t(lang, "collection"), callback_data="collection")
        b.button(text=t(lang, "battle_with_friend"), callback_data="pvp")
    b.adjust(1)
    return b.as_markup()


def kb_collection_only(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "collection"), callback_data="collection")
    b.adjust(1)
    return b.as_markup()


def kb_result_actions(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "rematch"), callback_data="pvp")
    b.button(text=t(lang, "collection"), callback_data="collection")
    b.adjust(2)
    return b.as_markup()


def kb_duel_result_actions(opponent_id: int, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "rematch"), callback_data=f"duel_rematch:{int(opponent_id)}")
    b.button(text=t(lang, "collection"), callback_data="collection")
    b.adjust(2)
    return b.as_markup()


def kb_profile_actions(energy: int, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if energy > 0:
        b.button(text=t(lang, "daily_energy_spend", energy=energy), callback_data="e")
    else:
        b.button(text=t(lang, "daily_energy", energy=0), callback_data="e")
    b.button(text=t(lang, "collection"), callback_data="collection")
    b.button(text=t(lang, "matchmaking"), callback_data="mm")
    b.button(text=t(lang, "battle_with_friend"), callback_data="pvp")
    b.button(text=t(lang, "leaderboard"), callback_data="leaderboard")
    b.adjust(1)
    return b.as_markup()


def kb_no_chips(energy: int, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if energy > 0:
        b.button(text=t(lang, "daily_energy_spend", energy=energy), callback_data="e")
    else:
        b.button(text=t(lang, "daily_energy", energy=0), callback_data="e")
    b.button(text=t(lang, "collection"), callback_data="collection")
    b.button(text=t(lang, "leaderboard"), callback_data="leaderboard")
    b.adjust(1)
    return b.as_markup()


def kb_duel_pick(inv_items: List[Tuple[str, int]], picked: Dict[str, int], lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    total_energy = 0
    all_selected = True
    for idx, (file_id, total) in enumerate(inv_items):
        cur = 1 if int(picked.get(file_id, 0)) > 0 else 0
        if cur:
            total_energy += int(total)
        else:
            all_selected = False
        mark = " ✅" if cur else ""
        b.button(text=f"№{idx+1} · ⚡️{total}{mark}", callback_data=f"duel_pick_toggle:{idx}")
    b.adjust(3)
    
    if inv_items:
        select_all_text = t(lang, "deselect_all") if all_selected else t(lang, "select_all")
        b.row(InlineKeyboardButton(text=select_all_text, callback_data="duel_pick_all"))
        
    b.row(InlineKeyboardButton(text=t(lang, "create_challenge", energy=total_energy), callback_data="duel_create"))
    b.row(InlineKeyboardButton(text=t(lang, "button_cancel"), callback_data="duel_cancel"))
    return b.as_markup()



def kb_duel_offer(duel_id: str, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "accept"), callback_data=f"duel_accept:{duel_id}")
    b.button(text=t(lang, "decline"), callback_data=f"duel_decline:{duel_id}")
    b.adjust(1)
    return b.as_markup()


def kb_share_duel(invite_text: str, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=t(lang, "forward_battle_link"), switch_inline_query=invite_text))
    b.row(InlineKeyboardButton(text=t(lang, "button_cancel"), callback_data="duel_share_cancel"))
    return b.as_markup()


def kb_duel_accept_pick(inv_items: List[Tuple[str, int]], picked: Dict[str, int], target_energy: int, duel_id: str, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    total_energy = 0
    all_selected = True
    for idx, (file_id, total) in enumerate(inv_items):
        cur = 1 if int(picked.get(file_id, 0)) > 0 else 0
        if cur:
            total_energy += int(total)
        else:
            all_selected = False
        mark = " ✅" if cur else ""
        b.button(text=f"№{idx+1} · ⚡️{total}{mark}", callback_data=f"duel2_pick_toggle:{idx}")
    b.adjust(3)
    
    if inv_items:
        select_all_text = t(lang, "deselect_all") if all_selected else t(lang, "select_all")
        b.row(InlineKeyboardButton(text=select_all_text, callback_data=f"duel2_pick_all:{duel_id}"))

    can_accept = (total_energy == int(target_energy))
    b.row(InlineKeyboardButton(text=t(lang, "accept_battle", current=total_energy, target=target_energy), callback_data=(f"duel_accept_go:{duel_id}" if can_accept else "noop")))
    b.row(InlineKeyboardButton(text=t(lang, "button_cancel"), callback_data=f"duel_accept_cancel:{duel_id}"))
    return b.as_markup()



def kb_setup_confirm(can_confirm: bool, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "ready"), callback_data=("setup_done" if can_confirm else "setup_done_disabled"))
    b.button(text=t(lang, "button_cancel"), callback_data="setup_cancel")
    b.adjust(1)
    return b.as_markup()


def kb_battle_pick(inv_items: List[Tuple[str, int]], picked: Dict[str, int], lang: str, required: int = 3) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    total_energy = 0
    all_selected = True
    for idx, (file_id, total) in enumerate(inv_items):
        cur = 1 if int(picked.get(file_id, 0)) > 0 else 0
        if cur:
            total_energy += int(total)
        else:
            all_selected = False
        mark = " ✅" if cur else ""
        b.button(text=f"№{idx+1} · ⚡️{total}{mark}", callback_data=f"pick_toggle:{idx}")
    b.adjust(3)
    
    if inv_items:
        select_all_text = t(lang, "deselect_all") if all_selected else t(lang, "select_all")
        b.row(InlineKeyboardButton(text=select_all_text, callback_data="pick_all"))

    b.row(InlineKeyboardButton(text=t(lang, "start_battle", energy=total_energy), callback_data="battle_go"))
    b.row(InlineKeyboardButton(text=t(lang, "button_cancel"), callback_data="battle_cancel"))
    return b.as_markup()



def kb_energy_menu(energy: int, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=f"⚡️ {energy}/3", callback_data="noop")
    b.button(text=t(lang, "upgrade_existing_chips"), callback_data="eu")
    b.button(text=t(lang, "add_new_chip"), callback_data="ea")
    b.button(text=t(lang, "back"), callback_data="collection")
    b.adjust(1)
    return b.as_markup()


def kb_energy_upgrade(inv_items: List[Tuple[str, int]], spend: Dict[str, int], energy: int, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    used = sum(int(x) for x in spend.values())
    for idx, (file_id, total) in enumerate(inv_items):
        add = int(spend.get(file_id, 0))
        mark = f" +{add}" if add > 0 else ""
        b.button(text=f"№{idx+1} · ⚡{total}{mark}", callback_data=f"eu+:{idx}")
    b.adjust(3)
    b.row(InlineKeyboardButton(text=t(lang, "upgrade_apply", used=used, energy=energy), callback_data="eu_go"))
    b.row(InlineKeyboardButton(text=t(lang, "button_cancel"), callback_data="eu_cancel"))
    return b.as_markup()


def kb_ea_collect(count: int, max_e: int, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if count > 0:
        b.button(text=t(lang, "ea_confirm_btn", count=count, max=max_e), callback_data="ea_confirm")
    b.button(text=t(lang, "button_cancel"), callback_data="ea_cancel")
    b.adjust(1)
    return b.as_markup()


def kb_matchmaking_pick(inv_items: List[Tuple[str, int]], picked: Dict[str, int], lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    total_energy = 0
    all_selected = True
    for idx, (file_id, total) in enumerate(inv_items):
        cur = 1 if int(picked.get(file_id, 0)) > 0 else 0
        if cur:
            total_energy += int(total)
        else:
            all_selected = False
        mark = " ✅" if cur else ""
        b.button(text=f"№{idx+1} · ⚡️{total}{mark}", callback_data=f"mm_pick_toggle:{idx}")
    b.adjust(3)
    
    if inv_items:
        select_all_text = t(lang, "deselect_all") if all_selected else t(lang, "select_all")
        b.row(InlineKeyboardButton(text=select_all_text, callback_data="mm_pick_all"))

    b.row(InlineKeyboardButton(text=t(lang, "start_mm", energy=total_energy), callback_data="mm_go"))
    b.row(InlineKeyboardButton(text=t(lang, "mm_cancel"), callback_data="mm_cancel"))
    return b.as_markup()



def kb_matchmaking_result(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "mm_rematch"), callback_data="mm")
    b.button(text=t(lang, "collection"), callback_data="collection")
    b.adjust(2)
    return b.as_markup()


def kb_reset_confirm(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "reset_confirm"), callback_data="reset_ok")
    b.button(text=t(lang, "button_cancel"), callback_data="reset_no")
    b.adjust(1)
    return b.as_markup()

