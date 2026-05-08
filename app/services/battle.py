from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List


def counts_from_list(file_ids: list[str]) -> Dict[str, int]:
    return dict(Counter(file_ids))


def expand_counts(counts: Dict[str, int]) -> list[str]:
    out: list[str] = []
    for file_id, cnt in counts.items():
        out.extend([file_id] * int(cnt))
    return out


@dataclass(frozen=True)
class BattleResult:
    player_won: List["BattleUnit"]
    enemy_won: List["BattleUnit"]


@dataclass(frozen=True)
class BattleUnit:
    file_id: str
    nominal: int


def run_battle(player_units: List[BattleUnit], enemy_units: List[BattleUnit]) -> BattleResult:
    all_units: List[BattleUnit] = list(player_units) + list(enemy_units)
    random.shuffle(all_units)
    player_won: List[BattleUnit] = []
    enemy_won: List[BattleUnit] = []

    for unit in all_units:
        if random.random() < 0.5:
            player_won.append(unit)
        else:
            enemy_won.append(unit)

    return BattleResult(player_won=player_won, enemy_won=enemy_won)


# Таблица: разница кеглей → доля победителя (от общей ⚡энергии пула)
PIN_DIFF_PCT: Dict[int, float] = {
    0: 0.50,
    1: 0.60,
    2: 0.65,
    3: 0.70,
    4: 0.75,
    5: 0.85,
    6: 1.00,
}


def distribute_by_slot(
    player_units: List[BattleUnit],
    enemy_units: List[BattleUnit],
    player_slot: int,
    enemy_slot: int,
) -> BattleResult:
    """Детерминированное распределение по разнице кеглей. Никакого random."""
    if player_slot == 0 and enemy_slot == 0:
        return BattleResult(player_won=list(player_units), enemy_won=list(enemy_units))
    diff = abs(player_slot - enemy_slot)
    w_pct = PIN_DIFF_PCT.get(diff, 1.00)
    player_wins = player_slot >= enemy_slot  # при ничьей нападающий = winner по w_pct=0.5

    # Детерминированная сортировка: сначала маленькие фишки, тай-брейк по file_id
    all_units: List[BattleUnit] = sorted(
        list(player_units) + list(enemy_units),
        key=lambda u: (u.nominal, u.file_id),
    )
    total_energy = sum(u.nominal for u in all_units)
    winner_quota = total_energy * w_pct

    winner_won: List[BattleUnit] = []
    loser_won: List[BattleUnit] = []
    winner_energy = 0.0
    for u in all_units:
        if winner_energy < winner_quota:
            winner_won.append(u)
            winner_energy += u.nominal
        else:
            loser_won.append(u)

    if player_wins:
        return BattleResult(player_won=winner_won, enemy_won=loser_won)
    else:
        return BattleResult(player_won=loser_won, enemy_won=winner_won)

