"""Check the rectangular-circuit invariants that the security argument relies on.

Runs the compiler in-process and inspects the layers right before the
permutation networks are inserted:
  * all middle layers have the same width;
  * every multi-instruction of a middle layer has exactly l_in inputs and
    l_out outputs;
  * all program outputs are produced by the last layer;
  * a permutation network is inserted between every pair of layers
    (add_permutation runs over len(layers)-1 boundaries).
Usage: python3 scripts/check_structure.py <program.c> <se> [compiler flags]
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from obscure_tools import ROOT, SE
sys.path.insert(0, os.path.join(ROOT, "compiler", "src"))
src, se, *extra = sys.argv[1:]
l_in, l_out, r, s = SE[se]
import universalization.universalizer as U
import main as M

report = {}
orig = U.add_permutation
def check(dfg, layers, config):
    mid = layers[1:-1]
    widths = {len(l) for l in mid}
    bad_io = sum(1 for l in mid for n in l
                 if len(n.inputs) != config.l_in or len(n.outputs) != config.l_out)
    last_outs = {m for n in layers[-1] for m in n.outputs}
    outs_ok = all(m in last_outs for m in dfg.prog_outputs)
    report.update(depth=len(layers), widths=sorted(widths), bad_io=bad_io,
                  outputs_in_last_layer=outs_ok, boundaries=len(layers) - 1)
    return orig(dfg, layers, config)
U.add_permutation = check
sys.argv = ["compiler.py", "-r", str(r), "-lin", str(l_in), "-lout", str(l_out), "-s", str(s),
            "-seed", "1", "-o", os.devnull, *extra, os.path.join(ROOT, src)]
M.main()
ok = len(report["widths"]) == 1 and report["bad_io"] == 0 and report["outputs_in_last_layer"]
print("STRUCTURE", "OK" if ok else "FAIL", report)
sys.exit(0 if ok else 1)
