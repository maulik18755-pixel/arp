"""Regression tests for the LP solver."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Crude, Product, ProcessUnit, Scenario
from solver import solve_scenario


def test_two_crude_cdu_optimal():
    """Regression Test 1: Two-crude CDU finds optimal solution."""
    crudes = [
        Crude("Crude1", cost_per_bbl=48, api_gravity=35, sulfur_wt_pct=1.0,
              max_available_bpd=30_000),
        Crude("Crude2", cost_per_bbl=30, api_gravity=28, sulfur_wt_pct=2.0,
              max_available_bpd=30_000),
    ]
    products = [
        Product("Gasoline", price_per_bbl=72, min_demand_bpd=0, max_demand_bpd=24_000),
        Product("Kerosene", price_per_bbl=48, min_demand_bpd=0, max_demand_bpd=2_000),
        Product("Fuel Oil", price_per_bbl=42, min_demand_bpd=0, max_demand_bpd=6_000),
        Product("Residual", price_per_bbl=20, min_demand_bpd=0, max_demand_bpd=100_000),
    ]
    unit = ProcessUnit(
        name="CDU",
        max_capacity_bpd=45_000,
        operating_cost_per_bbl=1.0,
        yields={
            "Crude1": {"Gasoline": 0.80, "Kerosene": 0.05, "Fuel Oil": 0.10, "Residual": 0.05},
            "Crude2": {"Gasoline": 0.44, "Kerosene": 0.10, "Fuel Oil": 0.36, "Residual": 0.10},
        },
    )
    scenario = Scenario(name="Test Two-Crude", crudes=crudes, products=products, units=[unit])
    result = solve_scenario(scenario)

    assert result.status == "optimal", f"Expected optimal, got {result.status}"
    assert result.objective_value is not None
    assert result.objective_value > 0, "Margin should be positive"
    # Crude1 has much higher gasoline yield and gasoline is highest price
    # so Crude1 should be used at or near its max
    assert result.crude_volumes["Crude1"] > 20_000, (
        f"Crude1 should be heavily used, got {result.crude_volumes['Crude1']}"
    )
    print(f"  ✅ Optimal margin: ${result.objective_value:,.0f}/day")
    print(f"  ✅ Crude1: {result.crude_volumes['Crude1']:,.0f} bpd, "
          f"Crude2: {result.crude_volumes['Crude2']:,.0f} bpd")
    print(f"  ✅ Binding: {result.binding_constraints}")


def test_infeasibility_detection():
    """Regression Test 2: Detect infeasible scenario."""
    crudes = [
        Crude("TinyCrude", cost_per_bbl=40, api_gravity=30, sulfur_wt_pct=1.0,
              max_available_bpd=1_000),
    ]
    products = [
        Product("Gasoline", price_per_bbl=72, min_demand_bpd=100_000),
    ]
    unit = ProcessUnit(
        name="CDU",
        max_capacity_bpd=50_000,
        operating_cost_per_bbl=1.0,
        yields={"TinyCrude": {"Gasoline": 0.50}},
    )
    scenario = Scenario(name="Test Infeasible", crudes=crudes, products=products, units=[unit])
    result = solve_scenario(scenario)

    assert result.status in ("infeasible", "error"), (
        f"Expected infeasible, got {result.status}"
    )
    print(f"  ✅ Correctly detected: {result.status}")


def test_default_scenario_solves():
    """Test that the default sample data scenario solves optimally."""
    from sample_data import build_default_scenario
    scenario = build_default_scenario()
    result = solve_scenario(scenario)

    assert result.status == "optimal", f"Default scenario should solve, got {result.status}"
    assert result.objective_value is not None
    assert result.objective_value > 0
    print(f"  ✅ Default scenario margin: ${result.objective_value:,.0f}/day")
    print(f"  ✅ Products: {result.product_volumes}")
    print(f"  ✅ Binding: {result.binding_constraints}")


if __name__ == "__main__":
    print("\n🔧 Running solver regression tests...\n")
    
    print("Test 1: Two-crude CDU optimal solution")
    test_two_crude_cdu_optimal()
    
    print("\nTest 2: Infeasibility detection")
    test_infeasibility_detection()
    
    print("\nTest 3: Default scenario solves")
    test_default_scenario_solves()
    
    print("\n✅ All solver tests passed!\n")
