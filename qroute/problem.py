"""State-Space Search Formulation for Quantum Qubit Routing.

Formulates qubit routing as an informed state-space graph search problem.

Mathematical Formulation:
- State Space: s = (pi, G_rem)
  - pi: L -> V_P is a bijective mapping of logical program qubits to physical chip vertices.
  - G_rem is the set of remaining unexecuted quantum gates in the circuit DAG.
- Actions: SWAP(u, v) on physical coupler (u, v) in E_P.
- Settle Phase: After any SWAP, all ready gates whose operands are physically adjacent
  are executed immediately for free (zero additional search cost).
- Step Cost: c(s, SWAP(u, v), s') = 1 + beta * eps(u, v)
  - beta >= 0: noise penalty weight.
  - eps(u, v): empirical two-qubit CNOT calibration error rate of coupler (u, v).
- Admissible Heuristic:
  h(s) = max_{g = (q_a, q_b) in Ready(s)} ( dist_H(pi(q_a), pi(q_b)) - 1 )
  Guaranteed lower bound on remaining SWAP count since a single SWAP reduces
  distance by at most 1 and step cost >= 1.
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .circuit import DependencyDAG, CX_COUNT
from .hardware import Hardware


@dataclass
class Node:
    """A search tree node in the qubit routing state space.

    Attributes:
        g: Accumulated cost from initial state to this node (sum of 1 + beta * eps).
        l2p: Logical-to-physical placement mapping tuple (pi). l2p[q] = physical node p.
        done: Bitmask of scheduled quantum gates.
        frontier: Tuple of gate indices currently ready for execution but not yet adjacent.
        parent: Predecessor Node in the search tree (used to reconstruct solution path).
        ops: Tuple of operations applied in the transition to this node:
             ('swap', u, v) or ('gate', gate_idx, (phys_qubits...)).
    """
    g: float
    l2p: Tuple[int, ...]
    done: int
    frontier: Tuple[int, ...]
    parent: Optional[Node] = None
    ops: Tuple[Tuple[Any, ...], ...] = ()


@dataclass
class RouteResult:
    """Compilation result returned by any routing algorithm.

    Attributes:
        method: Name of the compiler algorithm (e.g., 'A*-noise+comm', 'Greedy', 'BFS').
        success: Whether the routing terminated successfully with a complete schedule.
        optimal: True if the result is mathematically guaranteed cost-optimal.
        ops: Reconstructed chronological sequence of SWAP and gate operations.
        l2p_init: Initial logical-to-physical qubit mapping.
        l2p_final: Final logical-to-physical qubit mapping after all SWAPs.
        swaps: Total number of inserted physical SWAP gates.
        swap_cost: Cumulative noise-weighted SWAP cost (g-cost at goal).
        esp: Estimated Success Probability across all gates: prod(1 - gate_error).
        nodes_expanded: Number of search states popped and expanded.
        nodes_generated: Total number of child states created.
        runtime: Execution wall-clock runtime in seconds.
        peak_mem_kb: Peak memory consumption during routing in kilobytes.
        note: Explanatory note (e.g. 'optimal', 'greedy completion fallback').
        trace: Search trajectory trace for convergence analysis.
    """
    method: str
    success: bool = False
    optimal: bool = False
    ops: List[Tuple[Any, ...]] = field(default_factory=list)
    l2p_init: Tuple[int, ...] = ()
    l2p_final: Tuple[int, ...] = ()
    swaps: int = 0
    swap_cost: float = 0.0
    esp: float = 0.0
    nodes_expanded: int = 0
    nodes_generated: int = 0
    runtime: float = 0.0
    peak_mem_kb: float = 0.0
    note: str = ""
    trace: List[Dict[str, Any]] = field(default_factory=list)


class RoutingProblem:
    """Encapsulates the state space, transition mechanics, step costs, and heuristic for a circuit on hardware."""

    def __init__(
        self,
        hw: Hardware,
        dag: DependencyDAG,
        beta: float = 1.0,
        gate_weight: float = 0.0,
    ) -> None:
        """Initialize the routing problem environment.

        Args:
            hw: Target physical Hardware topology.
            dag: DependencyDAG representing circuit operations and commutation rules.
            beta: Noise penalty multiplier on coupler calibration error rates.
            gate_weight: Optional weight on gate errors during search.
        """
        if dag.n_qubits > hw.n:
            raise ValueError(
                f"Circuit requires {dag.n_qubits} qubits, but target hardware region has only {hw.n}."
            )
        self.hw: Hardware = hw
        self.dag: DependencyDAG = dag
        self.beta: float = beta
        self.gw: float = gate_weight
        self.D: List[List[int]] = hw.dist.tolist()

        # Precompute step cost for every hardware coupler: c = 1.0 + beta * eps(u, v)
        self.swap_cost: Dict[Tuple[int, int], float] = {}
        for u, v in hw.edges:
            cost = 1.0 + beta * hw.err(u, v)
            self.swap_cost[(u, v)] = self.swap_cost[(v, u)] = cost

    def settle(
        self,
        l2p: Tuple[int, ...],
        done: int,
        frontier: Tuple[int, ...],
    ) -> Tuple[int, Tuple[int, ...], List[Tuple[Any, ...]], float]:
        """Dispatch all quantum gates whose physical adjacency constraints are satisfied under `l2p`.

        Executes an atomic forward worklist pass over ready gates. Because logical-to-physical
        mapping does not change during the settle step, a single pass is guaranteed to resolve
        all immediate cascades.

        Returns:
            Tuple of (updated done mask, remaining waiting gates, scheduled ops list, extra gate cost).
        """
        gates, D = self.dag.gates, self.D
        ops: List[Tuple[Any, ...]] = []
        gcost = 0.0
        pending = list(frontier)
        waiting: List[int] = []

        while pending:
            gi = pending.pop(0)
            gate = gates[gi]
            if gate.is2q:
                pa, pb = l2p[gate.qubits[0]], l2p[gate.qubits[1]]
                if D[pa][pb] != 1:
                    waiting.append(gi)
                    continue
                ops.append(("gate", gi, (pa, pb)))
                if self.gw:
                    gcost += self.gw * self.hw.err(pa, pb)
            else:
                ops.append(("gate", gi, (l2p[gate.qubits[0]],)))

            done |= 1 << gi
            # Check if successors have all their predecessors satisfied
            for s in self.dag.succ[gi]:
                if (self.dag.pred_mask[s] & ~done) == 0 and not ((done >> s) & 1) \
                        and s not in pending and s not in waiting:
                    pending.append(s)
            pending.sort()

        return done, tuple(sorted(waiting)), ops, gcost

    def initial_node(self, l2p0: Tuple[int, ...]) -> Node:
        """Create the root search node from initial placement and execute initially adjacent gates."""
        done, fr, ops, gc = self.settle(tuple(l2p0), 0, tuple(self.dag.initial_frontier()))
        return Node(
            g=gc,
            l2p=tuple(l2p0),
            done=done,
            frontier=fr,
            parent=None,
            ops=tuple(ops),
        )

    def apply_swap(self, node: Node, u: int, v: int) -> Node:
        """Transition function: swap logical qubits at physical nodes u and v, then settle."""
        l2p = list(node.l2p)
        for q, p in enumerate(l2p):
            if p == u:
                l2p[q] = v
            elif p == v:
                l2p[q] = u
        new_l2p = tuple(l2p)

        done, fr, ops, gc = self.settle(new_l2p, node.done, node.frontier)
        step_cost = self.swap_cost[(u, v)] + gc
        return Node(
            g=node.g + step_cost,
            l2p=new_l2p,
            done=done,
            frontier=fr,
            parent=node,
            ops=(("swap", u, v),) + tuple(ops),
        )

    def candidates(self, node: Node, restrict: bool = True) -> List[Tuple[int, int]]:
        """Generate candidate physical couplers for SWAP actions from the current state.

        When `restrict=True` (Frontier-Restricted Pruning), only couplers touching at least
        one physical qubit currently hosting a gate in the ready frontier are considered.
        This prunes the effective branching factor from ~30 down to 4-8 with negligible optimality loss.
        """
        if not restrict:
            return self.hw.edges

        gates = self.dag.gates
        active: Set[int] = {node.l2p[q] for gi in node.frontier for q in gates[gi].qubits}
        return [e for e in self.hw.edges if e[0] in active or e[1] in active]

    def h(self, node: Node) -> float:
        """Admissible and consistent remaining distance lower bound heuristic.

        h(s) = max_{g in frontier} ( dist_H(pi(q0), pi(q1)) - 1 )

        Admissibility Proof:
        Every SWAP costs >= 1.0 and reduces any single gate's shortest-path distance
        by at most 1. Hence, a gate currently at distance d requires at least d - 1 SWAPs.
        Taking the maximum over all currently ready gates establishes a guaranteed
        under-estimate of remaining cost.
        """
        if not node.frontier:
            return 0.0
        gates, D, l2p = self.dag.gates, self.D, node.l2p
        return float(
            max(D[l2p[gates[gi].qubits[0]]][l2p[gates[gi].qubits[1]]] - 1 for gi in node.frontier)
        )

    @staticmethod
    def trace_ops(node: Node) -> List[Tuple[Any, ...]]:
        """Backtrack from goal node to root to reconstruct chronological operations."""
        out = []
        curr: Optional[Node] = node
        while curr is not None:
            out.append(curr.ops)
            curr = curr.parent
        return [op for chunk in reversed(out) for op in chunk]


def evaluate(
    hw: Hardware,
    dag: DependencyDAG,
    l2p0: Tuple[int, ...],
    ops: List[Tuple[Any, ...]],
    beta: float,
) -> Dict[str, Any]:
    """Independent metric computation by replaying scheduled operations on the hardware graph.

    Provides a standard metric evaluation across all algorithms:
    - SWAP count
    - Noise-weighted SWAP cost (using the benchmark beta parameter)
    - Estimated Success Probability (ESP = product of (1 - error_gate))
    - Final logical-to-physical placement mapping
    """
    l2p = list(l2p0)
    swaps = 0
    cost = 0.0
    logesp = 0.0

    for op in ops:
        if op[0] == "swap":
            _, u, v = op
            for q, p in enumerate(l2p):
                if p == u:
                    l2p[q] = v
                elif p == v:
                    l2p[q] = u
            e = hw.err(u, v)
            swaps += 1
            cost += 1.0 + beta * e
            # A SWAP decomposes to 3 CNOT gates
            logesp += 3 * math.log1p(-e)
        else:
            _, gi, phys = op
            if len(phys) == 2:
                cnot_mult = CX_COUNT.get(dag.gates[gi].name, 2)
                logesp += cnot_mult * math.log1p(-hw.err(*phys))

    return {
        "swaps": swaps,
        "swap_cost": cost,
        "esp": math.exp(logesp),
        "l2p_final": tuple(l2p),
    }
