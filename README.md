# Memory-Efficient Universalization in OBSCURE (B.Tech. Project)

B.Tech. Project (CSP-400A), Department of Computer Science and Engineering, IIT Roorkee.
Kandarp Singh Mahobiya (23114045), Vankunavath Venkatesh (23114106).
Supervisor: Dr. Rajat Sadhukhan.

This README explains the project in plain language: what the original code does, what we
changed, why the output stays exactly the same, how we measure memory, how to run everything,
and what we measured. The full report is in `report/BTP_Report.pdf`.

---

## 1. Repository layout

```
compiler/                     the OBSCURE compiler (original code + our optimizations)
  src/universalization/       universalizer.py, rectangularize.py, routing.py  (O1-O4, layering)
  src/main.py                 compiler driver: new flags, deterministic -seed mode, O5
runtime/                      interpreter and software secure element (unchanged)
tests/, programs/, benchs/    test programs and benchmarks of the original OBSCURE
verification/                 testing utility and demo scripts
  compare_mem.py              original vs memory-optimized: memory, time, output, correctness
  run_original_seeded.py      runs the ORIGINAL compiler reproducibly, without editing it
  native_ref.py               builds the plain (gcc) version of a test program
  setup_demo.sh               one-time setup inside WSL/Linux
  demo.sh, run_basic_tests.sh, quick_identical.sh, profile_demo.sh, run_experiments.sh
report/                       final report (LaTeX source, PDF, figures)
OBSCURE_README.md             the original OBSCURE README
```

The first commit of this repository is the original OBSCURE code (CryptoExperts,
https://github.com/CryptoExperts/OBSCURE, commit b494c8b), so the history shows exactly what
we changed.

---

## 2. What OBSCURE does (the original implementation)

OBSCURE (Mercadier, Nguyen, Rivain, Udovenko, TCHES 2024) is a **software obfuscator**. It
takes a program written in a subset of C and produces an **encrypted bytecode**. The bytecode
is run by an **interpreter**, which sends every small block of work to a tiny trusted chip,
the **secure element (SE)**. Only the SE can decrypt the instructions and intermediate values,
so someone who holds the bytecode learns nothing about the program's secrets.

The compiler works in passes (file `compiler/src/main.py`):

| Pass | Input → output | What it does |
|---|---|---|
| Frontend | C → HLIR | parses C (pycparser), makes simple 3-address instructions (HLIs) |
| Clusterization | HLIR → MLIR / DFG | groups instructions into **multi-instructions (MLMIs)**; each one fits in the SE (at most `l_in` inputs, `l_out` outputs, `s` instructions, `r` registers). The program is now a **data-flow graph (DFG)** of MLMIs |
| **Universalization** | DFG → DFG | hides the program's data flow (details below). **This is the pass we optimized.** |
| Lowering | DFG → LLIR | schedules the MLMIs in order and allocates SE registers |
| Serialization | LLIR → bytecode | encodes and encrypts every instruction, writes the file |

The SE size is given by four numbers `(l_in, l_out, r, s)`. The paper uses four sizes:
small (8, 8, 40, 32), medium (16, 16, 80, 64), large (32, 32, 160, 128) and
xlarge (64, 64, 320, 256).

### 2.1 What universalization does

Even if every instruction is encrypted, the bytecode still shows **which MLMI reads the output
of which MLMI** (the wiring). That wiring can reveal the program. Universalization removes
this leak by forcing every program into the same public shape:

1. **Rectangularize** (`rectangularize.py`): put the MLMIs into layers (each MLMI as early as
   possible), copy values through layers they must cross, then pad every layer with dummy
   MLMIs so that **all layers have the same width** (number of MLMIs) and every MLMI has
   exactly `l_in` inputs and `l_out` outputs. The program becomes a rectangle:
   *depth × width*.
2. **Add a permutation network between every two layers** (`add_permutation` in
   `universalizer.py`, using `routing.py`). The outputs of layer *i* must reach the right
   inputs of layer *i+1*. Instead of wiring them directly, OBSCURE builds a **Beneš network**
   (plus a copy network for values used more than once). Each column of the network is made
   of small secret "shuffle" gates, and **each gate is itself an MLMI** made of `MOV`
   instructions. Because all gates are encrypted, the real wiring is hidden.

After universalization every program of the same depth and width "looks the same" from
outside, which is what gives full obfuscation.

### 2.2 Why universalization uses a lot of memory

A Beneš network on *N* wires has *2·log₂N − 1* columns of *N/2* small swap gates, and one
such network (plus a copy network) sits between every two layers. The paper gives the total
cost as about *d·n·log n* gates for depth *d* and width *n*, so the number of gate MLMIs grows
as **depth × width × log(width)**. Each gate is several Python objects
(MLMI, MLS, a list of HLIs, a new MemOperand for every output, dictionary entries in the DFG).
For larger programs the compiler needs hundreds of MB to several GB of RAM.

---

## 3. Where the memory actually goes (profiling)

Before changing anything we measured. Our earlier study (`REPORT.md`,
`results/PROFILE.md`) used Python's `tracemalloc` inside `universalize()` (flag
`-profile-mem`, which we added):

* **86–96 % of the memory created by universalization comes from `add_permutation`,
  i.e. the routing gates.** These gates *are the output* of the pass, so they cannot be
  removed without changing the obfuscated program.
* The memory is held until the end of the pass (peak and final memory differ by at most a
  few MB). The temporary structures we first planned to shrink are **not** where the peak is.
* An allocation-site breakdown (AES, small SE) showed that, next to the gates themselves, a
  big part is **bookkeeping**: the DFG's `backward_edges` dictionary, many empty successor
  sets, and the old pre-clustering program kept in `dfg.prog`.

With the new utility (section 7) we also measured the **whole compiler** over time. The
highest memory of the whole compilation is reached **at the end, during serialization**,
because the compiler still keeps the universalized DFG alive while it builds the bytecode.
That observation led to O5.

**Conclusion:** with the rule "output must stay exactly the same", the only memory we can
save is memory that is *not part of the output*: temporary structures and bookkeeping, and
data kept alive longer than needed.

---

## 4. Our optimizations

All changes are behind command-line flags and **off by default**, so the compiler behaves
exactly like the original unless a flag is given.

| Flag | Name | Output |
|---|---|---|
| `-opt-o1` | leaner rectangularization | identical |
| `-opt-o2` | lazy routing-network generation | identical |
| `-opt-o3` | in-place gate application | identical |
| `-opt-o4` | compact DFG hand-off to lowering | identical |
| `-opt-all` | O1 + O2 + O3 + O4 | identical |
| `-opt-o5` | release finished program representations (new in this phase) | identical |
| `-opt-layering` | width-balancing layer assignment (stretch goal) | **changes** the program (smaller) |
| `-seed N` | deterministic mode, used for comparing outputs | — |
| `-profile-mem` | memory per phase of `universalize()` (tracemalloc) | — |

**Our recommended configuration is `-opt-all -opt-o5` (O1–O5).**

### O1: leaner rectangularization (`rectangularize.py`, `universalizer.py`)

* **Before:** for every value copied through intermediate layers, `segregate_layers` created
  a list as long as the whole program depth: `alternative_defs[m] = [None] * len(layers)`,
  even though only a few entries are ever used.
* **After:** one dictionary keyed by `(value, layer)`: `alternative_defs[(m, layer)] = new_m`.
  Memory is proportional to the copies that really exist.
* Also: every padding instruction `MOV out, 0` used a new `ImmOperand(0)` object. Now they
  all share one. This is safe because an `ImmOperand` is never modified after creation.
* **Why the output is the same:** the lookups return exactly the same values.

### O2: lazy routing-network generation (`routing.py`)

* **Before:** for every layer the code built the whole input Beneš network, the copy network
  and the output Beneš network together (`BDBFuncMI`), then a full "canonical" copy of the
  column list, then an "optimized" copy of that.
* **After:** `iter_bdb_columns()` produces the same columns **one at a time**. Each
  sub-network is dropped as soon as its columns are used, identity columns are skipped on the
  fly (what `optimize()` did), and columns are stored as compact `array('i')`.
* **Why the output is the same:** the column sequence is identical.
  `test_iter_bdb_columns()` checks this against the original code on 400 random routing
  problems.

### O3: in-place gate application (`universalizer.py`)

* **Before:** for every secret gate, `apply_secret_perm` copied the **entire** list of wires
  and the entire checker list, even though a gate only touches `k` neighbouring wires. With
  *N* wires per layer this is about *N²/k* copying per column.
* **After:** `apply_secret_perm_inplace` reads only the gate's window `inputs[off:off+k]`
  and overwrites only that window.
* **Why the output is the same:** nodes, operands and instructions are created in the same
  order with the same values. The full routing self-check is kept.
* **Effect:** mostly **time** (universalization up to 50 % faster on wide programs).

### O4: compact hand-off to lowering (`universalizer.py`, `compact_dfg_for_lowering`)

After universalization, the next pass (lowering, `DFG.to_LLIR`) only reads `dfg.nodes`,
`dfg.forward_edges` and the program inputs/outputs. So, at the end of `universalize()`:

* `dfg.backward_edges` is released (one entry per value: never read again);
* empty successor sets are dropped; a missing key returns one shared empty `frozenset`;
* `dfg.prog` (the pre-clustering program, one wrapper MLMI per source instruction) is
  replaced by a tiny object holding only `inputs`, the one field lowering reads.

Important detail: a first version also turned the non-empty successor sets into tuples. That
**changed the bytecode**, because the scheduler does `todo.update(successors)` and Python's
set-to-set update copies the internal table order. Our identical-output check caught it and
non-empty sets are now left untouched. This shows why the byte-for-byte check matters.

### O5: release finished program representations (`main.py`, new in this phase)

The original driver `main()` keeps two big objects alive until the very end:

* `hlir_prog` (frontend output) is only read by the clusterizer, but it lives through all
  later passes;
* `dfg` (the universalized program: every routing gate, its MLS/HLI objects, edge
  dictionaries) is only read by lowering, but it lives through **serialization**, the phase
  where the whole compilation reaches its highest memory.

With `-opt-o5`, `main()` deletes `hlir_prog` right after clusterization and deletes `dfg`
right after lowering (then runs `gc.collect()`), so the serializer's memory no longer comes
on top of the universalized DFG.

* **Why the output is the same:** nothing reads these objects afterwards. Deleting a
  reference only changes *when* memory is freed, never *what* is computed. (Verified
  byte-for-byte below.)

### Stretch goal: width-balancing layering (`-opt-layering`)

`layerize` puts every MLMI in the earliest possible layer (ASAP). Crowded layers make *every*
layer as wide as the widest one, and the network size follows the width. Each MLMI can legally
sit anywhere between its earliest and latest possible layer; we place it in the least-loaded
layer of that window. A **guard** estimates both widths and switches only if the permutation
network becomes strictly smaller (next power of two of width × l). This **changes the
obfuscated program** (it is smaller, still rectangular and functionally correct), so it is
reported separately and is **not** part of the "identical output" result.

---

## 5. How the optimized compiler runs

```
C file ─► Frontend ─► Clusterizer ─► [O5: drop HLIR]
        ─► Universalization
              rectangularize        [O1: sparse copies, shared zero]
              add_permutation       [O2: columns one at a time] [O3: gates in place]
              check_dfg_integrity
              compact_dfg_for_lowering [O4]
        ─► Lowering ─► [O5: drop universalized DFG]
        ─► Serialization ─► bytecode (same bytes as the original)
```

---

## 6. How we prove the output is exactly the same

1. **Determinism.** The original compiler gives a *different* (equally valid) program on every
   run: it never seeds Python's `random`, and MLMI objects have no `__hash__`, so sets of MLMIs
   are iterated in memory-address order. To compare outputs at all, both compilers run in the
   same deterministic mode: `random.seed(1)`, `PYTHONHASHSEED=0`, and every MLMI gets a hash
   equal to its creation number. In our repo this is the `-seed` flag. For the original repo,
   `verification/run_original_seeded.py` applies the **same** switch from outside, **without
   editing any original file**. It only fixes the iteration order; it does not change what any
   pass computes.
2. **Byte comparison.** Bytes 28–91 of the bytecode are the session key sealed with libsodium's
   `crypto_box_seal`, which is randomized on every compilation **by design**. We mask these
   64 bytes and compare the rest (SHA-256). Every encrypted instruction is compared.
3. **Functional check.** Every bytecode is run in the interpreter on random inputs and compared
   with the normal gcc build of the same C program.
4. **Test suite.** The repository's own test runner (`run_tests.pl`) on its 49 basic tests.

---

## 7. How memory is measured

| What | How | Used for |
|---|---|---|
| **Peak memory of the whole compiler** | peak RSS (resident set size) reported by the Linux kernel when the process ends (`os.wait4` → `ru_maxrss`). No profiler attached, so it does not slow down or change the program | main result |
| Memory over time | `/proc/<pid>/status` → `VmRSS`, sampled every 50 ms | timeline graph, peak per phase |
| Phase boundaries | the compiler's own `-stats` lines, time-stamped when printed | time and peak per phase |
| Memory inside `universalize()` | Python `tracemalloc` (flag `-profile-mem`) | where the memory goes (section 3) |

To keep the comparison fair:
* compilations run **one at a time**, never in parallel;
* a small **warm-up** compile runs first (the first run of a repo compiles its `.py` files
  into `__pycache__`, which costs extra memory once; we saw a 20 MB difference before adding
  this);
* small programs are compiled **3 times** and the **median** is reported;
* both compilers use the same Python, the same machine and the same seed.

The project already had `-stats` (time and sizes per pass) and our earlier `-profile-mem`
(tracemalloc inside universalization), but no tool that measures the whole compiler's peak
memory and compares the original with the optimized version. `compare_mem.py` fills that gap.

---

## 8. How to run everything

All scripts run in **Linux / WSL Ubuntu** (they read `/proc`). On Windows, open PowerShell and
type `wsl -d Ubuntu` first.

**One-time setup** (builds the original and the memory-optimized compiler side by side in
`~/btp_demo`, installs pycparser locally, builds the interpreter). Requires `python3`, `gcc`,
`make`, `perl`, `git` and the libsodium library (`sudo apt install build-essential perl libsodium23`):

```bash
git clone https://github.com/kandarp2000/BTP_obfuscation_memory_optimization.git
cd BTP_obfuscation_memory_optimization/verification
bash setup_demo.sh
```

Run `setup_demo.sh` again after changing the compiler code.

**The testing utility:**

```bash
# original vs ours (default ours = -opt-all -opt-o5)
python3 compare_mem.py --program TinyJambu --se small

# compare several of our configurations, median of 3 runs
python3 compare_mem.py --program AES --se small --repeat 3

# the medium test case (about 10 minutes per compile on our laptop)
python3 compare_mem.py --program Photon --se large --tests 2

# any C test file, with extra flags given to both compilers
python3 compare_mem.py --source tests/automated/basic/add.c --flags "-width 4 -depth 25"
```

Options: `--program` or `--source` (test case), `--se small|medium|large|xlarge`,
`--ours "<flags>"` (advanced: compare other flag sets instead of the final version), `--flags "<flags for both>"`, `--repeat N` (median),
`--tests N` (random functional tests, 0 = skip), `--seed N`, `--label name`.

It prints a table (peak memory, change, time, sizes, same output?, functional tests, peak and
time per phase) and saves `summary.json`, `log_*.txt` and `timeline_*.csv` in
`verification/results/<program>_<SE>/`.

**Other scripts:**

```bash
bash demo.sh TinyJambu              # step-by-step demonstration (PAUSE=1 waits for Enter)
bash run_basic_tests.sh memoryoptimized   # 49 functional tests with the memory-optimized compiler
bash run_basic_tests.sh original    # same tests with the original compiler
bash quick_identical.sh             # same bytecode on 5 small tests (~30 s)
bash profile_demo.sh AES            # memory per phase inside universalize()
bash run_experiments.sh             # every measurement used in the report (~1 hour)
python plot_results.py              # (Windows or Linux, needs matplotlib) report figures
```

---

## 9. Results (measured on our laptop)

**Machine:** AMD Ryzen 7 5800HS, 7.5 GB RAM visible to WSL2 Ubuntu 24.04, Python 3.12.3.
**Procedure:** `verification/run_experiments.sh`. Seed 1 for both compilers; one compile at a time;
warm-up first; small programs = median of 3 runs (the 3 runs differed by at most 0.3 MB).
All raw data: `verification/results/<program>_<SE>/summary.json`.

### 9.1 Same output? (most important)

| Program | SE | O1–O4 same bytecode | O1–O5 same bytecode | Functional tests (orig / O1–O4 / O1–O5) |
|---|---|---|---|---|
| TinyJambu | small | YES | YES | 3/3, 3/3, 3/3 |
| AES | small | YES | YES | 3/3, 3/3, 3/3 |
| tracingAES | small | YES | YES | 3/3, 3/3, 3/3 |
| sum_tree | small | YES | YES | 3/3, 3/3, 3/3 |
| Ascon | small | YES | YES | 3/3, 3/3, 3/3 |
| Photon | large | YES | YES | 2/2, 2/2, 2/2 |

Repository test suite (49 basic tests): original 49/49, ours with O1–O4 49/49 (checked earlier
today), ours with O1–O5 **49/49**.

### 9.2 Peak memory of the whole compiler (MB)

| Program | SE | Original | O1–O4 | change | **O1–O5** | **change** |
|---|---|---:|---:|---:|---:|---:|
| TinyJambu | small | 113.9 | 106.7 | −6.3 % | **95.4** | **−16.2 %** |
| AES | small | 138.8 | 131.7 | −5.1 % | **115.3** | **−16.9 %** |
| tracingAES | small | 316.2 | 300.6 | −4.9 % | **260.5** | **−17.6 %** |
| sum_tree | small | 245.0 | 234.9 | −4.1 % | **202.5** | **−17.3 %** |
| Ascon | small | 962.5 | 916.0 | −4.8 % | **788.3** | **−18.1 %** |
| **Photon (medium test)** | large | 710.5 | 663.5 | −6.6 % | **599.2** | **−15.7 %** |

**Conclusion: the optimization works.** With O1–O5 the peak memory is 15.7–18.1 % lower on every
program (111 MB less on the medium test case Photon), with byte-identical output. O1–O4 alone
give 4.1–6.6 % (consistent with our earlier 36-configuration study: median 5.9 %); O5 more than
doubles the saving.

### 9.3 Where the memory is saved (AES, small SE, peak RSS during each phase, MB)

| Phase | Original | O1–O4 | O1–O5 |
|---|---:|---:|---:|
| frontend | 39.7 | 40.3 | 41.1 |
| clusterization | 41.0 | 41.8 | 41.8 |
| universalize: rectangularize | 41.8 | 41.8 | 41.9 |
| universalize: permutation networks | 78.2 | 78.6 | 78.7 |
| lowering | 113.9 | 106.9 | 106.8 |
| serialization | **138.9** | **131.6** | **115.4** |

Up to the end of universalization all versions are equal (the gates are the output). O4 saves in
lowering, O5 saves in serialization, which is where the original reaches its peak.

### 9.4 Time (seconds; permutation-network step / whole compile)

| Program | Original | O1–O4 | O1–O5 |
|---|---|---|---|
| TinyJambu | 1.70 / 5.6 | 1.74 / 5.7 | 1.70 / 5.9 |
| AES | 2.50 / 11.7 | 2.49 / 11.9 | 2.57 / 12.1 |
| tracingAES | 6.51 / 28.0 | 6.21 / 27.4 | 6.30 / 28.2 |
| sum_tree (wide, width 186) | **11.39** / 17.8 | **5.83** / 13.6 | 6.77 / 14.7 |
| Ascon | 24.67 / 71.7 | 22.82 / 68.8 | 24.01 / 71.7 |
| Photon | 50.09 / 561.7 | 49.78 / 564.4 | 52.07 / 515.0 | |

No meaningful slowdown; O3 halves the permutation-network time on the wide sum_tree.

### 9.5 Stretch goal: layering (changes the output)

Ascon, small SE, `-opt-all -opt-o5 -opt-layering`: peak memory **962.5 → 157.3 MB (−83.7 %)**,
120,188 → 20,033 multi-instructions, bytecode 17.3 MB → 2.9 MB, compile time 71.7 s → 28.0 s.
The bytecode is different (as expected) and still gives correct results (3/3 functional tests).

### 9.6 Figures

`report/figures/fig_peak_memory_percent.pdf`, `fig_timeline_Photon_large.pdf`,
`fig_phase_peaks_Photon_large.pdf` (made by `verification/plot_results.py` from the results).

---

## 10. Limitations

* The identical-output gain is limited because the routing gates are the output.
* All measurements in section 9 are from one laptop (WSL2, Python 3.12). Our earlier study used a
  different machine and Python 3.13 and found consistent relative results for O1–O4.
* The heaviest configurations (3–5 GB: Photon small/medium, sum_naive and findmax_naive small)
  were not rerun in this phase; they are in our earlier study (O1–O4 only). mnist was
  excluded because its frontend alone runs more than 30 minutes.
* O2 makes universalization slower on large/extra-large SEs (earlier study: 9–24 %).
* Layering is a heuristic and changes the output; it is reported separately.
* The functional check runs a few random inputs per program, not a proof of equivalence; the
  byte-identical comparison is the stronger evidence for O1–O5.

---
