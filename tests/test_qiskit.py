"""Unit Tests for Qiskit Transpiler Benchmarking Integration.

Verifies:
1. Qiskit SabreSwap pass generates valid routed circuits on target hardware.
2. Qiskit StochasticSwap pass runs successfully and terminates.
3. Qiskit LookaheadSwap pass runs successfully.
4. pipeline.route() supports 'Qiskit-Sabre' and 'Qiskit-Stochastic'.
5. Head-to-head comparison function returns expected keys and metrics.
"""

import pytest
from qiskit import QuantumCircuit

from qroute import (
    load_backend,
    route,
    heavy_hex,
    qiskit_route,
    stochastic_route,
    compare_with_qiskit,
    METHODS,
)
from qroute.benchmarks import qaoa_maxcut, qft, ghz


def test_qiskit_sabre_routing() -> None:
    """Verify Qiskit SabreSwap produces valid results and expected fields."""
    hw = heavy_hex(2, 2, seed=1)
    circ = qaoa_maxcut(6, seed=1)
    res, info = qiskit_route(circ, hw, routing_method="sabre", beta=10.0)

    assert res.success
    assert res.swaps >= 0
    assert res.swap_cost >= 0.0
    assert 0.0 < res.esp <= 1.0
    assert info["depth"] > 0
    assert info["routed_qc"] is not None


def test_qiskit_stochastic_routing() -> None:
    """Verify Qiskit classic StochasticSwap router completes and outputs metrics."""
    hw = heavy_hex(2, 2, seed=2)
    circ = ghz(6)
    res, _ = qiskit_route(circ, hw, routing_method="stochastic", beta=10.0)

    assert res.success
    assert res.swaps >= 0
    assert 0.0 < res.esp <= 1.0


def test_qiskit_lookahead_routing() -> None:
    """Verify Qiskit LookaheadSwap pass compiles properly."""
    hw = heavy_hex(2, 2, seed=3)
    circ = qft(5)
    res, info = qiskit_route(circ, hw, routing_method="lookahead", beta=10.0)

    assert res.success
    assert info["depth"] > 0


def test_pipeline_integration_qiskit_methods() -> None:
    """Verify pipeline.route() can execute Qiskit-Sabre and Qiskit-Stochastic."""
    hw = heavy_hex(2, 2, seed=4)
    circ = qaoa_maxcut(6, seed=1)

    for method in ("Qiskit-Sabre", "Qiskit-Stochastic"):
        assert method in METHODS
        res, info = route(circ, hw, method=method, beta=10.0)
        assert res.success
        assert res.swaps >= 0


def test_compare_with_qiskit() -> None:
    """Verify the compare_with_qiskit helper calculates comparative advantages."""
    hw = heavy_hex(2, 2, seed=5)
    circ = qaoa_maxcut(6, seed=1)
    cmp = compare_with_qiskit(circ, hw, beta=10.0)

    assert "qroute" in cmp
    assert "qiskit_sabre" in cmp
    assert "qiskit_stochastic" in cmp
    assert "esp_gain_pct" in cmp
    assert "depth_reduction_pct" in cmp
