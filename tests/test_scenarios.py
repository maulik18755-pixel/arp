"""Tests for scenario CRUD and isolation."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sample_data import build_default_scenario
from scenarios import save_scenario, load_scenario, clone_scenario, list_scenarios, delete_scenario
from solver import solve_scenario


def test_save_load_roundtrip():
    """Save a scenario, load it back, verify equality."""
    original = build_default_scenario("Roundtrip Test")
    save_scenario(original)
    loaded = load_scenario(original.id)
    
    assert loaded.name == original.name
    assert len(loaded.crudes) == len(original.crudes)
    assert loaded.crudes[0].cost_per_bbl == original.crudes[0].cost_per_bbl
    print(f"  ✅ Round-trip: saved and loaded scenario {original.id}")
    
    # Cleanup
    delete_scenario(original.id)


def test_clone_isolation():
    """Regression Test 3: Cloning + modifying doesn't mutate original."""
    original = build_default_scenario("Original")
    save_scenario(original)
    original_cost = original.crudes[0].cost_per_bbl
    
    # Clone and modify Arabian Light cost
    cloned = clone_scenario(
        original.id,
        name="Modified Clone",
        modifications={"crudes.0.cost_per_bbl": 99.0}
    )
    
    # Reload original from disk
    reloaded_original = load_scenario(original.id)
    
    assert reloaded_original.crudes[0].cost_per_bbl == original_cost, (
        f"Original mutated! Was {original_cost}, now {reloaded_original.crudes[0].cost_per_bbl}"
    )
    assert cloned.crudes[0].cost_per_bbl == 99.0
    assert cloned.id != original.id
    print(f"  ✅ Isolation: original {original.id} unchanged, clone {cloned.id} modified")
    
    # Cleanup
    delete_scenario(original.id)
    delete_scenario(cloned.id)


def test_list_scenarios():
    """List scenarios returns correct summaries."""
    s1 = build_default_scenario("List Test 1")
    s2 = build_default_scenario("List Test 2")
    save_scenario(s1)
    save_scenario(s2)
    
    summaries = list_scenarios()
    ids = [s["id"] for s in summaries]
    assert s1.id in ids
    assert s2.id in ids
    print(f"  ✅ Listed {len(summaries)} scenarios, found both test scenarios")
    
    # Cleanup
    delete_scenario(s1.id)
    delete_scenario(s2.id)


def test_solve_and_compare():
    """Solve two scenarios and compare them."""
    s1 = build_default_scenario("Compare A")
    save_scenario(s1)
    
    # Clone with higher Arabian Light cost
    s2 = clone_scenario(s1.id, "Compare B", {"crudes.0.cost_per_bbl": 60.0})
    
    # Solve both
    r1 = solve_scenario(s1)
    s1.result = r1
    save_scenario(s1)
    
    r2 = solve_scenario(s2)
    s2.result = r2
    save_scenario(s2)
    
    from scenarios import compare_scenarios
    comparison = compare_scenarios([s1.id, s2.id])
    
    assert len(comparison["scenarios"]) == 2
    assert "delta" in comparison
    assert comparison["delta"]["objective_change"] < 0, (
        "Higher crude cost should reduce margin"
    )
    print(f"  ✅ Compare: A=${r1.objective_value:,.0f}, B=${r2.objective_value:,.0f}, "
          f"delta=${comparison['delta']['objective_change']:,.0f}")
    
    # Cleanup
    delete_scenario(s1.id)
    delete_scenario(s2.id)


if __name__ == "__main__":
    print("\n🔧 Running scenario tests...\n")
    
    print("Test 1: Save/Load roundtrip")
    test_save_load_roundtrip()
    
    print("\nTest 2: Clone isolation")
    test_clone_isolation()
    
    print("\nTest 3: List scenarios")
    test_list_scenarios()
    
    print("\nTest 4: Solve and compare")
    test_solve_and_compare()
    
    print("\n✅ All scenario tests passed!\n")
