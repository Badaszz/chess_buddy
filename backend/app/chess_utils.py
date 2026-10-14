import io

import chess
import chess.pgn

from .errors import ApiError


def board_from_pgn(pgn: str) -> chess.Board:
    game = chess.pgn.read_game(io.StringIO(pgn))
    board = game.board()
    for mv in game.mainline_moves():
        board.push(mv)
    return board


def pgn_from_board(board: chess.Board, player_color: str, result: str | None = None) -> str:
    game = chess.pgn.Game.from_board(board)
    game.headers["Event"] = "Chess Buddy"
    game.headers["White"] = "Player" if player_color == "white" else "Stockfish"
    game.headers["Black"] = "Stockfish" if player_color == "white" else "Player"
    if result is None:
        out = board.outcome(claim_draw=True)
        result = out.result() if out else "*"
    game.headers["Result"] = result
    return str(game)


def san_list(board: chess.Board) -> list[str]:
    b, out = board.root(), []
    for mv in board.move_stack:
        out.append(b.san(mv))
        b.push(mv)
    return out


def status_of(board: chess.Board) -> dict:
    out = board.outcome(claim_draw=True)
    if out is None:
        return {"state": "ongoing", "winner": None, "reason": None}
    winner = None if out.winner is None else chess.COLOR_NAMES[out.winner]
    if out.termination == chess.Termination.CHECKMATE:
        state = "checkmate"
    elif out.termination == chess.Termination.STALEMATE:
        state = "stalemate"
    else:
        state = "draw"
    return {"state": state, "winner": winner, "reason": out.termination.name.lower()}


def pv_to_san(board: chess.Board, pv: list[chess.Move], limit: int = 8) -> list[str]:
    b, out = board.copy(stack=False), []
    for mv in pv[:limit]:
        out.append(b.san(mv))
        b.push(mv)
    return out


def terminal_result(board: chess.Board, depth: int, multipv: int) -> dict:
    out, cp, mate = board.outcome(), 0, None
    if out and out.winner is not None:
        cp, mate = (10000 if out.winner == chess.WHITE else -10000), 0
    return {"depth": depth, "multipv": multipv, "eval_cp": cp, "mate_in": mate,
            "best_uci": None, "lines": []}


def parse_fen(fen: str) -> chess.Board:
    try:
        b = chess.Board(fen)
    except ValueError:
        raise ApiError(422, "invalid_fen", "That FEN is not valid")
    if not b.is_valid():
        raise ApiError(422, "invalid_fen", "That position is not legal")
    return b


def position_at(pgn: str, ply: int | None):
    """Replay a stored game to `ply`. Returns (board, board_before_last_move, last_move, ply)."""
    game = chess.pgn.read_game(io.StringIO(pgn))
    moves = list(game.mainline_moves())
    n = len(moves) if ply is None else ply
    if n > len(moves):
        raise ApiError(422, "bad_ply", "That position is past the end of the game")
    board, prev, last = game.board(), None, None
    for i, mv in enumerate(moves[:n]):
        if i == n - 1:
            prev, last = board.copy(), mv
        board.push(mv)
    return board, prev, last, n