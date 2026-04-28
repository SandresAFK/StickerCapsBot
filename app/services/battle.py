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

