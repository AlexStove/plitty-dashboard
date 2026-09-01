"""Register pre-uploaded pool videos in the AF content-catalog (colleague side).

STDLIB-ONLY on purpose: runs with bare Python 3 on the farm host — no repo
checkout, no pip installs. Reads the identity manifest produced by
pool_upload_minio.py (local file or an http(s)/presigned URL), binds the policy
fields (--allowed-platforms/--source/--kind) at register time, and POSTs each
unit to `POST {catalog}/content/register`.

Idempotent: the catalog dedupes on content_hash (ON CONFLICT DO NOTHING), and a
local state file skips already-registered units on re-run.

    python3 pool_register_catalog.py --manifest register_manifest.json \
        --catalog-url http://af-catalog:8081 \
        --allowed-platforms tiktok,youtube,instagram,facebook \
        --limit 1                      # smoke unit first!

WARNING: an EMPTY allowed_platforms makes a unit permanently un-claimable
(REST register applies no defaults, and re-register is a no-op) — that is why
--allowed-platforms is required and has no default.
"""

import argparse
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request


def _load_manifest(src):
    if src.startswith(("http://", "https://")):
        with urllib.request.urlopen(src, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8-sig"))
    else:
        with open(src, encoding="utf-8-sig") as f:  # BOM-tolerant (Windows editors)
            data = json.load(f)
    if not isinstance(data, list):
        raise SystemExit("manifest must be a JSON list")
    return data


def _load_state(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    return {r["content_id"]: r for r in rows} if isinstance(rows, list) else {}


def _save_state(path, state):
    fd, tmp = tempfile.mkstemp(prefix=".regstate.", suffix=".tmp",
                               dir=os.path.dirname(os.path.abspath(path)) or ".")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(list(state.values()), f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _post_json(url, payload, timeout=30):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def _get_json(url, timeout=60):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def register_one(catalog_url, unit, platforms, source, kind):
    payload = {
        "command_id": unit.get("command_id", ""),
        "content_id": unit["content_id"],
        "project": unit["project"],
        "content_type": unit["content_type"],
        "source": source,
        "source_job_id": unit.get("source_job_id", ""),
        "location": {
            "kind": kind,
            "bucket": unit["bucket"],
            "original_key": unit["original_key"],
            "thumb_key": unit.get("thumb_key", ""),
        },
        "allowed_platforms": platforms,
        "content_hash": unit["content_hash"],
        "width": unit.get("width", 0),
        "height": unit.get("height", 0),
        "duration_seconds": unit.get("duration_seconds", 0),
    }
    return _post_json(catalog_url.rstrip("/") + "/content/register", payload)


def main():
    parser = argparse.ArgumentParser(description="Register pool units in the AF content-catalog")
    parser.add_argument("--manifest", required=True, help="register_manifest.json path or URL")
    parser.add_argument("--catalog-url", required=True, help="e.g. http://af-catalog:8081")
    parser.add_argument("--allowed-platforms", required=True,
                        help="comma-separated, e.g. tiktok,youtube,instagram,facebook "
                             "(REQUIRED: empty platforms = permanently dead unit)")
    parser.add_argument("--source", default="manual")
    parser.add_argument("--kind", default="single")
    parser.add_argument("--limit", type=int, default=0, help="only first N units (0 = all)")
    parser.add_argument("--state", default="register_state.json")
    parser.add_argument("--verify-count", type=int, default=0,
                        help="after run: assert /content/available count >= N (use 500 for the full pool)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    platforms = [p.strip() for p in args.allowed_platforms.split(",") if p.strip()]
    if not platforms:
        raise SystemExit("--allowed-platforms must not be empty")

    units = _load_manifest(args.manifest)
    if args.limit:
        units = units[: args.limit]
    state = _load_state(args.state)

    done = errors = 0
    for unit in units:
        cid = unit["content_id"]
        if state.get(cid, {}).get("status") == "ok":
            done += 1
            continue
        if args.dry_run:
            print(f"would register {cid}  {unit.get('label', '')}")
            continue

        attempt = 0
        while True:
            attempt += 1
            try:
                code, body = register_one(args.catalog_url, unit, platforms, args.source, args.kind)
                state[cid] = {"content_id": cid, "status": "ok", "http_code": code}
                _save_state(args.state, state)
                done += 1
                print(f"[{done}/{len(units)}] {code} {cid}  {unit.get('label', '')}")
                break
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                if 400 <= e.code < 500:
                    # contract error: stop before poisoning more rows
                    state[cid] = {"content_id": cid, "status": "http_4xx", "http_code": e.code}
                    _save_state(args.state, state)
                    print(f"ABORT: {e.code} on {cid}: {body}", file=sys.stderr)
                    return 1
                if attempt >= 5:
                    state[cid] = {"content_id": cid, "status": "http_5xx", "http_code": e.code}
                    _save_state(args.state, state)
                    errors += 1
                    print(f"giving up on {cid}: {e.code} {body}", file=sys.stderr)
                    break
                time.sleep(min(2 ** attempt, 30))
            except (urllib.error.URLError, OSError) as e:
                if attempt >= 5:
                    state[cid] = {"content_id": cid, "status": "network_error", "http_code": 0}
                    _save_state(args.state, state)
                    errors += 1
                    print(f"giving up on {cid}: {e}", file=sys.stderr)
                    break
                time.sleep(min(2 ** attempt, 30))

    print(f"\nregistered/skipped: {done}, errors: {errors}, state: {args.state}")

    if args.verify_count and not args.dry_run:
        url = (args.catalog_url.rstrip("/")
               + f"/content/available?project=music&content_type=video&limit={args.verify_count + 100}")
        rows = _get_json(url) or []
        print(f"available in catalog: {len(rows)} (expected >= {args.verify_count})")
        if len(rows) < args.verify_count:
            print("MISMATCH: some units are missing — check content_hash collisions "
                  "(byte-identical files are silently deduped) and 4xx aborts",
                  file=sys.stderr)
            return 1

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
