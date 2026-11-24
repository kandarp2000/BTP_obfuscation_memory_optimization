"""Run the ORIGINAL OBSCURE compiler in deterministic mode, WITHOUT modifying it.

Usage: python3 run_original_seeded.py <original_repo> <normal compiler args...>

The original compiler is not reproducible even for the same input: MLMI objects
have no __hash__, so sets of MLMIs iterate in memory-address order, and the
random module is never seeded. To compare it fairly with our version, we apply
exactly the same switch as our `-seed N` flag (memopt/compiler/src/main.py):
  * random.seed(N)
  * every MLMI gets a hash equal to its creation index
  * PYTHONHASHSEED=0 (set by the caller)
This only fixes iteration order; it does not change what any pass computes.
"""
import os
import random
import runpy
import sys

repo = os.path.abspath(sys.argv[1])
src = os.path.join(repo, "compiler", "src")
sys.path.insert(0, src)

import IR  # noqa: E402  (the original repo's IR module)

_orig_init = IR.MLMI.__init__
_counter = [0]


def _det_init(self, *args, **kwargs):
    _counter[0] += 1
    self._det_hash = _counter[0]
    _orig_init(self, *args, **kwargs)


IR.MLMI.__init__ = _det_init
IR.MLMI.__hash__ = lambda self: self._det_hash
random.seed(int(os.environ.get("DEMO_SEED", "1")))

main_py = os.path.join(src, "main.py")
sys.argv = [main_py] + sys.argv[2:]
runpy.run_path(main_py, run_name="__main__")
