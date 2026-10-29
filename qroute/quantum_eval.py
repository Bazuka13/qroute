"""Simulated output fidelity of a routed circuit using Qiskit Aer + a calibration-derived noise model."""
from __future__ import annotations
from qiskit import QuantumCircuit, transpile
from qiskit.quantum_info import Statevector, hellinger_fidelity

from .hardware import Hardware


def noisy_fidelity(original: QuantumCircuit, routed: QuantumCircuit, l2p_final, hw: Hardware,
                   shots=8192, error_scale=1.0, seed=7) -> float:
    """Hellinger fidelity between the ideal output distribution of `original` and the noisy output
    of `routed` (physical-qubit circuit incl. SWAPs).  Each CNOT on edge (u,v) gets a 2-qubit
    depolarizing error whose average gate infidelity equals the calibrated error rate.
    Needs n_logical <= ~14 and routed region <= ~20 qubits."""
    from qiskit_aer import AerSimulator
    from qiskit_aer.noise import NoiseModel, depolarizing_error

    n_log = original.num_qubits
    ideal = Statevector(original.remove_final_measurements(inplace=False)).probabilities_dict()

    nm = NoiseModel()
    for u, v in hw.edges:
        p = min(4.0 * hw.err(u, v) * error_scale / 3.0, 15.0 / 16.0)   # avg infidelity e = 3p/4 for d=4
        err = depolarizing_error(p, 2)
        nm.add_quantum_error(err, "cx", [u, v]); nm.add_quantum_error(err, "cx", [v, u])

    qc = QuantumCircuit(hw.n, n_log)
    qc.compose(routed, inplace=True)
    for l in range(n_log):
        qc.measure(l2p_final[l], l)                      # undo final permutation by measuring right qubit
    basis = transpile(qc, basis_gates=["cx", "u"], optimization_level=0)
    sim = AerSimulator(noise_model=nm, seed_simulator=seed)
    counts = sim.run(basis, shots=shots).result().get_counts()
    return float(hellinger_fidelity(ideal, {k: v / shots for k, v in counts.items()}))
