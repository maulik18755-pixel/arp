"""Learning loop — log runs and surface insights from past optimizations."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from models import SolveResult

LOG_FILE = Path(__file__).parent / "data" / "learning_log.jsonl"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


def log_run(scenario_id: str, result: SolveResult, feedback: str | None = None) -> None:
    """Append a run record to the learning log."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scenario_id": scenario_id,
        "status": result.status,
        "objective_value": result.objective_value,
        "crude_volumes": result.crude_volumes,
        "product_volumes": result.product_volumes,
        "binding_constraints": result.binding_constraints,
        "solver": result.solver_used,
        "feedback": feedback,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def log_feedback(scenario_id: str, feedback: str) -> None:
    """Log user feedback for a scenario."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scenario_id": scenario_id,
        "type": "feedback",
        "feedback": feedback,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def get_insights(n_recent: int = 10) -> str:
    """Analyze recent runs and return human-readable insights."""
    if not LOG_FILE.exists():
        return "No runs logged yet. Solve a scenario first!"
    
    entries = []
    with open(LOG_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    
    # Filter to solve results (not feedback-only entries)
    runs = [e for e in entries if e.get("status") and e.get("type") != "feedback"]
    feedback_entries = [e for e in entries if e.get("type") == "feedback"]
    
    if not runs:
        return "No optimization runs logged yet."
    
    recent = runs[-n_recent:]
    
    insights = []
    insights.append(f"📊 Analysis of {len(recent)} recent runs (out of {len(runs)} total):")
    
    # Objective stats
    objectives = [r["objective_value"] for r in recent if r.get("objective_value")]
    if objectives:
        avg_obj = sum(objectives) / len(objectives)
        max_obj = max(objectives)
        min_obj = min(objectives)
        insights.append(f"\n💰 Margin range: ${min_obj:,.0f} — ${max_obj:,.0f}/day (avg ${avg_obj:,.0f})")
    
    # Binding constraint frequency
    all_binding = []
    for r in recent:
        all_binding.extend(r.get("binding_constraints", []))
    if all_binding:
        counter = Counter(all_binding)
        insights.append("\n🔒 Most common binding constraints:")
        for constraint, count in counter.most_common(5):
            pct = count / len(recent) * 100
            insights.append(f"  • {constraint}: {count}/{len(recent)} runs ({pct:.0f}%)")
    
    # Crude usage patterns
    crude_usage = Counter()
    crude_zero = Counter()
    for r in recent:
        for crude, vol in r.get("crude_volumes", {}).items():
            if vol > 100:
                crude_usage[crude] += 1
            else:
                crude_zero[crude] += 1
    
    if crude_usage:
        insights.append("\n🛢️ Crude usage frequency:")
        for crude, count in crude_usage.most_common():
            insights.append(f"  • {crude}: used in {count}/{len(recent)} runs")
    if crude_zero:
        for crude, count in crude_zero.most_common():
            if count > len(recent) * 0.5:
                insights.append(f"  ⚠️ {crude} was unused in {count}/{len(recent)} runs — may not be economic")
    
    # Feedback summary
    if feedback_entries:
        insights.append(f"\n💬 User feedback logged: {len(feedback_entries)} entries")
        for fb in feedback_entries[-3:]:  # show last 3
            insights.append(f"  • [{fb['scenario_id']}]: {fb['feedback']}")
    
    # Status summary
    statuses = Counter(r["status"] for r in recent)
    if statuses.get("infeasible", 0) > 0:
        insights.append(f"\n⚠️ {statuses['infeasible']} infeasible runs detected — check constraint compatibility")
    
    return "\n".join(insights)
