"""Break down the memory allocated inside universalize() by source line and by
object type, at the end of the pass and at the peak inside add_permutation.

Usage: python3 scripts/alloc_breakdown.py <program.c> <se> [extra compiler flags]
"""
import os, sys, tracemalloc, collections, gc
sys.path.insert(0, os.path.dirname(__file__))
from obscure_tools import ROOT, SE
sys.path.insert(0, os.path.join(ROOT, "compiler", "src"))
src, se, *extra = sys.argv[1:]
l_in, l_out, r, s = SE[se]
import universalization.universalizer as U
import main as M

orig = U.universalize
def wrapped(dfg, config):
    gc.collect()
    tracemalloc.start(1)
    before = set(map(id, gc.get_objects()))
    out = orig(dfg, config)
    snap = tracemalloc.take_snapshot()
    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"== allocated in universalize: current {cur/2**20:.2f} MB, peak {peak/2**20:.2f} MB")
    print("== top allocation sites still alive at end:")
    for st in snap.statistics("lineno")[:15]:
        fr = st.traceback[0]
        print(f"  {st.size/2**20:8.2f} MB  {st.count:9d} blocks  {os.path.relpath(fr.filename, ROOT)}:{fr.lineno}")
    cnt = collections.Counter(type(o).__name__ for o in gc.get_objects() if id(o) not in before)
    print("== new GC-tracked objects by type:", cnt.most_common(12))
    return out
U.universalize = wrapped
sys.argv = ["compiler.py", "-r", str(r), "-lin", str(l_in), "-lout", str(l_out), "-s", str(s),
            "-seed", "1", "-o", "/dev/null", *extra, os.path.join(ROOT, src)]
M.main()
