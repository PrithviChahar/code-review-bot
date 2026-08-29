"""M4 integration test: FP filter catches the all-caps constant false positive.

Uses mock agents (no API calls for reviewer/security/summary/tests/semgrep)
but calls filter_false_positives with the real Groq LLM.
"""
import sys
import os
import time
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))

from supervisor import filter_false_positives

print("=" * 60)
print("M4 FP Filter Test (real Groq LLM call)")
print("=" * 60)

issues = [
    {"severity": "warning", "file": "app/config.py", "line": 12,
     "message": "Magic number 42 found; SYSTEM_PROMPT uses an unnamed numeric literal instead of a named constant"},
    {"severity": "warning", "file": "app/main.py", "line": 8,
     "message": "Unsanitized user input in SQL query"},
    {"severity": "nit", "file": "app/utils.py", "line": 3,
     "message": "Consider using a more descriptive variable name"},
    {"severity": "warning", "file": "app/semgrep_runner.py", "line": 25,
     "message": "semgrep executable path not found in PATH; falling back to venv directory"},
]

print(f"\nInput: {len(issues)} issues")
for i, iss in enumerate(issues):
    print(f"  [{i}] {iss['severity']:>8} | {iss['file']}:{iss.get('line', '?')} | {iss['message'][:70]}")

print("\nCalling filter_false_positives (real LLM)...")
t0 = time.time()
result = filter_false_positives(issues)
elapsed = time.time() - t0
print(f"Done in {elapsed:.1f}s\n")

print("Output:")
for i, iss in enumerate(result):
    fp_tag = " [FP]" if iss.get("likely_fp") else ""
    print(f"  [{i}] {iss['severity']:>8} | {iss['file']}:{iss.get('line', '?')} | fp={iss.get('likely_fp', False)} | {iss['message'][:60]}{fp_tag}")

fp_count = sum(1 for i in result if i.get("likely_fp"))
real_count = len(result) - fp_count
print(f"\nFlagged as FP: {fp_count}/{len(result)}")
print(f"Real issues:   {real_count}/{len(result)}")

# The SYSTEM_PROMPT constant issue should be flagged as FP
config_fp = any(
    i.get("likely_fp") and "config" in i.get("file", "")
    for i in result
)
print(f"\nConfig constant flagged as FP: {config_fp}")

# SQLi should NOT be flagged as FP
sqli_real = any(
    not i.get("likely_fp") and "sql" in i.get("message", "").lower()
    for i in result
)
print(f"SQLi kept as real: {sqli_real}")

all_fields = all("likely_fp" in i for i in result)
print(f"All items have likely_fp field: {all_fields}")

print("\n" + "=" * 60)
ok = config_fp and sqli_real and all_fields
print(f"Result: {'PASS' if ok else 'FAIL'}")
print("=" * 60)
sys.exit(0 if ok else 1)
