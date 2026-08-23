
# An async generator that pulls tokens from the agent
async def event_generator(user_input: str):
    # .astream yields events as the agent processes the request
    async for chunk in agent.astream({"input": user_input}):
        
        # Check if the chunk contains message updates (tokens)
        if "messages" in chunk:
            token = chunk["messages"][-1].content
            
            # Format as Server-Sent Events (SSE) standard
            yield f"data: {token}\n\n"





