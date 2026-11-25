# Memory-Efficient Universalization in OBSCURE: project code

This repository is the original OBSCURE code (TCHES 2024,
github.com/CryptoExperts/OBSCURE) with the memory optimizations from our project
proposal. All compiler changes are inside the universalization pass:

| File | Change |
| --- | --- |
| `compiler/src/universalization/universalizer.py` | per-phase memory probes (`-profile-mem`), O1 shared padding constant, O3 in-place gate application, O4 compact hand-off to lowering |
| `compiler/src/universalization/rectangularize.py` | O1 sparse alternative definitions, stretch goal (width-balancing layering) |
| `compiler/src/universalization/routing.py` | O2 lazy, compact generation of the Beneš/copy network columns (+ equivalence test) |
| `compiler/src/main.py` | new command-line flags (plus a reproducibility switch behind `-seed`, see below) and O5: release of the HLIR after clusterization and of the universalized DFG after lowering |

The frontend, clusterizer, lowering, serializer, interpreter, secure element and
bytecode format are unchanged.

## New compiler flags

| Flag | Effect | Output |
| --- | --- | --- |
| `-seed N` | seeds the RNG and makes compilation reproducible (see below) | same as original for that seed |
| `-profile-mem` | prints memory (tracemalloc) and time for each phase of `universalize()` | unchanged |
| `-opt-o1` | O1: leaner rectangularization | byte-identical |
| `-opt-o2` | O2: incremental, compact routing generation | byte-identical |
| `-opt-o3` | O3: in-place application of routing gates | byte-identical |
| `-opt-o4` | O4: compact DFG bookkeeping handed to lowering | byte-identical |
| `-opt-all` | O1 + O2 + O3 + O4 | byte-identical |
| `-opt-o5` | O5: free the HLIR after clusterization and the universalized DFG after lowering (the whole compiler peaks during serialization). Recommended: `-opt-all -opt-o5`. Results: `../../verification/` and `../../README.md` | byte-identical |
| `-debug-routing` | extra independent check of every routing network | unchanged |
| `-opt-layering` | stretch goal: width-balancing layer assignment | **changes the program** (smaller), kept only when predicted narrower |

Example:

    python3 compiler/compiler.py -r 40 -lin 8 -lout 8 -s 32 -opt-all -stats \
        tests/automated/programs/TinyJambu.c -o tinyjambu.bin

### Why `-seed` also fixes hashing

The original compiler isn't deterministic even with a fixed random seed.
Multi-instructions (`MLMI`) have no `__hash__`, so the sets that hold them iterate
in memory-address order, which changes from run to run. To compare outputs byte for
byte, `-seed N` also gives each `MLMI` a hash equal to its creation index (and the
scripts set `PYTHONHASHSEED=0`). This only fixes the iteration order. Equality is
still identity, and every pass computes the same thing. The switch is used for both
the baseline and the optimized runs.

The 64-byte sealed-key header (`crypto_box_seal`) is randomized by libsodium on
every compilation by design. Output comparisons therefore mask bytes 28–91 of the
bytecode. Everything else, including every encrypted instruction, is compared.

## Environment

The official setup needs `pycparser`, `pysodium`, `graphviz`, `swig` and
`libsodium-dev`. Our test machine had none of these except the libsodium shared
library, and package installation wasn't possible. `env_shims/` provides minimal
equivalents and doesn't modify the compiler:

* `graphviz.py`: a no-op (graphviz is only used to draw debug plots)
* `pysodium.py`: `crypto_box_seal` through ctypes on the system libsodium
* `schwaemm/`: a ctypes binding to the Schwaemm C code shipped in `compiler/schwaemm`
* `include/sodium.h`: the two libsodium prototypes the runtime needs

To set up, run this from the repository root (`pycparser` must be installed):

    . env_shims/setup_env.sh

On a normal machine, follow `INSTALL.md` instead and skip the shims.

Note: `compiler/compiler.py` is a symbolic link to `compiler/src/main.py` (as in the
original repository). If your unzip tool doesn't keep symbolic links (for example on
Windows), run `python3 compiler/src/main.py ...` instead.

## Reproducing the results

    sh scripts/run_all.sh          # everything (several hours on 2 cores)

Individual steps:

| Script | What it does |
| --- | --- |
| `scripts/run_matrix.py <label> [-- flags]` | compiles every program for every SE size; writes `results/runs/<label>.jsonl` (peak RSS, times, sizes, digest, per-phase memory) |
| `scripts/make_profile_report.py` | profiling CSV, chart and `results/PROFILE.md` |
| `scripts/check_identical.py ref.jsonl new.jsonl` | byte-identical output check |
| `scripts/check_structure.py prog.c se [flags]` | rectangular-circuit invariants (equal width, l_in/l_out, outputs in last layer) |
| `scripts/scaling_sweep.py prog se` | memory against forced depth and width |
| `scripts/run_tests_flags.pl` | the repository's functional tests (`run_tests.pl`) with extra flags and SE size |
| `scripts/alloc_breakdown.py prog.c se` | allocation sites still alive after `universalize()` |
| `scripts/make_eval_report.py` | `results/results.csv`, `results/ablation_table.md`, figures |

`compiler/src/universalization/routing.py` also contains `test_iter_bdb_columns()`,
which checks O2 against the original routing code on random inputs.
