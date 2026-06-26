"""Domain models for ARP — Agentic Refinery Planner."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import json
from typing import Any


@dataclass
class Crude:
    """A crude oil feedstock with its properties and availability."""
    name: str
    cost_per_bbl: float        # $/bbl
    api_gravity: float         # degrees API
    sulfur_wt_pct: float       # weight percent
    max_available_bpd: float   # barrels per day
    ron: float | None = None   # Research Octane Number
    rvp: float | None = None   # Reid Vapor Pressure (psi)


@dataclass
class Product:
    """A refinery output product with specs and demand."""
    name: str
    price_per_bbl: float       # $/bbl
    min_demand_bpd: float = 0.0
    max_demand_bpd: float = 1e9
    min_api: float | None = None
    max_sulfur_wt_pct: float | None = None
    min_octane: float | None = None


@dataclass
class ProcessUnit:
    """A refinery processing unit (e.g., CDU, FCC)."""
    name: str
    max_capacity_bpd: float
    yields: dict[str, dict[str, float]]  # crude_name -> product_name -> fraction
    operating_cost_per_bbl: float = 0.0


@dataclass
class SolveResult:
    """Result from the LP solver."""
    status: str                          # optimal, infeasible, unbounded, error
    objective_value: float | None        # $/day margin
    crude_volumes: dict[str, float]      # crude_name -> bpd processed
    product_volumes: dict[str, float]    # product_name -> bpd produced
    shadow_prices: dict[str, float]      # constraint_name -> dual value
    solver_used: str                     # "pyomo_cbc" or "scipy"
    binding_constraints: list[str]       # names of binding constraints
    solve_time_sec: float = 0.0


@dataclass
class Scenario:
    """A complete refinery planning scenario."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = "Unnamed Scenario"
    crudes: list[Crude] = field(default_factory=list)
    products: list[Product] = field(default_factory=list)
    units: list[ProcessUnit] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    result: SolveResult | None = None
    user_feedback: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict."""
        return asdict(self)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Scenario:
        """Deserialize from dict."""
        crudes = [Crude(**c) for c in d.get("crudes", [])]
        products = [Product(**p) for p in d.get("products", [])]
        units = [ProcessUnit(**u) for u in d.get("units", [])]
        result = None
        if d.get("result"):
            result = SolveResult(**d["result"])
        return cls(
            id=d.get("id", uuid.uuid4().hex[:8]),
            name=d.get("name", "Unnamed"),
            crudes=crudes,
            products=products,
            units=units,
            created_at=d.get("created_at", datetime.now(timezone.utc).isoformat()),
            result=result,
            user_feedback=d.get("user_feedback"),
        )
