from __future__ import annotations

import functools
import hashlib
import os
import asyncio
import secrets
import time
from typing import Dict, List, Tuple

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ContentType
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto, Message

from app.cleanup import flush as _flush, track as _track
from app.config import Config, load_config
from app.db import Database
from app.i18n import get_event_lang, t
from app.keyboards import kb_battle_pick, kb_duel_accept_pick, kb_duel_offer, kb_duel_pick, kb_duel_result_actions, kb_ea_collect, kb_energy_menu, kb_energy_upgrade, kb_matchmaking_pick, kb_matchmaking_result, kb_no_chips, kb_profile_actions, kb_reset_confirm, kb_result_actions, kb_setup_confirm, kb_share_duel, kb_start
from app.middleware import DI
from app.render.profile import RenderSticker, render_battle_result, render_duel_result, render_profile
from app.services.avatars import AvatarCache
from app.services.battle import BattleUnit, counts_from_list, distribute_by_slot, run_battle
from app.services.energy import MAX_ENERGY, get_user_with_regen, seconds_until_next_utc_midnight, utc_midnight_ts
from app.services.stickers import StickerCache, pick_enemy_stickers
from app.states import BattlePick, DuelAccept, DuelCreate, EnergySpend, MatchmakingPick, SetupChips

router = Router()


async def _in_executor(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))


_render_hashes: dict[str, str] = {}


def _render_cached(out_path: str, *args) -> bool:
    h = hashlib.md5(str(args).encode()).hexdigest()[:12]
    if _render_hashes.get(out_path) == h and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        return True
    _render_hashes[out_path] = h
    return False


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery) -> None:
    # Used for disabled buttons in inline keyboards.
    await cb.answer(_t(cb, "noop_hint"), show_alert=False)


async def _loading(cb: CallbackQuery) -> None:
    try:
        await cb.answer(_t(cb, "loading"), show_alert=False)
    except Exception:
        pass


def _fmt_seconds(secs: int) -> str:
    secs = max(0, int(secs))
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _t(event: Message | CallbackQuery, key: str, **kwargs) -> str:
    return t(get_event_lang(event), key, **kwargs)


async def _user_lang(db: Database, user_id: int) -> str:
    return await db.get_ui_language(user_id)


def _energy_wait_text(*, energy: int, updated_at: int, lang: str) -> str:
    if int(energy) >= int(MAX_ENERGY):
        return t(lang, "energy_full", energy=energy, max_energy=MAX_ENERGY)
    left = seconds_until_next_utc_midnight()
    return t(lang, "no_energy_wait", time_left=_fmt_seconds(left))


def _no_energy_and_chips_text(*, energy: int, updated_at: int, lang: str) -> str:
    return t(
        lang,
        "no_chips_and_energy",
        energy_text=_energy_wait_text(energy=energy, updated_at=updated_at, lang=lang),
    )


async def _notify_user_no_chips(*, bot: Bot, db: Database, user_id: int) -> None:
    lang = await _user_lang(db, user_id)
    left = seconds_until_next_utc_midnight()
    await db.set_notify_energy_reset(user_id, 1)
    msg = await bot.send_message(
        chat_id=user_id,
        text=t(lang, "no_chips_notify", time_left=_fmt_seconds(left)),
    )
    _track(user_id, msg)


async def _energy_reset_worker(*, bot: Bot, db: Database, cache: StickerCache, avatars: AvatarCache) -> None:
    while True:
        try:
            await asyncio.sleep(seconds_until_next_utc_midnight() + 1)
            ts = int(time.time())
            midnight = utc_midnight_ts(ts)
            await db.reset_energy_for_all(MAX_ENERGY, updated_at=midnight)
            user_ids = await db.get_all_user_ids()
            for uid in user_ids:
                try:
                    lang = await _user_lang(db, uid)
                    _msg = await bot.send_message(
                        chat_id=uid,
                        text=t(lang, "energy_restored"),
                    )
                    _track(uid, _msg)
                    await _send_profile_to_user(uid, bot=bot, db=db, cache=cache, avatars=avatars)
                except Exception:
                    pass
        except Exception:
            await asyncio.sleep(5)


def _display_name(obj: Message | CallbackQuery, lang: str | None = None) -> str:
    u = obj.from_user
    current_lang = lang or get_event_lang(obj)
    if not u:
        return t(current_lang, "player")
    if u.username:
        return f"@{u.username}"
    return u.full_name or t(current_lang, "player_by_id", user_id=u.id)


def _battle_score_title(my_slot: int, their_slot: int) -> str:
    return f"{my_slot} vs {their_slot}"


async def _display_name_by_id(bot: Bot, user_id: int, lang: str = "en") -> str:
    try:
        chat = await bot.get_chat(user_id)
        if getattr(chat, "username", None):
            return f"@{chat.username}"
        if getattr(chat, "full_name", None):
            return str(chat.full_name)
    except Exception:
        pass
    return t(lang, "player_by_id", user_id=user_id)


def _inv_to_render(paths: Dict[str, str], inv_items: List[Tuple[str, int]]) -> List[RenderSticker]:
    out: List[RenderSticker] = []
    for file_id, cnt in inv_items:
        p = paths.get(file_id)
        if p:
            out.append(RenderSticker(file_id=file_id, path=p, count=int(cnt)))
    return out


async def _render_and_send_profile(message_or_cb: Message | CallbackQuery, *, bot: Bot, db: Database, cache: StickerCache, avatars: AvatarCache, user_id: int, edit_in_place: bool = False) -> None:
    lang = get_event_lang(message_or_cb)
    user = await get_user_with_regen(db, user_id)
    inv = await db.get_inventory(user_id)
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    paths = await cache.get_paths_for_inv(bot, inv_items)
    avatar = await avatars.get_avatar_path(bot, user_id)
    out = os.path.join(os.getcwd(), "data", "renders", f"profile_{user_id}.webp")
    empty_lines: list[str] | None = None
    if len(inv_items) == 0:
        if int(user.setup_done) == 0:
            empty_lines = [t(lang, "no_chips_setup_hint")]
        else:
            left = seconds_until_next_utc_midnight()
            empty_lines = [
                t(lang, "no_chips_wait_line", time_left=_fmt_seconds(left)),
                t(lang, "notification_when_energy_restored"),
            ]
    duels_count = await db.get_user_duels_count(user_id)
    if not _render_cached(out, tuple(inv_items), duels_count, lang, avatar, str(empty_lines)):
        await _in_executor(
            render_profile,
            user_title=_display_name(message_or_cb, lang),
            avatar_path=avatar,
            stickers=_inv_to_render(paths, inv_items),
            out_path=out,
            empty_lines=empty_lines,
            duels_count=duels_count,
            lang=lang,
        )

    if len(inv_items) == 0:
        if int(user.setup_done) == 0:
            markup = kb_start(no_chips=True, lang=lang)
        else:
            markup = kb_no_chips(user.energy, lang=lang)
    else:
        markup = kb_profile_actions(user.energy, lang=lang)
    pic = FSInputFile(out)
    if isinstance(message_or_cb, CallbackQuery):
        if edit_in_place and message_or_cb.message:
            try:
                await message_or_cb.message.edit_media(media=InputMediaPhoto(media=pic, caption=t(lang, "collection_caption")), reply_markup=markup)
                _track(user_id, message_or_cb.message)
            except Exception:
                _msg = await message_or_cb.message.answer_photo(pic, caption=t(lang, "collection_caption"), reply_markup=markup)
                _track(user_id, _msg)
        else:
            _msg = await message_or_cb.message.answer_photo(pic, caption=t(lang, "collection_caption"), reply_markup=markup)
            _track(user_id, _msg)
        try:
            await message_or_cb.answer()
        except Exception:
            pass
    else:
        _msg = await message_or_cb.answer_photo(pic, caption=t(lang, "collection_caption"), reply_markup=markup)
        _track(user_id, _msg)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await state.clear()
    await db.get_or_create_user(message.from_user.id, ui_language=get_event_lang(message))
    arg = ""
    try:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) > 1:
            arg = parts[1].strip()
    except Exception:
        arg = ""
    if arg.startswith("duel_"):
        duel_id = arg[len("duel_") :]
        await _show_duel_offer(message, duel_id=duel_id, db=db, bot=bot, cache=cache, avatars=avatars)
        return
    await _render_and_send_profile(message, bot=bot, db=db, cache=cache, avatars=avatars, user_id=message.from_user.id)


@router.callback_query(F.data == "collection")
async def cb_collection(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await _loading(cb)
    await state.clear()
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=True)


@router.callback_query(F.data == "result_collection")
async def cb_result_collection(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await _loading(cb)
    await state.clear()
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=False)


@router.callback_query(F.data == "pvp")
async def cb_pvp(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache) -> None:
    await _loading(cb)
    lang = get_event_lang(cb)
    inv = await db.get_inventory(cb.from_user.id)
    if not inv:
        await cb.answer(t(lang, "setup_first"), show_alert=False)
        return
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    await state.set_state(DuelCreate.picking)
    await state.update_data(picked={}, inv_order=[k for k, _ in inv_items], rematch_opponent_id=0)

    paths = await cache.get_paths_for_inv(bot, inv_items)
    out = os.path.join(os.getcwd(), "data", "renders", f"duel_pick_{cb.from_user.id}.webp")
    if not _render_cached(out, tuple(inv_items), lang):
        await _in_executor(render_profile, user_title=_display_name(cb, lang), avatar_path=None, stickers=_inv_to_render(paths, inv_items), out_path=out, lang=lang)
    pic = FSInputFile(out)
    caption = t(lang, "choose_chips_buttons")
    if cb.message:
        try:
            await cb.message.edit_media(media=InputMediaPhoto(media=pic, caption=caption), reply_markup=kb_duel_pick(inv_items, picked={}, lang=lang))
            _track(cb.from_user.id, cb.message)
        except Exception:
            _msg = await cb.message.answer_photo(pic, caption=caption, reply_markup=kb_duel_pick(inv_items, picked={}, lang=lang))
            _track(cb.from_user.id, _msg)
    await cb.answer()


@router.callback_query(F.data == "result_pvp")
async def cb_result_pvp(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache) -> None:
    await _loading(cb)
    lang = get_event_lang(cb)
    inv = await db.get_inventory(cb.from_user.id)
    if not inv:
        await cb.answer(t(lang, "setup_first"), show_alert=False)
        return
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    await state.set_state(DuelCreate.picking)
    await state.update_data(picked={}, inv_order=[k for k, _ in inv_items], rematch_opponent_id=0)

    paths = await cache.get_paths_for_inv(bot, inv_items)
    out = os.path.join(os.getcwd(), "data", "renders", f"duel_pick_{cb.from_user.id}.webp")
    if not _render_cached(out, tuple(inv_items), lang):
        await _in_executor(render_profile, user_title=_display_name(cb, lang), avatar_path=None, stickers=_inv_to_render(paths, inv_items), out_path=out, lang=lang)
    pic = FSInputFile(out)
    caption = t(lang, "choose_chips_buttons")
    if cb.message:
        _msg = await cb.message.answer_photo(pic, caption=caption, reply_markup=kb_duel_pick(inv_items, picked={}, lang=lang))
        _track(cb.from_user.id, _msg)
    await cb.answer()


@router.callback_query(F.data.startswith("duel_rematch:"))
async def cb_duel_rematch(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache) -> None:
    await _loading(cb)
    lang = get_event_lang(cb)
    try:
        opponent_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer(t(lang, "stale_button"), show_alert=False)
        return
    if opponent_id == cb.from_user.id:
        await cb.answer(t(lang, "cannot_challenge_self"), show_alert=False)
        return

    inv = await db.get_inventory(cb.from_user.id)
    if not inv:
        await cb.answer(t(lang, "setup_first"), show_alert=False)
        return
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    await state.set_state(DuelCreate.picking)
    await state.update_data(picked={}, inv_order=[k for k, _ in inv_items], rematch_opponent_id=opponent_id)

    paths = await cache.get_paths_for_inv(bot, inv_items)
    out = os.path.join(os.getcwd(), "data", "renders", f"duel_pick_{cb.from_user.id}.webp")
    if not _render_cached(out, tuple(inv_items), lang):
        await _in_executor(render_profile, user_title=_display_name(cb, lang), avatar_path=None, stickers=_inv_to_render(paths, inv_items), out_path=out, lang=lang)
    pic = FSInputFile(out)
    caption = t(lang, "choose_chips_buttons")
    if cb.message:
        try:
            await cb.message.edit_media(media=InputMediaPhoto(media=pic, caption=caption), reply_markup=kb_duel_pick(inv_items, picked={}, lang=lang))
            _track(cb.from_user.id, cb.message)
        except Exception:
            _msg = await cb.message.answer_photo(pic, caption=caption, reply_markup=kb_duel_pick(inv_items, picked={}, lang=lang))
            _track(cb.from_user.id, _msg)
    await cb.answer()


@router.callback_query(F.data.startswith("duel_rematch_new:"))
async def cb_duel_rematch_new(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache) -> None:
    await _loading(cb)
    lang = get_event_lang(cb)
    try:
        opponent_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer(t(lang, "stale_button"), show_alert=False)
        return
    if opponent_id == cb.from_user.id:
        await cb.answer(t(lang, "cannot_challenge_self"), show_alert=False)
        return

    inv = await db.get_inventory(cb.from_user.id)
    if not inv:
        await cb.answer(t(lang, "setup_first"), show_alert=False)
        return
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    await state.set_state(DuelCreate.picking)
    await state.update_data(picked={}, inv_order=[k for k, _ in inv_items], rematch_opponent_id=opponent_id)

    paths = await cache.get_paths_for_inv(bot, inv_items)
    out = os.path.join(os.getcwd(), "data", "renders", f"duel_pick_{cb.from_user.id}.webp")
    if not _render_cached(out, tuple(inv_items), lang):
        await _in_executor(render_profile, user_title=_display_name(cb, lang), avatar_path=None, stickers=_inv_to_render(paths, inv_items), out_path=out, lang=lang)
    pic = FSInputFile(out)
    caption = t(lang, "choose_chips_buttons")
    if cb.message:
        _msg = await cb.message.answer_photo(pic, caption=caption, reply_markup=kb_duel_pick(inv_items, picked={}, lang=lang))
        _track(cb.from_user.id, _msg)
    await cb.answer()


async def _update_duel_pick(cb: CallbackQuery, state: FSMContext, db: Database, inc: bool, prefix: str) -> None:
    lang = get_event_lang(cb)
    inv = await db.get_inventory(cb.from_user.id)
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    data = await state.get_data()
    picked: Dict[str, int] = dict(data.get("picked", {}))
    inv_order: list[str] = list(data.get("inv_order", []))
    try:
        idx = int(cb.data.split(":", 1)[1])
        file_id = inv_order[idx]
    except Exception:
        await cb.answer(t(lang, "stale_button"), show_alert=False)
        return
    cur = int(picked.get(file_id, 0))
    if cur > 0:
        picked.pop(file_id, None)
    else:
        if file_id in inv and int(inv[file_id]) > 0:
            picked[file_id] = 1
    await state.update_data(picked=picked)
    if prefix == "duel1":
        await cb.message.edit_reply_markup(reply_markup=kb_duel_pick(inv_items, picked, lang=lang))
    else:
        target_energy = int(data.get("target_energy") or 0)
        duel_id = str(data.get("duel_id") or "")
        await cb.message.edit_reply_markup(reply_markup=kb_duel_accept_pick(inv_items, picked, target_energy=target_energy, duel_id=duel_id, lang=lang))
    await cb.answer()


@router.callback_query(DuelCreate.picking, F.data.startswith("duel_pick_toggle:"))
async def cb_duel_pick_toggle(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    await _update_duel_pick(cb, state, db, True, "duel1")


@router.callback_query(DuelCreate.picking, F.data == "duel_pick_all")
async def cb_duel_pick_all(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    lang = get_event_lang(cb)
    inv = await db.get_inventory(cb.from_user.id)
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    data = await state.get_data()
    picked: Dict[str, int] = dict(data.get("picked", {}))
    all_selected = all(int(picked.get(fid, 0)) > 0 for fid, _ in inv_items)
    if all_selected:
        picked = {}
    else:
        picked = {fid: 1 for fid, cnt in inv_items if int(cnt) > 0}
    await state.update_data(picked=picked)
    await cb.message.edit_reply_markup(reply_markup=kb_duel_pick(inv_items, picked, lang=lang))
    await cb.answer()


@router.callback_query(DuelCreate.picking, F.data == "duel_cancel")
async def cb_duel_cancel(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await _loading(cb)
    await state.clear()
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=True)


@router.callback_query(DuelCreate.picking, F.data == "duel_create")
async def cb_duel_create(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await _loading(cb)
    lang = get_event_lang(cb)
    inv = await db.get_inventory(cb.from_user.id)
    data = await state.get_data()
    picked: Dict[str, int] = dict(data.get("picked", {}))
    picked = {k: 1 for k, v in picked.items() if int(v) > 0 and int(inv.get(k, 0)) > 0}
    if not picked:
        await cb.answer(t(lang, "choose_at_least_one_chip"), show_alert=False)
        return
    target_energy = sum(int(inv.get(fid, 1)) for fid in picked.keys())
    duel_id = secrets.token_urlsafe(6).replace("-", "").replace("_", "")
    await db.create_duel(duel_id, cb.from_user.id, list(picked.keys()), target_energy)
    rematch_opponent_id = int(data.get("rematch_opponent_id") or 0)
    await state.clear()
    if rematch_opponent_id > 0:
        try:
            await _send_duel_offer_to_user(rematch_opponent_id, duel_id=duel_id, db=db, bot=bot, cache=cache, avatars=avatars)
            _msg = await cb.message.answer(t(lang, "rematch_dm_sent"))
            _track(cb.from_user.id, _msg)
        except Exception:
            me = await bot.get_me()
            link = f"https://t.me/{me.username}?start=duel_{duel_id}"
            inviter = _display_name(cb, lang)
            invite_text = t(lang, "duel_invite_text", inviter=inviter, link=link)
            _msg = await cb.message.answer(t(lang, "invite_rematch_dm_failed"), reply_markup=kb_share_duel(invite_text, lang=lang))
            _track(cb.from_user.id, _msg)
            _msg = await cb.message.answer(link)
            _track(cb.from_user.id, _msg)
    else:
        me = await bot.get_me()
        link = f"https://t.me/{me.username}?start=duel_{duel_id}"
        inviter = _display_name(cb, lang)
        invite_text = t(lang, "duel_invite_text", inviter=inviter, link=link)
        _msg = await cb.message.answer(t(lang, "battle_link", link=link), reply_markup=kb_share_duel(invite_text, lang=lang))
        _track(cb.from_user.id, _msg)
    await cb.answer()


@router.callback_query(F.data == "duel_share_cancel")
async def cb_duel_share_cancel(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await _loading(cb)
    await state.clear()
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=False)
    await cb.answer()


@router.callback_query(F.data == "duel_cancel")
async def cb_duel_cancel_any(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await _loading(cb)
    await state.clear()
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=True)
    await cb.answer()


@router.callback_query(F.data == "battle_cancel")
async def cb_battle_cancel_any(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await state.clear()
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=True)
    await cb.answer()


@router.callback_query(F.data.startswith("duel_accept_cancel:"))
async def cb_duel_accept_cancel_any(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await _loading(cb)
    await state.clear()
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=False)
    await cb.answer()


@router.callback_query(F.data.startswith("duel_decline:"))
async def cb_duel_decline(cb: CallbackQuery) -> None:
    await _loading(cb)
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.answer(_t(cb, "declined"), show_alert=False)


@router.callback_query(F.data.startswith("duel_accept:"))
async def cb_duel_accept(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await _loading(cb)
    lang = get_event_lang(cb)
    duel_id = cb.data.split(":", 1)[1]
    duel = await db.get_duel(duel_id)
    if not duel or duel.get("status") != "open":
        await cb.answer(t(lang, "duel_unavailable"), show_alert=False)
        return
    if int(duel.get("creator_id") or 0) == int(cb.from_user.id):
        await cb.answer(t(lang, "cannot_accept_own_duel"), show_alert=False)
        return
    inv = await db.get_inventory(cb.from_user.id)
    if not inv:
        await state.clear()
        _msg = await cb.message.answer(t(lang, "setup_first"))
        _track(cb.from_user.id, _msg)
        await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=False)
        await cb.answer()
        return

    ok = await db.accept_duel(duel_id, cb.from_user.id)
    if not ok:
        await cb.answer(t(lang, "duel_already_taken"), show_alert=False)
        return

    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    await state.set_state(DuelAccept.picking)
    await state.update_data(picked={}, inv_order=[k for k, _ in inv_items], duel_id=duel_id, target_energy=int(duel.get("target_energy") or 0))

    paths = await cache.get_paths_for_inv(bot, inv_items)
    out = os.path.join(os.getcwd(), "data", "renders", f"duel_accept_{cb.from_user.id}_{duel_id}.webp")
    user_duels = await db.get_user_duels_count(cb.from_user.id)
    if not _render_cached(out, tuple(inv_items), user_duels, lang):
        await _in_executor(render_profile, user_title=_display_name(cb, lang), avatar_path=None, stickers=_inv_to_render(paths, inv_items), out_path=out, duels_count=user_duels, lang=lang)
    pic = FSInputFile(out)
    _msg = await cb.message.answer_photo(
        pic,
        caption=t(lang, "choose_chips_buttons"),
        reply_markup=kb_duel_accept_pick(inv_items, picked={}, target_energy=int(duel.get("target_energy") or 0), duel_id=duel_id, lang=lang),
    )
    _track(cb.from_user.id, _msg)
    await cb.answer()


@router.callback_query(DuelAccept.picking, F.data.startswith("duel2_pick_toggle:"))
async def cb_duel2_pick_toggle(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    await _loading(cb)
    await _update_duel_pick(cb, state, db, True, "duel2")


@router.callback_query(DuelAccept.picking, F.data.startswith("duel2_pick_all:"))
async def cb_duel2_pick_all(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    lang = get_event_lang(cb)
    inv = await db.get_inventory(cb.from_user.id)
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    data = await state.get_data()
    picked: Dict[str, int] = dict(data.get("picked", {}))
    all_selected = all(int(picked.get(fid, 0)) > 0 for fid, _ in inv_items)
    if all_selected:
        picked = {}
    else:
        picked = {fid: 1 for fid, cnt in inv_items if int(cnt) > 0}
    await state.update_data(picked=picked)
    target_energy = int(data.get("target_energy") or 0)
    duel_id = str(data.get("duel_id") or "")
    await cb.message.edit_reply_markup(reply_markup=kb_duel_accept_pick(inv_items, picked, target_energy=target_energy, duel_id=duel_id, lang=lang))
    await cb.answer()


@router.callback_query(DuelAccept.picking, F.data.startswith("duel_accept_cancel:"))
async def cb_duel_accept_cancel(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await _loading(cb)
    await state.clear()
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=False)


async def _send_profile_to_user(user_id: int, *, bot: Bot, db: Database, cache: StickerCache, avatars: AvatarCache, caption: str | None = None) -> None:
    lang = await _user_lang(db, user_id)
    user = await get_user_with_regen(db, user_id)
    inv = await db.get_inventory(user_id)
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    paths = await cache.get_paths_for_inv(bot, inv_items)
    avatar = await avatars.get_avatar_path(bot, user_id)
    out = os.path.join(os.getcwd(), "data", "renders", f"profile_{user_id}.webp")
    user_title = await _display_name_by_id(bot, user_id, lang)
    duels_count = await db.get_user_duels_count(user_id)
    if not _render_cached(out, tuple(inv_items), duels_count, lang, avatar):
        await _in_executor(render_profile, user_title=user_title, avatar_path=avatar, stickers=_inv_to_render(paths, inv_items), out_path=out, duels_count=duels_count, lang=lang)
    if len(inv_items) == 0:
        markup = kb_start(no_chips=True, lang=lang) if int(user.setup_done) == 0 else kb_no_chips(user.energy, lang=lang)
    else:
        markup = kb_profile_actions(user.energy, lang=lang)
    _msg = await bot.send_photo(chat_id=user_id, photo=FSInputFile(out), caption=caption or t(lang, "collection_caption"), reply_markup=markup)
    _track(user_id, _msg)


@router.callback_query(DuelAccept.picking, F.data.startswith("duel_accept_go:"))
async def cb_duel_accept_go(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await _loading(cb)
    lang = get_event_lang(cb)
    duel_id = cb.data.split(":", 1)[1]
    duel = await db.get_duel(duel_id)
    if not duel or duel.get("status") not in ("picking", "open"):
        await cb.answer(t(lang, "duel_unavailable"), show_alert=False)
        return
    if int(duel.get("opponent_id") or 0) != int(cb.from_user.id):
        await cb.answer(t(lang, "duel_not_for_you"), show_alert=False)
        return
    creator_id = int(duel.get("creator_id") or 0)
    creator_pick: list[str] = list(duel.get("creator_pick") or [])
    target_energy = int(duel.get("target_energy") or 0)

    data = await state.get_data()
    picked: Dict[str, int] = dict(data.get("picked", {}))
    inv_op = await db.get_inventory(cb.from_user.id)
    opponent_pick = [fid for fid, v in picked.items() if int(v) > 0 and int(inv_op.get(fid, 0)) > 0]
    op_energy = sum(int(inv_op.get(fid, 1)) for fid in opponent_pick)
    if op_energy != target_energy:
        _msg = await cb.message.answer(t(lang, "equal_energy_needed"))
        _track(cb.from_user.id, _msg)
        await cb.answer(t(lang, "need_choose_same_energy"), show_alert=False)
        return

    inv_creator = await db.get_inventory(creator_id)
    creator_units: list[BattleUnit] = [BattleUnit(file_id=fid, nominal=int(inv_creator.get(fid, 1))) for fid in creator_pick if fid in inv_creator]
    opponent_units: list[BattleUnit] = [BattleUnit(file_id=fid, nominal=int(inv_op.get(fid, 1))) for fid in opponent_pick]

    # ── 🎳 Боулинг определяет победителя ─────────────────────────────────────
    creator_dice_msg, opponent_dice_msg = await asyncio.gather(
        bot.send_dice(chat_id=creator_id, emoji="🎳"),
        bot.send_dice(chat_id=cb.from_user.id, emoji="🎳"),
    )
    _track(creator_id, creator_dice_msg)
    _track(cb.from_user.id, opponent_dice_msg)
    _bowling_pins = {1: 0, 2: 1, 3: 3, 4: 4, 5: 5, 6: 6}
    creator_slot = _bowling_pins.get(creator_dice_msg.dice.value, creator_dice_msg.dice.value)
    opponent_slot = _bowling_pins.get(opponent_dice_msg.dice.value, opponent_dice_msg.dice.value)
    await asyncio.sleep(4)  # ждём завершения анимации слот-машины

    result = distribute_by_slot(creator_units, opponent_units, creator_slot, opponent_slot)

    creator_ids = set(u.file_id for u in creator_units)
    opponent_ids = set(u.file_id for u in opponent_units)
    creator_gained_units = [u for u in result.player_won if u.file_id in opponent_ids]
    opponent_gained_units = [u for u in result.enemy_won if u.file_id in creator_ids]
    creator_delta = sum(int(u.nominal) for u in result.player_won) - sum(int(u.nominal) for u in creator_units)
    opponent_delta = sum(int(u.nominal) for u in result.enemy_won) - sum(int(u.nominal) for u in opponent_units)

    stake_creator = set(u.file_id for u in creator_units)
    stake_op = set(u.file_id for u in opponent_units)

    new_inv_creator: Dict[str, int] = {k: int(v) for k, v in inv_creator.items() if k not in stake_creator}
    for u in result.player_won:
        new_inv_creator[u.file_id] = int(new_inv_creator.get(u.file_id, 0)) + int(u.nominal)

    new_inv_op: Dict[str, int] = {k: int(v) for k, v in inv_op.items() if k not in stake_op}
    for u in result.enemy_won:
        new_inv_op[u.file_id] = int(new_inv_op.get(u.file_id, 0)) + int(u.nominal)

    await db.set_inventory_exact(creator_id, new_inv_creator)
    await db.set_inventory_exact(cb.from_user.id, new_inv_op)

    if not new_inv_creator:
        try:
            await _notify_user_no_chips(bot=bot, db=db, user_id=creator_id)
        except Exception:
            pass
    if not new_inv_op:
        try:
            await _notify_user_no_chips(bot=bot, db=db, user_id=cb.from_user.id)
        except Exception:
            pass

    await db.set_opponent_pick(duel_id, opponent_pick)
    await db.complete_duel(duel_id)

    try:
        c_chat = await bot.get_chat(creator_id)
        creator_name = (f"@{c_chat.username}" if getattr(c_chat, "username", None) else (getattr(c_chat, "full_name", None) or str(creator_id)))
    except Exception:
        creator_name = str(creator_id)
    opponent_name = _display_name(cb, lang)

    # рендер результата (две персональные картинки; показываем только переданные фишки)
    paths = await cache.get_paths_for_ids(bot, set([u.file_id for u in creator_gained_units] + [u.file_id for u in opponent_gained_units]))
    attacker_gained = [RenderSticker(file_id=u.file_id, path=paths[u.file_id], count=int(u.nominal)) for u in creator_gained_units if u.file_id in paths]
    defender_gained = [RenderSticker(file_id=u.file_id, path=paths[u.file_id], count=int(u.nominal)) for u in opponent_gained_units if u.file_id in paths]

    ts = int(time.time())
    out_creator = os.path.join(os.getcwd(), "data", "renders", f"duel_result_{creator_id}_{cb.from_user.id}_{ts}_c.webp")
    out_op = os.path.join(os.getcwd(), "data", "renders", f"duel_result_{creator_id}_{cb.from_user.id}_{ts}_o.webp")

    creator_lang = await _user_lang(db, creator_id)
    await asyncio.gather(
        _in_executor(
            render_duel_result,
            title=_battle_score_title(creator_slot, opponent_slot),
            user_title=creator_name,
            opponent_title=opponent_name,
            avatar_path=None,
            attacker_delta=creator_delta,
            defender_delta=opponent_delta,
            attacker_gained=attacker_gained,
            defender_gained=defender_gained,
            out_path=out_creator,
            lang=creator_lang,
        ),
        _in_executor(
            render_duel_result,
            title=_battle_score_title(opponent_slot, creator_slot),
            user_title=opponent_name,
            opponent_title=creator_name,
            avatar_path=None,
            attacker_delta=opponent_delta,
            defender_delta=creator_delta,
            attacker_gained=defender_gained,
            defender_gained=attacker_gained,
            out_path=out_op,
            lang=lang,
        ),
    )

    await _flush(bot, creator_id)
    await _flush(bot, cb.from_user.id)
    await bot.send_photo(chat_id=creator_id, photo=FSInputFile(out_creator), caption="", reply_markup=kb_duel_result_actions(cb.from_user.id, lang=creator_lang))
    await bot.send_photo(chat_id=cb.from_user.id, photo=FSInputFile(out_op), caption="", reply_markup=kb_duel_result_actions(creator_id, lang=lang))

    await state.clear()
    await cb.answer(t(lang, "duel_finished"))


async def _show_duel_offer(message: Message, *, duel_id: str, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    lang = get_event_lang(message)
    duel = await db.get_duel(duel_id)
    if not duel or duel.get("status") != "open":
        _msg = await message.answer(t(lang, "duel_unavailable"))
        _track(message.from_user.id, _msg)
        return
    if int(duel.get("creator_id") or 0) == int(message.from_user.id):
        _msg = await message.answer(t(lang, "send_link_friend"))
        _track(message.from_user.id, _msg)
        return
    creator_id = int(duel["creator_id"])
    creator_pick: list[str] = list(duel.get("creator_pick") or [])
    target_energy = int(duel.get("target_energy") or 0)

    try:
        c_chat = await bot.get_chat(creator_id)
        creator_name = (f"@{c_chat.username}" if getattr(c_chat, "username", None) else (getattr(c_chat, "full_name", None) or str(creator_id)))
    except Exception:
        creator_name = str(creator_id)

    inv_creator = await db.get_inventory(creator_id)
    paths = await cache.get_paths_for_ids(bot, creator_pick)
    won = [RenderSticker(file_id=fid, path=paths[fid], count=int(inv_creator.get(fid, 1))) for fid in creator_pick if fid in paths]

    creator_avatar = None
    try:
        creator_avatar = await avatars.get_avatar_path(bot, creator_id)
    except Exception:
        pass
    out = os.path.join(os.getcwd(), "data", "renders", f"duel_offer_{creator_id}_{duel_id}.webp")
    await _in_executor(
        render_battle_result,
        title="",
        user_title=t(lang, "duel_offer_title", name=creator_name),
        avatar_path=creator_avatar,
        lost=[],
        won=won,
        out_path=out,
        top_label=t(lang, "attacker_dash"),
        show_bottom=False,
        header_energy=target_energy,
        lang=lang,
    )
    _msg = await message.answer_photo(FSInputFile(out), caption="", reply_markup=kb_duel_offer(duel_id, lang=lang))
    _track(message.from_user.id, _msg)


async def _send_duel_offer_to_user(user_id: int, *, duel_id: str, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    lang = await _user_lang(db, user_id)
    duel = await db.get_duel(duel_id)
    if not duel or duel.get("status") != "open":
        return
    creator_id = int(duel["creator_id"])
    creator_pick: list[str] = list(duel.get("creator_pick") or [])
    target_energy = int(duel.get("target_energy") or 0)

    try:
        c_chat = await bot.get_chat(creator_id)
        creator_name = (f"@{c_chat.username}" if getattr(c_chat, "username", None) else (getattr(c_chat, "full_name", None) or str(creator_id)))
    except Exception:
        creator_name = str(creator_id)

    inv_creator = await db.get_inventory(creator_id)
    paths = await cache.get_paths_for_ids(bot, creator_pick)
    won = [RenderSticker(file_id=fid, path=paths[fid], count=int(inv_creator.get(fid, 1))) for fid in creator_pick if fid in paths]

    creator_avatar = None
    try:
        creator_avatar = await avatars.get_avatar_path(bot, creator_id)
    except Exception:
        pass
    out = os.path.join(os.getcwd(), "data", "renders", f"duel_offer_{creator_id}_{duel_id}_{user_id}.webp")
    await _in_executor(
        render_battle_result,
        title="",
        user_title=t(lang, "duel_offer_title", name=creator_name),
        avatar_path=creator_avatar,
        lost=[],
        won=won,
        out_path=out,
        top_label=t(lang, "attacker_dash"),
        show_bottom=False,
        header_energy=target_energy,
        lang=lang,
    )
    _msg = await bot.send_photo(chat_id=user_id, photo=FSInputFile(out), caption="", reply_markup=kb_duel_offer(duel_id, lang=lang))
    _track(user_id, _msg)


@router.callback_query(F.data == "setup")
async def cb_setup(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SetupChips.waiting_stickers)
    await state.update_data(stickers=[])
    _msg = await cb.message.answer(_t(cb, "send_3_stickers"))
    _track(cb.from_user.id, _msg)
    await cb.answer()


@router.callback_query(F.data == "setup_default")
async def cb_setup_default(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache, cfg) -> None:
    await _loading(cb)
    lang = get_event_lang(cb)
    await state.clear()
    try:
        file_ids = await pick_enemy_stickers(bot, cfg.default_sticker_set_name, n=3)
        file_ids = [str(x) for x in (file_ids or [])][:3]
        if len(file_ids) != 3:
            raise RuntimeError("not enough default stickers")
        await db.set_inventory_exact(cb.from_user.id, counts_from_list(file_ids))
        await db.set_setup_done(cb.from_user.id, 1)
        _msg = await cb.message.answer(t(lang, "setup_default_done"))
        _track(cb.from_user.id, _msg)
        await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=False)
        await cb.answer()
    except Exception:
        await cb.answer(t(lang, "setup_default_failed"), show_alert=False)
        try:
            _msg = await cb.message.answer(t(lang, "setup_default_failed_hint"))
            _track(cb.from_user.id, _msg)
        except Exception:
            pass


def _static_sticker_id(sticker) -> str:
    if getattr(sticker, "is_animated", False) or getattr(sticker, "is_video", False):
        thumb = getattr(sticker, "thumbnail", None)
        if thumb and getattr(thumb, "file_id", None):
            return str(thumb.file_id)
    return str(sticker.file_id)


@router.message(SetupChips.waiting_stickers)
async def on_setup_collect(message: Message, state: FSMContext) -> None:
    lang = get_event_lang(message)
    data = await state.get_data()
    stickers: list[str] = list(data.get("stickers", []))
    if message.content_type != ContentType.STICKER or message.sticker is None:
        _msg = await message.answer(t(lang, "need_sticker"))
        _track(message.from_user.id, _msg)
        return
    stickers.append(_static_sticker_id(message.sticker))
    stickers = stickers[:3]
    await state.update_data(stickers=stickers)
    if len(stickers) < 3:
        _msg = await message.answer(t(lang, "accepted_progress", count=len(stickers)))
        _track(message.from_user.id, _msg)
        return
    _msg = await message.answer(t(lang, "accepted_done_press_ready"), reply_markup=kb_setup_confirm(can_confirm=True, lang=lang))
    _track(message.from_user.id, _msg)


@router.callback_query(F.data == "setup_done_disabled")
async def cb_setup_done_disabled(cb: CallbackQuery) -> None:
    await cb.answer(_t(cb, "need_3_stickers"), show_alert=False)


@router.callback_query(F.data == "setup_cancel")
async def cb_setup_cancel(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await state.clear()
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=True)
    await cb.answer()


@router.callback_query(F.data == "setup_done")
async def cb_setup_done(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    lang = get_event_lang(cb)
    data = await state.get_data()
    stickers: list[str] = list(data.get("stickers", []))
    if len(stickers) != 3:
        await cb.answer(t(lang, "need_3_stickers"), show_alert=False)
        return
    await db.set_inventory_exact(cb.from_user.id, counts_from_list(stickers))
    await db.set_setup_done(cb.from_user.id, 1)
    await state.clear()
    _msg = await cb.message.answer(t(lang, "chips_saved"))
    _track(cb.from_user.id, _msg)
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id)


@router.callback_query(F.data == "play")
async def cb_play(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache) -> None:
    await _loading(cb)
    lang = get_event_lang(cb)
    user = await get_user_with_regen(db, cb.from_user.id)
    inv = await db.get_inventory(cb.from_user.id)
    if not inv:
        if user.energy <= 0:
            _msg = await cb.message.answer(_no_energy_and_chips_text(energy=user.energy, updated_at=user.energy_updated_at, lang=lang))
            _track(cb.from_user.id, _msg)
            await cb.answer(t(lang, "no_energy"), show_alert=False)
        else:
            await cb.answer(t(lang, "setup_first"), show_alert=False)
        return
    if user.energy <= 0:
        _msg = await cb.message.answer(_energy_wait_text(energy=user.energy, updated_at=user.energy_updated_at, lang=lang))
        _track(cb.from_user.id, _msg)
        await cb.answer(t(lang, "no_energy"), show_alert=False)
        return
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    await state.set_state(BattlePick.picking)
    await state.update_data(picked={}, inv_order=[k for k, _ in inv_items])
    paths = await cache.get_paths_for_inv(bot, inv_items)
    out = os.path.join(os.getcwd(), "data", "renders", f"battle_pick_{cb.from_user.id}.webp")
    if not _render_cached(out, tuple(inv_items), lang):
        await _in_executor(render_profile, user_title=_display_name(cb, lang), avatar_path=None, stickers=_inv_to_render(paths, inv_items), out_path=out, lang=lang)
    pic = FSInputFile(out)
    if cb.message:
        try:
            await cb.message.edit_media(media=InputMediaPhoto(media=pic, caption=t(lang, "collection")), reply_markup=kb_battle_pick(inv_items, picked={}, lang=lang))
            _track(cb.from_user.id, cb.message)
        except Exception:
            _msg = await cb.message.answer_photo(pic, caption=t(lang, "collection"), reply_markup=kb_battle_pick(inv_items, picked={}, lang=lang))
            _track(cb.from_user.id, _msg)
    await cb.answer()


async def _update_pick(cb: CallbackQuery, state: FSMContext, db: Database, inc: bool) -> None:
    lang = get_event_lang(cb)
    inv = await db.get_inventory(cb.from_user.id)
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    data = await state.get_data()
    picked: Dict[str, int] = dict(data.get("picked", {}))
    inv_order: list[str] = list(data.get("inv_order", []))
    try:
        idx = int(cb.data.split(":", 1)[1])
        file_id = inv_order[idx]
    except Exception:
        await cb.answer(t(lang, "stale_button"), show_alert=False)
        return
    cur = int(picked.get(file_id, 0))
    if cur > 0:
        picked.pop(file_id, None)
    else:
        if file_id in inv and int(inv[file_id]) > 0:
            picked[file_id] = 1
    await state.update_data(picked=picked)
    await cb.message.edit_reply_markup(reply_markup=kb_battle_pick(inv_items, picked, lang=lang))
    await cb.answer()


@router.callback_query(BattlePick.picking, F.data.startswith("pick_toggle:"))
async def cb_pick_toggle(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    await _update_pick(cb, state, db, True)


@router.callback_query(BattlePick.picking, F.data == "pick_all")
async def cb_pick_all(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    lang = get_event_lang(cb)
    inv = await db.get_inventory(cb.from_user.id)
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    data = await state.get_data()
    picked: Dict[str, int] = dict(data.get("picked", {}))
    all_selected = all(int(picked.get(fid, 0)) > 0 for fid, _ in inv_items)
    if all_selected:
        picked = {}
    else:
        picked = {fid: 1 for fid, cnt in inv_items if int(cnt) > 0}
    await state.update_data(picked=picked)
    await cb.message.edit_reply_markup(reply_markup=kb_battle_pick(inv_items, picked, lang=lang))
    await cb.answer()


@router.callback_query(BattlePick.picking, F.data == "battle_cancel")
async def cb_battle_cancel(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await state.clear()
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=True)
    await cb.answer()


@router.callback_query(BattlePick.picking, F.data == "battle_go")
async def cb_battle_go(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache, cfg) -> None:
    await _loading(cb)
    lang = get_event_lang(cb)
    user = await get_user_with_regen(db, cb.from_user.id)
    inv = await db.get_inventory(cb.from_user.id)
    data = await state.get_data()
    picked: Dict[str, int] = dict(data.get("picked", {}))
    picked = {k: min(int(v), int(inv.get(k, 0))) for k, v in picked.items() if int(v) > 0 and int(inv.get(k, 0)) > 0}
    required = sum(picked.values())
    if required <= 0:
        await cb.answer(t(lang, "choose_at_least_one_chip"), show_alert=False)
        return

    player_units: list[BattleUnit] = []
    for fid in picked.keys():
        player_units.append(BattleUnit(file_id=fid, nominal=int(inv.get(fid, 1))))
    total_energy = sum(u.nominal for u in player_units)

    enemy_units: list[BattleUnit] = []
    try:
        enemy_ids = await pick_enemy_stickers(bot, cfg.default_sticker_set_name, n=len(player_units))
    except Exception:
        pool: list[str] = []
        for fid, cnt in inv.items():
            pool.extend([fid] * max(1, int(cnt)))
        if not pool:
            _msg = await cb.message.answer(t(lang, "opponent_build_failed_empty"))
            _track(cb.from_user.id, _msg)
            await cb.answer()
            return
        import random

        enemy_ids = [random.choice(pool) for _ in range(len(player_units))]
        _msg = await cb.message.answer(t(lang, "use_collection_fallback"))
        _track(cb.from_user.id, _msg)

    for i, u in enumerate(player_units):
        enemy_units.append(BattleUnit(file_id=enemy_ids[i % len(enemy_ids)], nominal=u.nominal))

    result = run_battle(player_units, enemy_units)

    stake_ids = set([u.file_id for u in player_units] + [u.file_id for u in enemy_units])
    new_inv: Dict[str, int] = {k: int(v) for k, v in inv.items() if k not in stake_ids}
    for u in result.player_won:
        new_inv[u.file_id] = max(int(new_inv.get(u.file_id, 0)), int(u.nominal))
    await db.set_inventory_exact(cb.from_user.id, new_inv)

    if not new_inv:
        try:
            await _notify_user_no_chips(bot=bot, db=db, user_id=cb.from_user.id)
        except Exception:
            pass

    paths = await cache.get_paths_for_ids(bot, set([u.file_id for u in result.player_won] + [u.file_id for u in result.enemy_won]))
    won = [RenderSticker(file_id=u.file_id, path=paths[u.file_id], count=int(u.nominal)) for u in result.player_won if u.file_id in paths]
    lost = [RenderSticker(file_id=u.file_id, path=paths[u.file_id], count=int(u.nominal)) for u in result.enemy_won if u.file_id in paths]
    out = os.path.join(os.getcwd(), "data", "renders", f"battle_{cb.from_user.id}_{int(time.time())}.webp")
    avatar = await avatars.get_avatar_path(bot, cb.from_user.id)
    await _in_executor(render_battle_result, title=t(lang, "battle_result_title"), user_title=_display_name(cb, lang), avatar_path=avatar, lost=lost, won=won, out_path=out, lang=lang)
    await state.clear()
    await _flush(bot, cb.from_user.id)
    await cb.message.answer_photo(FSInputFile(out), caption="", reply_markup=kb_result_actions(lang=lang))


MEME_OPPONENTS = [
    "PepeTheFrog", "GigaChad420", "DogeMaster777", "KermitVibes99",
    "MLG_Quickscoper", "NyanCat2077", "SadFrog_irl", "BasedLord",
    "MemeKing777", "TrollFace2000", "SkibidiToilet", "GrumpyCat",
    "DankMemer69", "WojakPro", "StonksGuy", "ThisIsFine_Dog",
    "PepoHappy", "MonkaS_Gaming", "BigBrain200IQ", "ChadMindset",
    "ClownWorld42", "BrainwormBob", "CopiumKing", "TouchGrass_Bot",
    "NPC_Enjoyer", "RatioMaster", "VibeCheck_Pro", "YesChad",
    "GigaNerd", "FeelsWeirdMan", "OmegaLUL", "PauseChamp",
]

_BOWLING_PINS: dict[int, int] = {1: 0, 2: 1, 3: 3, 4: 4, 5: 5, 6: 6}


@router.callback_query(F.data == "mm")
async def cb_matchmaking(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await _loading(cb)
    lang = get_event_lang(cb)
    user = await get_user_with_regen(db, cb.from_user.id)
    inv = await db.get_inventory(cb.from_user.id)
    if not inv:
        await cb.answer(t(lang, "setup_first"), show_alert=False)
        return
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    await state.set_state(MatchmakingPick.picking)
    await state.update_data(picked={}, inv_order=[k for k, _ in inv_items])
    paths = await cache.get_paths_for_inv(bot, inv_items)
    out = os.path.join(os.getcwd(), "data", "renders", f"mm_pick_{cb.from_user.id}.webp")
    if not _render_cached(out, tuple(inv_items), lang):
        await _in_executor(render_profile, user_title=_display_name(cb, lang), avatar_path=None, stickers=_inv_to_render(paths, inv_items), out_path=out, lang=lang)
    pic = FSInputFile(out)
    try:
        await cb.message.edit_media(media=InputMediaPhoto(media=pic, caption=t(lang, "collection")), reply_markup=kb_matchmaking_pick(inv_items, picked={}, lang=lang))
        _track(cb.from_user.id, cb.message)
    except Exception:
        _msg = await cb.message.answer_photo(pic, caption=t(lang, "collection"), reply_markup=kb_matchmaking_pick(inv_items, picked={}, lang=lang))
        _track(cb.from_user.id, _msg)
    await cb.answer()


@router.callback_query(F.data == "result_mm")
async def cb_result_mm(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await _loading(cb)
    lang = get_event_lang(cb)
    inv = await db.get_inventory(cb.from_user.id)
    if not inv:
        await cb.answer(t(lang, "setup_first"), show_alert=False)
        return
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    await state.set_state(MatchmakingPick.picking)
    await state.update_data(picked={}, inv_order=[k for k, _ in inv_items])
    paths = await cache.get_paths_for_inv(bot, inv_items)
    out = os.path.join(os.getcwd(), "data", "renders", f"mm_pick_{cb.from_user.id}.webp")
    if not _render_cached(out, tuple(inv_items), lang):
        await _in_executor(render_profile, user_title=_display_name(cb, lang), avatar_path=None, stickers=_inv_to_render(paths, inv_items), out_path=out, lang=lang)
    pic = FSInputFile(out)
    _msg = await cb.message.answer_photo(pic, caption=t(lang, "collection"), reply_markup=kb_matchmaking_pick(inv_items, picked={}, lang=lang))
    _track(cb.from_user.id, _msg)
    await cb.answer()


@router.callback_query(MatchmakingPick.picking, F.data.startswith("mm_pick_toggle:"))
async def cb_mm_pick_toggle(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    lang = get_event_lang(cb)
    inv = await db.get_inventory(cb.from_user.id)
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    data = await state.get_data()
    picked: Dict[str, int] = dict(data.get("picked", {}))
    inv_order: list[str] = list(data.get("inv_order", []))
    try:
        idx = int(cb.data.split(":", 1)[1])
        file_id = inv_order[idx]
    except Exception:
        await cb.answer(t(lang, "stale_button"), show_alert=False)
        return
    cur = int(picked.get(file_id, 0))
    if cur > 0:
        picked.pop(file_id, None)
    else:
        if file_id in inv and int(inv[file_id]) > 0:
            picked[file_id] = 1
    await state.update_data(picked=picked)
    await cb.message.edit_reply_markup(reply_markup=kb_matchmaking_pick(inv_items, picked, lang=lang))
    await cb.answer()


@router.callback_query(MatchmakingPick.picking, F.data == "mm_cancel")
async def cb_mm_cancel(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await state.clear()
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=True)
    await cb.answer()


@router.callback_query(MatchmakingPick.picking, F.data == "mm_go")
async def cb_mm_go(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache, cfg) -> None:
    await _loading(cb)
    lang = get_event_lang(cb)
    user = await get_user_with_regen(db, cb.from_user.id)
    inv = await db.get_inventory(cb.from_user.id)
    data = await state.get_data()
    picked: Dict[str, int] = dict(data.get("picked", {}))
    picked = {k: min(int(v), int(inv.get(k, 0))) for k, v in picked.items() if int(v) > 0 and int(inv.get(k, 0)) > 0}
    if not picked:
        await cb.answer(t(lang, "choose_at_least_one_chip"), show_alert=False)
        return

    import random as _random
    bot_name = _random.choice(MEME_OPPONENTS)

    searching_msg = await cb.message.answer(t(lang, "mm_searching", count=3))
    _track(cb.from_user.id, searching_msg)
    await asyncio.sleep(1)
    try:
        await searching_msg.edit_text(t(lang, "mm_searching", count=2))
    except Exception:
        pass
    await asyncio.sleep(1)
    try:
        await searching_msg.edit_text(t(lang, "mm_searching", count=1))
    except Exception:
        pass
    await asyncio.sleep(1)
    try:
        await searching_msg.edit_text(t(lang, "mm_found", name=bot_name))
    except Exception:
        pass

    player_units: list[BattleUnit] = [BattleUnit(file_id=fid, nominal=int(inv.get(fid, 1))) for fid in picked]
    total_energy = sum(u.nominal for u in player_units)
    try:
        all_enemy_ids = await pick_enemy_stickers(bot, cfg.default_sticker_set_name, n=10)
    except Exception:
        all_enemy_ids = [fid for fid, _ in inv.items()]
    if not all_enemy_ids:
        all_enemy_ids = list(inv.keys())
    enemy_units: list[BattleUnit] = []
    if total_energy > 0 and all_enemy_ids:
        n = _random.randint(1, total_energy)
        if n > 1 and total_energy > 1:
            cut_positions = sorted(_random.sample(range(1, total_energy), min(n - 1, total_energy - 1)))
        else:
            cut_positions = []
        cuts = [0] + cut_positions + [total_energy]
        nominals = [cuts[i + 1] - cuts[i] for i in range(len(cuts) - 1)]
        enemy_units = [BattleUnit(file_id=_random.choice(all_enemy_ids), nominal=nom) for nom in nominals]

    _msg_your = await cb.message.answer(t(lang, "mm_your_roll"))
    _track(cb.from_user.id, _msg_your)
    player_dice_msg = await bot.send_dice(chat_id=cb.from_user.id, emoji="🎳")
    _track(cb.from_user.id, player_dice_msg)
    await asyncio.sleep(1)
    _msg_bot = await cb.message.answer(t(lang, "mm_bot_roll", name=bot_name))
    _track(cb.from_user.id, _msg_bot)
    bot_dice_msg = await bot.send_dice(chat_id=cb.from_user.id, emoji="🎳")
    _track(cb.from_user.id, bot_dice_msg)
    await asyncio.sleep(4)

    player_slot = _BOWLING_PINS.get(player_dice_msg.dice.value, player_dice_msg.dice.value)
    bot_slot = _BOWLING_PINS.get(bot_dice_msg.dice.value, bot_dice_msg.dice.value)

    result = distribute_by_slot(player_units, enemy_units, player_slot, bot_slot)

    player_ids = set(u.file_id for u in player_units)
    enemy_ids_set = set(u.file_id for u in enemy_units)
    player_gained = [u for u in result.player_won if u.file_id in enemy_ids_set]
    bot_gained = [u for u in result.enemy_won if u.file_id in player_ids]
    player_delta = sum(u.nominal for u in result.player_won) - sum(u.nominal for u in player_units)
    bot_delta = sum(u.nominal for u in result.enemy_won) - sum(u.nominal for u in enemy_units)

    stake_player = set(u.file_id for u in player_units)
    stake_enemy = set(u.file_id for u in enemy_units)
    new_inv: Dict[str, int] = {k: int(v) for k, v in inv.items() if k not in stake_player}
    for u in result.player_won:
        new_inv[u.file_id] = int(new_inv.get(u.file_id, 0)) + int(u.nominal)
    await db.set_inventory_exact(cb.from_user.id, new_inv)
    await db.increment_mm_games(cb.from_user.id)

    if not new_inv:
        try:
            await _notify_user_no_chips(bot=bot, db=db, user_id=cb.from_user.id)
        except Exception:
            pass

    paths = await cache.get_paths_for_ids(bot, set([u.file_id for u in player_gained] + [u.file_id for u in bot_gained]))
    attacker_gained_r = [RenderSticker(file_id=u.file_id, path=paths[u.file_id], count=int(u.nominal)) for u in player_gained if u.file_id in paths]
    defender_gained_r = [RenderSticker(file_id=u.file_id, path=paths[u.file_id], count=int(u.nominal)) for u in bot_gained if u.file_id in paths]

    ts = int(time.time())
    out = os.path.join(os.getcwd(), "data", "renders", f"mm_result_{cb.from_user.id}_{ts}.webp")
    avatar = await avatars.get_avatar_path(bot, cb.from_user.id)
    await _in_executor(
        render_duel_result,
        title=_battle_score_title(player_slot, bot_slot),
        user_title=_display_name(cb, lang),
        opponent_title=bot_name,
        avatar_path=avatar,
        attacker_delta=player_delta,
        defender_delta=bot_delta,
        attacker_gained=attacker_gained_r,
        defender_gained=defender_gained_r,
        out_path=out,
        lang=lang,
    )
    await state.clear()
    await _flush(bot, cb.from_user.id)
    await cb.message.answer_photo(FSInputFile(out), caption="", reply_markup=kb_matchmaking_result(lang=lang))


@router.callback_query(F.data == "e")
async def cb_energy(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    lang = get_event_lang(cb)
    user = await get_user_with_regen(db, cb.from_user.id)
    _msg = await cb.message.answer(_energy_wait_text(energy=user.energy, updated_at=user.energy_updated_at, lang=lang))
    _track(cb.from_user.id, _msg)
    user = await get_user_with_regen(db, cb.from_user.id)
    await state.set_state(EnergySpend.menu)
    _msg = await cb.message.answer(t(lang, "energy_menu_prompt"), reply_markup=kb_energy_menu(user.energy, lang=lang))
    _track(cb.from_user.id, _msg)
    await cb.answer()


@router.callback_query(EnergySpend.menu, F.data == "eu")
async def cb_eu(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache) -> None:
    await _loading(cb)
    lang = get_event_lang(cb)
    user = await get_user_with_regen(db, cb.from_user.id)
    if user.energy <= 0:
        _msg = await cb.message.answer(_energy_wait_text(energy=user.energy, updated_at=user.energy_updated_at, lang=lang))
        _track(cb.from_user.id, _msg)
        await cb.answer(t(lang, "no_energy"), show_alert=False)
        return
    inv = await db.get_inventory(cb.from_user.id)
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    await state.set_state(EnergySpend.upgrade)
    await state.update_data(spend={}, inv_order=[k for k, _ in inv_items])
    paths = await cache.get_paths_for_inv(bot, inv_items)
    out = os.path.join(os.getcwd(), "data", "renders", f"energy_upgrade_{cb.from_user.id}.webp")
    if not _render_cached(out, tuple(inv_items), lang):
        await _in_executor(render_profile, user_title=_display_name(cb, lang), avatar_path=None, stickers=_inv_to_render(paths, inv_items), out_path=out, lang=lang)
    pic = FSInputFile(out)
    if cb.message:
        try:
            await cb.message.edit_media(media=InputMediaPhoto(media=pic, caption=t(lang, "collection")), reply_markup=kb_energy_upgrade(inv_items, spend={}, energy=user.energy, lang=lang))
            _track(cb.from_user.id, cb.message)
        except Exception:
            _msg = await cb.message.answer_photo(pic, caption=t(lang, "collection"), reply_markup=kb_energy_upgrade(inv_items, spend={}, energy=user.energy, lang=lang))
            _track(cb.from_user.id, _msg)
    await cb.answer()


@router.callback_query(EnergySpend.upgrade, F.data.startswith("eu+:"))
async def cb_eu_plus(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    lang = get_event_lang(cb)
    try:
        await cb.answer()
    except Exception:
        pass
    user = await get_user_with_regen(db, cb.from_user.id)
    inv = await db.get_inventory(cb.from_user.id)
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    data = await state.get_data()
    spend: Dict[str, int] = dict(data.get("spend", {}))
    inv_order: list[str] = list(data.get("inv_order", []))
    if sum(int(x) for x in spend.values()) >= user.energy:
        await cb.answer(t(lang, "energy_depleted"), show_alert=False)
        return
    try:
        idx = int(cb.data.split(":", 1)[1])
        file_id = inv_order[idx]
    except Exception:
        await cb.answer(t(lang, "stale_button"), show_alert=False)
        return
    if file_id in inv:
        spend[file_id] = int(spend.get(file_id, 0)) + 1
        await state.update_data(spend=spend)
    try:
        if cb.message:
            await cb.message.edit_reply_markup(reply_markup=kb_energy_upgrade(inv_items, spend=spend, energy=user.energy, lang=lang))
    except Exception:
        pass


@router.callback_query(EnergySpend.upgrade, F.data == "eu_go")
async def cb_eu_go(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    lang = get_event_lang(cb)
    user = await get_user_with_regen(db, cb.from_user.id)
    data = await state.get_data()
    spend: Dict[str, int] = dict(data.get("spend", {}))
    used = sum(int(x) for x in spend.values())
    if used <= 0:
        await cb.answer(t(lang, "nothing_to_apply"), show_alert=False)
        return
    if used > user.energy:
        await cb.answer(t(lang, "not_enough_energy"), show_alert=False)
        return
    await _loading(cb)
    await db.add_inventory(cb.from_user.id, spend)
    await db.update_energy(cb.from_user.id, user.energy - used, updated_at=int(time.time()))
    await state.clear()
    _msg = await cb.message.answer(t(lang, "upgrade_chips_done"))
    _track(cb.from_user.id, _msg)
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id)


@router.callback_query(EnergySpend.upgrade, F.data == "eu_cancel")
async def cb_eu_cancel(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await state.clear()
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=True)
    await cb.answer()


@router.callback_query(EnergySpend.menu, F.data == "ea")
async def cb_ea(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    lang = get_event_lang(cb)
    user = await get_user_with_regen(db, cb.from_user.id)
    if user.energy <= 0:
        _msg = await cb.message.answer(_energy_wait_text(energy=user.energy, updated_at=user.energy_updated_at, lang=lang))
        _track(cb.from_user.id, _msg)
        await cb.answer(t(lang, "no_energy"), show_alert=False)
        return
    await state.set_state(EnergySpend.add_sticker)
    await state.update_data(ea_pending=[], ea_max=user.energy)
    _msg = await cb.message.answer(t(lang, "ea_prompt", energy=user.energy), reply_markup=kb_ea_collect(0, user.energy, lang))
    _track(cb.from_user.id, _msg)
    await cb.answer()


@router.message(EnergySpend.add_sticker)
async def on_ea_sticker(message: Message, state: FSMContext, db: Database, bot: Bot, cache: StickerCache) -> None:
    lang = get_event_lang(message)
    if message.content_type != ContentType.STICKER or message.sticker is None:
        _msg = await message.answer(t(lang, "need_sticker"))
        _track(message.from_user.id, _msg)
        return
    data = await state.get_data()
    pending: list[str] = list(data.get("ea_pending", []))
    max_e: int = int(data.get("ea_max", 1))
    if len(pending) >= max_e:
        _msg = await message.answer(t(lang, "ea_full", max=max_e), reply_markup=kb_ea_collect(len(pending), max_e, lang))
        _track(message.from_user.id, _msg)
        return
    file_id = _static_sticker_id(message.sticker)
    try:
        await cache.get_static_sticker_path(bot, file_id)
    except Exception:
        _msg = await message.answer(t(lang, "sticker_unavailable"))
        _track(message.from_user.id, _msg)
        return
    pending.append(file_id)
    await state.update_data(ea_pending=pending)
    if len(pending) >= max_e:
        _msg = await message.answer(t(lang, "ea_full", max=max_e), reply_markup=kb_ea_collect(len(pending), max_e, lang))
        _track(message.from_user.id, _msg)
    else:
        _msg = await message.answer(t(lang, "ea_progress", count=len(pending), max=max_e), reply_markup=kb_ea_collect(len(pending), max_e, lang))
        _track(message.from_user.id, _msg)


@router.callback_query(EnergySpend.add_sticker, F.data == "ea_confirm")
async def cb_ea_confirm(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    lang = get_event_lang(cb)
    data = await state.get_data()
    pending: list[str] = list(data.get("ea_pending", []))
    if not pending:
        await cb.answer(t(lang, "nothing_to_apply"), show_alert=False)
        return
    user = await get_user_with_regen(db, cb.from_user.id)
    if len(pending) > user.energy:
        await cb.answer(t(lang, "not_enough_energy"), show_alert=False)
        return
    await db.add_inventory(cb.from_user.id, counts_from_list(pending))
    await db.update_energy(cb.from_user.id, user.energy - len(pending), updated_at=int(time.time()))
    await state.clear()
    _msg = await cb.message.answer(t(lang, "ea_done"))
    _track(cb.from_user.id, _msg)
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id)
    await cb.answer()


@router.callback_query(EnergySpend.add_sticker, F.data == "ea_cancel")
async def cb_ea_cancel(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await state.clear()
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=False)
    await cb.answer()


@router.callback_query(F.data == "reset")
async def cb_reset(cb: CallbackQuery) -> None:
    lang = get_event_lang(cb)
    _msg = await cb.message.answer(t(lang, "reset_all_chips"), reply_markup=kb_reset_confirm(lang=lang))
    _track(cb.from_user.id, _msg)
    await cb.answer()


@router.callback_query(F.data == "reset_no")
async def cb_reset_no(cb: CallbackQuery, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=True)
    await cb.answer()


@router.callback_query(F.data == "reset_ok")
async def cb_reset_ok(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await state.clear()
    await db.set_inventory_exact(cb.from_user.id, {})
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=True)
    await cb.answer()


@router.callback_query(F.data == "leaderboard")
async def cb_leaderboard(cb: CallbackQuery, db: Database, bot: Bot) -> None:
    await _loading(cb)
    lang = get_event_lang(cb)
    stats = await db.get_all_users_stats()
    if not stats:
        await cb.answer(t(lang, "leaderboard_empty"), show_alert=True)
        return
    stats.sort(key=lambda s: (s["total_nominal"], s["duels_count"]), reverse=True)
    top = stats[:15]
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = [t(lang, "leaderboard_header")]
    for rank, s in enumerate(top, 1):
        name = await _display_name_by_id(bot, s["user_id"], lang)
        prefix = medals.get(rank, f"#{rank}")
        lines.append(
            f"{prefix} {name}\n"
            f"  🃏{s['chips_count']} ({s['total_nominal']}⚡) | ⚔️{s['duels_count']} | 🎮{s.get('mm_games', 0)}"
        )
    _msg = await cb.message.answer("\n".join(lines))
    _track(cb.from_user.id, _msg)
    await cb.answer()


@router.message(Command("stats"))
async def cmd_stats(message: Message, db: Database, cfg: Config, bot: Bot) -> None:
    lang = get_event_lang(message)
    if cfg.admin_id is None or message.from_user.id != cfg.admin_id:
        return
    stats = await db.get_all_users_stats()
    if not stats:
        await message.answer(t(lang, "no_players"))
        return
    total_duels = sum(s["duels_count"] for s in stats)
    total_mm = sum(s.get("mm_games", 0) for s in stats)
    total_nominal = sum(s["total_nominal"] for s in stats)
    lines = [t(lang, "stats_header", players=len(stats), duels=total_duels, mm=total_mm, points=total_nominal)]
    for s in stats:
        setup = "✅" if s["setup_done"] else "⏳"
        name = await _display_name_by_id(bot, s["user_id"], lang)
        lines.append(
            f"{name}\n"
            f"  🃏{s['chips_count']} ({s['total_nominal']}⚡) | ⚡{s['energy']} | ⚔️{s['duels_count']} | 🎮{s.get('mm_games', 0)} | {setup}"
        )
    text = "\n".join(lines)
    for i in range(0, len(text), 4096):
        await message.answer(text[i : i + 4096])


async def main() -> None:
    cfg = load_config()
    bot = Bot(token=cfg.bot_token)
    dp = Dispatcher()
    db = Database(db_path=os.path.join(cfg.data_dir, "db.sqlite3"))
    await db.init()
    cache = StickerCache(cfg.data_dir)
    avatars = AvatarCache(cfg.data_dir)
    asyncio.create_task(_energy_reset_worker(bot=bot, db=db, cache=cache, avatars=avatars))
    dp.include_router(router)
    dp.update.middleware(DI(db=db, cache=cache, avatars=avatars, cfg=cfg))
    await dp.start_polling(bot)
