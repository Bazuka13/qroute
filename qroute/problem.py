"""Search-problem definition shared by A*, BFS and greedy (state, transitions, cost, h)."""
from __future__ import annotations
import math
from dataclasses import dataclass, field

from .circuit import DependencyDAG, CX_COUNT
from .hardware import Hardware


@dataclass
class Node:
    g: float
    l2p: tuple          # logical -> physical placement  (pi in the proposal)
    done: int           # bitmask of scheduled gates      (G_rem = complement)
    frontier: tuple     # ready-but-not-yet-adjacent gates (sorted)
    parent: "Node | None" = None
    ops: tuple = ()     # ops applied since parent: ("swap",u,v) / ("gate",idx,(p,..))


@dataclass
class RouteResult:
    method: str
    success: bool = False
    optimal: bool = False
    ops: list = field(default_factory=list)
    l2p_init: tuple = ()
    l2p_final: tuple = ()
    swaps: int = 0
    swap_cost: float = 0.0        # sum(1 + beta*err) over inserted SWAPs  (= g at goal)
    esp: float = 0.0              # estimated success probability (product of (1-err))
    nodes_expanded: int = 0
    nodes_generated: int = 0
    runtime: float = 0.0
    peak_mem_kb: float = 0.0
    note: str = ""
    trace: list = field(default_factory=list)


class RoutingProblem:
    """State s=(pi, G_rem).  Action = SWAP on a hardware edge.  After each SWAP every gate that
    became executable is scheduled for free (zero-cost 'settle' step)."""

    def __init__(self, hw: Hardware, dag: DependencyDAG, beta=1.0, gate_weight=0.0):
        if dag.n_qubits > hw.n:
            raise ValueError(f"circuit needs {dag.n_qubits} qubits, hardware region has {hw.n}")
        self.hw, self.dag, self.beta, self.gw = hw, dag, beta, gate_weight
        self.D = hw.dist.tolist()
        self.swap_cost = {}
        for u, v in hw.edges:
            self.swap_cost[(u, v)] = self.swap_cost[(v, u)] = 1.0 + beta * hw.err(u, v)

    # ---- transition helpers -------------------------------------------------
    def settle(self, l2p, done, frontier):
        """Schedule every ready gate that is executable under `l2p`.  The mapping does not
        change while settling, so one worklist pass is enough."""
        gates, D = self.dag.gates, self.D
        ops, gcost = [], 0.0
        pending, waiting = sorted(frontier), []
        while pending:
            gi = pending.pop(0)
            gate = gates[gi]
            if gate.is2q:
                pa, pb = l2p[gate.qubits[0]], l2p[gate.qubits[1]]
                if D[pa][pb] != 1:
                    waiting.append(gi); continue
                ops.append(("gate", gi, (pa, pb)))
                if self.gw:
                    gcost += self.gw * self.hw.err(pa, pb)
            else:
                ops.append(("gate", gi, (l2p[gate.qubits[0]],)))
            done |= 1 << gi
            for s in self.dag.succ[gi]:
                if (self.dag.pred_mask[s] & ~done) == 0 and not (done >> s) & 1 \
                        and s not in pending and s not in waiting:
                    pending.append(s)
            pending.sort()
        return done, tuple(sorted(waiting)), ops, gcost

    def initial_node(self, l2p0) -> Node:
        done, fr, ops, gc = self.settle(tuple(l2p0), 0, self.dag.initial_frontier())
        return Node(gc, tuple(l2p0), done, fr, None, tuple(ops))

    def apply_swap(self, node: Node, u: int, v: int) -> Node:
        l2p = list(node.l2p)
        for q, p in enumerate(l2p):
            if p == u: l2p[q] = v
            elif p == v: l2p[q] = u
        l2p = tuple(l2p)
        done, fr, ops, gc = self.settle(l2p, node.done, node.frontier)
        return Node(node.g + self.swap_cost[(u, v)] + gc, l2p, done, fr, node,
                    (("swap", u, v),) + tuple(ops))

    def candidates(self, node: Node, restrict=True):
        if not restrict:
            return self.hw.edges
        gates = self.dag.gates
        active = {node.l2p[q] for gi in node.frontier for q in gates[gi].qubits}
        return [e for e in self.hw.edges if e[0] in active or e[1] in active]

    # ---- heuristic ------------------------------------------------------------
    def h(self, node: Node) -> float:
        """h(n) = max over frontier gates of (dist - 1).  Every SWAP costs >= 1.0 and shrinks any
        single gate's distance by at most 1  =>  admissible; consistent as shown in README."""
        if not node.frontier:
            return 0.0
        gates, D, l2p = self.dag.gates, self.D, node.l2p
        return float(max(D[l2p[gates[gi].qubits[0]]][l2p[gates[gi].qubits[1]]] - 1
                         for gi in node.frontier))

    @staticmethod
    def trace_ops(node: Node):
        out = []
        while node is not None:
            out.append(node.ops); node = node.parent
        return [op for chunk in reversed(out) for op in chunk]


def evaluate(hw: Hardware, dag: DependencyDAG, l2p0, ops, beta):
    """Independent metric computation by replaying `ops` (so every method is judged identically)."""
    l2p = list(l2p0)
    swaps, cost, logesp = 0, 0.0, 0.0
    for op in ops:
        if op[0] == "swap":
            _, u, v = op
            for q, p in enumerate(l2p):
                if p == u: l2p[q] = v
                elif p == v: l2p[q] = u
            e = hw.err(u, v)
            swaps += 1; cost += 1.0 + beta * e
            logesp += 3 * math.log1p(-e)
        else:
            _, gi, phys = op
            if len(phys) == 2:
                logesp += CX_COUNT.get(dag.gates[gi].name, 2) * math.log1p(-hw.err(*phys))
    return dict(swaps=swaps, swap_cost=cost, esp=math.exp(logesp), l2p_final=tuple(l2p))
