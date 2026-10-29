"""Noise-weighted, commutativity-aware A* qubit router."""
from __future__ import annotations
import heapq
import itertools
import time

from .problem import RoutingProblem, RouteResult, Node
from .baselines import greedy_finish


def astar_route(problem: RoutingProblem, l2p0, *, weight=1.0, restrict_swaps=True,
                max_nodes=50_000, time_limit=60.0, record_trace=0, name="A*") -> RouteResult:
    """f(n) = g(n) + weight*h(n).   weight=1 -> optimal under the cost model
    (given restrict_swaps=False; with restrict_swaps=True only SWAPs touching a frontier qubit are tried).
    weight>1 -> weighted A* (bounded sub-optimal, far fewer nodes).
    If the node/time budget runs out we finish greedily from the most promising open node
    and flag the result as non-optimal."""
    t0 = time.perf_counter()
    root = problem.initial_node(l2p0)
    counter = itertools.count()
    open_heap = [(weight * problem.h(root), problem.h(root), next(counter), root)]
    best_g = {(root.l2p, root.done): root.g}
    expanded, generated, trace = 0, 1, []
    goal, note = None, ""

    while open_heap:
        f, h, _, node = heapq.heappop(open_heap)
        key = (node.l2p, node.done)
        if best_g.get(key, float("inf")) < node.g - 1e-12:
            continue                                   # stale entry
        if not node.frontier:                          # G_rem is empty -> goal
            goal = node; break
        if expanded >= max_nodes or time.perf_counter() - t0 > time_limit:
            note = "budget exhausted -> greedy completion"; break
        expanded += 1
        if record_trace and len(trace) < record_trace:
            trace.append(dict(step=expanded, g=node.g, h=h, f=f, l2p=node.l2p, ops=node.ops,
                              frontier=len(node.frontier), open=len(open_heap)))
        for (u, v) in problem.candidates(node, restrict_swaps):
            child = problem.apply_swap(node, u, v)
            generated += 1
            k = (child.l2p, child.done)
            if child.g < best_g.get(k, float("inf")) - 1e-12:
                best_g[k] = child.g
                hc = problem.h(child)
                heapq.heappush(open_heap, (child.g + weight * hc, hc, next(counter), child))

    optimal = goal is not None and weight == 1.0 and not restrict_swaps
    if goal is None:                                   # fallback: finish from best open node
        if not open_heap:
            return RouteResult(name, success=False, note="search space exhausted",
                               nodes_expanded=expanded, nodes_generated=generated,
                               runtime=time.perf_counter() - t0)
        _, _, _, start = min(open_heap, key=lambda e: (e[1], e[3].g))
        ops_prefix = problem.trace_ops(start)
        extra = greedy_finish(problem, start)
        ops = ops_prefix + extra
    else:
        ops = problem.trace_ops(goal)
        if weight == 1.0 and restrict_swaps:
            note = "optimal w.r.t. relevant-SWAP action set"
    return RouteResult(name, success=True, optimal=optimal, ops=ops, l2p_init=tuple(l2p0),
                       nodes_expanded=expanded, nodes_generated=generated,
                       runtime=time.perf_counter() - t0, note=note, trace=trace)
