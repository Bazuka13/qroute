"""High-performance visualization utilities for the Qiskit Qubit Routing Dashboard.

Includes:
1. Fast, responsive vector SVG coupler graph visualizer (sub-millisecond render time).
2. Cached graph layout coordinates to eliminate repetitive spring layout re-computations.
3. Precomputed step-by-step SWAP replay sequencer for instant playback scrubbing.
4. Styled Matplotlib scientific export renderer.
"""
from __future__ import annotations
import math
from typing import Any, Dict, List, Optional, Tuple
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np

# Cache for hardware graph 2D coordinates so Kamada-Kawai / spring layout runs once per topology
_LAYOUT_CACHE: Dict[str, Dict[int, Tuple[float, float]]] = {}


def get_cached_layout(hw_graph: nx.Graph, layout_key: str = "") -> Dict[int, Tuple[float, float]]:
    """Compute and cache normalized 2D coordinates (in [0, 1] range) for hardware nodes."""
    key = layout_key or f"graph_{hw_graph.number_of_nodes()}_{hw_graph.number_of_edges()}"
    if key in _LAYOUT_CACHE:
        return _LAYOUT_CACHE[key]

    n = hw_graph.number_of_nodes()
    if n <= 1:
        _LAYOUT_CACHE[key] = {0: (0.5, 0.5)}
        return _LAYOUT_CACHE[key]

    try:
        raw_pos = nx.kamada_kawai_layout(hw_graph)
    except Exception:
        raw_pos = nx.spring_layout(hw_graph, seed=42)

    xs = [coord[0] for coord in raw_pos.values()]
    ys = [coord[1] for coord in raw_pos.values()]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)

    # Normalize to [0.08, 0.92] to preserve margins for node radius
    normalized = {}
    for node, (x, y) in raw_pos.items():
        norm_x = 0.08 + 0.84 * ((x - min_x) / span_x)
        # Invert y so top is top
        norm_y = 0.08 + 0.84 * (1.0 - ((y - min_y) / span_y))
        normalized[node] = (float(norm_x), float(norm_y))

    _LAYOUT_CACHE[key] = normalized
    return normalized


def error_to_color(err: float, min_err: float = 0.005, max_err: float = 0.06) -> str:
    """Map calibration error rate to a smooth gradient from green to yellow to red."""
    if err <= min_err:
        return "#10b981"  # Emerald green (low noise)
    if err >= max_err:
        return "#ef4444"  # Red (high noise)

    ratio = (err - min_err) / max(max_err - min_err, 1e-6)
    if ratio < 0.5:
        # Green to yellow
        t = ratio / 0.5
        r = int(16 + t * (245 - 16))
        g = int(185 + t * (158 - 185))
        b = int(129 + t * (11 - 129))
    else:
        # Yellow to red
        t = (ratio - 0.5) / 0.5
        r = int(245 + t * (239 - 245))
        g = int(158 + t * (68 - 158))
        b = int(11 + t * (68 - 11))
    return f"#{r:02x}{g:02x}{b:02x}"


def render_hardware_svg(
    sub_hw: Any,
    l2p: List[int],
    highlight_edge: Optional[Tuple[int, int]] = None,
    width: int = 740,
    height: int = 480,
    layout_key: str = "",
) -> str:
    """Generate an ultra-fast, responsive SVG visualization of the hardware topology.

    Renders physical qubits, assigned logical qubits, calibration error-weighted couplers,
    and highlights active SWAP gates with glow effects and tooltips.
    """
    pos = get_cached_layout(sub_hw.graph, layout_key or f"sub_{sub_hw.name}_{sub_hw.n}")
    p2l = {p: q for q, p in enumerate(l2p)}

    # Min and max error for color mapping
    edge_errs = [sub_hw.err(*e) for e in sub_hw.edges]
    min_err = min(edge_errs) if edge_errs else 0.005
    max_err = max(edge_errs) if edge_errs else 0.05
    if max_err == min_err:
        max_err = min_err + 0.01

    hl_set = set()
    if highlight_edge:
        hl_set.add((min(highlight_edge), max(highlight_edge)))

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'style="width: 100%; height: auto; max-height: 520px; background: #0f172a; '
        f'border-radius: 12px; border: 1px solid #1e293b; box-shadow: 0 8px 24px rgba(0,0,0,0.3); font-family: ui-sans-serif, system-ui, sans-serif;">',
        "<defs>",
        '  <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">',
        '    <feGaussianBlur stdDeviation="3.5" result="blur" />',
        '    <feComposite in="SourceGraphic" in2="blur" operator="over" />',
        "  </filter>",
        '  <filter id="nodeShadow" x="-20%" y="-20%" width="140%" height="140%">',
        '    <feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#000000" flood-opacity="0.5" />',
        "  </filter>",
        '  <linearGradient id="activeGrad" x1="0%" y1="0%" x2="100%" y2="100%">',
        '    <stop offset="0%" stop-color="#38bdf8" />',
        '    <stop offset="100%" stop-color="#0284c7" />',
        "  </linearGradient>",
        '  <linearGradient id="logicalGrad" x1="0%" y1="0%" x2="100%" y2="100%">',
        '    <stop offset="0%" stop-color="#fbbf24" />',
        '    <stop offset="100%" stop-color="#f59e0b" />',
        "  </linearGradient>",
        '  <linearGradient id="inactiveGrad" x1="0%" y1="0%" x2="100%" y2="100%">',
        '    <stop offset="0%" stop-color="#334155" />',
        '    <stop offset="100%" stop-color="#1e293b" />',
        "  </linearGradient>",
        "</defs>",
    ]

    # Render regular edges
    for u, v in sub_hw.edges:
        is_hl = (min(u, v), max(u, v)) in hl_set
        if is_hl:
            continue  # Highlighted edge will be drawn on top
        x1, y1 = pos[u][0] * width, pos[u][1] * height
        x2, y2 = pos[v][0] * width, pos[v][1] * height
        err = sub_hw.err(u, v)
        color = error_to_color(err, min_err, max_err)
        tooltip = (
            f"Physical Coupler: Qubit P{u} ⟷ Qubit P{v}&#10;"
            f"Calibration Two-Qubit Error: {err * 100:.2f}%"
        )
        svg_parts.append(
            f'  <line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{color}" stroke-width="3" stroke-linecap="round" opacity="0.85">'
            f"<title>{tooltip}</title></line>"
        )

    # Render highlighted active SWAP edge on top
    if highlight_edge:
        u, v = highlight_edge
        if u in pos and v in pos:
            x1, y1 = pos[u][0] * width, pos[u][1] * height
            x2, y2 = pos[v][0] * width, pos[v][1] * height
            err = sub_hw.err(u, v)
            hl_tooltip = (
                f"ACTIVE SWAP OPERATION: Physical Qubit P{u} ⟷ Physical Qubit P{v}&#10;"
                f"Coupler Calibration Error: {err * 100:.2f}%"
            )
            # Glowing background stroke
            svg_parts.append(
                f'  <line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                f'stroke="#00f0ff" stroke-width="9" stroke-linecap="round" opacity="0.75" filter="url(#glow)">'
                f"<title>{hl_tooltip}</title></line>"
            )
            # Crisp foreground stroke
            svg_parts.append(
                f'  <line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                f'stroke="#ffffff" stroke-width="4" stroke-linecap="round">'
                f"<title>{hl_tooltip}</title></line>"
            )

    # Render nodes
    node_radius = 21 if sub_hw.n <= 16 else 17 if sub_hw.n <= 32 else 13
    font_size_main = 13 if sub_hw.n <= 16 else 11 if sub_hw.n <= 32 else 9
    font_size_sub = 9 if sub_hw.n <= 16 else 8 if sub_hw.n <= 32 else 7

    for p in range(sub_hw.n):
        x, y = pos[p][0] * width, pos[p][1] * height
        has_logical = p in p2l
        is_swap_qubit = highlight_edge and p in highlight_edge

        if is_swap_qubit:
            fill_style = 'fill="url(#activeGrad)" stroke="#38bdf8" stroke-width="3.5" filter="url(#glow)"'
            text_color = "#ffffff"
        elif has_logical:
            fill_style = 'fill="url(#logicalGrad)" stroke="#d97706" stroke-width="2" filter="url(#nodeShadow)"'
            text_color = "#1e1b4b"
        else:
            fill_style = 'fill="url(#inactiveGrad)" stroke="#475569" stroke-width="1.5"'
            text_color = "#94a3b8"

        logical_name = f"q{p2l[p]}" if has_logical else ""
        phys_name = f"P{p}"
        tooltip = (
            f"Physical Hardware Qubit P{p}"
            + (f" &#10;Holding Program Logical Qubit: {logical_name}" if has_logical else " (Unassigned Ancilla)")
            + (f" &#10;[ACTIVE SWAP PARTICIPANT]" if is_swap_qubit else "")
        )

        svg_parts.append(f'  <g cursor="pointer"><title>{tooltip}</title>')
        svg_parts.append(f'    <circle cx="{x:.1f}" cy="{y:.1f}" r="{node_radius}" {fill_style} />')

        if has_logical:
            # Display logical qubit as primary label, physical qubit as small subscript
            svg_parts.append(
                f'    <text x="{x:.1f}" y="{y - 2:.1f}" text-anchor="middle" dominant-baseline="middle" '
                f'fill="{text_color}" font-weight="700" font-size="{font_size_main}px">{logical_name}</text>'
            )
            svg_parts.append(
                f'    <text x="{x:.1f}" y="{y + 9:.1f}" text-anchor="middle" dominant-baseline="middle" '
                f'fill="{text_color}" opacity="0.8" font-weight="500" font-size="{font_size_sub}px">{phys_name}</text>'
            )
        else:
            # Display physical qubit number
            svg_parts.append(
                f'    <text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" dominant-baseline="middle" '
                f'fill="{text_color}" font-weight="600" font-size="{font_size_main}px">{phys_name}</text>'
            )
        svg_parts.append("  </g>")

    # Legend at bottom
    svg_parts.extend([
        f'  <g transform="translate(16, {height - 24})" font-size="11px" fill="#cbd5e1">',
        '    <circle cx="6" cy="6" r="6" fill="#f59e0b" />',
        '    <text x="18" y="10">Active Logical Qubit (q_i)</text>',
        '    <circle cx="170" cy="6" r="6" fill="#334155" stroke="#475569" />',
        '    <text x="182" y="10">Physical Ancilla (P_i)</text>',
        '    <line x1="310" y1="6" x2="330" y2="6" stroke="#00f0ff" stroke-width="4" />',
        '    <text x="336" y="10">Active SWAP Coupler</text>',
        '    <line x1="480" y1="6" x2="495" y2="6" stroke="#10b981" stroke-width="3" />',
        '    <text x="500" y="10">Low Noise</text>',
        '    <line x1="565" y1="6" x2="580" y2="6" stroke="#ef4444" stroke-width="3" />',
        '    <text x="585" y="10">High Noise Coupler</text>',
        "  </g>",
        "</svg>",
    ])

    return "\n".join(svg_parts)


def precompute_replay_steps(
    ops: List[Any],
    l2p_init: List[int],
    hw: Any,
    dag: Any,
    beta: float = 10.0,
) -> List[Dict[str, Any]]:
    """Precompute all state changes across the sequence of operations.

    Returns a list of step dictionaries for 0ms slider scrubbing.
    Step 0 is initial state; step k corresponds to the k-th inserted SWAP gate.
    """
    l2p_current = list(l2p_init)
    p2l_current = {p: q for q, p in enumerate(l2p_current)}

    # Collect initial gates executed before any SWAP
    initial_gates = []
    swap_steps = []

    # Track gates scheduled
    current_settled_gates = []
    cumulative_cost = 0.0

    # Step 0: Initial Placement
    step_0 = {
        "step_index": 0,
        "swap_edge": None,
        "swap_qubits": None,
        "coupler_error": 0.0,
        "step_cost": 0.0,
        "cumulative_cost": 0.0,
        "l2p": list(l2p_current),
        "settled_gates": [],
        "description": "Initial Logical-to-Physical Qubit Placement (Prior to any SWAP gates)",
    }

    step_counter = 1
    for op in ops:
        if op[0] == "gate":
            _, gi, phys = op
            g = dag.gates[gi]
            qubit_str = ", ".join(f"q{q} (on P{p})" for q, p in zip(g.qubits, phys))
            gate_desc = f"{g.name.upper()} Gate on {qubit_str}"
            if step_counter == 1 and not swap_steps:
                step_0["settled_gates"].append(gate_desc)
            else:
                current_settled_gates.append(gate_desc)
        elif op[0] == "swap":
            _, u, v = op
            err = hw.err(u, v)
            step_cost = 1.0 + beta * err
            cumulative_cost += step_cost

            # Apply swap to mapping
            qu, qv = p2l_current.pop(u, None), p2l_current.pop(v, None)
            if qu is not None:
                p2l_current[v] = qu
                l2p_current[qu] = v
            if qv is not None:
                p2l_current[u] = qv
                l2p_current[qv] = u

            q_u_str = f"q{qu}" if qu is not None else "Empty Ancilla"
            q_v_str = f"q{qv}" if qv is not None else "Empty Ancilla"

            swap_entry = {
                "step_index": step_counter,
                "swap_edge": (u, v),
                "swap_qubits": (u, v),
                "coupler_error": err,
                "step_cost": step_cost,
                "cumulative_cost": cumulative_cost,
                "l2p": list(l2p_current),
                "settled_gates": list(current_settled_gates),
                "description": (
                    f"SWAP Operation between Physical Qubit P{u} ({q_u_str}) "
                    f"and Physical Qubit P{v} ({q_v_str})"
                ),
            }
            swap_steps.append(swap_entry)
            current_settled_gates = []
            step_counter += 1

    return [step_0] + swap_steps


def render_matplotlib_figure(
    sub_hw: Any,
    l2p: List[int],
    highlight_edge: Optional[Tuple[int, int]] = None,
    layout_key: str = "",
) -> plt.Figure:
    """Render a publication-ready Matplotlib figure reusing precalculated coordinates."""
    pos = get_cached_layout(sub_hw.graph, layout_key or f"sub_{sub_hw.name}_{sub_hw.n}")
    # Convert normalized [0, 1] pos to array for networkx
    nx_pos = {k: np.array([coord[0], coord[1]]) for k, coord in pos.items()}

    fig, ax = plt.subplots(figsize=(7, 5), facecolor="#0f172a")
    ax.set_facecolor("#0f172a")

    errs = [sub_hw.err(*e) for e in sub_hw.edges]
    nx.draw_networkx_edges(
        sub_hw.graph,
        nx_pos,
        edgelist=sub_hw.edges,
        edge_color=errs,
        edge_cmap=plt.cm.RdYlGn_r,
        width=2.5,
        ax=ax,
        alpha=0.85,
    )

    if highlight_edge:
        nx.draw_networkx_edges(
            sub_hw.graph,
            nx_pos,
            edgelist=[highlight_edge],
            edge_color="#00f0ff",
            width=6,
            ax=ax,
        )

    p2l = {p: q for q, p in enumerate(l2p)}
    colors = ["#f59e0b" if p in p2l else "#334155" for p in range(sub_hw.n)]
    edgecolors = ["#d97706" if p in p2l else "#64748b" for p in range(sub_hw.n)]

    nx.draw_networkx_nodes(
        sub_hw.graph,
        nx_pos,
        node_color=colors,
        edgecolors=edgecolors,
        linewidths=1.5,
        node_size=420,
        ax=ax,
    )

    labels = {p: (f"q{p2l[p]}" if p in p2l else f"P{p}") for p in range(sub_hw.n)}
    label_colors = {p: ("#1e1b4b" if p in p2l else "#94a3b8") for p in range(sub_hw.n)}

    for p, (x, y) in nx_pos.items():
        ax.text(
            x,
            y,
            labels[p],
            color=label_colors[p],
            fontweight="bold",
            fontsize=9,
            ha="center",
            va="center",
        )

    ax.set_axis_off()
    fig.tight_layout()
    return fig
