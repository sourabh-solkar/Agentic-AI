import sys
import os
from langgraph.checkpoint.memory import InMemorySaver

# 1. Calculate the absolute path of the directory one level up
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
print("parent_dir",parent_dir)

from Agent.graph.router_graph import router_graph

compiled =  router_graph.compile(checkpointer=InMemorySaver())
# Add this code block at the bottom of agent_backend.py to export a visualization diagram
try:
    with open("graph_architecture.png", "wb") as f:
        f.write(compiled.get_graph().draw_mermaid_png())
    print("🎨 Topology saved to graph_architecture.png")
except Exception:
    # Requires optional dependencies: pip install grandalf pygraphviz
    pass
