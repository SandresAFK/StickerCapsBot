from __future__ import annotations

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

from app.config import Config, load_config
from app.db import Database
from app.keyboards import kb_battle_pick, kb_duel_accept_pick, kb_duel_offer, kb_duel_pick, kb_energy_menu, kb_energy_upgrade, kb_no_chips, kb_profile_actions, kb_reset_confirm, kb_setup_confirm, kb_share_duel, kb_start
from app.middleware import DI
from app.render.profile import RenderSticker, render_battle_result, render_duel_result, render_profile
from app.services.avatars import AvatarCache
from app.services.battle import BattleUnit, counts_from_list, distribute_by_slot, run_battle
from app.services.energy import MAX_ENERGY, get_user_with_regen, seconds_until_next_utc_midnight, utc_midnight_ts
from app.services.stickers import StickerCache, pick_enemy_stickers
from app.states import BattlePick, DuelAccept, DuelCreate, EnergySpend, SetupChips

router = Router()


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery) -> None:
    # Used for disabled buttons in inline keyboards.
    await cb.answer("Выберите фишки на нужную энергию.", show_alert=False)


async def _loading(cb: CallbackQuery) -> None:
    try:
        await cb.answer("Подождите, идёт загрузка…", show_alert=False)
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


def _energy_wait_text(*, energy: int, updated_at: int) -> str:
    if int(energy) >= int(MAX_ENERGY):
        return f"Энергия: {energy}/{MAX_ENERGY}"
    left = seconds_until_next_utc_midnight()
    return f"Нет энергии. Новая энергия появится через {_fmt_seconds(left)}."


def _no_energy_and_chips_text(*, energy: int, updated_at: int) -> str:
    return "У вас нет энергии и фишек.\n" + _energy_wait_text(energy=energy, updated_at=updated_at)


async def _notify_user_no_chips(*, bot: Bot, db: Database, user_id: int) -> None:
    left = seconds_until_next_utc_midnight()
    await db.set_notify_energy_reset(user_id, 1)
    await bot.send_message(
        chat_id=user_id,
        text=(
            "У вас нет фишек.\n"
            f"Вы можете получить новые фишки через {_fmt_seconds(left)}.\n"
            "Вы получите уведомление, когда энергия восстановится."
        ),
    )


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
                    await bot.send_message(
                        chat_id=uid,
                        text="Энергия восстановилась до 3. Можешь получить новые фишки в меню энергии.",
                    )
                    await _send_profile_to_user(uid, bot=bot, db=db, cache=cache, avatars=avatars)
                except Exception:
                    pass
        except Exception:
            await asyncio.sleep(5)


def _display_name(obj: Message | CallbackQuery) -> str:
    u = obj.from_user
    if not u:
        return "Игрок"
    if u.username:
        return f"@{u.username}"
    return u.full_name or f"Игрок #{u.id}"


async def _display_name_by_id(bot: Bot, user_id: int) -> str:
    try:
        chat = await bot.get_chat(user_id)
        if getattr(chat, "username", None):
            return f"@{chat.username}"
        if getattr(chat, "full_name", None):
            return str(chat.full_name)
    except Exception:
        pass
    return f"Игрок #{user_id}"


def _inv_to_render(paths: Dict[str, str], inv_items: List[Tuple[str, int]]) -> List[RenderSticker]:
    out: List[RenderSticker] = []
    for file_id, cnt in inv_items:
        p = paths.get(file_id)
        if p:
            out.append(RenderSticker(file_id=file_id, path=p, count=int(cnt)))
    return out


async def _render_and_send_profile(message_or_cb: Message | CallbackQuery, *, bot: Bot, db: Database, cache: StickerCache, avatars: AvatarCache, user_id: int, edit_in_place: bool = False) -> None:
    user = await get_user_with_regen(db, user_id)
    inv = await db.get_inventory(user_id)
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    paths: Dict[str, str] = {}
    for file_id, _ in inv_items:
        try:
            paths[file_id] = (await cache.get_static_sticker_path(bot, file_id)).local_path
        except Exception:
            pass
    avatar = await avatars.get_avatar_path(bot, user_id)
    out = os.path.join(os.getcwd(), "data", "renders", f"profile_{user_id}.png")
    empty_lines: list[str] | None = None
    if len(inv_items) == 0:
        if int(user.setup_done) == 0:
            empty_lines = ["Фишек нет. Нажмите «Настроить фишки». "]
        else:
            left = seconds_until_next_utc_midnight()
            empty_lines = [
                f"Вы можете получить новые фишки через {_fmt_seconds(left)}.",
                "Вы получите уведомление, когда энергия восстановится.",
            ]
    duels_count = await db.get_user_duels_count(user_id)
    render_profile(user_title=_display_name(message_or_cb), avatar_path=avatar, stickers=_inv_to_render(paths, inv_items), out_path=out, empty_lines=empty_lines, duels_count=duels_count)

    if len(inv_items) == 0:
        if int(user.setup_done) == 0:
            markup = kb_start(no_chips=True)
        else:
            markup = kb_no_chips(user.energy)
    else:
        markup = kb_profile_actions(user.energy)
    pic = FSInputFile(out)
    if isinstance(message_or_cb, CallbackQuery):
        if edit_in_place and message_or_cb.message:
            try:
                await message_or_cb.message.edit_media(media=InputMediaPhoto(media=pic, caption="Твоя коллекция"), reply_markup=markup)
            except Exception:
                await message_or_cb.message.answer_photo(pic, caption="Твоя коллекция", reply_markup=markup)
        else:
            await message_or_cb.message.answer_photo(pic, caption="Твоя коллекция", reply_markup=markup)
        await message_or_cb.answer()
    else:
        await message_or_cb.answer_photo(pic, caption="Твоя коллекция", reply_markup=markup)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await state.clear()
    await db.get_or_create_user(message.from_user.id)
    arg = ""
    try:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) > 1:
            arg = parts[1].strip()
    except Exception:
        arg = ""
    if arg.startswith("duel_"):
        duel_id = arg[len("duel_") :]
        await _show_duel_offer(message, duel_id=duel_id, db=db, bot=bot, cache=cache)
        return
    await _render_and_send_profile(message, bot=bot, db=db, cache=cache, avatars=avatars, user_id=message.from_user.id)


@router.callback_query(F.data == "collection")
async def cb_collection(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await _loading(cb)
    await state.clear()
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=True)


@router.callback_query(F.data == "pvp")
async def cb_pvp(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache) -> None:
    await _loading(cb)
    inv = await db.get_inventory(cb.from_user.id)
    if not inv:
        await cb.answer("Сначала настрой фишки.", show_alert=False)
        return
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    await state.set_state(DuelCreate.picking)
    await state.update_data(picked={}, inv_order=[k for k, _ in inv_items])

    paths: Dict[str, str] = {}
    for file_id, _ in inv_items:
        try:
            paths[file_id] = (await cache.get_static_sticker_path(bot, file_id)).local_path
        except Exception:
            pass
    out = os.path.join(os.getcwd(), "data", "renders", f"duel_pick_{cb.from_user.id}.png")
    render_profile(user_title=_display_name(cb), avatar_path=None, stickers=_inv_to_render(paths, inv_items), out_path=out)
    pic = FSInputFile(out)
    caption = "выберите фишки кнопками"
    if cb.message:
        try:
            await cb.message.edit_media(media=InputMediaPhoto(media=pic, caption=caption), reply_markup=kb_duel_pick(inv_items, picked={}))
        except Exception:
            await cb.message.answer_photo(pic, caption=caption, reply_markup=kb_duel_pick(inv_items, picked={}))
    await cb.answer()


async def _update_duel_pick(cb: CallbackQuery, state: FSMContext, db: Database, inc: bool, prefix: str) -> None:
    inv = await db.get_inventory(cb.from_user.id)
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    data = await state.get_data()
    picked: Dict[str, int] = dict(data.get("picked", {}))
    inv_order: list[str] = list(data.get("inv_order", []))
    try:
        idx = int(cb.data.split(":", 1)[1])
        file_id = inv_order[idx]
    except Exception:
        await cb.answer("Кнопка устарела.", show_alert=False)
        return
    cur = int(picked.get(file_id, 0))
    if cur > 0:
        picked.pop(file_id, None)
    else:
        if file_id in inv and int(inv[file_id]) > 0:
            picked[file_id] = 1
    await state.update_data(picked=picked)
    if prefix == "duel1":
        await cb.message.edit_reply_markup(reply_markup=kb_duel_pick(inv_items, picked))
    else:
        target_energy = int(data.get("target_energy") or 0)
        duel_id = str(data.get("duel_id") or "")
        await cb.message.edit_reply_markup(reply_markup=kb_duel_accept_pick(inv_items, picked, target_energy=target_energy, duel_id=duel_id))
    await cb.answer()


@router.callback_query(DuelCreate.picking, F.data.startswith("duel_pick_toggle:"))
async def cb_duel_pick_toggle(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    await _update_duel_pick(cb, state, db, True, "duel1")


@router.callback_query(DuelCreate.picking, F.data == "duel_cancel")
async def cb_duel_cancel(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await _loading(cb)
    await state.clear()
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=True)


@router.callback_query(DuelCreate.picking, F.data == "duel_create")
async def cb_duel_create(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await _loading(cb)
    inv = await db.get_inventory(cb.from_user.id)
    data = await state.get_data()
    picked: Dict[str, int] = dict(data.get("picked", {}))
    picked = {k: 1 for k, v in picked.items() if int(v) > 0 and int(inv.get(k, 0)) > 0}
    if not picked:
        await cb.answer("Выбери хотя бы одну фишку.", show_alert=False)
        return
    target_energy = sum(int(inv.get(fid, 1)) for fid in picked.keys())
    duel_id = secrets.token_urlsafe(6).replace("-", "").replace("_", "")
    await db.create_duel(duel_id, cb.from_user.id, list(picked.keys()), target_energy)
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=duel_{duel_id}"
    await state.clear()
    inviter = _display_name(cb)
    invite_text = f"Тебя вызвал на бой {inviter} в игре Sticker CapsBot!\nНажми, чтобы принять бой: {link}"
    await cb.message.answer(f"Ссылка на бой:\n{link}", reply_markup=kb_share_duel(invite_text))
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
    await cb.answer("Отклонено.", show_alert=False)


@router.callback_query(F.data.startswith("duel_accept:"))
async def cb_duel_accept(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await _loading(cb)
    duel_id = cb.data.split(":", 1)[1]
    duel = await db.get_duel(duel_id)
    if not duel or duel.get("status") != "open":
        await cb.answer("Вызов недоступен.", show_alert=False)
        return
    if int(duel.get("creator_id") or 0) == int(cb.from_user.id):
        await cb.answer("Нельзя принять свой вызов.", show_alert=False)
        return
    inv = await db.get_inventory(cb.from_user.id)
    if not inv:
        await state.clear()
        await cb.message.answer("Сначала настрой фишки.")
        await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=False)
        await cb.answer()
        return

    ok = await db.accept_duel(duel_id, cb.from_user.id)
    if not ok:
        await cb.answer("Этот вызов уже принят.", show_alert=False)
        return

    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    await state.set_state(DuelAccept.picking)
    await state.update_data(picked={}, inv_order=[k for k, _ in inv_items], duel_id=duel_id, target_energy=int(duel.get("target_energy") or 0))

    paths: Dict[str, str] = {}
    for file_id, _ in inv_items:
        try:
            paths[file_id] = (await cache.get_static_sticker_path(bot, file_id)).local_path
        except Exception:
            pass
    out = os.path.join(os.getcwd(), "data", "renders", f"duel_accept_{cb.from_user.id}_{duel_id}.png")
    user_duels = await db.get_user_duels_count(cb.from_user.id)
    render_profile(user_title=_display_name(cb), avatar_path=None, stickers=_inv_to_render(paths, inv_items), out_path=out, duels_count=user_duels)
    pic = FSInputFile(out)
    await cb.message.answer_photo(pic, caption="выберите фишки кнопками", reply_markup=kb_duel_accept_pick(inv_items, picked={}, target_energy=int(duel.get("target_energy") or 0), duel_id=duel_id))
    await cb.answer()


@router.callback_query(DuelAccept.picking, F.data.startswith("duel2_pick_toggle:"))
async def cb_duel2_pick_toggle(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    await _loading(cb)
    await _update_duel_pick(cb, state, db, True, "duel2")


@router.callback_query(DuelAccept.picking, F.data.startswith("duel_accept_cancel:"))
async def cb_duel_accept_cancel(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await _loading(cb)
    await state.clear()
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=False)


async def _send_profile_to_user(user_id: int, *, bot: Bot, db: Database, cache: StickerCache, avatars: AvatarCache, caption: str = "Твоя коллекция") -> None:
    user = await get_user_with_regen(db, user_id)
    inv = await db.get_inventory(user_id)
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    paths: Dict[str, str] = {}
    for file_id, _ in inv_items:
        try:
            paths[file_id] = (await cache.get_static_sticker_path(bot, file_id)).local_path
        except Exception:
            pass
    avatar = await avatars.get_avatar_path(bot, user_id)
    out = os.path.join(os.getcwd(), "data", "renders", f"profile_{user_id}.png")
    user_title = await _display_name_by_id(bot, user_id)
    duels_count = await db.get_user_duels_count(user_id)
    render_profile(user_title=user_title, avatar_path=avatar, stickers=_inv_to_render(paths, inv_items), out_path=out, duels_count=duels_count)
    markup = kb_start(no_chips=(len(inv_items) == 0)) if len(inv_items) == 0 else kb_profile_actions(user.energy)
    await bot.send_photo(chat_id=user_id, photo=FSInputFile(out), caption=caption, reply_markup=markup)


@router.callback_query(DuelAccept.picking, F.data.startswith("duel_accept_go:"))
async def cb_duel_accept_go(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await _loading(cb)
    duel_id = cb.data.split(":", 1)[1]
    duel = await db.get_duel(duel_id)
    if not duel or duel.get("status") not in ("picking", "open"):
        await cb.answer("Вызов недоступен.", show_alert=False)
        return
    if int(duel.get("opponent_id") or 0) != int(cb.from_user.id):
        await cb.answer("Этот вызов не для тебя.", show_alert=False)
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
        await cb.message.answer("Общая энергия ваших фишек должна быть равна энергии соперника.")
        await cb.answer("Нужно выбрать фишки на ту же энергию.", show_alert=False)
        return

    inv_creator = await db.get_inventory(creator_id)
    creator_units: list[BattleUnit] = [BattleUnit(file_id=fid, nominal=int(inv_creator.get(fid, 1))) for fid in creator_pick if fid in inv_creator]
    opponent_units: list[BattleUnit] = [BattleUnit(file_id=fid, nominal=int(inv_op.get(fid, 1))) for fid in opponent_pick]

    # ── � Боулинг определяет победителя ─────────────────────────────────────
    creator_dice_msg, opponent_dice_msg = await asyncio.gather(
        bot.send_dice(chat_id=creator_id, emoji="�"),
        bot.send_dice(chat_id=cb.from_user.id, emoji="�"),
    )
    creator_slot = creator_dice_msg.dice.value
    opponent_slot = opponent_dice_msg.dice.value
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
        new_inv_creator[u.file_id] = max(int(new_inv_creator.get(u.file_id, 0)), int(u.nominal))

    new_inv_op: Dict[str, int] = {k: int(v) for k, v in inv_op.items() if k not in stake_op}
    for u in result.enemy_won:
        new_inv_op[u.file_id] = max(int(new_inv_op.get(u.file_id, 0)), int(u.nominal))

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
    opponent_name = _display_name(cb)

    # рендер результата (две персональные картинки; показываем только переданные фишки)
    paths: Dict[str, str] = {}
    for file_id in set([u.file_id for u in creator_gained_units] + [u.file_id for u in opponent_gained_units]):
        try:
            paths[file_id] = (await cache.get_static_sticker_path(bot, file_id)).local_path
        except Exception:
            pass
    attacker_gained = [RenderSticker(file_id=u.file_id, path=paths[u.file_id], count=int(u.nominal)) for u in creator_gained_units if u.file_id in paths]
    defender_gained = [RenderSticker(file_id=u.file_id, path=paths[u.file_id], count=int(u.nominal)) for u in opponent_gained_units if u.file_id in paths]

    ts = int(time.time())
    out_creator = os.path.join(os.getcwd(), "data", "renders", f"duel_result_{creator_id}_{cb.from_user.id}_{ts}_c.png")
    out_op = os.path.join(os.getcwd(), "data", "renders", f"duel_result_{creator_id}_{cb.from_user.id}_{ts}_o.png")

    render_duel_result(
        title=f"� {creator_slot} vs {opponent_slot}",
        user_title=f"{creator_name} vs {opponent_name}",
        avatar_path=None,
        attacker_label=f"Нападающий (ты, {creator_name}):",
        defender_label=f"Обороняющийся ({opponent_name}):",
        attacker_delta=creator_delta,
        defender_delta=opponent_delta,
        attacker_gained=attacker_gained,
        defender_gained=defender_gained,
        out_path=out_creator,
    )
    render_duel_result(
        title=f"� {creator_slot} vs {opponent_slot}",
        user_title=f"{creator_name} vs {opponent_name}",
        avatar_path=None,
        attacker_label=f"Нападающий ({creator_name}):",
        defender_label=f"Обороняющийся (ты, {opponent_name}):",
        attacker_delta=creator_delta,
        defender_delta=opponent_delta,
        attacker_gained=attacker_gained,
        defender_gained=defender_gained,
        out_path=out_op,
    )

    await bot.send_photo(chat_id=creator_id, photo=FSInputFile(out_creator), caption="")
    await bot.send_photo(chat_id=cb.from_user.id, photo=FSInputFile(out_op), caption="")
    await _send_profile_to_user(creator_id, bot=bot, db=db, cache=cache, avatars=avatars)
    await _send_profile_to_user(cb.from_user.id, bot=bot, db=db, cache=cache, avatars=avatars)

    await state.clear()
    await cb.answer("Бой завершён.")


async def _show_duel_offer(message: Message, *, duel_id: str, db: Database, bot: Bot, cache: StickerCache) -> None:
    duel = await db.get_duel(duel_id)
    if not duel or duel.get("status") != "open":
        await message.answer("Этот вызов недоступен.")
        return
    if int(duel.get("creator_id") or 0) == int(message.from_user.id):
        await message.answer("Это твой вызов. Отправь ссылку другу.")
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
    paths: Dict[str, str] = {}
    for file_id in creator_pick:
        try:
            paths[file_id] = (await cache.get_static_sticker_path(bot, file_id)).local_path
        except Exception:
            pass
    won = [RenderSticker(file_id=fid, path=paths[fid], count=int(inv_creator.get(fid, 1))) for fid in creator_pick if fid in paths]

    out = os.path.join(os.getcwd(), "data", "renders", f"duel_offer_{creator_id}_{duel_id}.png")
    render_battle_result(
        title="",
        user_title=f"Дуэль vs {creator_name}",
        avatar_path=None,
        lost=[],
        won=won,
        out_path=out,
        top_label="Нападающий -",
        show_bottom=False,
        header_energy=target_energy,
    )
    await message.answer_photo(FSInputFile(out), caption="", reply_markup=kb_duel_offer(duel_id))


@router.callback_query(F.data == "setup")
async def cb_setup(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SetupChips.waiting_stickers)
    await state.update_data(stickers=[])
    await cb.message.answer("Отправь 3 любых стикера и нажми «Готово».")
    await cb.answer()


def _static_sticker_id(sticker) -> str:
    if getattr(sticker, "is_animated", False) or getattr(sticker, "is_video", False):
        thumb = getattr(sticker, "thumbnail", None)
        if thumb and getattr(thumb, "file_id", None):
            return str(thumb.file_id)
    return str(sticker.file_id)


@router.message(SetupChips.waiting_stickers)
async def on_setup_collect(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    stickers: list[str] = list(data.get("stickers", []))
    if message.content_type != ContentType.STICKER or message.sticker is None:
        await message.answer("Нужен стикер.")
        return
    stickers.append(_static_sticker_id(message.sticker))
    stickers = stickers[:3]
    await state.update_data(stickers=stickers)
    if len(stickers) < 3:
        await message.answer(f"Принято: {len(stickers)}/3")
        return
    await message.answer("Принято: 3/3. Нажми «Готово».", reply_markup=kb_setup_confirm(can_confirm=True))


@router.callback_query(F.data == "setup_done_disabled")
async def cb_setup_done_disabled(cb: CallbackQuery) -> None:
    await cb.answer("Нужно 3 стикера.", show_alert=False)


@router.callback_query(F.data == "setup_cancel")
async def cb_setup_cancel(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await state.clear()
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=True)
    await cb.answer()


@router.callback_query(F.data == "setup_done")
async def cb_setup_done(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    data = await state.get_data()
    stickers: list[str] = list(data.get("stickers", []))
    if len(stickers) != 3:
        await cb.answer("Нужно 3 стикера.", show_alert=False)
        return
    await db.set_inventory_exact(cb.from_user.id, counts_from_list(stickers))
    await db.set_setup_done(cb.from_user.id, 1)
    await state.clear()
    await cb.message.answer("Фишки сохранены.")
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id)


@router.callback_query(F.data == "play")
async def cb_play(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache) -> None:
    await _loading(cb)
    user = await get_user_with_regen(db, cb.from_user.id)
    inv = await db.get_inventory(cb.from_user.id)
    if not inv:
        if user.energy <= 0:
            await cb.message.answer(_no_energy_and_chips_text(energy=user.energy, updated_at=user.energy_updated_at))
            await cb.answer("Нет энергии.", show_alert=False)
        else:
            await cb.answer("Сначала настрой фишки.", show_alert=False)
        return
    if user.energy <= 0:
        await cb.message.answer(_energy_wait_text(energy=user.energy, updated_at=user.energy_updated_at))
        await cb.answer("Нет энергии.", show_alert=False)
        return
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    await state.set_state(BattlePick.picking)
    await state.update_data(picked={}, inv_order=[k for k, _ in inv_items])
    paths: Dict[str, str] = {}
    for file_id, _ in inv_items:
        try:
            paths[file_id] = (await cache.get_static_sticker_path(bot, file_id)).local_path
        except Exception:
            pass
    out = os.path.join(os.getcwd(), "data", "renders", f"battle_pick_{cb.from_user.id}.png")
    render_profile(user_title=_display_name(cb), avatar_path=None, stickers=_inv_to_render(paths, inv_items), out_path=out)
    pic = FSInputFile(out)
    if cb.message:
        try:
            await cb.message.edit_media(media=InputMediaPhoto(media=pic, caption="Коллекция"), reply_markup=kb_battle_pick(inv_items, picked={}))
        except Exception:
            await cb.message.answer_photo(pic, caption="Коллекция", reply_markup=kb_battle_pick(inv_items, picked={}))
    await cb.answer()


async def _update_pick(cb: CallbackQuery, state: FSMContext, db: Database, inc: bool) -> None:
    inv = await db.get_inventory(cb.from_user.id)
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    data = await state.get_data()
    picked: Dict[str, int] = dict(data.get("picked", {}))
    inv_order: list[str] = list(data.get("inv_order", []))
    try:
        idx = int(cb.data.split(":", 1)[1])
        file_id = inv_order[idx]
    except Exception:
        await cb.answer("Кнопка устарела.", show_alert=False)
        return
    cur = int(picked.get(file_id, 0))
    if cur > 0:
        picked.pop(file_id, None)
    else:
        if file_id in inv and int(inv[file_id]) > 0:
            picked[file_id] = 1
    await state.update_data(picked=picked)
    await cb.message.edit_reply_markup(reply_markup=kb_battle_pick(inv_items, picked))
    await cb.answer()


@router.callback_query(BattlePick.picking, F.data.startswith("pick_toggle:"))
async def cb_pick_toggle(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    await _update_pick(cb, state, db, True)


@router.callback_query(BattlePick.picking, F.data == "battle_cancel")
async def cb_battle_cancel(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await state.clear()
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=True)
    await cb.answer()


@router.callback_query(BattlePick.picking, F.data == "battle_go")
async def cb_battle_go(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache, cfg) -> None:
    await _loading(cb)
    user = await get_user_with_regen(db, cb.from_user.id)
    if user.energy <= 0:
        inv0 = await db.get_inventory(cb.from_user.id)
        if not inv0:
            await cb.message.answer(_no_energy_and_chips_text(energy=user.energy, updated_at=user.energy_updated_at))
        else:
            await cb.message.answer(_energy_wait_text(energy=user.energy, updated_at=user.energy_updated_at))
        await cb.answer("Нет энергии.", show_alert=False)
        return
    inv = await db.get_inventory(cb.from_user.id)
    data = await state.get_data()
    picked: Dict[str, int] = dict(data.get("picked", {}))
    picked = {k: min(int(v), int(inv.get(k, 0))) for k, v in picked.items() if int(v) > 0 and int(inv.get(k, 0)) > 0}
    required = sum(picked.values())
    if required <= 0:
        await cb.answer("Выбери хотя бы одну фишку.", show_alert=False)
        return

    await db.update_energy(cb.from_user.id, user.energy - 1, updated_at=int(time.time()))
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
            await cb.message.answer("Не удалось собрать фишки противника: у тебя пустая коллекция.")
            await cb.answer()
            return
        import random

        enemy_ids = [random.choice(pool) for _ in range(len(player_units))]
        await cb.message.answer("Не удалось взять дефолтный набор противника, использую фолбэк из твоей коллекции.")

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

    paths: Dict[str, str] = {}
    for file_id in set([u.file_id for u in result.player_won] + [u.file_id for u in result.enemy_won]):
        try:
            paths[file_id] = (await cache.get_static_sticker_path(bot, file_id)).local_path
        except Exception:
            pass
    won = [RenderSticker(file_id=u.file_id, path=paths[u.file_id], count=int(u.nominal)) for u in result.player_won if u.file_id in paths]
    lost = [RenderSticker(file_id=u.file_id, path=paths[u.file_id], count=int(u.nominal)) for u in result.enemy_won if u.file_id in paths]
    out = os.path.join(os.getcwd(), "data", "renders", f"battle_{cb.from_user.id}_{int(time.time())}.png")
    avatar = await avatars.get_avatar_path(bot, cb.from_user.id)
    render_battle_result(title="Итог схватки", user_title=_display_name(cb), avatar_path=avatar, lost=lost, won=won, out_path=out)
    await state.clear()
    await cb.message.answer_photo(FSInputFile(out), caption="")
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id)


@router.callback_query(F.data == "e")
async def cb_energy(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    user = await get_user_with_regen(db, cb.from_user.id)
    await cb.message.answer(_energy_wait_text(energy=user.energy, updated_at=user.energy_updated_at))
    user = await get_user_with_regen(db, cb.from_user.id)
    await state.set_state(EnergySpend.menu)
    await cb.message.answer("Прокачайте существующие фишки или добавьте новые.", reply_markup=kb_energy_menu(user.energy))
    await cb.answer()


@router.callback_query(EnergySpend.menu, F.data == "eu")
async def cb_eu(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache) -> None:
    await _loading(cb)
    user = await get_user_with_regen(db, cb.from_user.id)
    if user.energy <= 0:
        await cb.message.answer(_energy_wait_text(energy=user.energy, updated_at=user.energy_updated_at))
        await cb.answer("Нет энергии.", show_alert=False)
        return
    inv = await db.get_inventory(cb.from_user.id)
    inv_items = sorted(inv.items(), key=lambda x: (-x[1], x[0]))
    await state.set_state(EnergySpend.upgrade)
    await state.update_data(spend={}, inv_order=[k for k, _ in inv_items])
    paths: Dict[str, str] = {}
    for file_id, _ in inv_items:
        try:
            paths[file_id] = (await cache.get_static_sticker_path(bot, file_id)).local_path
        except Exception:
            pass
    out = os.path.join(os.getcwd(), "data", "renders", f"energy_upgrade_{cb.from_user.id}.png")
    render_profile(user_title=_display_name(cb), avatar_path=None, stickers=_inv_to_render(paths, inv_items), out_path=out)
    pic = FSInputFile(out)
    if cb.message:
        try:
            await cb.message.edit_media(media=InputMediaPhoto(media=pic, caption="Коллекция"), reply_markup=kb_energy_upgrade(inv_items, spend={}, energy=user.energy))
        except Exception:
            await cb.message.answer_photo(pic, caption="Коллекция", reply_markup=kb_energy_upgrade(inv_items, spend={}, energy=user.energy))
    await cb.answer()


@router.callback_query(EnergySpend.upgrade, F.data.startswith("eu+:"))
async def cb_eu_plus(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
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
        await cb.answer("Энергия закончилась.", show_alert=False)
        return
    try:
        idx = int(cb.data.split(":", 1)[1])
        file_id = inv_order[idx]
    except Exception:
        await cb.answer("Кнопка устарела.", show_alert=False)
        return
    if file_id in inv:
        spend[file_id] = int(spend.get(file_id, 0)) + 1
        await state.update_data(spend=spend)
    try:
        if cb.message:
            await cb.message.edit_reply_markup(reply_markup=kb_energy_upgrade(inv_items, spend=spend, energy=user.energy))
    except Exception:
        pass


@router.callback_query(EnergySpend.upgrade, F.data == "eu_go")
async def cb_eu_go(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    user = await get_user_with_regen(db, cb.from_user.id)
    data = await state.get_data()
    spend: Dict[str, int] = dict(data.get("spend", {}))
    used = sum(int(x) for x in spend.values())
    if used <= 0:
        await cb.answer("Нечего применять.", show_alert=False)
        return
    if used > user.energy:
        await cb.answer("Не хватает энергии.", show_alert=False)
        return
    await db.add_inventory(cb.from_user.id, spend)
    await db.update_energy(cb.from_user.id, user.energy - used, updated_at=int(time.time()))
    await state.clear()
    await cb.message.answer("Готово. Фишки прокачаны.")
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id)


@router.callback_query(EnergySpend.upgrade, F.data == "eu_cancel")
async def cb_eu_cancel(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    await state.clear()
    await _render_and_send_profile(cb, bot=bot, db=db, cache=cache, avatars=avatars, user_id=cb.from_user.id, edit_in_place=True)
    await cb.answer()


@router.callback_query(EnergySpend.menu, F.data == "ea")
async def cb_ea(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    user = await get_user_with_regen(db, cb.from_user.id)
    if user.energy <= 0:
        await cb.message.answer(_energy_wait_text(energy=user.energy, updated_at=user.energy_updated_at))
        await cb.answer("Нет энергии.", show_alert=False)
        return
    await state.set_state(EnergySpend.add_sticker)
    await cb.message.answer("Пришли стикер: добавлю фишку (+1) за 1 энергию.")
    await cb.answer()


@router.message(EnergySpend.add_sticker)
async def on_ea_sticker(message: Message, state: FSMContext, db: Database, bot: Bot, cache: StickerCache, avatars: AvatarCache) -> None:
    user = await get_user_with_regen(db, message.from_user.id)
    if user.energy <= 0:
        await message.answer(_energy_wait_text(energy=user.energy, updated_at=user.energy_updated_at))
        return
    if message.content_type != ContentType.STICKER or message.sticker is None:
        await message.answer("Нужен стикер.")
        return
    file_id = _static_sticker_id(message.sticker)
    try:
        await cache.get_static_sticker_path(bot, file_id)
    except Exception:
        await message.answer("Не удалось использовать этот стикер.")
        return
    await db.add_inventory(message.from_user.id, {file_id: 1})
    await db.update_energy(message.from_user.id, user.energy - 1, updated_at=int(time.time()))
    await state.clear()
    await message.answer("Фишка добавлена.")
    await _render_and_send_profile(message, bot=bot, db=db, cache=cache, avatars=avatars, user_id=message.from_user.id)


@router.callback_query(F.data == "reset")
async def cb_reset(cb: CallbackQuery) -> None:
    await cb.message.answer("Сбросить все фишки?", reply_markup=kb_reset_confirm())
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


@router.message(Command("stats"))
async def cmd_stats(message: Message, db: Database, cfg: Config, bot: Bot) -> None:
    if cfg.admin_id is None or message.from_user.id != cfg.admin_id:
        return
    stats = await db.get_all_users_stats()
    if not stats:
        await message.answer("Нет игроков.")
        return
    total_duels = sum(s["duels_count"] for s in stats)
    total_nominal = sum(s["total_nominal"] for s in stats)
    lines = [f"📊 Игроков: {len(stats)}  |  Дуэлей: {total_duels}  |  Очков всего: {total_nominal}\n"]
    for s in stats:
        setup = "✅" if s["setup_done"] else "⏳"
        name = await _display_name_by_id(bot, s["user_id"])
        lines.append(
            f"{name} | 🃏{s['chips_count']} ({s['total_nominal']}⚡) | ⚡{s['energy']} | ⚔️{s['duels_count']} | {setup}"
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
