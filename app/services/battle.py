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


def distribute_by_slot(
    player_units: List[BattleUnit],
    enemy_units: List[BattleUnit],
    player_slot: int,
    enemy_slot: int,
) -> BattleResult:
    """Распределяет фишки пропорционально очкам боулинга: winner_score / total_score."""
    total_score = player_slot + enemy_slot
    player_wins = player_slot >= enemy_slot
    winner_score = max(player_slot, enemy_slot)
    w_pct = (winner_score / total_score) if total_score > 0 else 0.5

    all_units: List[BattleUnit] = list(player_units) + list(enemy_units)
    random.shuffle(all_units)
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

