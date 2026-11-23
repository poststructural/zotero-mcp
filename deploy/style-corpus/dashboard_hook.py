#!/usr/bin/env python3
"""Bridge between the Strands dashboard (stdlib Python) and the style corpus (its own venv).

The dashboard calls this script with the corpus venv's Python, so numpy/fastembed never have to be
installed for the dashboard itself. Both commands read JSON on stdin and write JSON on stdout.

  python dashboard_hook.py block [--no-baseline] [--max 10] [--k 2]
      stdin:  [[paragraph_id, text, is_heading], ...]        (the strand body, as gpt_review.manuscript gives it)
      stdout: {"block": "<prompt section>", "used": [...]}

  python dashboard_hook.py screen
      stdin:  [[old, new], ...]
      stdout: [[problem, ...], ...]                           (one list per pair; empty list = clean)
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["block", "screen"])
    ap.add_argument("--no-baseline", action="store_true"); ap.add_argument("--max", type=int, default=10)
    ap.add_argument("--k", type=int, default=2)
    a = ap.parse_args()
    data = json.load(sys.stdin)
    if a.cmd == "block":
        from exemplars import corpus_block
        paras = [(int(i), t, bool(h)) for i, t, h in data]
        block, used = corpus_block(paras, max_targets=a.max, k=a.k, baseline=not a.no_baseline)
        json.dump({"block": block, "used": used}, sys.stdout)
    else:
        import guard
        from common import db
        con = db()
        json.dump([guard.check(o, n, con) for o, n in data], sys.stdout)


if __name__ == "__main__":
    main()
