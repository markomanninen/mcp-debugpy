#!/usr/bin/env python3
"""Run flaky tests repeatedly until first failure and collect diagnostics.

Usage:
  scripts/run_flaky_tests.py --nodeids <nodeid1> [<nodeid2> ...] [--outdir <dir>]

This script runs pytest for the provided node ids in sequence (one run per iteration),
stops on the first failing run, and writes diagnostics into a timestamped directory.
"""
import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = str(ROOT / ".venv" / "bin" / "python")


def collect_endpoints(outdir: Path):
    home_debugpy = Path.home() / ".debugpy"
    dest = outdir / "endpoints"
    dest.mkdir(parents=True, exist_ok=True)
    if home_debugpy.exists():
        for p in sorted(home_debugpy.glob("debugpy-endpoints-*.json")):
            try:
                name = p.name
                shutil.copy2(p, dest / name)
            except Exception:
                pass


def capture_ps(outdir: Path):
    try:
        p = subprocess.run(["ps", "-ef"], capture_output=True, text=True, check=False)
        (outdir / "ps.log").write_text(p.stdout)
    except Exception as e:
        (outdir / "ps.log").write_text(f"ps failed: {e}")


def run_diag_helper(outdir: Path):
    diag = ROOT / "scripts" / "diag_start_adapter.py"
    if not diag.exists():
        return
    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{ROOT}:{ROOT / 'src'}:{env.get('PYTHONPATH','')}"
        p = subprocess.run(
            [PY, str(diag)], capture_output=True, text=True, env=env, check=False
        )
        (outdir / "diag_start_adapter.log").write_text(
            p.stdout + "\n---stderr---\n" + p.stderr
        )
    except Exception as e:
        (outdir / "diag_start_adapter.log").write_text(
            f"failed running diag helper: {e}"
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--nodeids", nargs="+", required=True, help="pytest node ids to run"
    )
    ap.add_argument("--outdir", default="flake-logs", help="directory to store logs")
    ap.add_argument(
        "--max-iterations", type=int, default=1000, help="max iterations (safety)"
    )
    args = ap.parse_args()

    outroot = Path(args.outdir)
    outroot.mkdir(parents=True, exist_ok=True)

    iteration = 0
    for iteration in range(1, args.max_iterations + 1):
        print(f"Iteration {iteration} - running pytest for nodeids: {args.nodeids}")
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        run_out = outroot / ts
        run_out.mkdir(parents=True, exist_ok=True)

        # Run pytest for the nodeids (single invocation)
        cmd = [PY, "-m", "pytest", "-q"] + args.nodeids
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{ROOT}:{ROOT / 'src'}:{env.get('PYTHONPATH','')}"
        p = subprocess.run(cmd, capture_output=True, text=True, env=env)
        (run_out / "pytest.log").write_text(p.stdout + "\n---stderr---\n" + p.stderr)
        print("pytest exit code", p.returncode)

        # Collect endpoints and ps snapshot
        collect_endpoints(run_out)
        capture_ps(run_out)
        # Run diag helper to capture adapter state
        run_diag_helper(run_out)

        if p.returncode != 0:
            print("\nFound failure in iteration", iteration)
            print("Logs written to", run_out)
            print("Stopping loop for inspection.")
            sys.exit(1)

    print("Completed max iterations without failure")


if __name__ == "__main__":
    main()
