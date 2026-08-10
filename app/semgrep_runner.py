"""Semgrep integration: run the pinned p/ci ruleset and parse its JSON (M3).

Never raises. If Semgrep is missing, times out, errors, or finds nothing,
this returns an empty list and the caller degrades gracefully — the same
pattern as the rate-limit fallback in llm_client.
"""

import json
import os
import shutil
import subprocess
import sys

SEMGREP_JSON_FILE = "semgrep_results.json"
SEMGREP_TIMEOUT_SECONDS = 300


def run_semgrep(repo_path):
    """Run Semgrep (--config=p/ci) over repo_path, return simplified findings.

    If semgrep_results.json already exists in repo_path (the workflow's
    semgrep step writes it), parse that instead of re-running Semgrep.
    """
    json_path = os.path.join(repo_path, SEMGREP_JSON_FILE)
    if os.path.exists(json_path):
        return _parse_semgrep_json(json_path)
    return _run_and_parse(repo_path)


def _find_semgrep():
    exe = shutil.which("semgrep")
    if exe:
        return exe
    candidate = os.path.join(
        os.path.dirname(sys.executable),
        "semgrep.exe" if os.name == "nt" else "semgrep",
    )
    if os.path.exists(candidate):
        return candidate
    return None


def _run_and_parse(repo_path):
    exe = _find_semgrep()
    if not exe:
        print("WARNING: semgrep not found; skipping static analysis", file=sys.stderr)
        return []
    cmd = [
        exe,
        "scan",
        "--config=p/ci",
        "--json",
        "-o",
        os.path.join(repo_path, SEMGREP_JSON_FILE),
        "--exclude",
        ".venv",
        "--exclude",
        ".git",
        repo_path,
    ]
    try:
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=SEMGREP_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        print(f"WARNING: semgrep failed ({err}); treating as no findings", file=sys.stderr)
        return []
    return _parse_semgrep_json(os.path.join(repo_path, SEMGREP_JSON_FILE))


def _parse_semgrep_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except UnicodeDecodeError:
        # semgrep on Windows may write ANSI (cp1252) instead of UTF-8.
        try:
            with open(path, encoding="cp1252") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as err:
            print(f"WARNING: could not parse semgrep output ({err}); treating as no findings", file=sys.stderr)
            return []
    except (OSError, json.JSONDecodeError) as err:
        print(f"WARNING: could not parse semgrep output ({err}); treating as no findings", file=sys.stderr)
        return []
    findings = []
    for result in data.get("results", []):
        start = result.get("start") or {}
        extra = result.get("extra") or {}
        findings.append(
            {
                "rule_id": result.get("check_id", "?"),
                "file": result.get("path", "?"),
                "line": start.get("line"),
                "message": (extra.get("message") or "").strip(),
                "severity": (extra.get("severity") or "").lower(),
            }
        )
    return findings
