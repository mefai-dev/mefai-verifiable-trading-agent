#!/usr/bin/env python3
"""Reproducible backtest orchestrator for the Track 2 strategy skills.

Runs every skill's deterministic backtest against a pinned signal dataset,
fingerprints the inputs (dataset) and the strategy code that produced the
result, and writes a self-verifying artifact:

  skills/<skill>/output/report.manifest.json   (per skill)
  skills/BACKTEST_REPORTS.json                  (index + env fingerprint)

Each manifest carries:
  - dataset:  path, sha256, table row counts  (the exact inputs)
  - code:     sha256 of the skill backtest + the strategy engine modules
  - result:   PASS / FAIL from the backtest's own exit code, plus its report
  - content_hash: sha256 of the canonical report payload

Reproducibility contract: with the same pinned dataset and the same code, a
re-run produces identical `content_hash` and `dataset.sha256` / `code.sha256`
values. A judge regenerates with `python3 skills/run_backtests.py` and compares
BACKTEST_REPORTS.json. Read-only and deterministic; signs nothing.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
import time

SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SKILLS_DIR)                 # .../bnbhack
AGENT = os.path.join(ROOT, "agent")

# Strategy engine modules that the skill backtests import; their bytes are part
# of the result's provenance, so they are fingerprinted alongside each backtest.
ENGINE_MODULES = ["tp_sl_optimizer.py", "leaderboard.py", "sizing.py",
                  "fusion_core.py"]

# Pinned dataset resolution: explicit env wins, else the public sample db, else
# the production db. The chosen path is recorded in every manifest.
_DB_CANDIDATES = [
    os.path.join(os.path.dirname(ROOT), "data", "signal.db"),   # public sample
    os.path.join(ROOT, "data", "signal.db"),
    os.path.join(os.path.dirname(ROOT), "api", "security", "signal.db"),  # production
]


def _resolve_db() -> str:
    env = os.environ.get("MEFAI_SIGNAL_DB")
    if env:
        return env
    for p in _DB_CANDIDATES:
        if os.path.exists(p):
            return p
    return _DB_CANDIDATES[0]


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _dataset_fingerprint(db_path: str) -> dict:
    fp: dict = {"path": os.path.relpath(db_path, ROOT) if db_path.startswith(ROOT)
                else db_path}
    if not os.path.exists(db_path):
        fp["present"] = False
        return fp
    fp["present"] = True
    fp["bytes"] = os.path.getsize(db_path)
    fp["sha256"] = _sha256_file(db_path)
    counts: dict = {}
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            tables = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            for t in tables:
                try:
                    counts[t] = con.execute(
                        f"SELECT COUNT(*) FROM \"{t}\"").fetchone()[0]
                except sqlite3.Error:
                    counts[t] = None
        finally:
            con.close()
    except sqlite3.Error as exc:
        fp["count_error"] = str(exc)
    fp["row_counts"] = counts
    return fp


def _code_fingerprint(skill_dir: str) -> dict:
    files: dict = {}
    bt = os.path.join(skill_dir, "backtest", "backtest.py")
    if os.path.exists(bt):
        files["backtest/backtest.py"] = _sha256_file(bt)
    for m in ENGINE_MODULES:
        p = os.path.join(AGENT, m)
        if os.path.exists(p):
            files[f"agent/{m}"] = _sha256_file(p)
    combined = _sha256_bytes(_canonical(files))
    return {"files": files, "sha256": combined}


def _run_skill(skill: str, db_path: str) -> dict:
    skill_dir = os.path.join(SKILLS_DIR, skill)
    bt = os.path.join(skill_dir, "backtest", "backtest.py")
    out_dir = os.path.join(skill_dir, "output")
    os.makedirs(out_dir, exist_ok=True)

    env = dict(os.environ)
    env["MEFAI_SIGNAL_DB"] = db_path
    env["PYTHONHASHSEED"] = "0"
    proc = subprocess.run(
        [sys.executable, bt], env=env, cwd=skill_dir,
        capture_output=True, text=True, timeout=600)
    passed = proc.returncode == 0

    report = None
    report_path = os.path.join(out_dir, "report.json")
    if os.path.exists(report_path):
        try:
            with open(report_path) as fh:
                report = json.load(fh)
        except (OSError, json.JSONDecodeError):
            report = None

    content_hash = _sha256_bytes(_canonical(report)) if report is not None else None
    tail = "\n".join(proc.stdout.strip().splitlines()[-3:])

    manifest = {
        "skill": skill,
        "result": "PASS" if passed else "FAIL",
        "exit_code": proc.returncode,
        "dataset": _dataset_fingerprint(db_path),
        "code": _code_fingerprint(skill_dir),
        "content_hash": content_hash,
        "report_relpath": "output/report.json",
        "repro_command": f"python3 skills/run_backtests.py {skill}",
        "stdout_tail": tail,
        "report": report,
    }
    with open(os.path.join(out_dir, "report.manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    return manifest


def _discover() -> list:
    out = []
    for name in sorted(os.listdir(SKILLS_DIR)):
        d = os.path.join(SKILLS_DIR, name)
        if os.path.isdir(d) and os.path.exists(
                os.path.join(d, "backtest", "backtest.py")):
            out.append(name)
    return out


def main(argv: list) -> int:
    only = set(argv)
    db_path = _resolve_db()
    skills = [s for s in _discover() if not only or s in only]
    if not skills:
        print("no skills matched", file=sys.stderr)
        return 2

    results = []
    for s in skills:
        m = _run_skill(s, db_path)
        results.append(m)
        print(f"{m['result']:4s}  {s:32s}  content_hash={m['content_hash']}")

    overall = all(m["result"] == "PASS" for m in results)
    index = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "overall": "PASS" if overall else "FAIL",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dataset": _dataset_fingerprint(db_path),
        "skills": [{
            "skill": m["skill"], "result": m["result"],
            "content_hash": m["content_hash"], "code_sha256": m["code"]["sha256"],
            "manifest": f"skills/{m['skill']}/output/report.manifest.json",
        } for m in results],
    }
    # Repository-stable digest over the per-skill provenance (excludes the
    # wall-clock + host fields above so it is reproducible across machines).
    index["repro_digest"] = _sha256_bytes(_canonical({
        "dataset_sha256": index["dataset"].get("sha256"),
        "skills": [{"skill": s["skill"], "content_hash": s["content_hash"],
                    "code_sha256": s["code_sha256"], "result": s["result"]}
                   for s in index["skills"]],
    }))
    with open(os.path.join(SKILLS_DIR, "BACKTEST_REPORTS.json"), "w") as fh:
        json.dump(index, fh, indent=2, sort_keys=True)

    print(f"\noverall: {index['overall']}   repro_digest={index['repro_digest']}")
    print(f"dataset: {index['dataset'].get('path')}  "
          f"sha256={index['dataset'].get('sha256')}")
    print("wrote skills/BACKTEST_REPORTS.json")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
