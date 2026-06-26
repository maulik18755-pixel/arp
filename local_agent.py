"""Local agent — no API needed. Pattern-matches user intent and dispatches tools."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from models import Scenario
from sample_data import build_default_scenario, DEFAULT_CRUDES, DEFAULT_PRODUCTS, DEFAULT_UNITS
from scenarios import save_scenario, load_scenario, list_scenarios, clone_scenario, compare_scenarios
from solver import solve_scenario, run_sensitivity
from learning import log_run, get_insights


class LocalAgent:
    """Refinery planning agent that runs entirely locally — no API calls."""

    def __init__(self):
        self.last_scenario_id: str | None = None
        self.second_last_scenario_id: str | None = None
        self.history: list[dict] = []

    def chat(self, user_message: str) -> str:
        """Process user message and return response."""
        msg = user_message.strip().lower()
        self.history.append({"role": "user", "content": user_message})

        try:
            response = self._route(msg, user_message)
        except Exception as e:
            response = f"❌ Error: {e}"

        self.history.append({"role": "assistant", "content": response})
        return response

    def _route(self, msg: str, original: str) -> str:
        """Route user message to the right handler."""

        # Optimize / solve
        if any(kw in msg for kw in ["optimize", "solve", "run base", "run a ", "plan my", "run an "]):
            return self._handle_optimize(msg, original)

        # What-if / modify
        if any(kw in msg for kw in ["what if", "what-if", "change", "increase", "decrease", "goes up", "goes down", "drops to", "rises to"]):
            return self._handle_whatif(msg, original)

        # Compare
        if "compare" in msg:
            return self._handle_compare(msg)

        # Sensitivity
        if "sensitiv" in msg:
            return self._handle_sensitivity(msg, original)

        # Patterns / insights / learning
        if any(kw in msg for kw in ["pattern", "insight", "learn", "past run", "history"]):
            return self._handle_insights()

        # List crudes / what's available
        if any(kw in msg for kw in ["available", "what crude", "list crude", "which crude", "show crude"]):
            return self._show_crudes()

        # Help
        if any(kw in msg for kw in ["help", "what can you", "how do i"]):
            return self._show_help()

        # Fallback: try to be helpful
        return self._fallback(original)

    # ── HANDLERS ──────────────────────────────────────────────

    def _handle_optimize(self, msg: str, original: str) -> str:
        """Build and solve a scenario."""
        # Figure out which crudes
        crude_names = self._extract_crude_names(msg)
        if not crude_names:
            crude_names = [c.name for c in DEFAULT_CRUDES]

        # Check for cost overrides in the message
        cost_overrides = self._extract_cost_overrides(msg, original)

        # Build scenario
        crudes = []
        for c in DEFAULT_CRUDES:
            if c.name in crude_names:
                crude = copy.deepcopy(c)
                if c.name in cost_overrides:
                    crude.cost_per_bbl = cost_overrides[c.name]
                crudes.append(crude)

        if not crudes:
            return "❌ Couldn't find matching crudes. Available: Arabian Light, Brent, Maya."

        unit = copy.deepcopy(DEFAULT_UNITS[0])
        unit.yields = {c.name: unit.yields[c.name] for c in crudes if c.name in unit.yields}
        products = copy.deepcopy(DEFAULT_PRODUCTS)

        name = f"Optimization ({', '.join(c.name for c in crudes)})"
        scenario = Scenario(name=name, crudes=crudes, products=products, units=[unit])

        result = solve_scenario(scenario)
        scenario.result = result
        save_scenario(scenario)
        log_run(scenario.id, result)

        self.second_last_scenario_id = self.last_scenario_id
        self.last_scenario_id = scenario.id

        return self._format_result(scenario, result)

    def _handle_whatif(self, msg: str, original: str) -> str:
        """Clone last scenario with modifications and compare."""
        if not self.last_scenario_id:
            return "No previous scenario to modify. Run an optimization first!"

        base = load_scenario(self.last_scenario_id)
        modifications = {}

        # Parse price changes
        # "Arabian Light price goes up to $60" / "Arabian Light at $60" / "Arabian Light to 60"
        for i, crude in enumerate(base.crudes):
            crude_lower = crude.name.lower()
            # Match patterns like "arabian light ... $60" or "arabian light ... 60"
            pattern = rf'{crude_lower}.*?(?:to|at|=|goes\s+(?:up|down)\s+to)\s*\$?(\d+\.?\d*)'
            match = re.search(pattern, msg)
            if match:
                new_cost = float(match.group(1))
                modifications[f"crudes.{i}.cost_per_bbl"] = new_cost

            # "increase arabian light by 10"
            pattern2 = rf'(?:increase|raise)\s+{crude_lower}.*?(?:by)\s*\$?(\d+\.?\d*)'
            match2 = re.search(pattern2, msg)
            if match2:
                delta = float(match2.group(1))
                modifications[f"crudes.{i}.cost_per_bbl"] = crude.cost_per_bbl + delta

            # "decrease maya by 5"
            pattern3 = rf'(?:decrease|reduce|lower|drop)\s+{crude_lower}.*?(?:by)\s*\$?(\d+\.?\d*)'
            match3 = re.search(pattern3, msg)
            if match3:
                delta = float(match3.group(1))
                modifications[f"crudes.{i}.cost_per_bbl"] = crude.cost_per_bbl - delta

            # "maya unavailable" / "remove maya" / "without maya"
            if any(kw in msg for kw in ["unavailable", "remove", "without", "exclude", "no "]):
                if crude_lower in msg:
                    modifications[f"crudes.{i}.max_available_bpd"] = 0

        if not modifications:
            return ("I couldn't parse the modification. Try something like:\n"
                    "• \"What if Arabian Light goes up to $60?\"\n"
                    "• \"What if Maya becomes unavailable?\"\n"
                    "• \"What if we increase Brent by $5?\"")

        # Clone, modify, solve
        mod_desc = ", ".join(f"{k}={v}" for k, v in modifications.items())
        new_scenario = clone_scenario(self.last_scenario_id, f"What-If ({mod_desc})", modifications)
        result = solve_scenario(new_scenario)
        new_scenario.result = result
        save_scenario(new_scenario)
        log_run(new_scenario.id, result)

        self.second_last_scenario_id = self.last_scenario_id
        self.last_scenario_id = new_scenario.id

        # Compare with base
        output = []
        output.append(f"### 📊 What-If Analysis\n")
        output.append(f"**Base:** {base.name} (ID: {base.id})")
        output.append(f"**Modified:** {new_scenario.name} (ID: {new_scenario.id})")
        output.append(f"**Changes:** {mod_desc}\n")

        output.append(self._format_result(new_scenario, result))

        # Delta
        if base.result and base.result.objective_value and result.objective_value:
            delta = result.objective_value - base.result.objective_value
            pct = delta / abs(base.result.objective_value) * 100
            direction = "📈" if delta > 0 else "📉"
            output.append(f"\n{direction} **Impact:** ${delta:+,.0f}/day ({pct:+.1f}%) vs base case")
            output.append(f"   Base margin: ${base.result.objective_value:,.0f}/day → New: ${result.objective_value:,.0f}/day")

        return "\n".join(output)

    def _handle_compare(self, msg: str) -> str:
        """Compare the last two scenarios."""
        ids_to_compare = []

        # Check for explicit IDs in message
        id_matches = re.findall(r'[a-f0-9]{8}', msg)
        if len(id_matches) >= 2:
            ids_to_compare = id_matches[:2]
        elif self.last_scenario_id and self.second_last_scenario_id:
            ids_to_compare = [self.second_last_scenario_id, self.last_scenario_id]
        else:
            return "Need at least 2 scenarios to compare. Run an optimization and a what-if first!"

        comparison = compare_scenarios(ids_to_compare)

        output = ["### ⚖️ Scenario Comparison\n"]
        output.append(f"{'':20s} | {'Scenario A':>15s} | {'Scenario B':>15s}")
        output.append(f"{'-'*20}-+-{'-'*15}-+-{'-'*15}")

        a = comparison["scenarios"][0]
        b = comparison["scenarios"][1]

        output.append(f"{'Name':20s} | {a['name'][:15]:>15s} | {b['name'][:15]:>15s}")
        obj_a = f"${a.get('objective', 0):,.0f}" if a.get("objective") else "N/A"
        obj_b = f"${b.get('objective', 0):,.0f}" if b.get("objective") else "N/A"
        output.append(f"{'Margin ($/day)':20s} | {obj_a:>15s} | {obj_b:>15s}")

        # Crude volumes
        if a.get("crude_volumes") and b.get("crude_volumes"):
            all_crudes = set(list(a["crude_volumes"].keys()) + list(b["crude_volumes"].keys()))
            for crude in sorted(all_crudes):
                va = f"{a['crude_volumes'].get(crude, 0):,.0f}"
                vb = f"{b['crude_volumes'].get(crude, 0):,.0f}"
                output.append(f"{crude + ' (bpd)':20s} | {va:>15s} | {vb:>15s}")

        # Product volumes
        if a.get("product_volumes") and b.get("product_volumes"):
            all_products = set(list(a["product_volumes"].keys()) + list(b["product_volumes"].keys()))
            for prod in sorted(all_products):
                va = f"{a['product_volumes'].get(prod, 0):,.0f}"
                vb = f"{b['product_volumes'].get(prod, 0):,.0f}"
                output.append(f"{prod + ' (bpd)':20s} | {va:>15s} | {vb:>15s}")

        if "delta" in comparison:
            d = comparison["delta"]
            output.append(f"\n**Delta:** ${d['objective_change']:+,.0f}/day")
            if d.get("objective_pct_change"):
                output.append(f"**Change:** {d['objective_pct_change']:+.1f}%")

        return "\n".join(output)

    def _handle_sensitivity(self, msg: str, original: str) -> str:
        """Run sensitivity analysis."""
        if not self.last_scenario_id:
            return "No scenario to analyze. Run an optimization first!"

        scenario = load_scenario(self.last_scenario_id)

        # Parse crude name
        crude_name = None
        for c in DEFAULT_CRUDES:
            if c.name.lower() in msg:
                crude_name = c.name
                break
        if not crude_name:
            crude_name = scenario.crudes[0].name

        # Parse range: "from $30 to $50" or "30 to 50" or "between 30 and 50"
        range_match = re.search(r'(?:from|between)\s*\$?(\d+\.?\d*)\s*(?:to|and|-)\s*\$?(\d+\.?\d*)', msg)
        if range_match:
            min_val = float(range_match.group(1))
            max_val = float(range_match.group(2))
        else:
            # Default: ±20% of current cost
            current_cost = next((c.cost_per_bbl for c in scenario.crudes if c.name == crude_name), 50)
            min_val = current_cost * 0.7
            max_val = current_cost * 1.3

        # Determine parameter
        param = "cost_per_bbl"
        if any(kw in msg for kw in ["avail", "volume", "capacity", "supply"]):
            param = "max_available_bpd"

        import numpy as np
        steps = 6
        values = list(np.linspace(min_val, max_val, steps))
        results = run_sensitivity(scenario, crude_name, param, values)

        output = [f"### 📈 Sensitivity Analysis: {crude_name} {param}\n"]
        output.append(f"{'Value':>12s} | {'Margin ($/day)':>15s} | {'Status':>10s} | {'Chart'}")
        output.append(f"{'-'*12}-+-{'-'*15}-+-{'-'*10}-+-{'-'*20}")

        max_obj = max((r["objective"] for r in results if r["objective"]), default=1)

        for r in results:
            val_str = f"${r['param_value']:>9,.1f}" if param == "cost_per_bbl" else f"{r['param_value']:>10,.0f}"
            if r["objective"] is not None:
                obj_str = f"${r['objective']:>12,.0f}"
                bar_len = int(r["objective"] / max_obj * 20) if max_obj > 0 else 0
                bar = "█" * bar_len
            else:
                obj_str = f"{'N/A':>14s}"
                bar = ""
            output.append(f"{val_str:>12s} | {obj_str:>15s} | {r['status']:>10s} | {bar}")

        # Insight
        objectives = [r["objective"] for r in results if r["objective"] is not None]
        if len(objectives) >= 2:
            change = objectives[-1] - objectives[0]
            param_change = values[-1] - values[0]
            sensitivity = change / param_change if param_change != 0 else 0
            output.append(f"\n**Sensitivity:** ${sensitivity:,.0f}/day per $1 change in {crude_name} {param}")
            output.append(f"**Total range:** ${min(objectives):,.0f} — ${max(objectives):,.0f}/day")

        return "\n".join(output)

    def _handle_insights(self) -> str:
        """Show learning insights."""
        return get_insights(10)

    def _show_crudes(self) -> str:
        """Show available crudes."""
        output = ["### 🛢️ Available Crudes\n"]
        output.append(f"{'Name':20s} | {'Cost ($/bbl)':>12s} | {'API':>6s} | {'Sulfur %':>8s} | {'Max (bpd)':>10s}")
        output.append(f"{'-'*20}-+-{'-'*12}-+-{'-'*6}-+-{'-'*8}-+-{'-'*10}")
        for c in DEFAULT_CRUDES:
            output.append(f"{c.name:20s} | ${c.cost_per_bbl:>10.0f} | {c.api_gravity:>5.1f} | {c.sulfur_wt_pct:>7.1f} | {c.max_available_bpd:>9,.0f}")
        return "\n".join(output)

    def _show_help(self) -> str:
        return """### 🛢️ ARP Commands

**Optimize:** "Optimize with all crudes" / "Optimize with Arabian Light and Brent"
**What-If:** "What if Arabian Light goes up to $60?" / "What if Maya becomes unavailable?"
**Compare:** "Compare the last two scenarios"
**Sensitivity:** "Run sensitivity on Maya cost from $30 to $50"
**Insights:** "What patterns do you see from past runs?"
**List:** "What crudes are available?"
**Scenarios:** Type `/scenarios` to see saved scenarios
"""

    def _fallback(self, original: str) -> str:
        """Try to handle unrecognized input."""
        # If it mentions a crude and a number, assume they want to optimize
        for c in DEFAULT_CRUDES:
            if c.name.lower() in original.lower():
                return self._handle_optimize(original.lower(), original)
        return ("I'm not sure what you mean. Try:\n"
                "• \"Optimize with all crudes\"\n"
                "• \"What if Arabian Light goes up to $60?\"\n"
                "• \"Run sensitivity on Maya cost from $30 to $50\"\n"
                "• \"help\" for all commands")

    # ── HELPERS ────────────────────────────────────────────────

    def _extract_crude_names(self, msg: str) -> list[str]:
        """Extract crude names mentioned in the message."""
        found = []
        for c in DEFAULT_CRUDES:
            if c.name.lower() in msg:
                found.append(c.name)
        if "all" in msg and not found:
            found = [c.name for c in DEFAULT_CRUDES]
        return found

    def _extract_cost_overrides(self, msg: str, original: str) -> dict[str, float]:
        """Extract cost overrides like 'Arabian Light at $55'."""
        overrides = {}
        for c in DEFAULT_CRUDES:
            pattern = rf'{c.name.lower()}\s*(?:at|@|=|:)\s*\$?(\d+\.?\d*)'
            match = re.search(pattern, msg)
            if match:
                overrides[c.name] = float(match.group(1))
        return overrides

    def _format_result(self, scenario: Scenario, result: Any) -> str:
        """Format a solve result into readable text."""
        output = []
        output.append(f"### 🏭 {scenario.name}")
        output.append(f"**Scenario ID:** {scenario.id}")
        output.append(f"**Status:** {result.status.upper()}")

        if result.status != "optimal":
            output.append(f"\n⚠️ Problem is **{result.status}**.")
            if result.status == "infeasible":
                output.append("Some constraints conflict — check demand vs crude availability.")
            return "\n".join(output)

        output.append(f"**Margin:** ${result.objective_value:,.0f}/day")
        output.append(f"**Solver:** {result.solver_used} ({result.solve_time_sec:.3f}s)\n")

        # Crude allocation
        output.append("**Crude Allocation:**")
        total_crude = sum(result.crude_volumes.values())
        for name, vol in result.crude_volumes.items():
            pct = vol / total_crude * 100 if total_crude > 0 else 0
            bar = "█" * int(pct / 5)
            cost = next((c.cost_per_bbl for c in scenario.crudes if c.name == name), 0)
            output.append(f"  {name:20s} {vol:>8,.0f} bpd ({pct:4.1f}%) {bar}  @${cost}/bbl")
        output.append(f"  {'TOTAL':20s} {total_crude:>8,.0f} bpd")

        # Product output
        output.append("\n**Product Output:**")
        for name, vol in result.product_volumes.items():
            price = next((p.price_per_bbl for p in scenario.products if p.name == name), 0)
            revenue = vol * price
            output.append(f"  {name:20s} {vol:>8,.0f} bpd  @${price}/bbl = ${revenue:>12,.0f}/day")

        # Binding constraints
        if result.binding_constraints:
            output.append(f"\n🔒 **Binding Constraints:** {', '.join(result.binding_constraints)}")

        # Shadow prices
        if result.shadow_prices:
            output.append("\n**Shadow Prices (marginal value of relaxing constraint):**")
            for name, val in result.shadow_prices.items():
                output.append(f"  {name}: ${val:,.2f}/unit")

        return "\n".join(output)

    def clear_history(self):
        """Clear conversation history."""
        self.history = []
        self.last_scenario_id = None
        self.second_last_scenario_id = None
