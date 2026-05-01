from __future__ import annotations

from typing import Any


MESSAGES: dict[str, dict[str, str]] = {
    "accept": {"ru": "Принять", "en": "Accept"},
    "accept_battle": {"ru": "Принять бой ({current}/{target})", "en": "Accept battle ({current}/{target})"},
    "accepted_done_press_ready": {"ru": "Принято: 3/3. Нажми «Готово».", "en": "Accepted: 3/3. Tap \"Ready\"."},
    "accepted_progress": {"ru": "Принято: {count}/3", "en": "Accepted: {count}/3"},
    "add_new_chip": {"ru": "Добавить новую фишку", "en": "Add a new chip"},
    "attacker": {"ru": "Нападающий", "en": "Attacker"},
    "attacker_dash": {"ru": "Нападающий -", "en": "Attacker -"},
    "attacker_label_name": {"ru": "Нападающий ({name}):", "en": "Attacker ({name}):"},
    "attacker_label_you": {"ru": "Нападающий (ты, {name}):", "en": "Attacker (you, {name}):"},
    "back": {"ru": "Назад", "en": "Back"},
    "battle_link": {"ru": "Ссылка на бой:\n{link}", "en": "Battle link:\n{link}"},
    "battle_result_title": {"ru": "Итог схватки", "en": "Battle result"},
    "battle_with_friend": {"ru": "Схватка с другом", "en": "Battle with a friend"},
    "button_cancel": {"ru": "Отмена", "en": "Cancel"},
    "cannot_accept_own_duel": {"ru": "Нельзя принять свой вызов.", "en": "You cannot accept your own challenge."},
    "cannot_challenge_self": {"ru": "Нельзя вызвать самого себя.", "en": "You cannot challenge yourself."},
    "chips_saved": {"ru": "Фишки сохранены.", "en": "Chips saved."},
    "choose_at_least_one_chip": {"ru": "Выбери хотя бы одну фишку.", "en": "Choose at least one chip."},
    "choose_chips_buttons": {"ru": "выберите фишки кнопками", "en": "choose chips using the buttons"},
    "choose_chips_same_energy": {"ru": "Выберите фишки на нужную энергию.", "en": "Choose chips matching the required energy."},
    "collection": {"ru": "Коллекция", "en": "Collection"},
    "collection_caption": {"ru": "Твоя коллекция", "en": "Your collection"},
    "create_challenge": {"ru": "Создать вызов (⚡️{energy})", "en": "Create challenge (⚡️{energy})"},
    "daily_energy": {"ru": "Ежедневная энергия: ⚡️ {energy}/3", "en": "Daily energy: ⚡️ {energy}/3"},
    "daily_energy_spend": {"ru": "Ежедневная энергия: ⚡️ {energy}/3 • Потратить", "en": "Daily energy: ⚡️ {energy}/3 • Spend"},
    "decline": {"ru": "Отказаться", "en": "Decline"},
    "declined": {"ru": "Отклонено.", "en": "Declined."},
    "defender_label_name": {"ru": "Обороняющийся ({name}):", "en": "Defender ({name}):"},
    "defender_label_you": {"ru": "Обороняющийся (ты, {name}):", "en": "Defender (you, {name}):"},
    "duel_already_taken": {"ru": "Этот вызов уже принят.", "en": "This challenge has already been accepted."},
    "duel_finished": {"ru": "Бой завершён.", "en": "Battle finished."},
    "duel_invite_text": {
        "ru": "Тебя вызвал на бой {inviter} в игре Sticker CapsBot!\nНажми, чтобы принять бой: {link}",
        "en": "{inviter} challenged you in Sticker CapsBot!\nTap to accept the battle: {link}",
    },
    "duel_not_for_you": {"ru": "Этот вызов не для тебя.", "en": "This challenge is not for you."},
    "duel_offer_title": {"ru": "Дуэль vs {name}", "en": "Duel vs {name}"},
    "duel_unavailable": {"ru": "Вызов недоступен.", "en": "Challenge unavailable."},
    "energy_depleted": {"ru": "Энергия закончилась.", "en": "No energy left."},
    "energy_full": {"ru": "Энергия: {energy}/{max_energy}", "en": "Energy: {energy}/{max_energy}"},
    "energy_menu_prompt": {
        "ru": "Прокачайте существующие фишки или добавьте новые.",
        "en": "Upgrade existing chips or add new ones.",
    },
    "energy_restored": {
        "ru": "Энергия восстановилась до 3. Можешь получить новые фишки в меню энергии.",
        "en": "Energy has been restored to 3. You can get new chips in the energy menu.",
    },
    "equal_energy_needed": {
        "ru": "Общая энергия ваших фишек должна быть равна энергии соперника.",
        "en": "Your chips' total energy must match your opponent's energy.",
    },
    "forward_battle_link": {"ru": "Переслать ссылку на бой", "en": "Forward battle link"},
    "invite_rematch_dm_failed": {
        "ru": "Не удалось написать сопернику напрямую. Отправь ему ссылку на реванш:",
        "en": "Couldn't message your opponent directly. Send them the rematch link:",
    },
    "loading": {"ru": "Подождите, идёт загрузка…", "en": "Please wait, loading..."},
    "need_3_stickers": {"ru": "Нужно 3 стикера.", "en": "You need 3 stickers."},
    "need_choose_same_energy": {
        "ru": "Нужно выбрать фишки на ту же энергию.",
        "en": "You need to choose chips with the same energy.",
    },
    "need_sticker": {"ru": "Нужен стикер.", "en": "A sticker is required."},
    "no_chips": {"ru": "Фишек нет.", "en": "No chips."},
    "no_chips_and_energy": {"ru": "У вас нет энергии и фишек.\n{energy_text}", "en": "You have no energy and no chips.\n{energy_text}"},
    "no_chips_notify": {
        "ru": "У вас нет фишек.\nВы можете получить новые фишки через {time_left}.\nВы получите уведомление, когда энергия восстановится.",
        "en": "You have no chips.\nYou can get new chips in {time_left}.\nYou will receive a notification when energy is restored.",
    },
    "no_chips_setup_hint": {"ru": "Фишек нет. Нажмите «Настроить фишки».", "en": "No chips. Tap \"Set up chips\"."},
    "no_chips_wait_line": {"ru": "Вы можете получить новые фишки через {time_left}.", "en": "You can get new chips in {time_left}."},
    "no_energy": {"ru": "Нет энергии.", "en": "No energy."},
    "no_energy_wait": {"ru": "Нет энергии. Новая энергия появится через {time_left}.", "en": "No energy. New energy will appear in {time_left}."},
    "no_players": {"ru": "Нет игроков.", "en": "No players."},
    "noop_hint": {"ru": "Выберите фишки на нужную энергию.", "en": "Choose chips matching the required energy."},
    "not_enough_energy": {"ru": "Не хватает энергии.", "en": "Not enough energy."},
    "nothing_to_apply": {"ru": "Нечего применять.", "en": "Nothing to apply."},
    "notification_when_energy_restored": {
        "ru": "Вы получите уведомление, когда энергия восстановится.",
        "en": "You will receive a notification when energy is restored.",
    },
    "opponent": {"ru": "Соперник:", "en": "Opponent:"},
    "opponent_build_failed_empty": {
        "ru": "Не удалось собрать фишки противника: у тебя пустая коллекция.",
        "en": "Couldn't build opponent chips: your collection is empty.",
    },
    "player": {"ru": "Игрок", "en": "Player"},
    "player_by_id": {"ru": "Игрок #{user_id}", "en": "Player #{user_id}"},
    "profile_energy_duels": {"ru": "{energy} · {duels} дуэлей", "en": "{energy} · {duels} duels"},
    "profile_totals": {"ru": "{chips} фишек · ", "en": "{chips} chips · "},
    "ready": {"ru": "Готово", "en": "Ready"},
    "rematch": {"ru": "Реванш", "en": "Rematch"},
    "rematch_dm_sent": {"ru": "Приглашение на реванш отправлено сопернику в личку.", "en": "Rematch invitation sent to your opponent in DM."},
    "reset_all_chips": {"ru": "Сбросить все фишки?", "en": "Reset all chips?"},
    "reset_confirm": {"ru": "Да, сбросить", "en": "Yes, reset"},
    "send_3_stickers": {"ru": "Отправь 3 любых стикера и нажми «Готово».", "en": "Send any 3 stickers and tap \"Ready\"."},
    "send_link_friend": {"ru": "Это твой вызов. Отправь ссылку другу.", "en": "This is your challenge. Send the link to a friend."},
    "send_sticker_to_add": {"ru": "Пришли стикер: добавлю фишку (+1) за 1 энергию.", "en": "Send a sticker: I'll add a chip (+1) for 1 energy."},
    "setup_default_failed": {
        "ru": "Не удалось выдать фишки по умолчанию. Выбери любимые стикеры.",
        "en": "Couldn't issue the default chips. Choose your favorite stickers.",
    },
    "setup_default_failed_hint": {
        "ru": "Не удалось выдать фишки по умолчанию. Нажми «Выбрать любимые стикеры».",
        "en": "Couldn't issue the default chips. Tap \"Choose favorite stickers\".",
    },
    "setup_default_done": {"ru": "Готово! Выданы 3 фишки по умолчанию.", "en": "Done! 3 default chips have been issued."},
    "setup_first": {"ru": "Сначала настрой фишки.", "en": "Set up your chips first."},
    "share_own_link": {"ru": "Переслать ссылку на бой", "en": "Forward battle link"},
    "start_battle": {"ru": "Начать схватку (⚡️{energy})", "en": "Start battle (⚡️{energy})"},
    "stale_button": {"ru": "Кнопка устарела.", "en": "This button is outdated."},
    "stats_header": {"ru": "📊 Игроков: {players}  |  Дуэлей: {duels}  |  Очков всего: {points}\n", "en": "📊 Players: {players}  |  Duels: {duels}  |  Total points: {points}\n"},
    "sticker_added": {"ru": "Фишка добавлена.", "en": "Chip added."},
    "sticker_unavailable": {"ru": "Не удалось использовать этот стикер.", "en": "Couldn't use this sticker."},
    "use_collection_fallback": {
        "ru": "Не удалось взять дефолтный набор противника, использую фолбэк из твоей коллекции.",
        "en": "Couldn't use the default opponent set, using a fallback from your collection.",
    },
    "trophies": {"ru": "Трофеи:", "en": "Trophies:"},
    "upgrade_apply": {"ru": "Применить ({used}/{energy})", "en": "Apply ({used}/{energy})"},
    "upgrade_chips_done": {"ru": "Готово. Фишки прокачаны.", "en": "Done. Chips upgraded."},
    "upgrade_existing_chips": {"ru": "Прокачать существующие фишки", "en": "Upgrade existing chips"},
    "use_default_stickers": {"ru": "Использовать стикеры по умолчанию", "en": "Use default stickers"},
    "use_favorite_stickers": {"ru": "Выбрать любимые стикеры", "en": "Choose favorite stickers"},
    "wait_for_energy_notify": {
        "ru": "Вы получите уведомление, когда энергия восстановится.",
        "en": "You will receive a notification when energy is restored.",
    },
    "won": {"ru": "Выиграно", "en": "Won"},
    "yes_reset": {"ru": "Да, сбросить", "en": "Yes, reset"},
}


def normalize_language_code(language_code: str | None) -> str:
    code = (language_code or "").strip().lower()
    return "ru" if code.startswith("ru") else "en"


def get_event_lang(event: Any) -> str:
    from_user = getattr(event, "from_user", None)
    return normalize_language_code(getattr(from_user, "language_code", None))


def t(lang: str, key: str, **kwargs: Any) -> str:
    item = MESSAGES[key]
    template = item["ru"] if normalize_language_code(lang) == "ru" else item["en"]
    return template.format(**kwargs)
