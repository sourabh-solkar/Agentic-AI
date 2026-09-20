from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types  import interrupt, Command

def human_node(state:dict):
    result  =  interrupt("Please enter your name:")
    return {"name": result}

def robot_node(state:dict):
    result  =  interrupt("Please enter your name robot:")
    return {"name": result}

graph = StateGraph(dict)
graph.add_node("human", human_node)
graph.add_node("robot",robot_node)
graph.add_edge(START, "human")
graph.add_edge("human", "robot")
graph.add_edge("robot", END)


thread_config = { "configurable" : {"thread_id": "1234567890" } }



compiled_graph = graph.compile(checkpointer=InMemorySaver())

check1 =  compiled_graph.get_state(thread_config)
print("\nCheck 1 ", check1)

ineterrupt_data = compiled_graph.invoke({"data": "start me"},thread_config)
check1 =  compiled_graph.get_state(thread_config)
print("\n\n Check 2 ", check1)

result = compiled_graph.invoke(Command(resume= "Sourabh"), thread_config)

check1 =  compiled_graph.get_state(thread_config)
print("\n\n Check 3 ", check1)
# print("Result:",result)