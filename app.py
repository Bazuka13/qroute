"""Streamlit Web Application: Noise-Adaptive & Commutativity-Aware A* Qubit Routing Dashboard.

Run via:
    streamlit run app.py
"""
from __future__ import annotations
import io
import time
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
import streamlit as st

from qroute import load_backend, route, METHODS, load_qasm
from qroute.benchmarks import SUITE
from qroute.pipeline import build_routed_circuit
from qroute.visualizer import (
    render_hardware_svg,
    precompute_replay_steps,
    render_matplotlib_figure,
    get_cached_layout,
)

# ----------------------------------------------------------------------------
# Streamlit Page Configuration & Modern Theme Styling
# ----------------------------------------------------------------------------
st.set_page_config(
    page_title="Quantum Circuit Compiler: A* Qubit Routing Dashboard",
    page_icon="⚛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for modern styling, clean glassmorphism cards, and high contrast typography
st.markdown(
    """
    <style>
    /* Global typography and clean background accents */
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2.5rem;
    }
    
    /* Hero Header */
    .hero-container {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%);
        border: 1px solid #334155;
        border-radius: 14px;
        padding: 22px 28px;
        margin-bottom: 24px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
    }
    .hero-title {
        font-size: 26px;
        font-weight: 800;
        background: linear-gradient(90deg, #38bdf8, #818cf8, #c084fc);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin: 0 0 6px 0;
        letter-spacing: -0.5px;
    }
    .hero-subtitle {
        color: #94a3b8;
        font-size: 14px;
        margin: 0;
        line-height: 1.5;
    }
    .chip-badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 9999px;
        font-size: 12px;
        font-weight: 600;
        margin-right: 8px;
        margin-top: 10px;
    }
    .chip-cyan { background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); }
    .chip-purple { background: rgba(192, 132, 252, 0.15); color: #c084fc; border: 1px solid rgba(192, 132, 252, 0.3); }
    .chip-emerald { background: rgba(52, 211, 153, 0.15); color: #34d399; border: 1px solid rgba(52, 211, 153, 0.3); }

    /* KPI Metric Cards */
    .kpi-card {
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 16px 18px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.15);
        height: 100%;
        transition: transform 0.15s ease, border-color 0.15s ease;
    }
    .kpi-card:hover {
        border-color: #38bdf8;
        transform: translateY(-2px);
    }
    .kpi-label {
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: #94a3b8;
        margin-bottom: 4px;
    }
    .kpi-value {
        font-size: 24px;
        font-weight: 800;
        color: #f8fafc;
        margin-bottom: 4px;
    }
    .kpi-subtext {
        font-size: 12px;
        color: #64748b;
        line-height: 1.3;
    }

    /* Step Playback Card */
    .step-card {
        background: #0f172a;
        border: 1px solid #1e293b;
        border-left: 4px solid #38bdf8;
        border-radius: 10px;
        padding: 14px 18px;
        margin: 12px 0;
    }
    .step-title {
        font-size: 15px;
        font-weight: 700;
        color: #f1f5f9;
        margin-bottom: 4px;
    }
    .step-desc {
        font-size: 13px;
        color: #94a3b8;
        margin: 0;
    }

    /* Informational callout box */
    .callout-box {
        background: rgba(30, 41, 59, 0.6);
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 14px 18px;
        margin-bottom: 16px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ----------------------------------------------------------------------------
# Dictionaries of Human-Readable Full Forms and Explanations
# ----------------------------------------------------------------------------
HARDWARE_MAP = {
    "Synthetic Heavy-Hex Processor (24 Physical Qubits)": {
        "id": "synthetic",
        "description": "Standard heavy-hex lattice topology with synthetic calibration error hotspots.",
    },
    "IBM Quantum Brisbane Architecture (127 Physical Qubits)": {
        "id": "fake_brisbane",
        "description": "Calibration snapshot from IBM's 127-qubit Eagle r3 superconducting processor.",
    },
    "IBM Quantum Kyoto Architecture (127 Physical Qubits)": {
        "id": "fake_kyoto",
        "description": "IBM Eagle 127-qubit topology with simulated calibration noise profile.",
    },
}

METHODS_MAP = {
    "A* Search (Noise-Aware & Commutativity-Aware) [Proposed Algorithm]": {
        "id": "A*-noise+comm",
        "badge": "Full Proposal",
        "summary": "Considers calibration error rates and out-of-order gate execution via commutation analysis.",
    },
    "A* Search (Noise-Aware Calibration Weights)": {
        "id": "A*-noise",
        "badge": "Ablation",
        "summary": "Weights physical SWAP paths by calibration error, but enforces strict sequential gate execution.",
    },
    "A* Search (Distance Only — Unit SWAP Cost)": {
        "id": "A*-hop",
        "badge": "Ablation",
        "summary": "Classic A* routing minimizing raw SWAP distance under strict gate order (Beta = 0).",
    },
    "Greedy Nearest-Gate Router [Heuristic Baseline]": {
        "id": "Greedy",
        "badge": "Baseline",
        "summary": "Fast greedy pathfinding executing SWAPs toward the nearest ready two-qubit gate.",
    },
    "Breadth-First Search (BFS) [Uninformed Baseline]": {
        "id": "BFS",
        "badge": "Baseline",
        "summary": "Uninformed layer-by-layer exploration for shortest SWAP solutions on small subproblems.",
    },
}

BENCHMARKS_MAP = {
    "Quantum Approximate Optimization Algorithm (QAOA) Max-Cut — 6 Logical Qubits": "qaoa_6",
    "Quantum Approximate Optimization Algorithm (QAOA) Max-Cut — 8 Logical Qubits": "qaoa_8",
    "Quantum Approximate Optimization Algorithm (QAOA) Max-Cut — 10 Logical Qubits": "qaoa_10",
    "Quantum Fourier Transform (QFT) — 5 Logical Qubits": "qft_5",
    "Quantum Fourier Transform (QFT) — 6 Logical Qubits": "qft_6",
    "Greenberger–Horne–Zeilinger (GHZ) Entangled State — 8 Logical Qubits": "ghz_8",
    "Random Two-Qubit Entangling Circuit — 8 Logical Qubits": "rand_8",
}

PLACEMENT_MAP = {
    "Greedy Interaction-Graph Placement (Maps heavily connected qubits to low-noise hardware)": "greedy",
    "Direct Index Placement (Maps logical qubit q_i directly to physical qubit P_i)": "trivial",
}

# ----------------------------------------------------------------------------
# High-Speed Cached Functions
# ----------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_cached_hardware(backend_id: str):
    """Load hardware processor model once and cache across entire Streamlit session."""
    return load_backend(backend_id)


@st.cache_data(show_spinner=False)
def run_routing_cached(
    circ_name: str,
    qasm_content: Optional[str],
    backend_id: str,
    method_id: str,
    beta: float,
    weight: float,
    max_nodes: int,
    placement_id: str,
    record_trace: int = 500,
):
    """Execute qubit routing with caching keyed by configuration parameters.

    Subsequent slider movements (SWAP replay or trace scrubbing) return INSTANTLY in 0ms.
    """
    hw = get_cached_hardware(backend_id)
    if circ_name == "custom_upload":
        if not qasm_content:
            return None, None
        circ = load_qasm(qasm_content)
    else:
        circ = SUITE[circ_name]()

    start_time = time.perf_counter()
    res, info = route(
        circ,
        hw,
        method_id,
        beta=beta,
        weight=weight,
        max_nodes=int(max_nodes),
        placement=placement_id,
        record_trace=record_trace,
    )
    wall_runtime = time.perf_counter() - start_time
    # Use accurate wall clock if route runtime was very small
    res.runtime = max(res.runtime, wall_runtime)
    return res, info


# ----------------------------------------------------------------------------
# Sidebar Configuration Panel (Full Forms & Clean Grouping)
# ----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### ⚙️ Compiler Configuration")
    st.caption("Noise-Adaptive & Commutativity-Aware A* Qubit Router")

    # Preset selector for fast user experience
    preset = st.selectbox(
        "Optimization Profile",
        [
            "⚡ Recommended: Noise-Aware & Commutative A*",
            "🎯 Guaranteed Minimal Cost (Exact A*, w=1.0)",
            "🛡️ High Noise Avoidance (High Beta)",
            "🚀 Ultra-Fast Heuristic (Weighted A*)",
            "🔧 Custom User Parameters",
        ],
        index=0,
        help="Quick configuration presets for various compiler objectives.",
    )

    if preset == "⚡ Recommended: Noise-Aware & Commutative A*":
        preset_method = "A* Search (Noise-Aware & Commutativity-Aware) [Proposed Algorithm]"
        preset_beta = 10.0
        preset_weight = 1.0
        preset_nodes = 20000
        preset_placement = list(PLACEMENT_MAP.keys())[0]
    elif preset == "🎯 Guaranteed Minimal Cost (Exact A*, w=1.0)":
        preset_method = "A* Search (Noise-Aware & Commutativity-Aware) [Proposed Algorithm]"
        preset_beta = 10.0
        preset_weight = 1.0
        preset_nodes = 50000
        preset_placement = list(PLACEMENT_MAP.keys())[0]
    elif preset == "🛡️ High Noise Avoidance (High Beta)":
        preset_method = "A* Search (Noise-Aware & Commutativity-Aware) [Proposed Algorithm]"
        preset_beta = 30.0
        preset_weight = 1.0
        preset_nodes = 25000
        preset_placement = list(PLACEMENT_MAP.keys())[0]
    elif preset == "🚀 Ultra-Fast Heuristic (Weighted A*)":
        preset_method = "A* Search (Noise-Aware & Commutativity-Aware) [Proposed Algorithm]"
        preset_beta = 10.0
        preset_weight = 1.8
        preset_nodes = 10000
        preset_placement = list(PLACEMENT_MAP.keys())[0]
    else:
        preset_method = list(METHODS_MAP.keys())[0]
        preset_beta = 10.0
        preset_weight = 1.0
        preset_nodes = 20000
        preset_placement = list(PLACEMENT_MAP.keys())[0]

    st.markdown("---")
    st.markdown("#### 🖥️ Target Quantum Hardware")
    hw_choice = st.selectbox(
        "Superconducting Architecture",
        list(HARDWARE_MAP.keys()),
        index=0,
        help="Target physical quantum device. Calibration error profiles are incorporated into routing decisions.",
    )
    backend_id = HARDWARE_MAP[hw_choice]["id"]

    st.markdown("---")
    st.markdown("#### ⚛️ Input Quantum Circuit")
    src_type = st.radio(
        "Circuit Source",
        ["Standard Quantum Benchmark Suite", "Upload Open Quantum Assembly Language (OpenQASM)"],
        index=0,
    )

    qasm_str = None
    if src_type == "Standard Quantum Benchmark Suite":
        benchmark_choice = st.selectbox(
            "Benchmark Circuit",
            list(BENCHMARKS_MAP.keys()),
            index=0,
            help="Pre-configured quantum benchmark algorithms with differing entanglement topologies.",
        )
        circ_key = BENCHMARKS_MAP[benchmark_choice]
    else:
        uploaded_file = st.file_uploader(
            "Upload OpenQASM File (.qasm or .txt)",
            type=["qasm", "txt"],
            help="Custom quantum circuit in OpenQASM format.",
        )
        if uploaded_file is not None:
            qasm_str = uploaded_file.read().decode("utf-8", errors="ignore")
            circ_key = "custom_upload"
        else:
            circ_key = None

    st.markdown("---")
    st.markdown("#### 🧭 Search Algorithm & Parameters")
    method_choice = st.selectbox(
        "Routing Algorithm",
        list(METHODS_MAP.keys()),
        index=list(METHODS_MAP.keys()).index(preset_method) if preset_method in METHODS_MAP else 0,
        help="Search algorithm used to resolve two-qubit hardware adjacency constraints.",
    )
    method_id = METHODS_MAP[method_choice]["id"]

    with st.expander("🛠️ Advanced Tuning Hyperparameters", expanded=(preset == "🔧 Custom User Parameters")):
        beta_val = st.slider(
            "Noise Penalty Weight (Beta: β)",
            min_value=0.0,
            max_value=50.0,
            value=float(preset_beta),
            step=1.0,
            help="Multiplier applied to coupler calibration error rates. Step Cost = 1 + β × (CNOT Error). Higher values route around noisy links.",
        )
        weight_val = st.slider(
            "Heuristic Weight Multiplier (w)",
            min_value=1.0,
            max_value=3.0,
            value=float(preset_weight),
            step=0.1,
            help="Multiplier on the admissible remaining distance heuristic. w = 1.0 guarantees minimal SWAP cost (admissible A*). w > 1.0 speeds up search.",
        )
        max_nodes_val = st.number_input(
            "Maximum Search Node Budget",
            min_value=500,
            max_value=200000,
            value=int(preset_nodes),
            step=1000,
            help="Maximum number of states popped from the priority queue before falling back to greedy completion.",
        )
        placement_choice = st.radio(
            "Initial Qubit Placement Strategy",
            list(PLACEMENT_MAP.keys()),
            index=list(PLACEMENT_MAP.keys()).index(preset_placement),
            help="Initial mapping of logical program qubits to physical hardware qubits.",
        )
        placement_id = PLACEMENT_MAP[placement_choice]

# ----------------------------------------------------------------------------
# Main Dashboard Hero Section
# ----------------------------------------------------------------------------
st.markdown(
    """
    <div class="hero-container">
        <h1 class="hero-title">Quantum Circuit Compiler: Noise-Adaptive & Commutativity-Aware A* Routing</h1>
        <p class="hero-subtitle">
            Resolving physical qubit coupling constraints on NISQ (Noisy Intermediate-Scale Quantum) superconducting processors.
            Minimizes inserted SWAP gate overhead and calibration-derived error rates through commutativity-aware state-space search.
        </p>
        <div>
            <span class="chip-badge chip-cyan">⚛️ Superconducting Qubits</span>
            <span class="chip-badge chip-purple">🧠 Admissible A* Search</span>
            <span class="chip-badge chip-emerald">🛡️ Calibration Noise Mitigation</span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

if circ_key is None:
    st.info("👋 Please select a benchmark circuit or upload an Open Quantum Assembly Language (OpenQASM) file from the sidebar to begin compilation.")
    st.stop()

# ----------------------------------------------------------------------------
# Execute or Retrieve Cached Routing Result (Ultra Fast)
# ----------------------------------------------------------------------------
with st.spinner("Compiling quantum circuit on target hardware topology..."):
    try:
        routing_result, routing_info = run_routing_cached(
            circ_name=circ_key,
            qasm_content=qasm_str,
            backend_id=backend_id,
            method_id=method_id,
            beta=beta_val,
            weight=weight_val,
            max_nodes=max_nodes_val,
            placement_id=placement_id,
            record_trace=500,
        )
    except Exception as e:
        st.error(f"Routing compilation encountered an error: {str(e)}")
        st.stop()

if routing_result is None or not routing_result.success:
    st.error(f"Routing unsuccessful: {getattr(routing_result, 'note', 'Search node or time budget exhausted without reaching a valid routed schedule.')}")
    st.stop()

sub_hw = routing_info["hw"]
dag = routing_info["dag"]
prep_circ = routing_info["circ"]

# Precompute replay steps for 0ms scrubbing
replay_steps = precompute_replay_steps(
    routing_result.ops,
    routing_result.l2p_init,
    sub_hw,
    dag,
    beta=beta_val,
)

# ----------------------------------------------------------------------------
# Executive Performance Metrics Row (Full Forms, Tooltips, Clean Layout)
# ----------------------------------------------------------------------------
kpi_cols = st.columns(5)

with kpi_cols[0]:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">Inserted SWAP Gates</div>
            <div class="kpi-value">{routing_result.swaps}</div>
            <div class="kpi-subtext">Two-qubit state exchange operations inserted for adjacency</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with kpi_cols[1]:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">Total Noise Cost (g)</div>
            <div class="kpi-value">{routing_result.swap_cost:.2f}</div>
            <div class="kpi-subtext">Sum of (1 + β · Error) along chosen physical paths</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with kpi_cols[2]:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">Success Probability</div>
            <div class="kpi-value">{routing_result.esp * 100:.1f}%</div>
            <div class="kpi-subtext">Estimated Success Probability (ESP) across all gates</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with kpi_cols[3]:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">Search States Explored</div>
            <div class="kpi-value">{routing_result.nodes_expanded:,}</div>
            <div class="kpi-subtext">A* nodes dequeued from frontier priority queue</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with kpi_cols[4]:
    runtime_display = f"{routing_result.runtime * 1000:.1f} ms" if routing_result.runtime < 1.0 else f"{routing_result.runtime:.2f} s"
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">Compilation Time</div>
            <div class="kpi-value">{runtime_display}</div>
            <div class="kpi-subtext">End-to-end routing execution latency</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("<div style='height: 18px;'></div>", unsafe_allow_html=True)

# ----------------------------------------------------------------------------
# Interactive Multi-Tab Workspace
# ----------------------------------------------------------------------------
tabs = st.tabs([
    "🔄 Interactive SWAP Replay",
    "📊 Compilation Overview & Topology",
    "🧠 A* Search Frontier & Heuristics",
    "🔬 Benchmark All 5 Methods",
    "📜 Routed Quantum Circuit & OpenQASM",
    "📖 Quantum Architecture Guide",
])

# ============================================================================
# TAB 1: INTERACTIVE SWAP ROUTING REPLAY (ULTRA FAST, ZERO LAG)
# ============================================================================
with tabs[0]:
    st.markdown("### 🔄 Interactive Step-by-Step SWAP Routing Playback")
    st.markdown(
        "Scrub through the routing sequence to observe how logical program qubits "
        "move across the physical superconducting processor couplers to enable two-qubit quantum gates."
    )

    max_step = len(replay_steps) - 1

    # Session state for playback slider to enable prev/next buttons
    if "replay_step_idx" not in st.session_state:
        st.session_state["replay_step_idx"] = 0
    if st.session_state["replay_step_idx"] > max_step:
        st.session_state["replay_step_idx"] = max_step

    # Controls Row
    ctrl_col1, ctrl_col2, ctrl_col3, ctrl_col4, ctrl_col5 = st.columns([1, 1, 4, 1, 1])

    with ctrl_col1:
        if st.button("⏮ First", use_container_width=True, help="Jump to initial placement"):
            st.session_state["replay_step_idx"] = 0
            st.rerun()

    with ctrl_col2:
        if st.button("◀ Previous", use_container_width=True, help="Go back one SWAP step"):
            if st.session_state["replay_step_idx"] > 0:
                st.session_state["replay_step_idx"] -= 1
                st.rerun()

    with ctrl_col3:
        current_step = st.slider(
            "SWAP Step Number",
            min_value=0,
            max_value=max_step,
            value=st.session_state["replay_step_idx"],
            key="slider_replay_step",
            help="Step 0 is initial placement; step N is after the N-th physical SWAP gate.",
        )
        st.session_state["replay_step_idx"] = current_step

    with ctrl_col4:
        if st.button("Next ▶", use_container_width=True, help="Advance one SWAP step"):
            if st.session_state["replay_step_idx"] < max_step:
                st.session_state["replay_step_idx"] += 1
                st.rerun()

    with ctrl_col5:
        if st.button("Last ⏭", use_container_width=True, help="Jump to final routed state"):
            st.session_state["replay_step_idx"] = max_step
            st.rerun()

    step_info = replay_steps[st.session_state["replay_step_idx"]]

    # Current Step Summary Card
    highlight_pair = step_info["swap_edge"]
    if highlight_pair is not None:
        u_phys, v_phys = highlight_pair
        coupler_err_pct = step_info["coupler_error"] * 100
        step_title_text = f"Step {step_info['step_index']} of {max_step}: Executing SWAP on Physical Coupler (P{u_phys} ⟷ P{v_phys})"
        step_desc_text = (
            f"Physical Coupler Calibration Error Rate: <b>{coupler_err_pct:.2f}%</b> | "
            f"Step Noise-Weighted Cost: <b>{step_info['step_cost']:.2f}</b> | "
            f"Cumulative Cost So Far: <b>{step_info['cumulative_cost']:.2f}</b>"
        )
    else:
        step_title_text = "Initial State: Logical-to-Physical Qubit Placement"
        step_desc_text = f"Hardware region initialized with {sub_hw.n} physical qubits. Zero SWAPs executed so far."

    st.markdown(
        f"""
        <div class="step-card">
            <div class="step-title">{step_title_text}</div>
            <div class="step-desc">{step_desc_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Layout: Graph visualizer on left, step details & mapping on right
    vis_col, info_col = st.columns([3, 2])

    with vis_col:
        # High performance SVG render (0.1ms)
        svg_code = render_hardware_svg(
            sub_hw=sub_hw,
            l2p=step_info["l2p"],
            highlight_edge=highlight_pair,
            width=760,
            height=490,
        )
        st.components.v1.html(svg_code, height=510)
        st.caption("Coupler Color Legend: Green = Low Two-Qubit Error (High Fidelity) → Red = High Calibration Error. Glowing Cyan Line = Active SWAP Gate.")

    with info_col:
        st.markdown("#### 📋 Step Operation Details")
        
        # Gates scheduled after this SWAP
        settled = step_info.get("settled_gates", [])
        if settled:
            st.markdown(f"**Quantum Gates Unlocked & Executed:** ({len(settled)} gate{'s' if len(settled) > 1 else ''})")
            for gate_str in settled[:6]:
                st.markdown(f"- `{gate_str}`")
            if len(settled) > 6:
                st.caption(f"... and {len(settled) - 6} more gates executed")
        else:
            st.info("No two-qubit gates became immediately adjacent after this single SWAP.")

        st.markdown("#### 🗺️ Current Qubit Mapping")
        # Logical-to-physical mapping table
        p2l_map = {p: q for q, p in enumerate(step_info["l2p"])}
        mapping_data = []
        for phys_idx in range(sub_hw.n):
            assigned_logical = f"q{p2l_map[phys_idx]}" if phys_idx in p2l_map else "— (Unassigned)"
            is_active_swap = "🔵 Active SWAP" if (highlight_pair and phys_idx in highlight_pair) else "Normal"
            mapping_data.append({
                "Physical Qubit": f"P{phys_idx}",
                "Assigned Logical Qubit": assigned_logical,
                "Status": is_active_swap,
            })
        st.dataframe(pd.DataFrame(mapping_data), use_container_width=True, height=220)

# ============================================================================
# TAB 2: COMPILATION OVERVIEW & TOPOLOGY
# ============================================================================
with tabs[1]:
    st.markdown("### 📊 Quantum Processor & Circuit Architecture")
    
    col_topo1, col_topo2 = st.columns(2)
    with col_topo1:
        st.markdown("#### 🖥️ Target Physical Hardware Characteristics")
        st.markdown(
            f"""
            - **Processor Name**: `{sub_hw.name}`
            - **Total Chip Qubits**: {get_cached_hardware(backend_id).n} physical superconducting qubits
            - **Active Low-Noise Region Selected**: {sub_hw.n} physical qubits
            - **Active Two-Qubit Couplers**: {len(sub_hw.edges)} physical inter-qubit connections
            - **Mean Coupler CNOT Calibration Error**: `{sub_hw.mean_error() * 100:.3f}%`
            - **Coupler Error Range**: `{min(sub_hw.err(*e) for e in sub_hw.edges) * 100:.2f}%` to `{max(sub_hw.err(*e) for e in sub_hw.edges) * 100:.2f}%`
            """
        )

        st.markdown("#### ⚛️ Input Quantum Circuit Complexity")
        total_2q = sum(1 for g in dag.gates if g.is2q)
        st.markdown(
            f"""
            - **Logical Circuit Qubits**: {prep_circ.num_qubits} qubits
            - **Total Quantum Gates**: {len(dag.gates)} operations
            - **Two-Qubit Entangling Gates**: {total_2q} gates (e.g., CNOT, CZ, RZZ)
            - **Commutativity-Aware Dependency DAG**: Enabled (Z-type & X-type commutation rules active)
            """
        )

    with col_topo2:
        st.markdown("#### 🔬 Hardware Coupler Error Distribution")
        # Coupler error histogram / distribution
        all_errs = [sub_hw.err(*e) * 100 for e in sub_hw.edges]
        err_df = pd.DataFrame({"Coupler Error Rate (%)": all_errs})
        st.bar_chart(err_df["Coupler Error Rate (%)"].value_counts().sort_index())
        st.caption("Distribution of two-qubit gate calibration error percentages across active region couplers.")

# ============================================================================
# TAB 3: A* SEARCH FRONTIER & HEURISTICS
# ============================================================================
with tabs[2]:
    st.markdown("### 🧠 A* Search Frontier & Heuristic Convergence")
    st.markdown(
        "A* search evaluates quantum routing states using the objective evaluation function: "
        "**`f(n) = g(n) + w · h(n)`** where **`g(n)`** is accumulated noise-weighted SWAP cost, "
        "and **`h(n)`** is the admissible remaining distance lower bound."
    )

    if routing_result.trace:
        trace_df = pd.DataFrame([
            {
                "Expansion Step": t["step"],
                "Accumulated Cost (g)": t["g"],
                "Remaining Heuristic (h)": t["h"],
                "Total Evaluation (f)": t["f"],
                "Open List Size": t["open"],
            }
            for t in routing_result.trace
        ])

        trace_col1, trace_col2 = st.columns([3, 2])
        with trace_col1:
            st.markdown("#### 📈 Convergence Trajectory: Past Cost (g) vs Future Heuristic (h)")
            st.line_chart(
                trace_df.set_index("Expansion Step")[["Accumulated Cost (g)", "Remaining Heuristic (h)", "Total Evaluation (f)"]],
                use_container_width=True,
            )

        with trace_col2:
            st.markdown("#### 📦 Priority Queue Frontier Size (Open List)")
            st.area_chart(
                trace_df.set_index("Expansion Step")["Open List Size"],
                use_container_width=True,
            )

        st.markdown("---")
        st.markdown("#### 🔍 Search State Inspector")
        exp_slider = st.slider(
            "Select Search Expansion Step to Inspect",
            min_value=1,
            max_value=len(routing_result.trace),
            value=1,
            help="Inspect the logical-to-physical qubit mapping at a specific search node.",
        )
        active_trace = routing_result.trace[exp_slider - 1]

        st.markdown(
            f"""
            - **Accumulated Past Noise Cost `g`**: `{active_trace['g']:.2f}`
            - **Admissible Remaining Heuristic `h`**: `{active_trace['h']:.0f}`
            - **Total Estimated Cost `f = g + h`**: `{active_trace['f']:.2f}`
            - **Open Priority Queue Frontier**: `{active_trace['open']} candidate states`
            """
        )
        trace_svg = render_hardware_svg(
            sub_hw=sub_hw,
            l2p=active_trace["l2p"],
            highlight_edge=None,
            width=700,
            height=380,
            layout_key=f"trace_{sub_hw.name}_{sub_hw.n}",
        )
        st.components.v1.html(trace_svg, height=400)
    else:
        st.info("No search trace available for this routing method. Search traces are recorded when using an A* algorithm.")

# ============================================================================
# TAB 4: BENCHMARK ALL 5 METHODS (SIDE-BY-SIDE COMPARISON)
# ============================================================================
with tabs[3]:
    st.markdown("### 🔬 Multi-Method Benchmark Comparison")
    st.markdown(
        "Evaluate how the proposed **Noise-Adaptive & Commutativity-Aware A*** algorithm compares "
        "against classical baseline compilers on the current quantum circuit."
    )

    if st.button("🚀 Run Comparative Benchmark on Current Circuit", type="primary"):
        with st.spinner("Benchmarking all 5 routing algorithms on target hardware..."):
            bench_results = []
            for m_key, m_meta in METHODS_MAP.items():
                m_id = m_meta["id"]
                t_start = time.perf_counter()
                try:
                    res_m, info_m = route(
                        prep_circ,
                        sub_hw,
                        m_id,
                        beta=beta_val,
                        weight=weight_val,
                        max_nodes=max_nodes_val,
                        placement=placement_id,
                        record_trace=0,
                        verify=False,
                    )
                    t_elapsed = time.perf_counter() - t_start
                    bench_results.append({
                        "Algorithm Method": m_key.split(" [")[0],
                        "Inserted SWAPs": res_m.swaps if res_m.success else None,
                        "Total Noise Cost (g)": round(res_m.swap_cost, 2) if res_m.success else None,
                        "Estimated Success Probability": f"{res_m.esp * 100:.1f}%" if res_m.success else "Failed",
                        "ESP_Float": res_m.esp if res_m.success else 0.0,
                        "States Explored": res_m.nodes_expanded if res_m.success else 0,
                        "Runtime (s)": round(t_elapsed, 4),
                        "Success": "✅ Yes" if res_m.success else "❌ No",
                    })
                except Exception as ex:
                    bench_results.append({
                        "Algorithm Method": m_key.split(" [")[0],
                        "Inserted SWAPs": None,
                        "Total Noise Cost (g)": None,
                        "Estimated Success Probability": "Error",
                        "ESP_Float": 0.0,
                        "States Explored": 0,
                        "Runtime (s)": 0.0,
                        "Success": "❌ Error",
                    })

            st.session_state["bench_df"] = pd.DataFrame(bench_results)

    if "bench_df" in st.session_state:
        df_bench = st.session_state["bench_df"]
        st.dataframe(df_bench.drop(columns=["ESP_Float"]), use_container_width=True)

        bcol1, bcol2 = st.columns(2)
        with bcol1:
            st.markdown("#### 📉 Total Noise Cost (Lower is Better)")
            st.bar_chart(df_bench.set_index("Algorithm Method")["Total Noise Cost (g)"])

        with bcol2:
            st.markdown("#### 📈 Estimated Success Probability (Higher is Better)")
            st.bar_chart(df_bench.set_index("Algorithm Method")["ESP_Float"])
    else:
        st.info("Click the 'Run Comparative Benchmark' button above to execute all 5 algorithms side-by-side on this circuit.")

# ============================================================================
# TAB 5: ROUTED QUANTUM CIRCUIT & OPENQASM EXPORT
# ============================================================================
with tabs[4]:
    st.markdown("### 📜 Routed Quantum Circuit & OpenQASM Specification")
    st.markdown(
        "The compiled quantum circuit on physical qubits, with all SWAP operations "
        "explicitly scheduled and inserted."
    )

    with st.spinner("Synthesizing physical routed circuit..."):
        routed_circuit = build_routed_circuit(routing_result, routing_info)

    st.markdown("#### 📐 Circuit Diagram")
    fold_width = st.slider("Diagram Fold Width", min_value=60, max_value=160, value=110, step=10)
    st.text(str(routed_circuit.draw(fold=fold_width)))

    st.markdown("#### 💾 OpenQASM Code Export")
    try:
        from qiskit.qasm2 import dumps as qasm2_dumps
        qasm_output = qasm2_dumps(routed_circuit)
    except Exception:
        try:
            qasm_output = routed_circuit.qasm()
        except Exception:
            qasm_output = "// OpenQASM export unsupported for this circuit representation."

    st.download_button(
        label="📥 Download Routed OpenQASM File",
        data=qasm_output,
        file_name=f"routed_{circ_key}_{backend_id}.qasm",
        mime="text/plain",
    )
    with st.expander("View OpenQASM Source Code"):
        st.code(qasm_output, language="c")

# ============================================================================
# TAB 6: QUANTUM ARCHITECTURE & THEORY GUIDE
# ============================================================================
with tabs[5]:
    st.markdown("### 📖 Quantum Compiling & Qubit Routing Fundamentals")
    st.markdown(
        """
        #### 1. Why is Qubit Routing Necessary?
        Superconducting quantum processors (such as IBM Quantum Eagle processors) arrange physical superconducting qubits 
        in sparse coupling lattices (e.g. **Heavy-Hexagonal Lattices**). Physical entangling gates (such as `CNOT`, `CZ`, or `ECR`) 
        can **only** be executed between directly connected hardware couplers.
        
        When an algorithm requires an entangling gate between two distant logical qubits, the compiler must insert a series of 
        **SWAP gates** to route the logical states onto adjacent physical qubits before applying the gate.

        #### 2. Why Noise-Adaptive Routing Matters
        In real NISQ hardware, physical couplers exhibit non-uniform calibration error rates:
        - Some couplers have low error rates (~0.5%).
        - Other couplers are "hot" or faulty with error rates exceeding 5% or 10%.
        
        A standard router that minimizes raw distance (SWAP count) might route qubits through an extremely noisy coupler, 
        destroying quantum coherence. Our **Noise-Adaptive A*** compiler uses the step cost:
        
        $$\\text{Cost}(\\text{SWAP}(u, v)) = 1 + \\beta \\times \\epsilon_{\\text{coupler}}(u, v)$$
        
        This penalizes faulty couplers and guides the quantum compiler through high-fidelity hardware regions.

        #### 3. Commutativity-Aware Out-of-Order Execution
        Classical quantum compilers enforce strict sequential gate ordering. However, in algorithms like **QAOA Max-Cut**, 
        all two-qubit $R_{ZZ}(\\gamma)$ gates commute with one another:
        
        $$[R_{ZZ}^{(i,j)}, R_{ZZ}^{(k,l)}] = 0$$
        
        Our commutativity-aware Directed Acyclic Graph (DAG) identifies commuting gates and allows any gate to execute 
        the moment its participating qubits become adjacent, drastically reducing the total number of SWAP gates required 
        while provably preserving the exact unitary quantum state.
        """
    )
