"""Compare the masked bytecode digests of a run against the baseline reference.

Usage: python3 scripts/check_identical.py <reference.jsonl> <candidate.jsonl>
"""
import json, sys
ref = {(r["program"], r["se"]): r for r in map(json.loads, open(sys.argv[1])) if r["ok"]}
n = same = 0
for r in map(json.loads, open(sys.argv[2])):
    key = (r["program"], r["se"])
    if key not in ref or not r["ok"]:
        print("SKIP", key, "(missing or failed)"); continue
    n += 1
    if r["digest"] == ref[key]["digest"]:
        same += 1
    else:
        print("DIFFERENT", key)
print(f"identical: {same}/{n}")
sys.exit(0 if same == n else 1)
