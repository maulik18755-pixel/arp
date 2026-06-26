"""LP solver engine for refinery optimization."""

from __future__ import annotations

import logging
import time
from dataclasses import asdict

import numpy as np
from scipy.optimize import linprog

from models import Scenario, SolveResult

logger = logging.getLogger(__name__)


def solve_scenario(scenario: Scenario) -> SolveResult:
    """Solve a refinery LP for the given scenario. Returns SolveResult."""
    try:
        return _solve_scipy(scenario)
    except Exception as e:
        logger.error(f"Solver failed: {e}")
        return SolveResult(
            status="error",
            objective_value=None,
            crude_volumes={},
            product_volumes={},
            shadow_prices={},
            solver_used="scipy",
            binding_constraints=[],
            solve_time_sec=0.0,
        )


def _solve_scipy(scenario: Scenario) -> SolveResult:
    """
    Solve refinery LP using scipy.optimize.linprog.
    
    Decision variables: x[c] = barrels/day of crude c processed
    (one unit assumed for MVP — the first unit in scenario.units)
    
    Objective: maximize margin = sum(product_revenue) - sum(crude_cost) - sum(operating_cost)
    linprog minimizes, so we negate the objective.
    """
    t0 = time.time()
    
    unit = scenario.units[0]  # MVP: single unit
    crudes = scenario.crudes
    products = scenario.products
    n_crudes = len(crudes)
    
    # Validate: all crudes must have yields in the unit
    for crude in crudes:
        if crude.name not in unit.yields:
            return SolveResult(
                status="error",
                objective_value=None,
                crude_volumes={},
                product_volumes={},
                shadow_prices={},
                solver_used="scipy",
                binding_constraints=[],
                solve_time_sec=time.time() - t0,
            )
    
    # === BUILD OBJECTIVE ===
    # x[i] = bpd of crude i processed
    # margin per bbl of crude i = sum(yield[i][p] * price[p]) - cost[i] - operating_cost
    c_obj = []
    for crude in crudes:
        revenue_per_bbl = sum(
            unit.yields[crude.name].get(p.name, 0.0) * p.price_per_bbl
            for p in products
        )
        margin_per_bbl = revenue_per_bbl - crude.cost_per_bbl - unit.operating_cost_per_bbl
        c_obj.append(-margin_per_bbl)  # negate for minimization
    
    c_obj = np.array(c_obj)
    
    # === BOUNDS: 0 <= x[i] <= max_available ===
    bounds = [(0, crude.max_available_bpd) for crude in crudes]
    
    # === INEQUALITY CONSTRAINTS: A_ub @ x <= b_ub ===
    A_ub = []
    b_ub = []
    constraint_names = []
    
    # 1. Unit capacity: sum(x) <= max_capacity
    A_ub.append([1.0] * n_crudes)
    b_ub.append(unit.max_capacity_bpd)
    constraint_names.append(f"{unit.name}_capacity")
    
    # 2. Product max demand: sum(yield[c][p] * x[c]) <= max_demand[p]
    for product in products:
        row = [unit.yields[crude.name].get(product.name, 0.0) for crude in crudes]
        A_ub.append(row)
        b_ub.append(product.max_demand_bpd)
        constraint_names.append(f"{product.name}_max_demand")
    
    # 3. Product min demand: sum(yield[c][p] * x[c]) >= min_demand[p]
    #    → -sum(yield[c][p] * x[c]) <= -min_demand[p]
    for product in products:
        if product.min_demand_bpd > 0:
            row = [-unit.yields[crude.name].get(product.name, 0.0) for crude in crudes]
            A_ub.append(row)
            b_ub.append(-product.min_demand_bpd)
            constraint_names.append(f"{product.name}_min_demand")
    
    A_ub = np.array(A_ub) if A_ub else None
    b_ub = np.array(b_ub) if b_ub else None
    
    # === SOLVE ===
    result = linprog(c_obj, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs")
    
    solve_time = time.time() - t0
    
    if not result.success:
        status = "infeasible" if "infeasible" in str(result.message).lower() else "error"
        return SolveResult(
            status=status,
            objective_value=None,
            crude_volumes={c.name: 0.0 for c in crudes},
            product_volumes={p.name: 0.0 for p in products},
            shadow_prices={},
            solver_used="scipy_highs",
            binding_constraints=[],
            solve_time_sec=solve_time,
        )
    
    # === EXTRACT RESULTS ===
    x_opt = result.x
    objective = -result.fun  # un-negate
    
    crude_volumes = {crude.name: round(x_opt[i], 1) for i, crude in enumerate(crudes)}
    
    product_volumes = {}
    for product in products:
        vol = sum(
            unit.yields[crude.name].get(product.name, 0.0) * x_opt[i]
            for i, crude in enumerate(crudes)
        )
        product_volumes[product.name] = round(vol, 1)
    
    # Identify binding constraints
    binding = []
    
    # Check crude bounds
    for i, crude in enumerate(crudes):
        if abs(x_opt[i] - crude.max_available_bpd) < 1.0:
            binding.append(f"{crude.name}_availability")
        if abs(x_opt[i]) < 1.0 and crude.max_available_bpd > 0:
            binding.append(f"{crude.name}_at_zero")
    
    # Check unit capacity
    total_crude = sum(x_opt)
    if abs(total_crude - unit.max_capacity_bpd) < 1.0:
        binding.append(f"{unit.name}_capacity")
    
    # Check product demands
    for product in products:
        vol = product_volumes[product.name]
        if product.min_demand_bpd > 0 and abs(vol - product.min_demand_bpd) < 1.0:
            binding.append(f"{product.name}_min_demand")
        if abs(vol - product.max_demand_bpd) < 1.0:
            binding.append(f"{product.name}_max_demand")
    
    # Shadow prices from dual values
    shadow_prices = {}
    if hasattr(result, "ineqlin") and result.ineqlin is not None:
        duals = getattr(result.ineqlin, "marginals", None)
        if duals is not None:
            for i, name in enumerate(constraint_names):
                if i < len(duals) and abs(duals[i]) > 1e-6:
                    shadow_prices[name] = round(float(duals[i]), 4)
    
    return SolveResult(
        status="optimal",
        objective_value=round(objective, 2),
        crude_volumes=crude_volumes,
        product_volumes=product_volumes,
        shadow_prices=shadow_prices,
        solver_used="scipy_highs",
        binding_constraints=binding,
        solve_time_sec=round(solve_time, 4),
    )


def run_sensitivity(
    scenario: Scenario,
    crude_name: str,
    param: str,
    values: list[float],
) -> list[dict]:
    """
    Run the scenario across a range of parameter values.
    Returns list of {param_value, objective, status} dicts.
    """
    import copy
    results = []
    for val in values:
        s = Scenario.from_dict(scenario.to_dict())  # deep copy
        for crude in s.crudes:
            if crude.name == crude_name:
                setattr(crude, param, val)
                break
        res = solve_scenario(s)
        results.append({
            "param_value": val,
            "objective": res.objective_value,
            "status": res.status,
        })
    return results
