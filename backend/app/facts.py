import re

import chess

from .analysis_service import analysis
from .config import settings
from .engine import NORMAL, EngineManager
from .scoring import classify, pick_mood, pov_wp

VAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}


def norm(s: str) -> str:
    """Canonical SAN for set membership: no check/annotation marks, letter-O castling."""
    return s.strip().replace("0-0-0", "O-O-O").replace("0-0", "O-O").rstrip("+#!?")


def pawns(cp: int) -> float:
    return round(cp / 100, 2)


def eval_block(cp: int, mate: int | None) -> dict:
    if mate is not None:
        side = "White" if (mate > 0 or (mate == 0 and cp > 0)) else "Black"
        summary = f"{side} has a forced mate" + (f" in {abs(mate)}" if mate else " (game over)")
    else:
        a = abs(cp)
        if a < 30:
            summary = "roughly equal"
        else:
            side = "White" if cp > 0 else "Black"
            deg = "slightly better" if a < 100 else "clearly better" if a < 250 else "winning"
            summary = f"{side} is {deg}"
    return {"pawns_white_pov": pawns(cp), "mate_in": mate, "summary": summary}


def hanging(board: chess.Board) -> list[dict]:
    """Pieces that are undefended-and-attacked, or attacked by a cheaper piece. Ignores pins/x-rays (F12)."""
    out = []
    for sq, p in board.piece_map().items():
        if p.piece_type == chess.KING:
            continue
        attackers = board.attackers(not p.color, sq)
        if not attackers:
            continue
        cheapest = min(99 if board.piece_type_at(a) == chess.KING else VAL[board.piece_type_at(a)]
                       for a in attackers)
        undefended = not board.attackers(p.color, sq)
        if undefended or cheapest < VAL[p.piece_type]:
            out.append({"square": chess.square_name(sq), "piece": chess.piece_name(p.piece_type),
                        "color": chess.COLOR_NAMES[p.color],
                        "reason": "undefended" if undefended else "attacked by a cheaper piece"})
    return out


def material(board: chess.Board) -> dict:
    tot = {"white": 0, "black": 0}
    for p in board.piece_map().values():
        if p.piece_type != chess.KING:
            tot[chess.COLOR_NAMES[p.color]] += VAL[p.piece_type]
    return tot


# ---------- "what about Nf3?" detection in free-form questions ----------
SAN_TOKEN = re.compile(r"\b(O-O-O|O-O|[KQRBN][a-h]?[1-8]?x?[a-h][1-8]|[a-h]x[a-h][1-8]|[a-h][1-8](?:=[QRBN])?)[+#]?")
CUE = re.compile(r"what (about|if)|how about|instead|why not|should i (have )?play|play(ing)?", re.I)


def extract_whatif(question: str, board: chess.Board, skip: set[str]) -> chess.Move | None:
    cue = bool(CUE.search(question))
    for m in SAN_TOKEN.finditer(question):
        tok = m.group(1)
        if norm(tok) in skip:
            continue
        # plain pawn pushes ("e4") are ambiguous with square names, so they need a cue phrase
        if not (tok[0] in "KQRBNO" or "x" in tok or cue):
            continue
        try:
            return board.parse_san(tok)
        except ValueError:
            continue
    return None


async def build_facts(em: EngineManager, board: chess.Board, prev: chess.Board | None,
                      last: chess.Move | None, user_color: chess.Color,
                      whatif: chess.Move | None) -> tuple[dict, set[str], str]:
    d = settings.facts_depth
    cur = await analysis(em, board, d, 3, NORMAL)
    allowed = {norm(s) for line in cur["lines"] for s in line["san"]}
    all_san = [s for line in cur["lines"] for s in line["san"]]

    facts: dict = {
        "you_play": chess.COLOR_NAMES[user_color],
        "side_to_move": chess.COLOR_NAMES[board.turn],
        "fullmove": board.fullmove_number,
        "in_check": board.is_check(),
        "game_over": board.is_game_over(),
        "eval": eval_block(cur["eval_cp"], cur["mate_in"]),
        "top_lines": [{"rank": l["rank"], "eval_pawns_white_pov": pawns(l["eval_cp"]),
                       "mate_in": l["mate_in"], "moves": l["san"]} for l in cur["lines"]],
        "hanging": hanging(board),
        "checks_in_lines": sorted({s for s in all_san if "+" in s or "#" in s}),
        "captures_in_lines": sorted({s for s in all_san if "x" in s}),
        "material": material(board),
    }

    mood = "normal"
    if last is not None and prev is not None:
        before = await analysis(em, prev, d, 1, NORMAL)
        mover = prev.turn
        wb, wa = pov_wp(before["eval_cp"], mover), pov_wp(cur["eval_cp"], mover)
        drop = max(0.0, wb - wa)
        san = prev.san(last)
        best_line = before["lines"][0]["san"] if before["lines"] else []
        was_best = before["best_uci"] == last.uci()
        allowed |= {norm(san)} | {norm(s) for s in best_line}
        facts["last_move"] = {
            "san": san, "by": "you" if mover == user_color else "engine",
            "was_engine_best": was_best, "win_pct_before": round(wb, 1), "win_pct_after": round(wa, 1),
            "win_drop": round(drop, 1), "class": classify(drop),
            "engine_best_move": best_line[0] if best_line else None, "engine_best_line": best_line,
            "eval_before": eval_block(before["eval_cp"], before["mate_in"]),
        }
        if mover == user_color:      # the avatar only reacts to the player's own moves
            mood = pick_mood(drop, wa - wb, was_best, board.is_checkmate())

    if whatif is not None:
        mover, san = board.turn, board.san(whatif)
        after_board = board.copy()
        after_board.push(whatif)
        after = await analysis(em, after_board, d, 1, NORMAL)
        w_best, w_after = pov_wp(cur["eval_cp"], mover), pov_wp(after["eval_cp"], mover)
        drop = max(0.0, w_best - w_after)
        reply_line = after["lines"][0]["san"] if after["lines"] else []
        best_line = cur["lines"][0]["san"] if cur["lines"] else []
        allowed |= {norm(san)} | {norm(s) for s in reply_line}
        facts["what_if"] = {
            "move": san, "is_engine_best": cur["best_uci"] == whatif.uci(),
            "eval_after": eval_block(after["eval_cp"], after["mate_in"]),
            "win_pct_for_mover_after": round(w_after, 1), "win_drop_vs_best": round(drop, 1),
            "class": classify(drop), "engine_reply_line": reply_line,
            "engine_best_move": best_line[0] if best_line else None,
        }
    return facts, allowed, mood