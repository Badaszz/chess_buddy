import asyncio
import itertools
from collections import OrderedDict

import chess
import chess.engine

from .chess_utils import pv_to_san, terminal_result
from .config import settings

HIGH, NORMAL, LOW = 0, 1, 2

# preset -> (UCI options, movetime seconds)
PRESETS: dict[str, tuple[dict, float]] = {
    "beginner": ({"UCI_LimitStrength": False, "Skill Level": 0}, 0.15),
    "casual":   ({"UCI_LimitStrength": False, "Skill Level": 5}, 0.30),
    "club":     ({"UCI_LimitStrength": True, "UCI_Elo": 1500}, 0.50),
    "advanced": ({"UCI_LimitStrength": True, "UCI_Elo": 2000}, 0.70),
    "max":      ({"UCI_LimitStrength": False, "Skill Level": 20}, 1.00),
}


class EngineBusy(Exception):
    pass


class EngineManager:
    def __init__(self):
        self.queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._seq = itertools.count()
        self._eng: list[chess.engine.UciProtocol | None] = []
        self._workers: list[asyncio.Task] = []
        self._mem: OrderedDict[str, dict] = OrderedDict()

    # ---------- lifecycle ----------
    @property
    def ready(self) -> int:
        return sum(e is not None for e in self._eng)

    async def _spawn(self):
        _, eng = await chess.engine.popen_uci(settings.stockfish_path)
        await eng.configure({"Threads": 1, "Hash": settings.hash_mb})
        return eng

    async def start(self):
        self.queue = asyncio.PriorityQueue()
        for i in range(settings.engine_count):
            self._eng.append(await self._spawn())
            self._workers.append(asyncio.create_task(self._worker(i)))

    async def stop(self):
        for w in self._workers:
            w.cancel()
        for e in self._eng:
            if e:
                try:
                    await e.quit()
                except Exception:
                    pass

    async def _respawn(self, i: int):
        self._eng[i] = None
        while True:
            try:
                self._eng[i] = await self._spawn()
                return
            except Exception:
                await asyncio.sleep(2)

    async def _worker(self, i: int):
        while True:
            _, _, job, fut = await self.queue.get()
            if fut.cancelled():
                continue
            try:
                res = await job(self._eng[i])
            except chess.engine.EngineError as e:       # includes EngineTerminatedError
                if not fut.cancelled():
                    fut.set_exception(e)
                if isinstance(e, chess.engine.EngineTerminatedError):
                    await self._respawn(i)
            except Exception as e:
                if not fut.cancelled():
                    fut.set_exception(e)
            else:
                if not fut.cancelled():
                    fut.set_result(res)

    async def submit(self, job, priority: int = NORMAL):
        if priority != LOW and self.queue.qsize() >= settings.max_queue:
            raise EngineBusy()
        fut = asyncio.get_running_loop().create_future()
        await self.queue.put((priority, next(self._seq), job, fut))
        return await fut

    # ---------- cache (keyed by EPD so transpositions hit) ----------
    @staticmethod
    def clamp(depth: int, multipv: int) -> tuple[int, int]:
        return min(depth, settings.analysis_depth_cap), min(multipv, settings.multipv_cap)

    def lookup(self, board: chess.Board, depth: int, multipv: int) -> dict | None:
        k = board.epd()
        for (d, m), res in self._mem.get(k, {}).items():
            if d >= depth and m >= multipv:       # a deeper / wider result satisfies a shallower ask
                self._mem.move_to_end(k)
                return res
        return None

    def store(self, board: chess.Board, depth: int, multipv: int, res: dict):
        k = board.epd()
        self._mem.setdefault(k, {})[(depth, multipv)] = res
        self._mem.move_to_end(k)
        while len(self._mem) > 5000:
            self._mem.popitem(last=False)

    # ---------- searches ----------
    async def play(self, board: chess.Board, preset: str, priority: int = HIGH) -> chess.Move:
        opts, movetime = PRESETS[preset]
        movetime = min(movetime, settings.play_movetime_cap)
        b = board.copy()

        async def job(e):
            o = dict(opts)
            if "UCI_Elo" in o and "UCI_Elo" in e.options:     # clamp to this build's range
                lim = e.options["UCI_Elo"]
                o["UCI_Elo"] = max(lim.min, min(lim.max, o["UCI_Elo"]))
            r = await e.play(b, chess.engine.Limit(time=movetime), options=o)
            return r.move

        return await self.submit(job, priority)

    async def analyse_pos(self, board: chess.Board, depth: int = 14, multipv: int = 3,
                          priority: int = NORMAL) -> dict:
        depth, multipv = self.clamp(depth, multipv)
        if (hit := self.lookup(board, depth, multipv)) is not None:
            return hit
        if board.is_game_over():
            res = terminal_result(board, depth, multipv)
            self.store(board, depth, multipv, res)
            return res
        b = board.copy()

        async def job(e):
            return await e.analyse(b, chess.engine.Limit(depth=depth), multipv=multipv,
                                   options={"UCI_LimitStrength": False, "Skill Level": 20})

        infos = await self.submit(job, priority)
        infos = infos if isinstance(infos, list) else [infos]
        lines = []
        for i, info in enumerate(infos, 1):
            sc, pv = info["score"].white(), info.get("pv", [])
            lines.append({"rank": i, "eval_cp": sc.score(mate_score=10000), "mate_in": sc.mate(),
                          "uci": [m.uci() for m in pv[:8]], "san": pv_to_san(board, pv)})
        top = lines[0]
        res = {"depth": depth, "multipv": multipv, "eval_cp": top["eval_cp"], "mate_in": top["mate_in"],
               "best_uci": top["uci"][0] if top["uci"] else None, "lines": lines}
        self.store(board, depth, multipv, res)
        return res