#!/bin/bash
# =====================================================================
#  BTP viva demo: ORIGINAL OBSCURE  vs  MEMORY-OPTIMIZED OBSCURE
#
#  Usage (inside WSL):   bash demo.sh [PROGRAM] [SE] [extra flags for the memory-optimized compiler]
#     PROGRAM : AES | TinyJambu | Ascon | tracingAES | sum_tree | findmax_tree ...
#               (default AES)
#     SE      : small | medium | large | xlarge          (default small)
#     extra   : e.g.  -opt-layering   (stretch goal, changes the program)
#  The MEMORY-OPTIMIZED compiler runs with all optimizations on (-opt-all -opt-o5).
#
#  Examples:
#     bash demo.sh                      # AES, small SE, O1..O5
#     bash demo.sh TinyJambu            # fastest one
#     bash demo.sh Ascon small -opt-layering
#
#  Env:  PAUSE=1   wait for Enter between steps (nice for a live viva)
#        RUNS=3    how many random test inputs to check
# =====================================================================
set -e
PROG=${1:-AES}; SE=${2:-small}; shift $(( $# > 2 ? 2 : $# )); EXTRA="$*"
RUNS=${RUNS:-3}
DEMO=$(cd "$(dirname "$0")" && pwd)
W=$HOME/btp_demo
ORIG=$W/original; OURS=$W/memopt; OUT=$W/out/$PROG-$SE; mkdir -p "$OUT"
export PYTHONPATH=$W/shims:$W/pylib PYTHONHASHSEED=0 PYTHONWARNINGS=ignore

case $SE in
  small)  SEARGS="-r 40  -lin 8  -lout 8  -s 32";;
  medium) SEARGS="-r 80  -lin 16 -lout 16 -s 64";;
  large)  SEARGS="-r 160 -lin 32 -lout 32 -s 128";;
  xlarge) SEARGS="-r 320 -lin 64 -lout 64 -s 256";;
  *) echo "unknown SE $SE"; exit 1;;
esac
SRC=tests/automated/programs/$PROG.c
OURFLAGS="-seed 1 -opt-all -opt-o5 $EXTRA"

B='\033[1m'; G='\033[1;32m'; R='\033[1;31m'; C='\033[1;36m'; Y='\033[1;33m'; N='\033[0m'
step() { echo; echo -e "${C}════════════════════════════════════════════════════════════════${N}"; echo -e "${C}$*${N}"; echo -e "${C}════════════════════════════════════════════════════════════════${N}"; }
pause() { [ -n "$PAUSE" ] && { echo -e "${Y}[press Enter]${N}"; read -r _; } || true; }
stat() { grep -E "$1" "$2" | head -1 | grep -oE '[0-9]+(\.[0-9]+)?' | head -1; }

echo -e "${B}Program:${N} $PROG    ${B}Secure element:${N} $SE ($SEARGS)    ${B}Our flags:${N} $OURFLAGS"

# ---------------------------------------------------------------- 0
step "STEP 0 · What we changed (original repo vs our repo, compiler only)"
( cd "$W" && diff -rq --no-dereference --exclude=__pycache__ original/compiler memopt/compiler | sed 's|^|   |' ) || true
echo -e "   → only the ${B}universalization pass${N} (+ CLI flags in main.py). Frontend, clusterizer,"
echo    "     lowering, serializer, interpreter and bytecode format are untouched."
pause

# ---------------------------------------------------------------- 1
step "STEP 1 · Compile $PROG with the ORIGINAL compiler"
echo "   cmd: python3 run_original_seeded.py original $SEARGS -stats $SRC -o orig.bin"
( cd "$ORIG" && /usr/bin/time -f "%M %e" -o "$OUT/orig.time" \
    python3 "$DEMO/run_original_seeded.py" "$ORIG" $SEARGS -stats "$SRC" -o "$OUT/orig.bin" ) \
    > "$OUT/orig.log" 2>&1 || { cat "$OUT/orig.log"; exit 1; }
sed 's|^|   |' "$OUT/orig.log"
read O_RSS O_T < "$OUT/orig.time"
echo -e "   ${B}peak memory (RSS): $((O_RSS/1024)) MB    wall time: ${O_T}s${N}"
pause

# ---------------------------------------------------------------- 2
step "STEP 2 · Compile $PROG with the MEMORY-OPTIMIZED compiler"
echo "   cmd: python3 compiler/compiler.py $SEARGS -stats $OURFLAGS $SRC -o memoryoptimized.bin"
( cd "$OURS" && /usr/bin/time -f "%M %e" -o "$OUT/memoryoptimized.time" \
    python3 compiler/compiler.py $SEARGS -stats $OURFLAGS "$SRC" -o "$OUT/memoryoptimized.bin" ) \
    > "$OUT/memoryoptimized.log" 2>&1 || { cat "$OUT/memoryoptimized.log"; exit 1; }
sed 's|^|   |' "$OUT/memoryoptimized.log"
read P_RSS P_T < "$OUT/memoryoptimized.time"
echo -e "   ${B}peak memory (RSS): $((P_RSS/1024)) MB    wall time: ${P_T}s${N}"
pause

# ---------------------------------------------------------------- 3
step "STEP 3 · Is the obfuscated bytecode the same?"
python3 - "$OUT/orig.bin" "$OUT/memoryoptimized.bin" <<'PY'
import hashlib, sys
a, b = (open(p, "rb").read() for p in sys.argv[1:3])
print(f"   size  original         : {len(a):>10,} bytes")
print(f"   size  memory-optimized : {len(b):>10,} bytes")
diff = [i for i in range(min(len(a), len(b))) if a[i] != b[i]]
if diff:
    print(f"   differing bytes: {len(diff)}  (offsets {min(diff)}..{max(diff)})")
else:
    print("   differing bytes: 0")
print("   (bytes 28..91 = libsodium crypto_box_seal of the key: randomised on EVERY compile by design)")
def masked(x):
    x = bytearray(x); x[28:92] = bytes(64); return hashlib.sha256(x).hexdigest()
ma, mb = masked(a), masked(b)
print(f"   SHA-256 (key header masked) original        : {ma}")
print(f"   SHA-256 (key header masked) memory-optimized: {mb}")
same = len(a) == len(b) and all(28 <= i < 92 for i in diff)
print("   \033[1;32m=> BYTE-IDENTICAL obfuscated program (all encrypted instructions equal)\033[0m" if same
      else "   \033[1;33m=> program differs (expected only with -opt-layering, which builds a smaller circuit)\033[0m")
PY
pause

# ---------------------------------------------------------------- 4
step "STEP 4 · Run them: plain C  vs  original.bin  vs  memoryoptimized.bin (interpreter = secure element)"
if [ "$SE" != small ]; then
  echo "   (interpreter in runtime/ is built for the small SE only: skipping the run for SE=$SE)"
else
  read NIN NOUT < <(cd "$ORIG" && python3 "$DEMO/native_ref.py" "$SRC" "$OUT/native")
  ok=1
  for k in $(seq 1 "$RUNS"); do
    IN=$(python3 -c "import random;print(' '.join(str(random.getrandbits(32)) for _ in range($NIN)))")
    CSV=${IN// /,}
    o_nat=$("$OUT/native" $IN | tr '\n' ' ')
    o_org=$("$ORIG/runtime/interpreter" "$OUT/orig.bin" --inputs "$CSV" --out_count "$NOUT" | tr '\n' ' ')
    o_our=$("$OURS/runtime/interpreter" "$OUT/memoryoptimized.bin" --inputs "$CSV" --out_count "$NOUT" | tr '\n' ' ')
    echo -e "   ${B}test $k${N}  inputs: $(echo "$IN" | cut -d' ' -f1-4) ... ($NIN words)"
    echo "     plain C             : $o_nat"
    echo "     original.bin        : $o_org"
    echo "     memoryoptimized.bin : $o_our"
    if [ "$o_nat" = "$o_org" ] && [ "$o_org" = "$o_our" ]; then echo -e "     ${G}MATCH${N}"; else echo -e "     ${R}MISMATCH${N}"; ok=0; fi
  done
  [ $ok = 1 ] && echo -e "   ${G}=> all $RUNS random tests: original and memory-optimized give the same (correct) output${N}"
fi
pause

# ---------------------------------------------------------------- 5
step "STEP 5 · Result: memory"
U_O=$(stat '^Universalization' "$OUT/orig.log"); U_P=$(stat '^Universalization' "$OUT/memoryoptimized.log")
M_O=$(grep -A1 '^Universalization' "$OUT/orig.log" | grep -oE '[0-9]+ MLMIs'); M_P=$(grep -A1 '^Universalization' "$OUT/memoryoptimized.log" | grep -oE '[0-9]+ MLMIs')
python3 - "$O_RSS" "$P_RSS" "$O_T" "$P_T" "$U_O" "$U_P" "$M_O" "$M_P" <<'PY'
import sys
o, p, ot, pt, uo, up = map(float, sys.argv[1:7]); mo, mp = sys.argv[7], sys.argv[8]
row = lambda n, a, b, u: print(f"   {n:<28}{a:>12}{b:>18}{u:>10}")
print(f"   {'':<28}{'ORIGINAL':>12}{'MEMORY-OPTIMIZED':>18}{'change':>10}")
row("peak memory (RSS, MB)", f"{o/1024:.1f}", f"{p/1024:.1f}", f"{(p-o)/o*100:+.1f}%")
row("memory saved (MB)", "", f"{(o-p)/1024:.1f}", "")
row("universalization time (s)", f"{uo:.2f}", f"{up:.2f}", f"{(up-uo)/uo*100:+.0f}%")
row("total wall time (s)", f"{ot:.2f}", f"{pt:.2f}", f"{(pt-ot)/ot*100:+.0f}%")
row("final circuit size", mo, mp, "")
PY
echo
echo "   (peak RSS measured by /usr/bin/time, no profiler attached; single run, so small"
echo "    timing differences are noise. See results/ in our repo for the 36-config study.)"
