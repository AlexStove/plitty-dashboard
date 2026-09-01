#!/usr/bin/env python3
"""behavior_model.py — ЛЁГКАЯ behavior-модель (статистика+Марков), обучается на
data/behavior/*.jsonl (синтет.засев + реальный флот). Без GPU, на CPU.

Учит: распределение точек входа, событий-на-сессию, dwell по типу(видео/текст),
МАРКОВ-переходы действий, частоту лайков/свитчей, длительность свитча, активность
по часам. Генерит «план дня персоны» -> исполняют КОРы. Реальные данные приоритетнее
синтетики (вес ×3) — модель уточняется по мере накопления.

  python -m brain.behavior_model train        # обучить -> data/behavior_model.json
  python -m brain.behavior_model gen 19        # сэмпл сессии для часа 19
"""
from __future__ import annotations

import json
import random
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BDIR = ROOT / "data" / "behavior"
MODEL = ROOT / "data" / "behavior_model.json"
REAL_W = 3            # реальные события весомее синтетики
ACTIONS = ("dwell", "read", "like", "scroll", "scroll_back", "app_switch")


def _iter_events():
    """Все события из data/behavior/ (per-device + _seed). real=не synthetic_seed."""
    for p in BDIR.glob("*.jsonl"):
        if p.name == "_stream.jsonl":
            continue
        try:
            for ln in p.read_text(encoding="utf-8").splitlines():
                if ln.strip():
                    r = json.loads(ln)
                    r["_real"] = r.get("source") != "synthetic_seed"
                    yield r
        except Exception:
            continue


def _pct(xs):
    xs = sorted(xs)
    if not xs:
        return {}
    n = len(xs)
    return {"n": n, "mean": round(st.mean(xs), 2),
            "p10": round(xs[int(n * .1)], 2), "p50": round(xs[n // 2], 2),
            "p90": round(xs[min(n - 1, int(n * .9))], 2),
            "min": round(xs[0], 2), "max": round(xs[-1], 2)}


def train(out=MODEL) -> dict:
    entry = Counter()
    per_sess = []                       # событий действий на сессию
    dwell = defaultdict(list)           # kind -> [сек]
    trans = defaultdict(Counter)        # марков: cur_event -> Counter(next_event)
    likes = Counter(); dwells = Counter()
    switch_dur = []; n_switch = 0; n_act = 0
    hour_hist = Counter()
    sessions = defaultdict(list)        # sid -> [events] (для марков+счёта)

    for r in _iter_events():
        w = REAL_W if r.get("_real") else 1
        ev = r.get("event"); sid = r.get("session")
        if ev == "session_start":
            for _ in range(w):
                entry[r.get("entry", "icon")] += 1
                hour_hist[r.get("hour", 12)] += 1
        if sid:
            sessions[sid].append(r)
        if ev in ("dwell", "read") and r.get("dur_s") is not None:
            dwell[r.get("kind", "video")].append(r["dur_s"]); dwells[r.get("kind", "video")] += w
        if ev == "like":
            likes[r.get("kind", "video")] += w
        if ev == "app_switch" and r.get("dur_s") is not None:
            switch_dur.append(r["dur_s"]); n_switch += w
        if ev in ACTIONS:
            n_act += w

    # марков-переходы + событий-на-сессию
    for sid, evs in sessions.items():
        acts = [e["event"] for e in evs if e["event"] in ACTIONS]
        per_sess.append(len(acts))
        for a, b in zip(acts, acts[1:]):
            trans[a][b] += 1

    def norm(c):
        tot = sum(c.values()) or 1
        return {k: round(v / tot, 4) for k, v in c.items()}

    model = {
        "entry": norm(entry),
        "events_per_session": _pct(per_sess),
        "dwell": {k: _pct(v) for k, v in dwell.items()},
        "transitions": {a: norm(c) for a, c in trans.items()},
        "like_rate": {k: round(likes[k] / max(1, dwells[k]), 4) for k in dwells},
        "switch_rate": round(n_switch / max(1, n_act), 4),
        "switch_dur": _pct(switch_dur),
        "active_hours": norm(hour_hist),
        "trained_events": n_act, "real_events": sum(1 for r in _iter_events() if r.get("_real")),
    }
    out.write_text(json.dumps(model, ensure_ascii=False, indent=1), encoding="utf-8")
    return model


def load():
    try:
        return json.loads(MODEL.read_text(encoding="utf-8"))
    except Exception:
        return None


def _samp_pct(p):
    """Сэмпл из перцентилей (грубая обратная CDF)."""
    if not p:
        return random.uniform(2, 10)
    r = random.random()
    if r < .1:
        return random.uniform(p["min"], p["p10"])
    if r < .5:
        return random.uniform(p["p10"], p["p50"])
    if r < .9:
        return random.uniform(p["p50"], p["p90"])
    return random.uniform(p["p90"], p["max"])


def _pick(dist):
    r = random.random(); acc = 0
    for k, p in dist.items():
        acc += p
        if r <= acc:
            return k
    return next(iter(dist), None)


def generate_session(m, kind="video", max_actions=None):
    """План сессии: список действий по марков-цепи + сэмплы dwell. Исполняют КОРы."""
    m = m or load() or train()
    n = max_actions or max(4, int(_samp_pct(m["events_per_session"])))
    plan, cur = [], "dwell" if kind == "video" else "read"
    for _ in range(n):
        if cur in ("dwell", "read"):
            plan.append({"action": cur, "dur_s": round(_samp_pct(m["dwell"].get(kind, {})), 2)})
        elif cur == "like":
            plan.append({"action": "like"})
        elif cur == "app_switch":
            plan.append({"action": "app_switch", "dur_s": round(_samp_pct(m["switch_dur"]), 2)})
        else:
            plan.append({"action": cur})
        nxt = m["transitions"].get(cur)
        cur = _pick(nxt) if nxt else ("dwell" if kind == "video" else "read")
    return plan


def main():
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    cmd = sys.argv[1] if len(sys.argv) > 1 else "train"
    if cmd == "train":
        m = train()
        print(f"обучено: {m['trained_events']} действий ({m['real_events']} реальных)")
        print("entry:", m["entry"])
        print("dwell video:", m["dwell"].get("video"))
        print("like_rate:", m["like_rate"], "| switch_rate:", m["switch_rate"])
    elif cmd == "gen":
        kind = "video"
        plan = generate_session(load(), kind)
        print(f"план сессии ({len(plan)} действий):")
        for a in plan[:20]:
            print("  ", a)


if __name__ == "__main__":
    main()
