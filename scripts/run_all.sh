#!/bin/sh
# Reproduce every result of the memory-optimization project, from the repository root.
#
# Baseline numbers must come from the ORIGINAL code. Check out the baseline commit
# in a second directory and point BASE at it (its scripts/ must be this version):
#     git worktree add ../obscure-baseline <commit "Step 0/1">
#     cp scripts/*.py scripts/*.pl ../obscure-baseline/scripts/
#     BASE=../obscure-baseline sh scripts/run_all.sh
# Without BASE, the baseline runs use this checkout with no -opt flag, which we
# verified gives byte-identical output to the original code.
#
# Takes about 4 hours on a 2-core / 7 GB machine. The three 4 GB programs run one at
# a time. Every step resumes where it stopped (--resume). mnist is excluded: its
# frontend alone takes more than 30 minutes.
set -e
O=$(pwd)
B=${BASE:-$O}
[ -n "$SKIP_ENV" ] || . env_shims/setup_env.sh
export PYTHONHASHSEED=0
LIGHT=AES,Ascon,TinyJambu,tracingAES,sum_tree,findmax_tree
HEAVY=sum_naive,findmax_naive,Photon
LIGHTP="tests/automated/programs/AES.c tests/automated/programs/Ascon.c tests/automated/programs/TinyJambu.c tests/automated/programs/tracingAES.c tests/automated/programs/sum_tree.c tests/automated/programs/findmax_tree.c"
rb() { L=$1; shift; (cd "$B" && python3 scripts/run_matrix.py "$L" --resume "$@"); }
ro() { L=$1; shift; (cd "$O" && python3 scripts/run_matrix.py "$L" --resume "$@"); }

# 1. Baseline per-phase memory profile (tracemalloc roughly doubles memory, so the
#    4 GB programs are only profiled where they fit)
rb baseline_profile --jobs 2 --programs $LIGHT -- -profile-mem
rb baseline_profile --jobs 1 --programs sum_naive,findmax_naive --se medium,large,xlarge -- -profile-mem

# 2. Peak RSS (no profiler) + output digests
for P in "$LIGHT 2" "$HEAVY 1"; do set -- $P
  rb baseline     --jobs $2 --programs $1
  ro opt_all      --jobs $2 --programs $1 -- -opt-all
  ro opt_layering --jobs $2 --programs $1 -- -opt-all -opt-layering
done
ro opt_o1     --jobs 2 --programs $LIGHT --se small -- -opt-o1
ro opt_o1o2   --jobs 2 --programs $LIGHT --se small -- -opt-o1 -opt-o2
ro opt_o1o2o3 --jobs 2 --programs $LIGHT --se small -- -opt-o1 -opt-o2 -opt-o3
ro opt_o1o2o3 --jobs 1 --programs $HEAVY --se small -- -opt-o1 -opt-o2 -opt-o3
ro opt_all_prof --jobs 2 --programs $LIGHT -- -opt-all -profile-mem
[ "$B" = "$O" ] || cp "$B"/results/runs/baseline*.jsonl results/runs/
for c in opt_o1 opt_o1o2 opt_o1o2o3 opt_all opt_all_prof; do
  echo "== identical output: $c"
  python3 scripts/check_identical.py results/runs/baseline.jsonl results/runs/$c.jsonl || true
done

# 3. Compile-time medians (3 runs, one job at a time)
rb time_baseline --jobs 1 --repeat 3 --se small --programs $LIGHT
ro time_opt_all  --jobs 1 --repeat 3 --se small --programs $LIGHT -- -opt-all
[ "$B" = "$O" ] || cp "$B"/results/runs/time_baseline.jsonl results/runs/

# 4. Scaling sweep
python3 scripts/scaling_sweep.py TinyJambu small --jobs 2

# 5. Correctness: functional tests (the interpreter in runtime/ is built for the small SE)
OBSCURE_FLAGS="-opt-all" OBSCURE_REPEAT=3 perl scripts/run_tests_flags.pl \
    tests/automated/basic/*.c tests/automated/medium/*.c $LIGHTP
OBSCURE_FLAGS="-opt-all -opt-layering" OBSCURE_REPEAT=3 perl scripts/run_tests_flags.pl \
    tests/automated/basic/*.c tests/automated/medium/*.c $LIGHTP
# other SE sizes: build runtime/ with SE_MEDIUM/SE_LARGE/SE_EXTRALARGE=1 in SEconfig.h
# into another directory and pass OBSCURE_INTERP_DIR=<dir> OBSCURE_SE="l,l,r,s"
for c in "Photon medium" "Photon xlarge" "Ascon small" "Ascon medium" "Ascon large" \
         "tracingAES small" "tracingAES large" "sum_tree small" "sum_tree large"; do
  set -- $c
  python3 scripts/check_structure.py tests/automated/programs/$1.c $2 -opt-all -opt-layering
done
python3 -c "import sys; sys.path.insert(0,'compiler/src/universalization'); import routing; print(routing.test_iter_bdb_columns(400))"

# 6. Tables and figures
python3 scripts/make_profile_report.py
python3 scripts/make_eval_report.py
