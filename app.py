#!/usr/bin/env python3
"""ARP — Streamlit Web UI for Agentic Refinery Planner."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd
import json

from local_agent import LocalAgent
from sample_data import DEFAULT_CRUDES, DEFAULT_PRODUCTS, DEFAULT_UNITS, build_default_scenario
from scenarios import list_scenarios, load_scenario, save_scenario, delete_scenario
from solver import solve_scenario, run_sensitivity
from learning import log_run, log_feedback, get_insights
import copy
import numpy as np


# ── PAGE CONFIG ──────────────────────────────────────────────
st.set_page_config(
    page_title="ARP — Refinery Planner",
    page_icon="🛢️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CUSTOM CSS ───────────────────────────────────────────────
st.markdown("""
<style>
    .block-container { padding-top: 1rem; }
    .metric-card {
        background: linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%);
        border-radius: 10px;
        padding: 1.2rem;
        color: white;
        text-align: center;
        margin-bottom: 0.5rem;
    }
    .metric-card h2 { margin: 0; font-size: 1.8rem; }
    .metric-card p { margin: 0; opacity: 0.8; font-size: 0.85rem; }
    .binding-tag {
        display: inline-block;
        background: #ff6b6b;
        color: white;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.8rem;
        margin: 2px;
    }
    .optimal-tag {
        display: inline-block;
        background: #51cf66;
        color: white;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.8rem;
    }
</style>
""", unsafe_allow_html=True)


# ── SESSION STATE ────────────────────────────────────────────
if "agent" not in st.session_state:
    st.session_state.agent = LocalAgent()
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "optimizer"


# ── SIDEBAR ──────────────────────────────────────────────────
with st.sidebar:
    st.markdown("# 🛢️ ARP")
    st.markdown("**Agentic Refinery Planner**")
    st.markdown("---")

    # Crude library
    st.markdown("### Crude Library")
    for c in DEFAULT_CRUDES:
        with st.expander(f"🛢️ {c.name} — ${c.cost_per_bbl}/bbl"):
            st.markdown(f"""
            - **API Gravity:** {c.api_gravity}°
            - **Sulfur:** {c.sulfur_wt_pct}%
            - **Max Available:** {c.max_available_bpd:,.0f} bpd
            """)

    st.markdown("---")

    # Product prices
    st.markdown("### Product Prices")
    for p in DEFAULT_PRODUCTS:
        st.markdown(f"**{p.name}:** ${p.price_per_bbl}/bbl")

    st.markdown("---")

    # Saved scenarios
    st.markdown("### 📁 Saved Scenarios")
    scenarios = list_scenarios()
    if scenarios:
        for s in scenarios[-8:]:  # show last 8
            icon = "✅" if s["status"] == "optimal" else "❌" if s["status"] == "infeasible" else "⏳"
            obj_str = f"${s['objective']:,.0f}" if s["objective"] else "unsolved"
            st.markdown(f"`{s['id'][:6]}` {icon} {s['name'][:25]} — {obj_str}")
    else:
        st.caption("No scenarios yet. Run an optimization!")


# ── MAIN AREA ────────────────────────────────────────────────
st.markdown("# 🛢️ Agentic Refinery Planner")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "⚡ Optimizer", "🔄 What-If", "📈 Sensitivity", "💬 Chat", "📊 Insights", "🏗️ Architecture"
])


# ── TAB 1: OPTIMIZER ─────────────────────────────────────────
with tab1:
    st.markdown("### Configure & Optimize")

    col_config, col_results = st.columns([1, 1.5])

    with col_config:
        st.markdown("**Select Crudes:**")
        selected_crudes = []
        crude_costs = {}
        crude_avails = {}

        for c in DEFAULT_CRUDES:
            col_check, col_cost, col_avail = st.columns([1, 1, 1])
            with col_check:
                use = st.checkbox(c.name, value=True, key=f"use_{c.name}")
            with col_cost:
                cost = st.number_input(
                    "$/bbl", value=c.cost_per_bbl, step=1.0,
                    key=f"cost_{c.name}", label_visibility="collapsed"
                )
            with col_avail:
                avail = st.number_input(
                    "bpd", value=int(c.max_available_bpd), step=1000,
                    key=f"avail_{c.name}", label_visibility="collapsed"
                )
            if use:
                selected_crudes.append(c.name)
                crude_costs[c.name] = cost
                crude_avails[c.name] = avail

        st.markdown("---")
        scenario_name = st.text_input("Scenario Name", "Base Case")
        run_btn = st.button("🚀 Optimize", type="primary", use_container_width=True)

    with col_results:
        if run_btn and selected_crudes:
            # Build scenario
            crudes = []
            for c in DEFAULT_CRUDES:
                if c.name in selected_crudes:
                    crude = copy.deepcopy(c)
                    crude.cost_per_bbl = crude_costs[c.name]
                    crude.max_available_bpd = crude_avails[c.name]
                    crudes.append(crude)

            unit = copy.deepcopy(DEFAULT_UNITS[0])
            unit.yields = {c.name: unit.yields[c.name] for c in crudes if c.name in unit.yields}
            products = copy.deepcopy(DEFAULT_PRODUCTS)

            scenario = build_default_scenario(scenario_name)
            scenario.crudes = crudes
            scenario.units = [unit]
            scenario.products = products

            result = solve_scenario(scenario)
            scenario.result = result
            save_scenario(scenario)
            log_run(scenario.id, result)

            st.session_state.last_result = result
            st.session_state.last_scenario = scenario

            if result.status == "optimal":
                # Metrics row
                m1, m2, m3 = st.columns(3)
                with m1:
                    st.markdown(f"""<div class="metric-card">
                        <p>Daily Margin</p>
                        <h2>${result.objective_value:,.0f}</h2>
                    </div>""", unsafe_allow_html=True)
                with m2:
                    total_crude = sum(result.crude_volumes.values())
                    st.markdown(f"""<div class="metric-card">
                        <p>Total Throughput</p>
                        <h2>{total_crude:,.0f} bpd</h2>
                    </div>""", unsafe_allow_html=True)
                with m3:
                    st.markdown(f"""<div class="metric-card">
                        <p>Solver</p>
                        <h2>{result.solve_time_sec:.3f}s</h2>
                    </div>""", unsafe_allow_html=True)

                # Crude allocation chart
                st.markdown("**Crude Allocation**")
                crude_df = pd.DataFrame([
                    {"Crude": name, "Volume (bpd)": vol}
                    for name, vol in result.crude_volumes.items()
                ])
                st.bar_chart(crude_df.set_index("Crude"))

                # Product output chart
                st.markdown("**Product Output**")
                prod_df = pd.DataFrame([
                    {"Product": name, "Volume (bpd)": vol}
                    for name, vol in result.product_volumes.items()
                ])
                st.bar_chart(prod_df.set_index("Product"))

                # Binding constraints
                if result.binding_constraints:
                    st.markdown("**🔒 Binding Constraints**")
                    tags = " ".join(
                        f'<span class="binding-tag">{bc}</span>'
                        for bc in result.binding_constraints
                    )
                    st.markdown(tags, unsafe_allow_html=True)

                # Shadow prices
                if result.shadow_prices:
                    st.markdown("**Shadow Prices**")
                    sp_df = pd.DataFrame([
                        {"Constraint": k, "Marginal Value ($/unit)": v}
                        for k, v in result.shadow_prices.items()
                    ])
                    st.dataframe(sp_df, use_container_width=True, hide_index=True)

                st.markdown(f'<span class="optimal-tag">✅ Scenario {scenario.id} saved</span>',
                            unsafe_allow_html=True)
            else:
                st.error(f"❌ Problem is **{result.status}**. Check constraint compatibility.")

        elif run_btn:
            st.warning("Select at least one crude to optimize.")


# ── TAB 2: WHAT-IF ────────────────────────────────────────────
with tab2:
    st.markdown("### What-If Analysis")
    st.caption("Modify a parameter from the last scenario and compare results side-by-side.")

    scenarios_list = list_scenarios()
    solved_scenarios = [s for s in scenarios_list if s["status"] == "optimal"]

    if not solved_scenarios:
        st.info("Run an optimization first in the ⚡ Optimizer tab.")
    else:
        base_options = {f"{s['name']} ({s['id'][:6]})": s['id'] for s in solved_scenarios}
        base_choice = st.selectbox("Base Scenario", list(base_options.keys()))
        base_id = base_options[base_choice]
        base_scenario = load_scenario(base_id)

        st.markdown("**Modify Crude Parameters:**")

        modifications = {}
        for i, crude in enumerate(base_scenario.crudes):
            col_name, col_cost, col_avail = st.columns([1.5, 1, 1])
            with col_name:
                st.markdown(f"**{crude.name}**")
            with col_cost:
                new_cost = st.number_input(
                    f"Cost ($/bbl)", value=crude.cost_per_bbl, step=1.0,
                    key=f"wi_cost_{i}"
                )
                if new_cost != crude.cost_per_bbl:
                    modifications[f"crudes.{i}.cost_per_bbl"] = new_cost
            with col_avail:
                new_avail = st.number_input(
                    f"Avail (bpd)", value=int(crude.max_available_bpd), step=1000,
                    key=f"wi_avail_{i}"
                )
                if new_avail != crude.max_available_bpd:
                    modifications[f"crudes.{i}.max_available_bpd"] = float(new_avail)

        if st.button("🔄 Run What-If", type="primary", use_container_width=True):
            if not modifications:
                st.warning("Change at least one parameter to run a what-if.")
            else:
                from scenarios import clone_scenario, compare_scenarios

                mod_desc = ", ".join(f"{k}={v}" for k, v in modifications.items())
                new_scenario = clone_scenario(base_id, f"What-If ({mod_desc})", modifications)
                new_result = solve_scenario(new_scenario)
                new_scenario.result = new_result
                save_scenario(new_scenario)
                log_run(new_scenario.id, new_result)

                # Side-by-side comparison
                col_a, col_b = st.columns(2)

                with col_a:
                    st.markdown(f"#### 📋 Base: {base_scenario.name}")
                    if base_scenario.result:
                        st.metric("Margin", f"${base_scenario.result.objective_value:,.0f}/day")
                        for name, vol in base_scenario.result.crude_volumes.items():
                            st.markdown(f"- {name}: **{vol:,.0f}** bpd")

                with col_b:
                    st.markdown(f"#### 🔄 What-If: {new_scenario.name[:40]}")
                    if new_result.status == "optimal":
                        delta = new_result.objective_value - base_scenario.result.objective_value
                        st.metric("Margin", f"${new_result.objective_value:,.0f}/day",
                                  delta=f"${delta:+,.0f}/day")
                        for name, vol in new_result.crude_volumes.items():
                            base_vol = base_scenario.result.crude_volumes.get(name, 0)
                            diff = vol - base_vol
                            arrow = "🔺" if diff > 0 else "🔻" if diff < 0 else "➡️"
                            st.markdown(f"- {name}: **{vol:,.0f}** bpd {arrow} ({diff:+,.0f})")
                    else:
                        st.error(f"Status: {new_result.status}")

                # Binding constraints comparison
                st.markdown("---")
                comp_col1, comp_col2 = st.columns(2)
                with comp_col1:
                    st.markdown("**Base Binding:**")
                    if base_scenario.result:
                        for bc in base_scenario.result.binding_constraints:
                            st.markdown(f"🔒 {bc}")
                with comp_col2:
                    st.markdown("**What-If Binding:**")
                    for bc in new_result.binding_constraints:
                        st.markdown(f"🔒 {bc}")


# ── TAB 3: SENSITIVITY ───────────────────────────────────────
with tab3:
    st.markdown("### Sensitivity Analysis")
    st.caption("See how margin changes as you vary a single parameter.")

    solved_scenarios_s = [s for s in list_scenarios() if s["status"] == "optimal"]

    if not solved_scenarios_s:
        st.info("Run an optimization first.")
    else:
        s_options = {f"{s['name']} ({s['id'][:6]})": s['id'] for s in solved_scenarios_s}
        s_choice = st.selectbox("Scenario", list(s_options.keys()), key="sens_scenario")
        s_id = s_options[s_choice]
        s_scenario = load_scenario(s_id)

        col_param, col_range = st.columns(2)
        with col_param:
            crude_name = st.selectbox("Crude", [c.name for c in s_scenario.crudes])
            param = st.selectbox("Parameter", ["cost_per_bbl", "max_available_bpd"])
        with col_range:
            current_val = next(
                (getattr(c, param) for c in s_scenario.crudes if c.name == crude_name), 50
            )
            min_val = st.number_input("Min", value=float(current_val * 0.6), step=1.0)
            max_val = st.number_input("Max", value=float(current_val * 1.4), step=1.0)

        steps = st.slider("Steps", 4, 12, 6)

        if st.button("📈 Run Sensitivity", type="primary", use_container_width=True):
            values = list(np.linspace(min_val, max_val, steps))
            results = run_sensitivity(s_scenario, crude_name, param, values)

            # Chart
            chart_df = pd.DataFrame(results)
            chart_df = chart_df[chart_df["status"] == "optimal"]
            chart_df = chart_df.rename(columns={
                "param_value": f"{crude_name} {param}",
                "objective": "Margin ($/day)"
            })

            st.line_chart(
                chart_df.set_index(f"{crude_name} {param}")["Margin ($/day)"],
            )

            # Table
            st.dataframe(
                pd.DataFrame(results).style.format({
                    "param_value": "${:,.1f}" if "cost" in param else "{:,.0f}",
                    "objective": "${:,.0f}"
                }),
                use_container_width=True,
                hide_index=True,
            )

            # Key insight
            objectives = [r["objective"] for r in results if r["objective"]]
            if len(objectives) >= 2:
                sensitivity_rate = (objectives[-1] - objectives[0]) / (values[-1] - values[0])
                st.info(f"**Sensitivity:** ${sensitivity_rate:,.0f}/day per unit change in {param}")


# ── TAB 4: CHAT ───────────────────────────────────────────────
with tab4:
    st.markdown("### 💬 Chat with ARP")
    st.caption("Natural language interface — ask anything about your refinery.")

    # Show chat history
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat input
    if prompt := st.chat_input("Ask ARP anything..."):
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            response = st.session_state.agent.chat(prompt)
            st.markdown(f"```\n{response}\n```")
            st.session_state.chat_history.append({"role": "assistant", "content": f"```\n{response}\n```"})


# ── TAB 5: INSIGHTS ──────────────────────────────────────────
with tab5:
    st.markdown("### 📊 Learning Insights")
    st.caption("Patterns discovered from past optimization runs.")

    if st.button("🔄 Refresh Insights", use_container_width=True):
        st.rerun()

    insights_text = get_insights(20)
    st.markdown(f"```\n{insights_text}\n```")

    # Scenario history table
    all_scenarios = list_scenarios()
    if all_scenarios:
        st.markdown("### Scenario History")
        hist_df = pd.DataFrame(all_scenarios)
        hist_df = hist_df[["id", "name", "status", "objective", "n_crudes", "created_at"]]
        hist_df.columns = ["ID", "Name", "Status", "Margin ($/day)", "Crudes", "Created"]
        st.dataframe(hist_df, use_container_width=True, hide_index=True)

        # Cleanup option
        if st.button("🗑️ Clear All Scenarios"):
            for s in all_scenarios:
                delete_scenario(s["id"])
            st.success("All scenarios cleared.")
            st.rerun()


# ── TAB 6: ARCHITECTURE ──────────────────────────────────────
with tab6:
    st.markdown("### 🏗️ How ARP Was Built")
    st.markdown("""
    ARP (Agentic Refinery Planner) is a chat-based, AI-agentic refinery planning tool that
    replaces static LP workflows — like those in Aspen PIMS — with conversational scenario
    exploration, parallel what-if analysis, and learning from past runs.
    """)

    st.markdown("---")

    # Architecture diagram
    st.markdown("### System Architecture")
    st.code("""
    ┌─────────────────────────────────────────────────────────┐
    │              STREAMLIT WEB UI (app.py)                   │
    │   ⚡ Optimizer │ 🔄 What-If │ 📈 Sensitivity │ 💬 Chat   │
    └────────┬──────────┬──────────────┬──────────────────────┘
             │          │              │
             ▼          ▼              ▼
    ┌─────────────────────────────────────────────────────────┐
    │            AGENT ORCHESTRATOR (local_agent.py)           │
    │   Natural language parsing → Tool dispatch → Response    │
    │   Pattern matching routes to: solve / compare / modify   │
    └────┬──────────┬──────────────┬──────────────────────────┘
         │          │              │
         ▼          ▼              ▼
    ┌─────────┐ ┌──────────┐ ┌────────────┐
    │ SOLVER  │ │ SCENARIO │ │  LEARNING  │
    │ ENGINE  │ │  STORE   │ │   LOOP     │
    │         │ │          │ │            │
    │ scipy   │ │ JSON     │ │ JSONL log  │
    │ HiGHS   │ │ files    │ │ + insight  │
    │ LP      │ │ CRUD     │ │ analysis   │
    └─────────┘ └──────────┘ └────────────┘
    """, language=None)

    st.markdown("---")

    # Component breakdown
    st.markdown("### Component Breakdown")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""
        #### Core Engine
        | File | Purpose |
        |------|---------|
        | `solver.py` | LP optimization using scipy HiGHS — builds objective function, constraints, solves in ~10ms |
        | `models.py` | Domain dataclasses: `Crude`, `Product`, `ProcessUnit`, `Scenario`, `SolveResult` |
        | `sample_data.py` | Built-in crude/product library with validated yield vectors (must sum to 1.0) |
        | `scenarios.py` | Scenario CRUD — create, clone (deep copy), modify, compare, persist as JSON |
        | `learning.py` | Append-only JSONL log of every run; surfaces patterns (binding constraints, margin trends) |
        """)

    with col2:
        st.markdown("""
        #### Interface Layer
        | File | Purpose |
        |------|---------|
        | `app.py` | Streamlit web UI — 6 tabs for optimizer, what-if, sensitivity, chat, insights, architecture |
        | `local_agent.py` | NLP command parser — routes natural language to solver tools (runs locally, no API needed) |
        | `agent.py` | Claude API agent (requires API key) — full function-calling with agentic tool-use loop |
        | `main.py` | Rich terminal chat interface — alternative to web UI |
        | `CLAUDE.md` | AI coding guard file — hard rules, data model spec, regression anchors for Claude Code |
        """)

    st.markdown("---")

    # LP Formulation
    st.markdown("### LP Formulation")
    st.markdown("""
    The optimizer solves a **Linear Program** to maximize refinery margin:
    """)

    st.latex(r"""
    \max \sum_{c \in \text{Crudes}} x_c \cdot \left(
        \sum_{p \in \text{Products}} y_{c,p} \cdot \text{price}_p
        - \text{cost}_c - \text{opex}
    \right)
    """)

    st.markdown("""
    **Subject to:**
    """)

    st.latex(r"""
    \begin{aligned}
    & x_c \leq \text{availability}_c & \forall \; c \in \text{Crudes} \\
    & \sum_c x_c \leq \text{CDU capacity} \\
    & \sum_c y_{c,p} \cdot x_c \geq \text{min\_demand}_p & \forall \; p \in \text{Products} \\
    & \sum_c y_{c,p} \cdot x_c \leq \text{max\_demand}_p & \forall \; p \in \text{Products} \\
    & x_c \geq 0 & \forall \; c
    \end{aligned}
    """)

    st.markdown("""
    Where:
    - $x_c$ = barrels/day of crude $c$ processed
    - $y_{c,p}$ = yield fraction of product $p$ from crude $c$
    - Solved using **scipy.optimize.linprog** with the HiGHS solver (interior-point/simplex)
    """)

    st.markdown("---")

    # Key design decisions
    st.markdown("### Key Design Decisions")

    st.markdown("""
    **1. Scenario Isolation (Deep Copy)**
    Every what-if analysis creates a fully independent clone via JSON serialization.
    Modifying one scenario never mutates another — critical for reliable parallel analysis.

    **2. Loud Failure Over Silent Degradation**
    If the LP is infeasible, the system says so explicitly and identifies conflicting constraints.
    It never silently drops constraints or fabricates results.

    **3. Learning Loop (Append-Only Log)**
    Every optimization run is logged to `learning_log.jsonl` with objective value, binding constraints,
    and optional user feedback. The insights engine reads this log to surface patterns like
    "Maya availability has been binding in 100% of runs" — actionable intelligence for planners.

    **4. Spec-First Development**
    The project was built using a `CLAUDE.md` guard file — a specification document with hard rules,
    data models, regression test anchors, and coding conventions — read by Claude Code before
    writing any code. This ensures consistency and prevents common failure modes.
    """)

    st.markdown("---")

    # What this replaces
    st.markdown("### What This Replaces vs. Traditional Tools")

    compare_data = {
        "Capability": [
            "Interface",
            "Scenario Analysis",
            "What-If Speed",
            "Learning from Past Runs",
            "Collaboration",
            "Cost",
            "Extensibility",
        ],
        "Aspen PIMS": [
            "Spreadsheet-style config files",
            "Single scenario, manual re-run",
            "Minutes per scenario change",
            "None — no memory between sessions",
            "License-locked, single user",
            "$50K–200K/year license",
            "Vendor-dependent customization",
        ],
        "ARP": [
            "Natural language chat + web dashboard",
            "Parallel scenarios with auto-comparison",
            "~10ms per solve, instant branching",
            "JSONL learning loop surfaces patterns",
            "Web URL, shareable, open source",
            "Free (open source, scipy solver)",
            "Python — extend with Claude Code",
        ],
    }
    st.dataframe(pd.DataFrame(compare_data), use_container_width=True, hide_index=True)

    st.markdown("---")

    # Source references
    st.markdown("### 📚 Source References & Acknowledgments")

    st.markdown("""
    **Open-Source Foundation:**
    - [ND-Pyomo-Cookbook: Gasoline Blending](https://jckantor.github.io/ND-Pyomo-Cookbook/notebooks/02.05-Gasoline-Blending.html)
      — Jeff Kantor, Notre Dame. The standard open-source reference for refinery LP formulations
      in Python. ARP's solver architecture and constraint linearization approach are derived from
      these examples.
    - [scipy.optimize.linprog (HiGHS)](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linprog.html)
      — High-performance LP solver used as the backend engine.

    **Refinery Economics & LP Modeling Theory:**
    - Gary, Handwerk & Kaiser — *Petroleum Refining: Technology and Economics* (5th Ed.)
      — Refining economics, yield structures, and margin analysis fundamentals.
    - Liu, Chang & Pashikanti — *Petroleum Refinery Process Modeling* — LP and yield vector
      modeling approaches for CDU and downstream units.
    - Williams — *Model Building in Mathematical Programming* (5th Ed.) — General LP/MIP
      formulation patterns used in the constraint design.

    **Pooling & Advanced Optimization (Future Phases):**
    - Haverly (1978) — Original pooling problem formulation for refinery blending with
      nonlinear property specifications.
    - Misener & Floudas (2009) — Global optimization approaches for pooling problems.
    - Neiro & Pinto (2004) — Integrated supply chain optimization for refinery-petrochemical
      complexes.

    **Technology Stack:**
    - [Streamlit](https://streamlit.io) — Web application framework
    - [SciPy](https://scipy.org) — Scientific computing and LP solver
    - [Anthropic Claude](https://anthropic.com) — AI assistant used for code generation
      via Claude Code and the agentic chat interface
    - [Pyomo](https://www.pyomo.org) — Algebraic modeling language (available as alternate backend)

    **Development Methodology:**
    - Built using spec-first development with `CLAUDE.md` guard files
    - Regression-anchored testing (hand-verified LP optima locked before extending)
    - Incremental, tested phases — each component verified before integration
    """)

    st.markdown("---")
    st.caption("ARP v0.1 — Built with Claude Code | github.com/maulik18755-pixel/arp")
