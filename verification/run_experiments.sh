#!/bin/bash
# All measurements used in the README and the report (inside WSL). One compile at a time.
# Total time on our laptop: about 1 hour. Every step writes results/<label>/summary.json.
cd "$(dirname "$0")"
step() { echo; echo "######## $(date +%H:%M:%S) $*"; }
A="--ours -opt-all --ours"
B="-opt-all -opt-o5"

step "1. small programs, small SE, median of 3"
for P in TinyJambu AES tracingAES sum_tree; do
  python3 compare_mem.py --program $P --se small --repeat 3 --tests 3 $A "$B"
done

step "2. Ascon small SE (+ layering stretch goal, which changes the program)"
python3 compare_mem.py --program Ascon --se small --tests 3 $A "$B" --ours "-opt-all -opt-o5 -opt-layering"

step "3. MEDIUM test case: Photon, large SE"
python3 compare_mem.py --program Photon --se large --tests 2 $A "$B"

step "4. functional test suite (49 basic tests) with O1..O5"
FLAGS="-opt-all -opt-o5" bash run_basic_tests.sh ours

step DONE
