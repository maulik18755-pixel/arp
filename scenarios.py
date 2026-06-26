"""Scenario persistence, branching, and comparison."""

from __future__ import annotations

import copy
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from models import Scenario

SCENARIOS_DIR = Path(__file__).parent / "data" / "scenarios"
SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)


def save_scenario(scenario: Scenario) -> str:
    """Save scenario to disk. Returns the scenario ID."""
    path = SCENARIOS_DIR / f"{scenario.id}.json"
    path.write_text(scenario.to_json())
    return scenario.id


def load_scenario(scenario_id: str) -> Scenario:
    """Load a scenario from disk by ID."""
    path = SCENARIOS_DIR / f"{scenario_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Scenario {scenario_id} not found")
    data = json.loads(path.read_text())
    return Scenario.from_dict(data)


def list_scenarios() -> list[dict]:
    """List all saved scenarios with summary info."""
    summaries = []
    for path in sorted(SCENARIOS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            summary = {
                "id": data["id"],
                "name": data["name"],
                "created_at": data["created_at"],
                "n_crudes": len(data.get("crudes", [])),
                "n_products": len(data.get("products", [])),
                "status": data.get("result", {}).get("status", "unsolved") if data.get("result") else "unsolved",
                "objective": data.get("result", {}).get("objective_value") if data.get("result") else None,
            }
            summaries.append(summary)
        except Exception:
            continue
    return summaries


def clone_scenario(scenario_id: str, name: str | None = None, 
                   modifications: dict | None = None) -> Scenario:
    """
    Deep-copy a scenario, apply modifications, assign new ID.
    
    modifications is a flat dict like:
      {"crudes.0.cost_per_bbl": 55, "crudes.1.max_available_bpd": 0}
    """
    original = load_scenario(scenario_id)
    data = json.loads(original.to_json())  # true deep copy via JSON
    
    # New identity
    data["id"] = uuid.uuid4().hex[:8]
    data["name"] = name or f"{original.name} (modified)"
    data["created_at"] = datetime.now(timezone.utc).isoformat()
    data["result"] = None
    data["user_feedback"] = None
    
    # Apply modifications
    if modifications:
        for key_path, value in modifications.items():
            _set_nested(data, key_path, value)
    
    new_scenario = Scenario.from_dict(data)
    save_scenario(new_scenario)
    return new_scenario


def _set_nested(d: dict, key_path: str, value) -> None:
    """Set a value in a nested dict/list using dot notation: 'crudes.0.cost_per_bbl'."""
    keys = key_path.split(".")
    obj = d
    for key in keys[:-1]:
        if key.isdigit():
            obj = obj[int(key)]
        else:
            obj = obj[key]
    final_key = keys[-1]
    if final_key.isdigit():
        obj[int(final_key)] = value
    else:
        obj[final_key] = value


def compare_scenarios(scenario_ids: list[str]) -> dict:
    """Compare 2+ scenarios side by side."""
    scenarios = [load_scenario(sid) for sid in scenario_ids]
    
    comparison = {
        "scenarios": [],
    }
    
    for s in scenarios:
        entry = {
            "id": s.id,
            "name": s.name,
            "crudes": {c.name: c.cost_per_bbl for c in s.crudes},
        }
        if s.result:
            entry["status"] = s.result.status
            entry["objective"] = s.result.objective_value
            entry["crude_volumes"] = s.result.crude_volumes
            entry["product_volumes"] = s.result.product_volumes
            entry["binding_constraints"] = s.result.binding_constraints
        else:
            entry["status"] = "unsolved"
        comparison["scenarios"].append(entry)
    
    # Compute deltas if exactly 2 solved scenarios
    solved = [e for e in comparison["scenarios"] if e.get("objective") is not None]
    if len(solved) == 2:
        a, b = solved
        comparison["delta"] = {
            "objective_change": round(b["objective"] - a["objective"], 2),
            "objective_pct_change": round(
                (b["objective"] - a["objective"]) / abs(a["objective"]) * 100, 2
            ) if a["objective"] != 0 else None,
        }
    
    return comparison


def delete_scenario(scenario_id: str) -> bool:
    """Delete a scenario file."""
    path = SCENARIOS_DIR / f"{scenario_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False
