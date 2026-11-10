"""Quantum Hardware Architecture and Noise Calibration Modeling.

Represents physical quantum computing processors as undirected graphs H = (V_P, E_P),
where vertices correspond to physical transmon qubits and edges denote two-qubit
couplers capable of executing entangling operations (e.g., CNOT, CZ, ECR).

Features:
- Realistic coupler calibration error modeling (error rates in [0, 1)).
- Exact shortest path matrix precomputation (Floyd-Warshall / BFS).
- Greedy lowest-noise connected sub-region extraction (Prim-style expansion).
- Real IBM Quantum processor calibration loading (via QiskitRuntimeService).
- Synthetic topology generators (heavy-hex, grid, line) with log-normal error distributions.
"""

from __future__ import annotations
import heapq
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx
import numpy as np

TWO_Q_NAMES: Tuple[str, ...] = ("cx", "ecr", "cz")


@dataclass
class Hardware:
    """Model of a physical quantum processor with coupling constraints and error rates.

    Attributes:
        name: Hardware processor name or identifier (e.g., 'ibm_brisbane', 'heavy_hex_3x3').
        graph: NetworkX graph containing physical qubits as vertices 0..n-1 and
               edges with calibration error attributes.
        origin: Mapping of local sub-region indices back to original full-chip physical qubit IDs.
        t1: Optional dictionary mapping physical qubit index to T1 relaxation time (seconds).
        t2: Optional dictionary mapping physical qubit index to T2 dephasing time (seconds).
    """
    name: str
    graph: nx.Graph
    origin: List[int] = field(default_factory=list)
    t1: Dict[int, float] = field(default_factory=dict)
    t2: Dict[int, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        g = self.graph
        assert sorted(g.nodes) == list(range(g.number_of_nodes())), "Physical nodes must be indexed 0..n-1."
        if not self.origin:
            self.origin = list(range(g.number_of_nodes()))
        self.n: int = g.number_of_nodes()
        self.edges: List[Tuple[int, int]] = sorted(tuple(sorted(e)) for e in g.edges)  # type: ignore[misc]

        # Symmetric coupler calibration error lookup
        self._err: Dict[Tuple[int, int], float] = {}
        for u, v, d in g.edges(data=True):
            e = min(float(d.get("error", 0.01)), 0.999)
            self._err[(u, v)] = self._err[(v, u)] = e

        # Adjacency neighbor sets for O(1) connectivity queries
        self.adj: List[Set[int]] = [set(g.neighbors(i)) for i in range(self.n)]

        # Precompute all-pairs shortest path distance matrix
        lengths = dict(nx.all_pairs_shortest_path_length(g))
        self.dist: np.ndarray = np.full((self.n, self.n), 10**6, dtype=np.int64)
        for a, row in lengths.items():
            for b, d in row.items():
                self.dist[a, b] = d

    def err(self, u: int, v: int) -> float:
        """Return the two-qubit calibration error rate for physical coupler (u, v)."""
        return self._err.get((u, v), 0.01)

    def has_edge(self, u: int, v: int) -> bool:
        """Return True if a physical coupler connects qubits u and v."""
        return v in self.adj[u]

    def mean_error(self) -> float:
        """Return the mean two-qubit CNOT gate error rate across all hardware couplers."""
        return float(np.mean([self._err[e] for e in self.edges])) if self.edges else 0.0

    def best_region(self, size: int) -> "Hardware":
        """Extract a connected sub-region of `size` qubits with minimal mean calibration error.

        Executes a Prim-style greedy growth starting from each candidate vertex, selecting
        the connected subgraph that minimizes average coupler noise while favoring dense coupling.

        Args:
            size: Target number of physical qubits in the extracted region.

        Returns:
            A new Hardware instance representing the selected physical sub-region.
        """
        size = min(size, self.n)
        best, best_score = None, math.inf

        for s in range(self.n):
            chosen: Set[int] = {s}
            heap: List[Tuple[float, int]] = []
            for w in self.adj[s]:
                heapq.heappush(heap, (self.err(s, w), w))

            while len(chosen) < size and heap:
                _, w = heapq.heappop(heap)
                if w in chosen:
                    continue
                chosen.add(w)
                for x in self.adj[w]:
                    if x not in chosen:
                        heapq.heappush(heap, (self.err(w, x), x))

            if len(chosen) < size:
                continue

            induced_errs = [self.err(a, b) for a, b in self.edges if a in chosen and b in chosen]
            # Primary criterion: low calibration noise; secondary: higher connectivity
            score = float(np.mean(induced_errs)) - 1e-4 * len(induced_errs)
            if score < best_score:
                best, best_score = sorted(chosen), score

        return self.subgraph(best or list(range(size)))

    def subgraph(self, nodes: List[int]) -> "Hardware":
        """Induce a Hardware sub-region on the specified list of physical nodes.

        Relabels nodes to 0..k-1 while preserving original chip indices in `origin`.
        """
        nodes = sorted(nodes)
        relabel = {o: i for i, o in enumerate(nodes)}
        g = nx.Graph()
        g.add_nodes_from(range(len(nodes)))
        for a, b in self.edges:
            if a in relabel and b in relabel:
                g.add_edge(relabel[a], relabel[b], error=self.err(a, b))

        return Hardware(
            name=f"{self.name}[{len(nodes)}q]",
            graph=g,
            origin=[self.origin[o] for o in nodes],
            t1={relabel[o]: self.t1[o] for o in nodes if o in self.t1},
            t2={relabel[o]: self.t2[o] for o in nodes if o in self.t2},
        )


# ----------------------------------------------------------------------------
# Synthetic Topology Generators (with Realistic Calibration Noise)
# ----------------------------------------------------------------------------
def _add_noise(
    g: nx.Graph,
    rng: np.random.Generator,
    mean_err: float,
    hot_frac: float,
    hot_mult: float,
    sigma: float = 0.5,
) -> nx.Graph:
    """Inject log-normal calibration error rates and bad-coupler hotspots into a graph."""
    for u, v in g.edges:
        e = mean_err * math.exp(float(rng.normal(0, sigma)))
        if rng.random() < hot_frac:
            e *= hot_mult  # Simulate physical fabrication defect / defective coupler
        g[u][v]["error"] = float(min(e, 0.5))
    return g


def heavy_hex(
    rows: int = 2,
    cols: int = 2,
    seed: int = 0,
    mean_err: float = 0.01,
    hot_frac: float = 0.15,
    hot_mult: float = 8.0,
) -> Hardware:
    """Generate an IBM-style Heavy-Hexagonal lattice topology.

    The heavy-hex lattice is the industry-standard architecture for IBM Eagle,
    Osprey, and Heron quantum processors, consisting of a hexagonal lattice with
    every edge subdivided by an intermediate physical transmon.
    """
    base = nx.hexagonal_lattice_graph(rows, cols)
    idx = {n: i for i, n in enumerate(base.nodes)}
    g, nxt = nx.Graph(), len(idx)
    for u, v in base.edges:
        g.add_edge(idx[u], nxt)
        g.add_edge(nxt, idx[v])
        nxt += 1
    rng = np.random.default_rng(seed)
    _add_noise(g, rng, mean_err, hot_frac, hot_mult)
    return Hardware(f"heavy_hex_{rows}x{cols}", g)


def grid(
    rows: int = 4,
    cols: int = 4,
    seed: int = 0,
    mean_err: float = 0.01,
    hot_frac: float = 0.15,
    hot_mult: float = 8.0,
) -> Hardware:
    """Generate a standard 2D grid/mesh coupling topology (e.g., Google Sycamore style)."""
    g = nx.convert_node_labels_to_integers(nx.grid_2d_graph(rows, cols))
    _add_noise(g, np.random.default_rng(seed), mean_err, hot_frac, hot_mult)
    return Hardware(f"grid_{rows}x{cols}", g)


def line(
    n: int = 8,
    seed: int = 0,
    mean_err: float = 0.01,
    hot_frac: float = 0.15,
    hot_mult: float = 8.0,
) -> Hardware:
    """Generate a 1D linear chain coupling topology."""
    g = nx.path_graph(n)
    _add_noise(g, np.random.default_rng(seed), mean_err, hot_frac, hot_mult)
    return Hardware(f"line_{n}", g)


# ----------------------------------------------------------------------------
# Real IBM Quantum Calibration Ingestion
# ----------------------------------------------------------------------------
def from_backend(backend: Any, name: Optional[str] = None) -> Hardware:
    """Construct a Hardware model directly from a Qiskit BackendV2 target.

    Extracts coupler connectivity and empirical gate errors from the backend's Target.
    """
    target = backend.target
    errs: Dict[Tuple[int, int], float] = {}

    for op in target.operation_names:
        if op not in TWO_Q_NAMES:
            continue
        for qargs, props in target[op].items():
            if qargs is None or len(qargs) != 2:
                continue
            e = getattr(props, "error", None)
            e = 0.01 if e is None else float(e)
            key = tuple(sorted(qargs))  # type: ignore[assignment]
            errs[key] = min(errs.get(key, 1.0), e)

    # Some offline snapshots carry placeholder 1.0 error rates; fall back gracefully
    bad = [k for k, e in errs.items() if e >= 0.5]
    if errs and len(bad) > 0.5 * len(errs):
        import warnings
        warnings.warn(
            f"{name or backend.name}: Backend calibration data contains placeholder errors. "
            "Applying synthetic calibration noise model to real processor topology."
        )
        rng = np.random.default_rng(0)
        for k in errs:
            e = 0.01 * math.exp(float(rng.normal(0, 0.5))) * (8.0 if rng.random() < 0.15 else 1.0)
            errs[k] = min(e, 0.5)

    g = nx.Graph()
    g.add_nodes_from(range(target.num_qubits))
    for (a, b), e in errs.items():
        g.add_edge(a, b, error=e)

    t1, t2 = {}, {}
    for i in range(target.num_qubits):
        qp = target.qubit_properties[i] if target.qubit_properties else None
        if qp is not None:
            if qp.t1:
                t1[i] = qp.t1
            if qp.t2:
                t2[i] = qp.t2

    return Hardware(name or getattr(backend, "name", "backend"), g, t1=t1, t2=t2)


def load_backend(name: str) -> Hardware:
    """Load a hardware processor model by name.

    Supported options:
    - 'synthetic' or 'heavy_hex': 24-qubit heavy-hexagonal lattice.
    - 'fake_brisbane': IBM Eagle r3 (127 qubits) calibration snapshot.
    - 'fake_kyoto': IBM Eagle (127 qubits) calibration snapshot.
    - Any live IBM backend name (e.g. 'ibm_brisbane') if Qiskit account is configured.

    Args:
        name: Backend identifier string.

    Returns:
        Hardware instance.
    """
    n = name.lower()
    if n in ("synthetic", "heavy_hex"):
        return heavy_hex(3, 3)
    if n.startswith("fake_"):
        from qiskit_ibm_runtime import fake_provider as fp
        cls = "Fake" + "".join(p.capitalize() for p in n[5:].split("_"))
        return from_backend(getattr(fp, cls)(), name=n)
    from qiskit_ibm_runtime import QiskitRuntimeService
    return from_backend(QiskitRuntimeService().backend(name), name=name)
