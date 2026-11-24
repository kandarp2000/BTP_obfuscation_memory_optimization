from IR import MLMI, MemOperand, ImmOperand, MLS, HLI, Opcode
from DFG import DFG
from .rectangularize import rectangularize
from . import routing
import math
import random
import time
import tracemalloc


class _MemProfiler:
    """[Memory-optimization project] per-phase memory probe for universalize().

    Uses tracemalloc, so only memory allocated *inside* universalize() is
    counted (the input DFG built by earlier passes is not). For each phase we
    report the memory still held at the end of the phase ("current") and the
    highest value reached during the phase ("peak").
    """
    def __init__(self, enabled):
        self.enabled = enabled
        self.rows = []
        if enabled:
            tracemalloc.start()
            self.t = time.time()

    def phase(self, name):
        if not self.enabled:
            return
        cur, peak = tracemalloc.get_traced_memory()
        now = time.time()
        self.rows.append((name, cur / 2**20, peak / 2**20, now - self.t))
        print(f"[mem] {name:32s} current={cur / 2**20:9.2f} MB  "
              f"peak={peak / 2**20:9.2f} MB  time={now - self.t:7.2f} s", flush=True)
        tracemalloc.reset_peak()
        self.t = time.time()

    def finish(self):
        if not self.enabled:
            return
        tracemalloc.stop()
        peak = max(r[2] for r in self.rows)
        cur = self.rows[-1][1]
        tot = sum(r[3] for r in self.rows)
        print(f"[mem] universalize TOTAL{'':16s} current={cur:9.2f} MB  "
              f"peak={peak:9.2f} MB  time={tot:7.2f} s", flush=True)

def universalize(dfg:DFG, config) -> DFG :

    assert config.l_in == config.l_out and \
        2**math.log2(config.l_in) == config.l_in

    #dfg.show_dfg(filename="universalize_0")

    prof = _MemProfiler(getattr(config, "profile_mem", False))

    start_rectangularize_time = time.time()
    layers = rectangularize(dfg, config)
    prof.phase("rectangularize")

    if config.stats:
        if config.depth == 0 or config.depth <= len(layers):
            print(f"  program depth: {len(layers)}")
        else:
            print(f"  program initial depth: {len(layers)}")
            print(f"  program final depth: {config.depth}")


    #dfg.show_dfg(filename="universalize_1")

    add_depth_padding(dfg, layers, config)
    prof.phase("add_depth_padding")

    #dfg.show_dfg(filename="universalize_2")

    add_input_masking_layer(dfg, layers, config)
    prof.phase("add_input_masking_layer")

    #dfg.show_dfg(filename="universalize_3")

    propagate_outputs_to_last_layer(dfg, layers, config)
    prof.phase("propagate_outputs_to_last_layer")

    #dfg.show_dfg(filename="universalize_4")

    equalize_layers(dfg, layers, config)
    prof.phase("equalize_layers")

    #dfg.show_dfg(filename="universalize_5")

    match_layers_inputs_outputs(dfg, layers,config)
    prof.phase("match_layers_inputs_outputs")
    rectangularize_total_time = time.time() - start_rectangularize_time

    if config.stats:
        print(f"Rectangularization: {rectangularize_total_time:.2f}")
        print(f"  MLIR size: {len(dfg.nodes)} MLMIs")

    #dfg.show_dfg(filename="universalize_6")

    add_permutation(dfg, layers, config)
    prof.phase("add_permutation")

    #dfg.show_dfg(filename="universalize_7")

    dfg.check_dfg_integrity()
    prof.phase("check_dfg_integrity")

    if getattr(config, "opt_o4", False):
        compact_dfg_for_lowering(dfg)
        prof.phase("compact_dfg_for_lowering")
    prof.finish()

    return dfg

class _CompactEdges(dict):
    """[O4] Replacement for DFG.forward_edges after universalization.

    The original defaultdict(set) keeps an (empty) set for every node that
    has no successor and silently allocates a new one for every node that
    is merely looked up (e.g. all nodes of the last layer during
    scheduling). Here a missing key returns one shared empty frozenset
    *without* storing anything.
    """
    __slots__ = ()
    _EMPTY = frozenset()
    def __missing__(self, key):
        return self._EMPTY


def compact_dfg_for_lowering(dfg:DFG):
    """[O4] Compact the bookkeeping that universalization hands to lowering.

    Profiling showed that the memory left at the end of universalize() is
    dominated by the routing gates themselves (the output) plus the DFG's
    edge structures. After universalization the only remaining user of the
    DFG is DFG.to_LLIR(), which needs |nodes|, |forward_edges| (read-only)
    and the program inputs/outputs; |backward_edges| is never used again.

      * backward_edges is released (one dict entry per variable of the
        universalized program, i.e. one per routing-gate output).
      * dfg.prog, the pre-clusterization MLIRProgram, is replaced by a
        light object that only keeps its |inputs| (the only field read
        afterwards, by DFG.to_LLIR). The original keeps one wrapper MLMI +
        MLS + lists for every HLI of the source program alive until the
        end of compilation.
      * forward_edges keeps every non-empty successor set *as is* (the
        scheduler calls todo.update(<set>), and CPython's set-to-set update
        depends on the internal layout of the set, so replacing the sets by
        tuples or frozensets would change the scheduling order and thus the
        bytecode). Only the empty sets are dropped: these are the
        before-layer sets cleared by add_permutation and the placeholders
        created by defaultdict look-ups. Updating with an empty set and
        with the shared empty frozenset are both no-ops, so the scheduling
        order is unchanged.
    """
    # release first, so that building the compact edge dict below does not
    # raise the peak
    dfg.backward_edges = {}
    dfg.prog = _ProgInputs(dfg.prog.inputs)
    old_edges = dfg.forward_edges
    dfg.forward_edges = None
    dfg.forward_edges = _CompactEdges(
        (node, succ) for node, succ in old_edges.items() if succ)
    del old_edges


class _ProgInputs:
    """[O4] What DFG.to_LLIR still needs from the original MLIRProgram."""
    __slots__ = ("inputs",)
    def __init__(self, inputs):
        self.inputs = inputs


# [O1] Shared padding constant. Rectangularization pads every dummy output
# with "MOV out, 0"; the original code allocates a fresh ImmOperand(0) for
# each one (thousands per program). ImmOperand is an immutable value
# (compared and hashed by value, never modified by later passes), so with
# -opt-o1 all padding instructions share one instance.
_ZERO = ImmOperand(0)

def _zero(config):
    return _ZERO if getattr(config, "opt_o1", False) else ImmOperand(0)


def add_depth_padding(dfg:DFG, layers, config):
    """Add layers so that the number of layers is at config.depth"""
    depth = len(layers)
    if config.depth != 0:
        if config.depth < depth:
            print(f"Flag '-depth {config.depth}' was used, but the program has a depth of {depth}. Ignoring the -depth flag and continuing.")
        else:
            depth = config.depth

    for _ in range(len(layers), depth):
        node = MLMI(MLS([]), [], [])
        dfg.nodes.add(node)
        layers.append([node])

def add_input_masking_layer(dfg:DFG, layers, config):
    """Add an initial layer to mask where inputs are going (because there
    will be a permutation layer in between this initial layer and the
    next layer)

    Note that at least one LLMI of this layer must have |config.l_out|
    outputs, so that all LLMI of the next layer can take fill all
    their inputs.

    """
    # Creating this initial layer
    initial_layer = []
    old_to_new_inputs = dict()
    old_inputs = set(dfg.prog.inputs)
    while len(old_inputs) != 0:
        node = MLMI(MLS([]), [], [])
        initial_layer.append(node)
        while len(node.inputs)  < config.l_in and \
              len(node.outputs) < config.l_out and \
              len(old_inputs) != 0:
            m = old_inputs.pop()
            new_input = MemOperand(dfg.memory_count)
            dfg.memory_count += 1

            node.inputs.append(m)
            node.outputs.append(new_input)
            node.seq.instrs.append(HLI(Opcode.MOV, new_input, m))

            dfg.backward_edges[new_input] = node
            old_to_new_inputs[m] = new_input

    node = initial_layer[0]
    while len(node.outputs) != config.l_out:
        out = MemOperand(dfg.memory_count)
        dfg.memory_count += 1
        node.outputs.append(out)
        node.seq.instrs.append(HLI(Opcode.MOV, out, _zero(config)))
        dfg.backward_edges[out] = node

    # Adding forward edges from this initial layer to the rest of the
    # graph, and updating the uses of the old inputs.
    dfg.prog_outputs = [ old_to_new_inputs.get(m, m) for m in dfg.prog_outputs ]
    for node in dfg.nodes:
        for m in node.inputs:
            if m in old_to_new_inputs:
                dfg.forward_edges[dfg.backward_edges[old_to_new_inputs[m]]].add(node)
        node.inputs = [ old_to_new_inputs.get(m, m) for m in node.inputs ]
        for instr in node.seq:
            instr.src1 = old_to_new_inputs.get(instr.src1, instr.src1)
            instr.src2 = old_to_new_inputs.get(instr.src2, instr.src2)
            instr.src3 = old_to_new_inputs.get(instr.src3, instr.src3)

    layers.insert(0, initial_layer)
    for node in initial_layer:
        dfg.nodes.add(node)



def propagate_outputs_to_last_layer(dfg:DFG, layers, config):

    """Propagate outputs to the last layer

    In the original DFG (and even after rectangularization), some
    outputs can be defined before the last layer. This is a problem
    for security: all outputs need to be defined on the last
    layer.

    """

    def add_input_output_to_node(m:MemOperand, node:MLMI) -> MemOperand:
        """Adds |m| as input to |node|, and make |node| return a copy of |m|"""
        new_output = MemOperand(dfg.memory_count)
        dfg.memory_count += 1

        node.inputs.append(m)
        node.outputs.append(new_output)
        node.seq.instrs.append(HLI(Opcode.MOV, new_output, m))

        def_m_node = dfg.backward_edges[m]
        dfg.forward_edges[def_m_node].add(node)
        dfg.backward_edges[new_output] = node

        return new_output


    to_take_as_inputs = set() # Outputs that were defined in the previous
    for layer_idx, layer in enumerate(layers):
        layer = layers[layer_idx]
        new_outputs = dict()
        while len(to_take_as_inputs) != 0:
            m = to_take_as_inputs.pop()
            node = None
            for mlmi in layer:
                if len(mlmi.inputs)  < config.l_in and \
                   len(mlmi.outputs) < config.l_out and \
                   len(mlmi.seq.instrs)  < config.s:
                    # TODO: do we need to check register pressure?
                    node = mlmi
                    break
            if node == None:
                # Need to create a new node in the next layer
                node = MLMI(MLS([]), [], [])
                dfg.nodes.add(node)
                layers[layer_idx].append(node)

            new_output = add_input_output_to_node(m, node)
            new_outputs[m] = new_output

        # Updating program outputs
        dfg.prog_outputs = [ new_outputs.get(m, m) for m in dfg.prog_outputs ]

        # Collecting outputs of this layer
        prog_outputs_set = set(dfg.prog_outputs)
        to_take_as_inputs = set()
        for mlmi in layer:
            to_take_as_inputs.update([ m for m in mlmi.outputs if m in prog_outputs_set ])

    # Adding a final layer to reveal the outputs
    final_layer = []
    new_outputs = dict()
    while len(to_take_as_inputs) != 0:
        curr_mlmi = MLMI(MLS([]), [], [])
        dfg.nodes.add(curr_mlmi)
        while len(curr_mlmi.inputs)  < config.l_in and \
              len(curr_mlmi.outputs) < config.l_out and \
              len(curr_mlmi.seq.instrs)  < config.s and \
              len(to_take_as_inputs) != 0:
            m = to_take_as_inputs.pop()
            new_output = add_input_output_to_node(m, curr_mlmi)
            new_outputs[m] = new_output
        final_layer.append(curr_mlmi)

    dfg.prog_outputs = [ new_outputs.get(m, m) for m in dfg.prog_outputs ]

    layers.append(final_layer)


def equalize_layers(dfg:DFG, layers, config):
    """Make all layers the same width"""
    # Find the width of the largest layer
    max_width = -1
    for layer in layers[1:-1]:
        max_width = max(max_width, len(layer))

    if config.width != 0:
        if config.width < max_width:
            print(f"Flag '-width {config.width}' was used, but the program has a width of {max_width}. Ignoring the -width flag and continuing.")
        else:
            max_width = config.width

    if config.stats:
        print(f"  program width: {max_width}")

    # Add dummy nodes to all layers whose width is less than |max_width|
    for layer in layers[1:-1]:
        for _ in range(len(layer), max_width):
            mlmi = MLMI(MLS([]), [], [])
            dfg.nodes.add(mlmi)
            layer.append(mlmi)


def match_layers_inputs_outputs(dfg:DFG, layers, config):
    """Make all MLMIs have the same number of inputs/outputs

    * Outputs: we add to an MLMI outputs some of its intermediate
      (internal) variables. If the MLMI doesn't have enough outputs,
      then we just return some 0s by padding the MLMI with:

          MOV __, 0

      Note that we prefer to return intermediate variables, since this
      does not increase the amount of instructions inside the MLMI. In
      practice though, I'm not sure if it really makes a difference...

    * Inputs: for inputs, we need to take some input of the previous
      layer. In practice, it doesn't matter which input we choose:
      with the permutation layers that will be added, all inputs are
      identical from the dataflow's standpoint.

    """

    prev_layer_outputs = list({ o for node in layers[0]
                                for o in node.outputs }) # outputs of the previous layer
    for layer_idx in range(1, len(layers)-1):
        layer = layers[layer_idx]

        # Add inputs
        for mlmi in layer:
            config.l_in > len(prev_layer_outputs)
            while len(mlmi.inputs) != config.l_in:
                new_input = random.choice(prev_layer_outputs)
                while new_input in mlmi.inputs:
                    new_input = random.choice(prev_layer_outputs)
                mlmi.inputs.append(new_input)
                def_node = dfg.backward_edges[new_input]
                dfg.forward_edges[def_node].add(mlmi)

        # Add outputs
        for mlmi in layer:
            if len(mlmi.outputs) != config.l_out:
                # Gathering intermediate variables that are not
                # returned.
                possible_returns = set()
                for hli in mlmi.seq:
                    if hli.dst not in mlmi.outputs:
                        possible_returns.add(hli.dst)
                # Actually adding new outputs
                while len(mlmi.outputs) != config.l_out:
                    if len(possible_returns) != 0:
                        # Adding an intermediate variable to the
                        # outputs.
                        new_output = possible_returns.pop()
                        mlmi.outputs.append(new_output)
                        dfg.backward_edges[new_output] = mlmi
                    else:
                        # Returning a 0
                        new_output = MemOperand(dfg.memory_count)
                        dfg.memory_count += 1
                        mlmi.seq.instrs.append(HLI(Opcode.MOV, new_output, _zero(config)))
                        mlmi.outputs.append(new_output)
                        dfg.backward_edges[new_output] = mlmi


        prev_layer_outputs = list({ m for mlmi in layer for m in mlmi.outputs })



def add_permutation(dfg:DFG, layers, config):
    o2 = getattr(config, "opt_o2", False)
    o3 = getattr(config, "opt_o3", False)
    for i in range(len(layers)-1):
        before_layer = layers[i]
        after_layer  = layers[i+1]

        inputs  = [ m for mlmi in before_layer for m in mlmi.outputs ]
        outputs = [ m for mlmi in after_layer  for m in mlmi.inputs  ]

        # Removing old foward edges: the permutation network will make
        # them obsolete.
        for mlmi in before_layer:
            dfg.forward_edges[mlmi] = set()

        perm_layer_min_size = max(len(inputs), len(outputs))
        if int(math.log2(perm_layer_min_size)) == math.log2(perm_layer_min_size):
            perm_layer_size = perm_layer_min_size
        else:
            perm_layer_size = 2**(1+int(math.log2(perm_layer_min_size)))

        inputs_pos = { m:i for i,m in enumerate(inputs) }
        if not o3:
            # (never used; with -opt-o3 it is simply not built)
            inputs_pos_rev = { i:m for i,m in enumerate(inputs) }
        perm_outputs = [ inputs_pos[m] for m in outputs ]
        perm_outputs += [ 0 ] * (perm_layer_size - len(perm_outputs))
        if o3:
            del inputs_pos  # [O3] no longer needed for this layer

        # Padding inputs so that it's the same length as outputs
        inputs += [ImmOperand(0)] * (perm_layer_size - len(inputs))

        le = math.log2(config.l_in)
        if o2:
            # [O2] columns are generated lazily, one at a time, in compact form
            perm = routing.iter_bdb_columns(perm_outputs, le)
        else:
            bf = routing.BDBFuncMI(perm_outputs, le=le)
            perm = [ ("pub", row) if isinstance(row, routing.PublicShuffle) else
                     ("sec", list(row.items())) if isinstance(row, routing.SecretShuffles) else
                     (None, row)
                     for row in routing.optimize(bf.canonical()) ]
        if getattr(config, "debug_routing", False):
            # full independent check of the routing program for this layer
            assert tuple(perm_outputs) == routing.BDBFuncMI(perm_outputs, le=le).apply()

        def apply_secret_perm_inplace(inputs, off, p, inputs_checker):
            """[O3] Same gate as apply_secret_perm, without copying the whole
            wire list (and checker list) for every gate: only the len(p)
            wires of the gate's window are read and overwritten. Nodes,
            MemOperands and instructions are created in the same order as in
            the original, so the generated program is identical."""
            k = len(p)
            window = inputs[off:off+k]
            window_chk = inputs_checker[off:off+k]
            node = MLMI(MLS([]), [], [])
            dfg.nodes.add(node)
            node.inputs = [ m for m in window if isinstance(m,MemOperand)]
            for i,idx in enumerate(p):
                out = MemOperand(dfg.memory_count)
                dfg.memory_count += 1
                node.seq.instrs.append(HLI(Opcode.MOV, out, window[idx]))
                node.outputs.append(out)

                inputs[off+i] = out
                inputs_checker[off+i] = window_chk[idx]

                dfg.backward_edges[out] = node

            for m in node.inputs:
                if m in dfg.backward_edges:
                    dfg.forward_edges[dfg.backward_edges[m]].add(node)

        def apply_secret_perm(inputs, off, p, inputs_checker):
            new_inputs = list(inputs)
            new_inputs_checker = list(inputs_checker)
            node = MLMI(MLS([]), [], [])
            dfg.nodes.add(node)
            node.inputs = [ m for m in inputs[off:off+len(p)] if isinstance(m,MemOperand)]
            for i,idx in enumerate(p):
                out = MemOperand(dfg.memory_count)
                dfg.memory_count += 1
                prev = inputs[off+idx]
                node.seq.instrs.append(HLI(Opcode.MOV, out, inputs[off+idx]))
                node.outputs.append(out)

                new_inputs[off+i] = out
                new_inputs_checker[off+i] = inputs_checker[off+idx]

                dfg.backward_edges[out] = node

            for m in node.inputs:
                if m in dfg.backward_edges:
                    dfg.forward_edges[dfg.backward_edges[m]].add(node)

            for i in range(len(inputs)):
                inputs[i] = new_inputs[i]
                inputs_checker[i] = new_inputs_checker[i]

        # inputs_checker is used to check that the permutation is
        # correct: it's an array of integers of which we apply the
        # permutation alongside the real |inputs|, and at the end we
        # check if |inputs_checker| is indeed |perm_outputs|.
        inputs_checker = [ i for i,_ in enumerate(inputs) ]

        # Converting the permutation into nodes in the DFG
        gate = apply_secret_perm_inplace if o3 else apply_secret_perm
        for kind, row in perm:
            if kind == "pub":
                inputs = [ inputs[i] for i in row ]
                inputs_checker = [ inputs_checker[i] for i in row ]

            elif kind == "sec":
                for off, p in row:
                    gate(inputs, off, p, inputs_checker)

            else:
                assert False
        del perm  # [O2/O3] routing data of this layer is no longer needed

        if perm_outputs != inputs_checker:
            print("Error in the permutation.")
            print("Target: ", perm_outputs)
            print("Got: ", inputs_checker)
            raise RuntimeError()

        # Updating the inputs of the next layer
        off = 0
        for mlmi in after_layer:
            old_to_new = dict()
            # Updating inputs and DFG edges
            for i,old_m in enumerate(mlmi.inputs):
                new_m = inputs[off+i]
                dfg.forward_edges[dfg.backward_edges[new_m]].add(mlmi)
                old_to_new[old_m] = new_m
                mlmi.inputs[i]    = new_m
            # Updating body of the MLMI
            for instr in mlmi.seq.instrs:
                instr.src1 = old_to_new.get(instr.src1, instr.src1)
                instr.src2 = old_to_new.get(instr.src2, instr.src2)
                instr.src3 = old_to_new.get(instr.src3, instr.src3)

            off += len(mlmi.inputs)
