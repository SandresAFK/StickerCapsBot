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


def _winner_pct(diff: int) -> float:
    """Доля энергии победителя в зависимости от разницы слот-машин.
    Максимально близко к рандому (50/50), слот лишь слегка смещает шансы."""
    if diff < 15:
        return 0.50
    elif diff < 30:
        return 0.53
    elif diff < 45:
        return 0.57
    else:
        return 0.62


def distribute_by_slot(
    player_units: List[BattleUnit],
    enemy_units: List[BattleUnit],
    player_slot: int,
    enemy_slot: int,
) -> BattleResult:
    """Распределяет фишки пропорционально разнице значений слот-машины."""
    diff = abs(player_slot - enemy_slot)
    w_pct = _winner_pct(diff)
    player_pct = w_pct if player_slot >= enemy_slot else (1.0 - w_pct)

    all_units: List[BattleUnit] = list(player_units) + list(enemy_units)
    random.shuffle(all_units)
    total_energy = sum(u.nominal for u in all_units)
    player_quota = total_energy * player_pct

    player_won: List[BattleUnit] = []
    enemy_won: List[BattleUnit] = []
    player_energy = 0.0
    for u in all_units:
        if player_energy < player_quota:
            player_won.append(u)
            player_energy += u.nominal
        else:
            enemy_won.append(u)

    return BattleResult(player_won=player_won, enemy_won=enemy_won)

