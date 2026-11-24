#!/bin/bash
# Same-output check on small tests: ORIGINAL compiler vs MEMORY-OPTIMIZED compiler (-opt-all -opt-o5).
# Both run deterministically (seed 1). Compares the bytecode with the 64 randomly
# sealed key bytes (offset 28..91) masked, and prints peak memory of each compile.
# Usage: bash quick_identical.sh [test names...]   (default: 5 basic tests)
DEMO=$(cd "$(dirname "$0")" && pwd); W=$HOME/btp_demo
export PYTHONPATH=$W/shims:$W/pylib PYTHONHASHSEED=0 PYTHONWARNINGS=ignore
SE="-r 40 -lin 8 -lout 8 -s 32 -width 4 -depth 25"
TESTS=${*:-"basic/add basic/binops basic/funs_complex basic/array_for basic/ptr_alias_middle_arith"}
mkdir -p "$W/out/quick"; O=$W/out/quick
printf "%-30s %10s %10s   %s\n" TEST "orig(MB)" "memopt(MB)" "same obfuscated program?"
for T in $TESTS; do
  S=tests/automated/$T.c; N=${T//\//_}
  (cd "$W/original" && /usr/bin/time -f %M -o $O/$N.o.t python3 "$DEMO/run_original_seeded.py" "$W/original" $SE $S -o $O/$N.orig.bin >/dev/null 2>&1)
  (cd "$W/memopt"   && /usr/bin/time -f %M -o $O/$N.p.t python3 compiler/compiler.py $SE -seed 1 -opt-all -opt-o5 $S -o $O/$N.memoryoptimized.bin >/dev/null 2>&1)
  R=$(python3 -c "
import hashlib,sys
def m(p):
    x=bytearray(open(p,'rb').read()); x[28:92]=bytes(64); return hashlib.sha256(x).hexdigest()
print('YES  sha256 '+m(sys.argv[1])[:16] if m(sys.argv[1])==m(sys.argv[2]) else 'NO')" $O/$N.orig.bin $O/$N.memoryoptimized.bin)
  printf "%-30s %10.1f %10.1f   %s\n" "$T" "$(echo "$(cat $O/$N.o.t)/1024" | bc -l)" "$(echo "$(cat $O/$N.p.t)/1024" | bc -l)" "$R"
done
