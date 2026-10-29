"""Baselines: uninformed BFS (fewest SWAPs, noise-blind) and greedy nearest-gate router."""
from __future__ import annotations
import time
from collections import deque

from .problem import RoutingProblem, RouteResult, Node


def greedy_finish(problem: RoutingProblem, node: Node):
    """Greedy: take the *first* ready gate (program order) and move one endpoint one hop along a
    shortest path.  Ignores downstream gates and noise.  Returns the list of ops appended."""
    D, hw, gates = problem.D, problem.hw, problem.dag.gates
    ops = []
    while node.frontier:
        gi = node.frontier[0]
        a, b = gates[gi].qubits
        pa, pb = node.l2p[a], node.l2p[b]
        best, best_d = None, D[pa][pb]
        for x, y in ((pa, pb), (pb, pa)):                # try moving either endpoint
            for w in hw.adj[x]:
                if D[w][y] < best_d:
                    best, best_d = (x, w), D[w][y]
        node = problem.apply_swap(node, *best)
        ops.extend(node.ops)
    return ops


def greedy_route(problem: RoutingProblem, l2p0, name="Greedy") -> RouteResult:
    t0 = time.perf_counter()
    root = problem.initial_node(l2p0)
    ops = list(root.ops) + greedy_finish(problem, root)
    n_swaps = sum(o[0] == "swap" for o in ops)
    return RouteResult(name, success=True, ops=ops, l2p_init=tuple(l2p0),
                       nodes_expanded=n_swaps, nodes_generated=n_swaps,
                       runtime=time.perf_counter() - t0)


def bfs_route(problem: RoutingProblem, l2p0, *, max_nodes=50_000, time_limit=60.0,
              name="BFS") -> RouteResult:
    """Breadth-first over SWAP count (uniform step cost 1, noise ignored)."""
    t0 = time.perf_counter()
    root = problem.initial_node(l2p0)
    q, seen = deque([root]), {(root.l2p, root.done)}
    expanded = generated = 0
    while q:
        node = q.popleft()
        if not node.frontier:
            return RouteResult(name, success=True, ops=problem.trace_ops(node),
                               l2p_init=tuple(l2p0), nodes_expanded=expanded,
                               nodes_generated=generated, runtime=time.perf_counter() - t0)
        if expanded >= max_nodes or time.perf_counter() - t0 > time_limit:
            return RouteResult(name, success=False, nodes_expanded=expanded,
                               nodes_generated=generated, runtime=time.perf_counter() - t0,
                               note="BFS budget exhausted")
        expanded += 1
        for u, v in problem.candidates(node, restrict=False):
            c = problem.apply_swap(node, u, v); generated += 1
            k = (c.l2p, c.done)
            if k not in seen:
                seen.add(k); q.append(c)
    return RouteResult(name, success=False, note="no solution")
