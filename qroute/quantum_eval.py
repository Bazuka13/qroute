"""Noisy Quantum Circuit Simulation and Output Fidelity Evaluation.

Simulates the physical execution of a routed circuit on target hardware using
Qiskit Aer with a calibration-derived depolarizing noise model.

Fidelity Metric:
Computes the classical Hellinger fidelity between the ideal probability distribution
of the original circuit and the noisy measurement distribution of the physical routed circuit:
    F_H(P, Q) = ( sum_x sqrt(P(x) * Q(x)) )^2
"""

from __future__ import annotations
from typing import Tuple

from qiskit import QuantumCircuit, transpile
from qiskit.quantum_info import Statevector, hellinger_fidelity

from .hardware import Hardware


def noisy_fidelity(
    original: QuantumCircuit,
    routed: QuantumCircuit,
    l2p_final: Tuple[int, ...],
    hw: Hardware,
    shots: int = 8192,
    error_scale: float = 1.0,
    seed: int = 7,
) -> float:
    """Calculate the Hellinger output fidelity between ideal and noisy execution.

    Constructs a localized two-qubit depolarizing noise model where the average
    gate infidelity on each hardware coupler matches its empirical calibration error rate.

    Args:
        original: Ideal abstract circuit without SWAP overhead.
        routed: Synthesized physical circuit including explicit SWAP gates.
        l2p_final: Final logical-to-physical placement mapping to un-permute measurement registers.
        hw: Target Hardware instance with coupler calibration error rates.
        shots: Number of Monte Carlo sampling measurement shots.
        error_scale: Multiplier on hardware error rates (default: 1.0).
        seed: Random seed for simulator repeatability.

    Returns:
        Hellinger fidelity in [0.0, 1.0].
    """
    from qiskit_aer import AerSimulator
    from qiskit_aer.noise import NoiseModel, depolarizing_error

    n_log = original.num_qubits
    ideal_probs = Statevector(
        original.remove_final_measurements(inplace=False)
    ).probabilities_dict()

    # Construct physical noise model
    noise_model = NoiseModel()
    for u, v in hw.edges:
        # For d=4 (two qubits), average gate infidelity e relates to depolarizing parameter p by e = 3p/4
        # Therefore: p = 4 * e / 3
        p = min(4.0 * hw.err(u, v) * error_scale / 3.0, 15.0 / 16.0)
        err = depolarizing_error(p, 2)
        noise_model.add_quantum_error(err, "cx", [u, v])
        noise_model.add_quantum_error(err, "cx", [v, u])

    # Build measurement circuit, mapping logical measurement bits to final physical qubit positions
    qc = QuantumCircuit(hw.n, n_log)
    qc.compose(routed, inplace=True)
    for l in range(n_log):
        qc.measure(l2p_final[l], l)

    basis_circ = transpile(qc, basis_gates=["cx", "u"], optimization_level=0)
    sim = AerSimulator(noise_model=noise_model, seed_simulator=seed)
    counts = sim.run(basis_circ, shots=shots).result().get_counts()

    noisy_probs = {k: v / shots for k, v in counts.items()}
    return float(hellinger_fidelity(ideal_probs, noisy_probs))
