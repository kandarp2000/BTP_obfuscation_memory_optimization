from pathlib import Path
import sys
import argparse
import time

import IR
import frontend.frontend as frontend
import clusterization.clusterizer as clusterizer
import universalization.universalizer as universalizer
import lowering.lowering as lowering
import code_gen.serializer as serializer

def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--outfile", dest="outfile",
                        help="name of the output file", required=True,
                        type=argparse.FileType('wb'))
    parser.add_argument("-v", "--verbose", dest="verbose",
                        type=int, help="set verbosity level. If >= 5, prints all major representations of the program (AST, HLIR, LLIR). If >= 10, prints minor representations (before SSA, before copy propagation, etc).",
                        default=0)
    parser.add_argument("inputfile", type=argparse.FileType('r'),
                        help="name of the input file");
    parser.add_argument("-r", dest="r",
                        help="number of internal registers in the secure element",
                        required=True, type=int)
    parser.add_argument("-lin", dest="l_in",
                        help="number of inputs of the secure element", required=True, type=int)
    parser.add_argument("-lout", dest="l_out",
                        help="number of outputs of the secure element", required=True, type=int)
    parser.add_argument("-s", dest="s",
                        help="number of maximal instructions in the secure element",
                        required=True, type=int)
    parser.add_argument("-w", dest="word_size", default=32, type=int,
                        help="word size")
    parser.add_argument("-version", dest="version", default=0, type=int,
                        help="version of the compiler")
    parser.add_argument("-stats", dest="stats", default=False,
                        help="print helpful statistics on the compilation",
                        action='store_true')
    parser.add_argument("-width", dest="width", default=0, type=int,
                        help="minimal width of the program")
    parser.add_argument("-depth", dest="depth", default=0, type=int,
                        help="minimal depth of the program")
    parser.add_argument("-simple-clusterizer", dest="simple_clusterizer", action="store_true",
                        help="faster compilation, but more multi-instructions")
    fast_group = parser.add_mutually_exclusive_group()
    fast_group.add_argument("-fast", action="store_true",
                            help="faster compilation, but maybe worse generated code (default: -fast)")
    fast_group.add_argument("-no-fast", action="store_true",
                            help="slower compilation, but maybe better generated code (default: -fast)")
    universal_group = parser.add_mutually_exclusive_group()
    universal_group.add_argument("-universal", action="store_true",
                                 help="enable universalization to protect the data-flow (default: -universal)")
    universal_group.add_argument("-no-universal", action="store_true",
                                 help="disable universalization (default: -universal)")

    # ---- [Memory-optimization project] additional flags ----------------
    parser.add_argument("-seed", dest="seed", default=None, type=int,
                        help="seed Python's RNG so that compilation is reproducible")
    parser.add_argument("-profile-mem", dest="profile_mem", action="store_true",
                        help="print per-phase memory usage (tracemalloc) of universalize()")
    parser.add_argument("-opt-o1", dest="opt_o1", action="store_true",
                        help="O1: leaner rectangularization")
    parser.add_argument("-opt-o2", dest="opt_o2", action="store_true",
                        help="O2: incremental generation of permutation/copy networks")
    parser.add_argument("-opt-o3", dest="opt_o3", action="store_true",
                        help="O3: in-place application of routing to the DFG")
    parser.add_argument("-opt-o4", dest="opt_o4", action="store_true",
                        help="O4: compact the DFG bookkeeping handed to lowering")
    parser.add_argument("-opt-all", dest="opt_all", action="store_true",
                        help="enable O1, O2, O3 and O4")
    parser.add_argument("-debug-routing", dest="debug_routing", action="store_true",
                        help="keep the original full per-gate routing self-check")
    parser.add_argument("-opt-layering", dest="opt_layering", action="store_true",
                        help="stretch goal: slack-based layer assignment (changes output)")
    parser.add_argument("-opt-o5", dest="opt_o5", action="store_true",
                        help="O5: release the HLIR after clusterization and the "
                             "universalized MLIR/DFG after lowering")
    # ---------------------------------------------------------------------

    config = parser.parse_args()

    # [Memory-optimization project]
    if config.opt_all:
        config.opt_o1 = config.opt_o2 = config.opt_o3 = config.opt_o4 = True
    if config.seed is not None:
        import random
        random.seed(config.seed)
        # Deterministic mode (verification only). MLMI objects have no
        # __hash__, so Python hashes them by memory address and the
        # iteration order of every set of MLMIs (DFG.nodes,
        # forward_edges, ...) changes from run to run. Giving each MLMI a
        # hash equal to its creation index makes the whole compilation
        # reproducible (together with PYTHONHASHSEED=0), without changing
        # what any pass computes: equality is still identity.
        _orig_mlmi_init = IR.MLMI.__init__
        _counter = [0]
        def _det_init(self, *args, **kwargs):
            _counter[0] += 1
            self._det_hash = _counter[0]
            _orig_mlmi_init(self, *args, **kwargs)
        IR.MLMI.__init__ = _det_init
        IR.MLMI.__hash__ = lambda self: self._det_hash


    if config.r < config.l_in + config.l_out:
        # If this constraint does not hold, we cannot have enough
        # registers inside the LLMI to store the inputs and the
        # outputs.
        sys.exit(f'`r` should be at least `l_in + l_out`. Provided: r={config.r}, l_in={config.l_in}, l_out={config.l_out}. Exiting.')

    if config.s < config.l_in or config.s < config.l_out:
        # If this constraint does not hold, an MLMI cannot contain
        # enough instructions to copy all of its inputs to outputs
        # (which it may need to do for rectangularization/universalization).
        sys.exit(f'`s` should be at least `l_in` and `l_out`. Provided: s={config.s}, l_in={config.l_in}, l_out={config.l_out}. Exiting.')

    # Enabling fast if neither -fast nor -no-fast were used
    if not config.fast and not config.no_fast:
        config.fast = True
    # Enabling universalization if neither -univeral nor -no-univeral were used
    if not config.universal and not config.no_universal:
        config.universal = True

    # -------------------------------------------------------------- #
    #                          Compiling!                            #
    # -------------------------------------------------------------- #
    global_start_time = time.time()

    # Frontend (C -> AST -> HLIR)
    pass_start_time = time.time()
    hlir_prog = frontend.file_to_IR(config.inputfile, config)
    pass_total_time = time.time() - pass_start_time
    if config.stats:
        print(f"Frontend: {pass_total_time:.2f} sec")
        print(f"  HLIR size: {len(hlir_prog.instrs)} HLIs")

    # Clusterizer (HLIR -> MLIR/DFG)
    pass_start_time = time.time()
    dfg = clusterizer.clusterize(hlir_prog, config)
    pass_total_time = time.time() - pass_start_time
    if config.stats:
        print(f"Clusterization: {pass_total_time:.2f} sec")
        print(f"  MLIR size: {len(dfg.nodes)} MLMIs")

    # [O5] The HLIR program is only read by the clusterizer. The original
    # driver keeps this reference until the end of compilation.
    if config.opt_o5:
        del hlir_prog

    # Universalizer (MLIR/DFG -> MLIR/DFG)
    if config.universal:
        pass_start_time = time.time()
        dfg = universalizer.universalize(dfg, config)
        pass_total_time = time.time() - pass_start_time
        if config.stats:
            print(f"Universalization: {pass_total_time:.2f} sec")
            print(f"  MLIR size: {len(dfg.nodes)} MLMIs")

    # Lowering (MLIR/DFG -> LLIR)
    pass_start_time = time.time()
    llir_prog = lowering.lower(dfg, config)
    pass_total_time = time.time() - pass_start_time
    if config.stats:
        print(f"Lowering: {pass_total_time:.2f} sec")
        print(f"  LLIR size: {len(llir_prog.instrs)} LLMIs")  # [Memory-optimization project]

    # [O5] After lowering, the universalized MLIR/DFG (all the routing gates,
    # their MLS/HLI objects and the edge dictionaries) is never read again:
    # the serializer only reads llir_prog. The original driver keeps |dfg|
    # alive during serialization, so the serializer's allocations come on
    # top of it. Releasing it here only changes *when* memory is freed, not
    # what is computed, so the bytecode is unchanged.
    if config.opt_o5:
        del dfg
        import gc
        gc.collect()

    # Serializer (LLIR -> bytecode)
    pass_start_time = time.time()
    serializer.serialize(llir_prog, config)
    pass_total_time = time.time() - pass_start_time
    if config.stats:
        print(f"Serialization: {pass_total_time:.2f} sec")

    global_total_time = time.time() - global_start_time
    if config.stats:
        print(f"Total compilation time: {global_total_time:.2f} sec")


if __name__ == "__main__":
    main()
