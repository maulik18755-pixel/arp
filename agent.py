"""Agent orchestrator — Claude API with tool-use for refinery planning."""

from __future__ import annotations

import json
import logging
import os

from anthropic import Anthropic

from models import Scenario
from sample_data import build_default_scenario, DEFAULT_CRUDES, DEFAULT_PRODUCTS, DEFAULT_UNITS
from scenarios import save_scenario, load_scenario, list_scenarios, clone_scenario, compare_scenarios
from solver import solve_scenario, run_sensitivity
from learning import log_run, get_insights

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are ARP (Agentic Refinery Planner), an expert refinery planning assistant.
You help engineers optimize crude oil processing, product blending, and refinery margins
through conversational LP modeling.

AVAILABLE CRUDES in the default library:
- Arabian Light: $48/bbl, API 33, Sulfur 1.8%, up to 20,000 bpd
- Brent: $55/bbl, API 38, Sulfur 0.4%, up to 15,000 bpd  
- Maya: $38/bbl, API 22, Sulfur 3.3%, up to 25,000 bpd

AVAILABLE PRODUCTS:
- Gasoline: $95/bbl (min 8,000 bpd demand)
- Kerosene: $85/bbl (min 2,000 bpd demand)
- Fuel Oil: $65/bbl (min 4,000 bpd demand)
- Residual: $45/bbl (no min demand)

CDU yields vary by crude — lighter crudes produce more gasoline, heavier crudes more fuel oil/residual.

BEHAVIOR RULES:
- Always explain what you're doing before calling a tool
- After solving, highlight: objective value ($/day), crude allocations, binding constraints,
  and the most interesting economic insight
- When asked "what if", create a modified scenario and solve both, then compare side-by-side
- Never guess property values — ask for data you don't have
- Use engineering units (bpd, $/bbl, wt%) consistently
- When a solve is infeasible, explain which constraints conflict
- Keep responses concise — engineers want numbers, not essays
- When the user first starts, offer to run a base case optimization
"""

# Tool definitions for Claude function calling
TOOLS = [
    {
        "name": "solve_refinery",
        "description": "Build and solve an LP optimization for a refinery scenario. Use the default scenario with all 3 crudes unless the user specifies otherwise. Returns optimal margin, crude allocations, product volumes, and binding constraints.",
        "input_schema": {
            "type": "object",
            "properties": {
                "scenario_name": {
                    "type": "string",
                    "description": "Name for this scenario"
                },
                "crude_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Which crudes to include (from: Arabian Light, Brent, Maya). Defaults to all 3."
                },
                "crude_cost_overrides": {
                    "type": "object",
                    "description": "Optional cost overrides, e.g. {'Arabian Light': 55.0}"
                },
                "crude_availability_overrides": {
                    "type": "object",
                    "description": "Optional availability overrides in bpd, e.g. {'Maya': 0} to exclude"
                },
            },
            "required": ["scenario_name"],
        },
    },
    {
        "name": "compare_saved_scenarios",
        "description": "Compare 2 or more previously solved scenarios side-by-side. Shows objective value, crude volumes, product volumes, binding constraints, and the delta between them.",
        "input_schema": {
            "type": "object",
            "properties": {
                "scenario_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "IDs of scenarios to compare"
                },
            },
            "required": ["scenario_ids"],
        },
    },
    {
        "name": "modify_and_solve",
        "description": "Clone an existing scenario, apply modifications, solve the new version, and return results. Use this for what-if analysis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "base_scenario_id": {
                    "type": "string",
                    "description": "ID of the scenario to clone"
                },
                "new_name": {
                    "type": "string",
                    "description": "Name for the modified scenario"
                },
                "modifications": {
                    "type": "object",
                    "description": "Modifications as dot-path keys, e.g. {'crudes.0.cost_per_bbl': 55}"
                },
            },
            "required": ["base_scenario_id", "new_name", "modifications"],
        },
    },
    {
        "name": "list_all_scenarios",
        "description": "List all saved scenarios with their status and objective values.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "run_sensitivity_analysis",
        "description": "Vary a single parameter across a range and show how the objective changes. Good for understanding price sensitivity or capacity impacts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "scenario_id": {
                    "type": "string",
                    "description": "Base scenario ID"
                },
                "crude_name": {
                    "type": "string",
                    "description": "Which crude's parameter to vary"
                },
                "parameter": {
                    "type": "string",
                    "enum": ["cost_per_bbl", "max_available_bpd"],
                    "description": "Which parameter to vary"
                },
                "min_value": {"type": "number"},
                "max_value": {"type": "number"},
                "steps": {"type": "integer", "description": "Number of steps (default 5)"},
            },
            "required": ["scenario_id", "crude_name", "parameter", "min_value", "max_value"],
        },
    },
    {
        "name": "get_learning_insights",
        "description": "Review patterns and insights from past optimization runs. Shows common binding constraints, margin trends, and user feedback patterns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "n_recent": {
                    "type": "integer",
                    "description": "How many recent runs to analyze (default 10)"
                },
            },
        },
    },
]


class Agent:
    """Agentic refinery planner powered by Claude."""
    
    def __init__(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("Set ANTHROPIC_API_KEY environment variable")
        self.client = Anthropic(api_key=api_key)
        self.messages: list[dict] = []
        self.last_scenario_id: str | None = None  # track for easy follow-ups
    
    def chat(self, user_message: str) -> str:
        """Send a message and get the agent's response, including tool use."""
        self.messages.append({"role": "user", "content": user_message})
        
        return self._run_agent_loop()
    
    def _run_agent_loop(self) -> str:
        """Run the agentic loop: call Claude, dispatch tools, repeat until text response."""
        max_iterations = 10  # safety limit
        
        for _ in range(max_iterations):
            response = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=self.messages,
            )
            
            # Collect all content blocks
            assistant_content = response.content
            self.messages.append({"role": "assistant", "content": assistant_content})
            
            # Check if there are tool uses
            tool_uses = [b for b in assistant_content if b.type == "tool_use"]
            
            if not tool_uses:
                # No tools — extract text and return
                text_parts = [b.text for b in assistant_content if hasattr(b, "text")]
                return "\n".join(text_parts)
            
            # Dispatch each tool call and collect results
            tool_results = []
            for tool_use in tool_uses:
                result = self._dispatch_tool(tool_use.name, tool_use.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": json.dumps(result, default=str),
                })
            
            self.messages.append({"role": "user", "content": tool_results})
        
        return "I hit the maximum number of tool calls. Please try a simpler request."
    
    def _dispatch_tool(self, name: str, inputs: dict) -> dict:
        """Route a tool call to the right function."""
        try:
            if name == "solve_refinery":
                return self._handle_solve(inputs)
            elif name == "compare_saved_scenarios":
                return self._handle_compare(inputs)
            elif name == "modify_and_solve":
                return self._handle_modify_and_solve(inputs)
            elif name == "list_all_scenarios":
                return {"scenarios": list_scenarios()}
            elif name == "run_sensitivity_analysis":
                return self._handle_sensitivity(inputs)
            elif name == "get_learning_insights":
                n = inputs.get("n_recent", 10)
                return {"insights": get_insights(n)}
            else:
                return {"error": f"Unknown tool: {name}"}
        except Exception as e:
            logger.exception(f"Tool {name} failed")
            return {"error": str(e)}
    
    def _handle_solve(self, inputs: dict) -> dict:
        """Build and solve a scenario from user parameters."""
        from sample_data import DEFAULT_CRUDES, DEFAULT_PRODUCTS, DEFAULT_UNITS
        import copy
        
        scenario_name = inputs.get("scenario_name", "Unnamed")
        crude_names = inputs.get("crude_names", [c.name for c in DEFAULT_CRUDES])
        cost_overrides = inputs.get("crude_cost_overrides", {})
        avail_overrides = inputs.get("crude_availability_overrides", {})
        
        # Select crudes
        crudes = []
        for c in DEFAULT_CRUDES:
            if c.name in crude_names:
                crude = copy.deepcopy(c)
                if c.name in cost_overrides:
                    crude.cost_per_bbl = cost_overrides[c.name]
                if c.name in avail_overrides:
                    crude.max_available_bpd = avail_overrides[c.name]
                crudes.append(crude)
        
        if not crudes:
            return {"error": f"No matching crudes found for {crude_names}"}
        
        # Build scenario with only relevant yields
        unit = copy.deepcopy(DEFAULT_UNITS[0])
        unit.yields = {c.name: unit.yields[c.name] for c in crudes if c.name in unit.yields}
        
        products = copy.deepcopy(DEFAULT_PRODUCTS)
        
        scenario = Scenario(name=scenario_name, crudes=crudes, products=products, units=[unit])
        
        # Solve
        result = solve_scenario(scenario)
        scenario.result = result
        save_scenario(scenario)
        self.last_scenario_id = scenario.id
        
        # Log for learning
        log_run(scenario.id, result)
        
        return {
            "scenario_id": scenario.id,
            "scenario_name": scenario_name,
            "status": result.status,
            "objective_value_per_day": result.objective_value,
            "crude_volumes_bpd": result.crude_volumes,
            "product_volumes_bpd": result.product_volumes,
            "binding_constraints": result.binding_constraints,
            "shadow_prices": result.shadow_prices,
            "solver": result.solver_used,
            "solve_time_sec": result.solve_time_sec,
        }
    
    def _handle_compare(self, inputs: dict) -> dict:
        """Compare scenarios."""
        ids = inputs.get("scenario_ids", [])
        if len(ids) < 2:
            return {"error": "Need at least 2 scenario IDs to compare"}
        return compare_scenarios(ids)
    
    def _handle_modify_and_solve(self, inputs: dict) -> dict:
        """Clone, modify, solve, return results."""
        base_id = inputs["base_scenario_id"]
        new_name = inputs["new_name"]
        modifications = inputs["modifications"]
        
        # Clone
        new_scenario = clone_scenario(base_id, new_name, modifications)
        
        # Solve
        result = solve_scenario(new_scenario)
        new_scenario.result = result
        save_scenario(new_scenario)
        self.last_scenario_id = new_scenario.id
        
        # Log
        log_run(new_scenario.id, result)
        
        return {
            "scenario_id": new_scenario.id,
            "scenario_name": new_name,
            "base_scenario_id": base_id,
            "status": result.status,
            "objective_value_per_day": result.objective_value,
            "crude_volumes_bpd": result.crude_volumes,
            "product_volumes_bpd": result.product_volumes,
            "binding_constraints": result.binding_constraints,
        }
    
    def _handle_sensitivity(self, inputs: dict) -> dict:
        """Run sensitivity analysis."""
        scenario = load_scenario(inputs["scenario_id"])
        steps = inputs.get("steps", 5)
        min_val = inputs["min_value"]
        max_val = inputs["max_value"]
        
        import numpy as np
        values = list(np.linspace(min_val, max_val, steps))
        
        results = run_sensitivity(
            scenario, 
            inputs["crude_name"], 
            inputs["parameter"], 
            values,
        )
        
        return {
            "crude": inputs["crude_name"],
            "parameter": inputs["parameter"],
            "results": results,
        }
    
    def clear_history(self):
        """Clear conversation history."""
        self.messages = []
        self.last_scenario_id = None
