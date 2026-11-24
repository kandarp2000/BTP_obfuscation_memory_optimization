"""No-op stand-in for the graphviz package (only used by OBSCURE's debug plots)."""
class _G:
    def __init__(self, *a, **k): pass
    def node(self, *a, **k): pass
    def edge(self, *a, **k): pass
    def render(self, *a, **k): pass
    def attr(self, *a, **k): pass
Digraph = _G
Graph = _G
