"""Classical Baseline Routers for Comparison and Ablation Analysis.

Provides two standard reference implementations:
1. Greedy Nearest-Gate Router:
   A fast local heuristic router that selects SWAPs moving physical qubits directly
   toward immediate gate adjacency along shortest paths. Demonstrates topological
   thrashing on complex entanglement graphs.
2. Breadth-First Search (BFS):
   An uninformed layer-by-layer graph search that treats all SWAPs as unit cost (c = 1).
   Finds the minimal SWAP count for tiny circuits but suffers from exponential state explosion.
"""

from __future__ import annotations
import time
from collections import deque
from typing import Any, List, Tuple

from .problem import RoutingProblem, RouteResult, Node


def greedy_finish(problem: RoutingProblem, node: Node) -> List[Tuple[Any, ...]]:
    """Greedy local completion routine.

    Iteratively takes the first ready gate in the frontier and performs SWAPs moving
    one of its operand qubits one hop closer along a shortest path until all gates settle.

    Args:
        problem: Active RoutingProblem.
        node: Starting state Node.

    Returns:
        List of generated operation tuples appended during greedy resolution.
    """
    D, hw, gates = problem.D, problem.hw, problem.dag.gates
    ops: List[Tuple[Any, ...]] = []

    while node.frontier:
        gi = node.frontier[0]
        a, b = gates[gi].qubits
        pa, pb = node.l2p[a], node.l2p[b]
        best, best_d = None, D[pa][pb]

        # Try moving either endpoint closer to the other
        for x, y in ((pa, pb), (pb, pa)):
            for w in hw.adj[x]:
                if D[w][y] < best_d:
                    best, best_d = (x, w), D[w][y]

        if best is None:
            break

        node = problem.apply_swap(node, *best)
        ops.extend(node.ops)

    return ops


def greedy_route(
    problem: RoutingProblem,
    l2p0: Tuple[int, ...],
    name: str = "Greedy",
) -> RouteResult:
    """Execute end-to-end greedy nearest-gate routing from initial placement."""
    t0 = time.perf_counter()
    root = problem.initial_node(l2p0)
    ops = list(root.ops) + greedy_finish(problem, root)
    n_swaps = sum(op[0] == "swap" for op in ops)

    return RouteResult(
        method=name,
        success=True,
        ops=ops,
        l2p_init=tuple(l2p0),
        nodes_expanded=n_swaps,
        nodes_generated=n_swaps,
        runtime=time.perf_counter() - t0,
    )


def bfs_route(
    problem: RoutingProblem,
    l2p0: Tuple[int, ...],
    *,
    max_nodes: int = 50_000,
    time_limit: float = 60.0,
    name: str = "BFS",
) -> RouteResult:
    """Execute uninformed Breadth-First Search over SWAP sequences.

    Treats every SWAP as cost 1 and explores layer-by-layer. Guarantees minimal
    SWAP count on small problem instances but lacks noise awareness and scalability.
    """
    t0 = time.perf_counter()
    root = problem.initial_node(l2p0)
    q = deque([root])
    seen = {(root.l2p, root.done)}
    expanded = 0
    generated = 0

    while q:
        node = q.popleft()
        if not node.frontier:
            return RouteResult(
                method=name,
                success=True,
                ops=problem.trace_ops(node),
                l2p_init=tuple(l2p0),
                nodes_expanded=expanded,
                nodes_generated=generated,
                runtime=time.perf_counter() - t0,
            )

        if expanded >= max_nodes or (time.perf_counter() - t0) > time_limit:
            return RouteResult(
                method=name,
                success=False,
                nodes_expanded=expanded,
                nodes_generated=generated,
                runtime=time.perf_counter() - t0,
                note="BFS budget exhausted",
            )

        expanded += 1
        for u, v in problem.candidates(node, restrict=False):
            c = problem.apply_swap(node, u, v)
            generated += 1
            k = (c.l2p, c.done)
            if k not in seen:
                seen.add(k)
                q.append(c)

    return RouteResult(
        method=name,
        success=False,
        note="no solution found in reachable space",
    )
