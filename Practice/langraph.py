from langgraph.graph import StateGraph,MessagesState, START, END


def check_number(state: MessagesState):
    # print("Checking number...")
    return {"messages": [{"role": "assistant", "content": "The number is 0"}]}

def win(state: MessagesState):
    # print("Winning...")
    return {"messages": [{"role": "assistant", "content": "You won!"}]}

def lose(state: MessagesState):
    # print("Losing...")
    return {"messages": [{"role": "assistant", "content": "You lost!"}]}

def edge_condition(state: MessagesState):
    # Fix: Use .content instead of ["content"]
    last_message_content = state["messages"][-1].content
    print("The number is: ", last_message_content)
    
    # Fix: Check against the substring or the full text
    if "1234567890" in last_message_content:
        return "win"
    else:
        return "lose"


graph = StateGraph(MessagesState)
graph.add_node(check_number)
graph.add_node(win)
graph.add_node(lose)
graph.add_edge(START, "check_number")
# graph.add_edge("check_number", "win")
# graph.add_edge("check_number", "lose")
graph.add_conditional_edges("check_number", edge_condition, {"win": "win", "lose": "lose"})
graph.add_edge("win", END)

graph = graph.compile()
result = graph.invoke({"messages": [{"role": "user", "content": "What is the number?"}]})

print(result)