#!/usr/bin/env python3
"""ARP — Agentic Refinery Planner: Chat-based refinery optimization."""

from __future__ import annotations

import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.spinner import Spinner
from rich.live import Live

from local_agent import LocalAgent
from learning import log_feedback

console = Console()

BANNER = """
# 🛢️ ARP — Agentic Refinery Planner

**Chat-based refinery optimization with parallel scenarios and learning**

Available crudes: Arabian Light ($48), Brent ($55), Maya ($38)
Products: Gasoline ($95), Kerosene ($85), Fuel Oil ($65), Residual ($45)

**Try:**
- "Optimize my refinery with all three crudes"
- "What if Arabian Light price goes up to $60?"
- "Compare the last two scenarios"
- "Run sensitivity analysis on Maya cost from $30 to $50"
- "What patterns do you see from past runs?"

Commands: `/scenarios` · `/clear` · `/quit`
"""


def main():
    console.print(Panel(Markdown(BANNER), border_style="blue", title="ARP v0.1"))
    
    agent = LocalAgent()
    
    console.print("[dim]Type your message or a command. Ctrl+C to exit.[/dim]\n")
    
    while True:
        try:
            user_input = console.input("[bold cyan]You:[/bold cyan] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye![/dim]")
            break
        
        if not user_input:
            continue
        
        # Handle commands
        if user_input.lower() == "/quit":
            console.print("[dim]Goodbye![/dim]")
            break
        
        if user_input.lower() == "/clear":
            agent.clear_history()
            console.print("[dim]Conversation cleared.[/dim]\n")
            continue
        
        if user_input.lower() == "/scenarios":
            from scenarios import list_scenarios
            scenarios = list_scenarios()
            if not scenarios:
                console.print("[dim]No saved scenarios yet.[/dim]\n")
            else:
                console.print(f"\n[bold]Saved Scenarios ({len(scenarios)}):[/bold]")
                for s in scenarios:
                    status_icon = "✅" if s["status"] == "optimal" else "❌" if s["status"] == "infeasible" else "⏳"
                    obj_str = f"${s['objective']:,.0f}/day" if s["objective"] else "unsolved"
                    console.print(f"  {status_icon} [{s['id']}] {s['name']} — {obj_str}")
                console.print()
            continue
        
        # Send to agent
        console.print()
        try:
            with Live(
                Spinner("dots", text="[dim]Thinking...[/dim]"),
                console=console,
                transient=True,
            ):
                response = agent.chat(user_input)
            
            console.print(Panel(
                Markdown(response),
                border_style="green",
                title="ARP",
                title_align="left",
            ))
            
            # Optional feedback prompt after solve results
            if agent.last_scenario_id and ("objective" in response.lower() or "margin" in response.lower()):
                try:
                    feedback = console.input("[dim]Feedback (Enter to skip): [/dim]").strip()
                    if feedback:
                        log_feedback(agent.last_scenario_id, feedback)
                        console.print("[dim]Feedback logged. ✓[/dim]")
                except (KeyboardInterrupt, EOFError):
                    pass
            
            console.print()
            
        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]\n")
            import traceback
            if os.environ.get("ARP_DEBUG"):
                traceback.print_exc()


if __name__ == "__main__":
    main()
