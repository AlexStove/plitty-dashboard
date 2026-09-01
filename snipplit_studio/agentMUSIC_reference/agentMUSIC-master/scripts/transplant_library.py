"""Transplant the local track/chorus library to a Linux agentMUSIC server.

Fast path for warming the server library WITHOUT re-running Whisper: chorus
records embed the word-timed lyrics, only the "path" values need fixing —
Windows writes backslash-relative paths that a Linux server treats as missing,
and the app's first list_user_* read PRUNES such records and re-saves the index
(self-destruct). Hence the mandatory non-destructive `verify` gate that runs
inside the stopped container BEFORE the app ever reads the index.

STDLIB-ONLY by design: merge/verify run on the server as
    docker run --rm -v <output_vol>:/app/output -w /app python:3.11 \
        python /app/output/transplant_library.py verify --index ...

Subcommands (run `pack` on the dev box from the repo root):
    pack   --user-id 694509855 [--output-base output] [--out output/_transplant]
    merge  --incoming <bundle index.json> --existing <server index.json>
    verify --index <index.json> --cwd /app
"""

import argparse
import json
import os
import shutil
import sys
import tarfile
import tempfile


def _load_list(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _save_atomic(path, rows):
    fd, tmp = tempfile.mkstemp(prefix=".index.", suffix=".tmp",
                               dir=os.path.dirname(os.path.abspath(path)) or ".")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _posix(path):
    return (path or "").replace("\\", "/")


def cmd_pack(args):
    src_user = os.path.join(args.output_base, str(args.user_id))
    out_user = os.path.join(args.out, str(args.user_id))
    total = 0
    for sub in ("_tracks", "_choruses"):
        src = os.path.join(src_user, sub)
        dst = os.path.join(out_user, sub)
        index = _load_list(os.path.join(src, "index.json"))
        if not index:
            print(f"skip {sub}: empty index", file=sys.stderr)
            continue
        os.makedirs(dst, exist_ok=True)
        kept = []
        for rec in index:
            local = rec.get("path", "")
            if not os.path.exists(local):
                print(f"  missing on disk, dropped: {local}", file=sys.stderr)
                continue
            shutil.copy2(local, os.path.join(dst, os.path.basename(local)))
            rec = dict(rec)
            rec["path"] = _posix(rec["path"])
            kept.append(rec)
        _save_atomic(os.path.join(dst, "index.json"), kept)
        total += len(kept)
        print(f"{sub}: {len(kept)} records packed")

    # ship this very script inside the bundle so the server side needs nothing else
    shutil.copy2(os.path.abspath(__file__), os.path.join(args.out, "transplant_library.py"))

    bundle = args.out.rstrip("/\\") + ".tar.gz"
    with tarfile.open(bundle, "w:gz") as tar:
        tar.add(args.out, arcname=os.path.basename(args.out.rstrip("/\\")))
    print(f"\nbundle: {bundle} ({total} records)")
    print("next: scp to the server, then merge + verify BEFORE starting the app")
    return 0


def cmd_merge(args):
    incoming = _load_list(args.incoming)
    existing = _load_list(args.existing)
    if not incoming:
        print(f"incoming index is empty: {args.incoming}", file=sys.stderr)
        return 1
    merged = {r.get("id"): r for r in incoming if r.get("id")}
    for rec in existing:          # existing server records win on id collision
        if rec.get("id"):
            merged[rec["id"]] = rec
    rows = list(merged.values())
    for rec in rows:
        rec["path"] = _posix(rec.get("path", ""))
    if args.backup and os.path.exists(args.existing):
        shutil.copy2(args.existing, args.existing + ".bak")
    _save_atomic(args.existing, rows)
    print(f"merged: {len(incoming)} incoming + {len(existing)} existing -> {len(rows)} records")
    return 0


def cmd_verify(args):
    """Non-destructive gate replicating the app's own pruning predicate:
    os.path.exists(record["path"]) resolved against the app CWD (/app)."""
    index = _load_list(args.index)
    if not index:
        print(f"FAIL: index empty or unreadable: {args.index}", file=sys.stderr)
        return 1
    os.chdir(args.cwd)
    bad = []
    for rec in index:
        path = rec.get("path", "")
        if "\\" in path:
            bad.append(f"backslash in path: {path}")
        elif not os.path.exists(path):
            bad.append(f"missing: {path}")
    if bad:
        print(f"FAIL ({len(bad)}/{len(index)}):", file=sys.stderr)
        for line in bad:
            print("  " + line, file=sys.stderr)
        return 1
    print(f"OK: all {len(index)} record paths resolve from {args.cwd}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Pack/merge/verify agentMUSIC library transplant")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("pack", help="pack _tracks + _choruses with posix paths into a tar.gz")
    p.add_argument("--user-id", type=int, default=694509855)
    p.add_argument("--output-base", default="output")
    p.add_argument("--out", default="output/_transplant")
    p.set_defaults(fn=cmd_pack)

    p = sub.add_parser("merge", help="merge incoming index.json into the server's existing one")
    p.add_argument("--incoming", required=True)
    p.add_argument("--existing", required=True)
    p.add_argument("--backup", action="store_true", default=True)
    p.set_defaults(fn=cmd_merge)

    p = sub.add_parser("verify", help="non-destructive check: every path resolves from --cwd")
    p.add_argument("--index", required=True)
    p.add_argument("--cwd", default="/app")
    p.set_defaults(fn=cmd_verify)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
