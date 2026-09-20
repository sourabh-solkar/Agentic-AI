from langgraph.graph import StateGraph, START, END, MessagesState




def supervisor_node(state:MessagesState):
    message = state["messages"][-1].content
    if "technical" in message:
        return "technical_support_node"
    elif "billing" in message:
        return "billing_support_node"
    elif "account" in message:
        return "account_support_node"
    else:
        return "general_support_node"


def routing_node(state:MessagesState):
    message = state["messages"][-1].content
    if "technical" in message:
        return "technical_support_node"
    elif "billing" in message:
        return "billing_support_node"
    elif "account" in message:
        return "account_support_node"
    else:
        return "general_support_node"

def technical_support_node(messages_state:MessagesState):
    return {"messages": [{"role": "assistant", "content": "You are a technical_support."}]}

def billing_support_node(messages_state:MessagesState):
    return {"messages": [{"role": "assistant", "content": "You are a billing_support."}]}

def account_support_node(messages_state:MessagesState):
    return {"messages": [{"role": "assistant", "content": "You are a account_support."}]}
    
def general_support_node(messages_state:MessagesState):
    return {"messages": [{"role": "assistant", "content": "You are a general_support."}]}


graph = StateGraph(MessagesState)
graph.add_node("supervisor", supervisor_node)
graph.add_node("technical_support_node", technical_support_node)
graph.add_node("billing_support_node", billing_support_node)
graph.add_node("account_support_node", account_support_node)
graph.add_node("general_support_node", general_support_node)

# add edges
graph.add_edge(START, "supervisor")
graph.add_conditional_edges("supervisor", routing_node , { "technical_support_node": "technical_support_node", "billing_support_node": "billing_support_node", "account_support_node": "account_support_node", "general_support_node": "general_support_node" })
graph.add_edge("technical_support_node", END)
graph.add_edge("billing_support_node", END)
graph.add_edge("account_support_node", END)
graph.add_edge("general_support_node", END)

compiled_graph = graph.compile()
# result = compiled_graph.invoke({"messages": [{"role": "user", "content": "I need help with my technical support."}]})
# print("result: ", result)








