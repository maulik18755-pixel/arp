"""Built-in sample crude/product/unit data for ARP demos."""

from models import Crude, Product, ProcessUnit, Scenario


# === CRUDE OIL LIBRARY ===

ARABIAN_LIGHT = Crude(
    name="Arabian Light",
    cost_per_bbl=48.0,
    api_gravity=33.0,
    sulfur_wt_pct=1.8,
    max_available_bpd=20_000,
)

BRENT = Crude(
    name="Brent",
    cost_per_bbl=55.0,
    api_gravity=38.0,
    sulfur_wt_pct=0.4,
    max_available_bpd=15_000,
)

MAYA = Crude(
    name="Maya",
    cost_per_bbl=38.0,
    api_gravity=22.0,
    sulfur_wt_pct=3.3,
    max_available_bpd=25_000,
)

DEFAULT_CRUDES = [ARABIAN_LIGHT, BRENT, MAYA]


# === PRODUCT LIBRARY ===

GASOLINE = Product(
    name="Gasoline",
    price_per_bbl=95.0,
    min_demand_bpd=8_000,
    max_demand_bpd=50_000,
    max_sulfur_wt_pct=0.05,  # Ultra-low sulfur gasoline
)

KEROSENE = Product(
    name="Kerosene",
    price_per_bbl=85.0,
    min_demand_bpd=2_000,
    max_demand_bpd=20_000,
)

FUEL_OIL = Product(
    name="Fuel Oil",
    price_per_bbl=65.0,
    min_demand_bpd=4_000,
    max_demand_bpd=30_000,
)

RESIDUAL = Product(
    name="Residual",
    price_per_bbl=45.0,
    min_demand_bpd=0,
    max_demand_bpd=100_000,
)

DEFAULT_PRODUCTS = [GASOLINE, KEROSENE, FUEL_OIL, RESIDUAL]


# === PROCESS UNITS ===

CDU = ProcessUnit(
    name="CDU",
    max_capacity_bpd=50_000,
    operating_cost_per_bbl=4.0,
    yields={
        "Arabian Light": {
            "Gasoline": 0.35,
            "Kerosene": 0.15,
            "Fuel Oil": 0.25,
            "Residual": 0.25,
        },
        "Brent": {
            "Gasoline": 0.45,
            "Kerosene": 0.18,
            "Fuel Oil": 0.20,
            "Residual": 0.17,
        },
        "Maya": {
            "Gasoline": 0.22,
            "Kerosene": 0.10,
            "Fuel Oil": 0.30,
            "Residual": 0.38,
        },
    },
)

DEFAULT_UNITS = [CDU]


def build_default_scenario(name: str = "Base Case") -> Scenario:
    """Create a default scenario with all sample data."""
    return Scenario(
        name=name,
        crudes=list(DEFAULT_CRUDES),
        products=list(DEFAULT_PRODUCTS),
        units=list(DEFAULT_UNITS),
    )


# Quick sanity check: yields must sum to 1.0 for each crude
def _validate_yields() -> None:
    for unit in DEFAULT_UNITS:
        for crude_name, yields in unit.yields.items():
            total = sum(yields.values())
            assert abs(total - 1.0) < 1e-6, (
                f"Yields for {crude_name} in {unit.name} sum to {total}, not 1.0"
            )

_validate_yields()
