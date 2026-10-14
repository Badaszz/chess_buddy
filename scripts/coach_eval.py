# scripts/coach_eval.py   (pip install httpx python-chess)   usage: python coach_eval.py <base_url> <n_games>
import json, random, sys
import chess, httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
GAMES = int(sys.argv[2]) if len(sys.argv) > 2 else 3
H = {"X-Session-Id": "coach-eval-0001"}


def ask(c, gid, ply, action):
    done, ev = None, None
    with c.stream("POST", f"{BASE}/chat", json={"game_id": gid, "ply": ply, "action": action},
                  headers=H, timeout=60) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: ") and ev == "done":
                done = json.loads(line[6:])
    return done


n = first = fb = 0
with httpx.Client() as c:
    for _ in range(GAMES):
        g = c.post(f"{BASE}/games", json={"color": "white", "strength": "beginner"}, headers=H).json()
        while g["status"]["state"] == "ongoing" and len(g["moves"]) < 30:
            mv = random.choice(list(chess.Board(g["fen"]).legal_moves))
            res = c.post(f"{BASE}/games/{g['game_id']}/move", json={"uci": mv.uci()}, headers=H, timeout=30).json()
            if "game_id" not in res:
                break
            g = res
            ply = max(1, len(g["moves"]) - random.choice([0, 1]))
            d = ask(c, g["game_id"], ply, random.choice(["explain_move", "why_not_best", "plan"]))
            n += 1
            fb += d["fallback"]
            first += d["attempts"] == 1 and not d["fallback"]
print(f"{n} questions | first-pass {first / n:.1%} | facts-only fallback {fb / n:.1%}")