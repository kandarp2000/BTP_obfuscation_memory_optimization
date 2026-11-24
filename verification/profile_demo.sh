#!/bin/bash
# Per-phase memory inside universalize() (tracemalloc), our repo:
#   optimisations OFF (= original behaviour)  vs  -opt-all
# Shows WHERE the memory is (add_permutation = routing networks) and what O4 releases.
# Usage: bash profile_demo.sh [PROGRAM] (default AES, small SE)
PROG=${1:-AES}
W=$HOME/btp_demo; cd "$W/memopt"
export PYTHONPATH=$W/shims:$W/pylib PYTHONHASHSEED=0 PYTHONWARNINGS=ignore
SE="-r 40 -lin 8 -lout 8 -s 32"; SRC=tests/automated/programs/$PROG.c
echo -e "\033[1;36m== $PROG, optimisations OFF (original code paths) ==\033[0m"
python3 compiler/compiler.py $SE -seed 1 -profile-mem $SRC -o /tmp/p_base.bin | grep '^\[mem\]'
echo -e "\033[1;36m== $PROG, -opt-all (O1+O2+O3+O4) ==\033[0m"
python3 compiler/compiler.py $SE -seed 1 -opt-all -profile-mem $SRC -o /tmp/p_opt.bin | grep '^\[mem\]'
echo
echo "current = memory still held after the phase; peak = max during the phase."
echo "Most memory is created by add_permutation (Benes routing gates = the output itself)."
echo "compact_dfg_for_lowering (O4) is where held memory drops."
