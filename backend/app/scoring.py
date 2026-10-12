import math

import chess


def win_pct(cp: float) -> float:
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def pov_wp(eval_cp: int, color: chess.Color) -> float:
    """Win % for `color`, given a White-POV centipawn eval."""
    return win_pct(eval_cp if color == chess.WHITE else -eval_cp)


def classify(drop: float) -> str:
    return ("blunder" if drop >= 30 else "mistake" if drop >= 20
            else "inaccuracy" if drop >= 10 else "ok")


def move_accuracy(before: float, after: float) -> float:
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * (before - after)) - 3.1669))


def pick_mood(drop: float, gain_cp: float, gave_mate: bool) -> str:
    if drop >= 30:
        return "blunder"
    if drop >= 10:
        return "inaccuracy"
    if gave_mate or gain_cp >= 40:
        return "impressed"
    return "normal"