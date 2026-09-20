"""Run LangSmith evals against the compiled villa router graph."""

import asyncio
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import InMemorySaver
from langsmith import Client, aevaluate

from graph.router_graph import build_router_graph

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DATASET_NAME = "SilverDB"

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=os.getenv("GEMINI_API_KEY"),
    streaming=False,
)

general_agent = create_agent(
    model=llm,
    tools=[],
    system_prompt="You are a helpful assistant. Answer using general knowledge.",
)

graph = build_router_graph(llm, general_agent).compile(checkpointer=InMemorySaver())

EXAMPLES = [
     {
        "inputs": {"question": "Who is Elon Musk"},
        "outputs": {"intent": "general"},
    },
    {
        "inputs": {"question": "What is the capital of France?"},
        "outputs": {"intent": "general"},
    },
    {
        "inputs": {"question": "Is Villa Aurora available from June 1 to June 5?"},
        "outputs": {"intent": "availability"},
    },
    {
        "inputs": {"question": "Book Villa Aurora from June 1 to June 5 for 2 guests."},
        "outputs": {"intent": "booking"},
    },
    {
        "inputs": {"question": "What is the cancellation policy for Villa Aurora?"},
        "outputs": {"intent": "policy"},
    },
]


def ensure_dataset() -> None:
    client = Client()
    if not client.has_dataset(dataset_name=DATASET_NAME):
        dataset = client.create_dataset(
            DATASET_NAME,
            description="Router intent evals for the villa booking agent.",
        )
        print("dataset==>",dataset)
        client.create_examples(
            dataset_id=dataset.id,
            examples=EXAMPLES,
        )


async def target(inputs: dict) -> dict:
    return await graph.ainvoke(
        {
            "messages": [{"role": "user", "content": inputs["question"]}],
            "intent": "",
            "combined_context": "",
        },
        config={"configurable": {"thread_id": str(uuid.uuid4())}},
    )


def intent_correct(outputs: dict, reference_outputs: dict) -> dict:
    expected = (reference_outputs or {}).get("intent")
    actual = outputs.get("intent")
    return {
        "key": "intent_accuracy",
        "score": 1.0 if expected and actual == expected else 0.0,
        "comment": f"expected={expected} actual={actual}",
    }


def used_tools(outputs: dict) -> dict:
    messages = outputs.get("messages", [])
    hit = any(getattr(m, "tool_calls", None) for m in messages)
    return {"key": "tool_called", "score": 1.0 if hit else 0.0}


async def run_benchmark():
    ensure_dataset()
    results = await aevaluate(
        target,
        data=DATASET_NAME,
        evaluators=[intent_correct, used_tools],
        experiment_prefix="router-v1",
        max_concurrency=2,
    )
    print(results)


if __name__ == "__main__":
    asyncio.run(run_benchmark())
