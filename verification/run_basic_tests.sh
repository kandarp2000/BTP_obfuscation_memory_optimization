#!/bin/bash
# Quick functional tests (basic suite, 49 small C programs) with the repo's own runner.
#   bash run_basic_tests.sh original          -> ORIGINAL OBSCURE-main, unmodified run_tests.pl
#   bash run_basic_tests.sh memoryoptimized   -> MEMORY-OPTIMIZED compiler (-opt-all -opt-o5)
#   bash run_basic_tests.sh                   -> both
# Each test: compile C -> obfuscated bytecode, run it in the interpreter on 5 random
# inputs, compare with the plain gcc build. Small SE (8,8,40,32).
# FLAGS="..." changes the flags of the memory-optimized compiler.
W=$HOME/btp_demo
export PYTHONPATH=$W/shims:$W/pylib PYTHONHASHSEED=0 PYTHONWARNINGS=ignore
TESTS="tests/automated/basic/*.c"
WHICH=${1:-both}
[ "$WHICH" = ours ] && WHICH=memoryoptimized   # old name still accepted

if [ "$WHICH" != memoryoptimized ]; then
  echo "############ ORIGINAL (OBSCURE-main) ############"
  cd "$W/original" && perl run_tests.pl $TESTS
fi
if [ "$WHICH" != original ]; then
  echo "############ MEMORY-OPTIMIZED (OBSCURE-memopt, ${FLAGS:--opt-all -opt-o5}) ############"
  cd "$W/memopt" && OBSCURE_FLAGS="${FLAGS:--opt-all -opt-o5}" perl scripts/run_tests_flags.pl $TESTS
fi
