"""LangGraph router: general → LLM, availability → check + alternatives, out-of-range → HITL."""

from typing import Annotated, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from utils.tools import (
    booking_villa,
    check_availability,
    find_villa_by_name,
    get_alternative_villas,
    get_villa_policy,
    get_villas,
)

AVAILABILITY_TOOLS = [get_villas, find_villa_by_name, check_availability]
BOOKING_TOOLS = [booking_villa]
POLICY_TOOLS = [get_villa_policy]
ALL_BOOKING_TOOLS = AVAILABILITY_TOOLS + BOOKING_TOOLS + POLICY_TOOLS


class IntentClassification(BaseModel):
    intent: Literal["general", "availability", "booking", "policy", "out_of_range"] = Field(
        description="Route for the user query."
    )
    reason: str = Field(
        default="",
        description="Brief reason for out_of_range or ambiguous routing.",
    )


class RouterState(TypedDict):
    messages: Annotated[list, add_messages]
    intent: str
    combined_context: str


CLASSIFY_PROMPT = """You are a query router for a villa booking assistant.

Classify the user message into exactly one intent:

- general: general knowledge, chitchat, or questions unrelated to villa booking
- availability: asking whether a specific villa (or villas in a location) is available
- booking: user wants to reserve / book a villa (with or without dates)
- policy: cancellation, refund, check-in/check-out rules for a villa
- out_of_range: requests outside what we can handle automatically, including:
  - legal, medical, or financial advice
  - unrelated services (flights, visas, etc.)
  - harmful, abusive, or impossible requests
  - complex bespoke requests needing a human agent

When unsure between availability and booking, pick availability if they only ask "is X available"."""


def build_router_graph(llm, general_agent):
    """Build and compile the top-level LangGraph router."""

    availability_model = llm.bind_tools(AVAILABILITY_TOOLS)
    booking_model = llm.bind_tools(BOOKING_TOOLS)
    policy_model = llm.bind_tools(POLICY_TOOLS)

    def classify_intent(state: RouterState) -> dict:
        classifier = llm.with_structured_output(IntentClassification)
        last_user = next(
            (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
            None,
        )
        user_text = last_user.content if last_user else ""
        if isinstance(user_text, list):
            user_text = " ".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in user_text
            )
        result = classifier.invoke(
            [SystemMessage(content=CLASSIFY_PROMPT), HumanMessage(content=str(user_text))]
        )
        return {"intent": result.intent}

    def inject_context(state: RouterState) -> dict:
        context = state.get("combined_context", "")
        if not context:
            return {}
        return {"messages": [SystemMessage(content=f"Conversation context:\n{context}")]}

    def route_by_intent(state: RouterState) -> str:
        intent = state.get("intent", "general")
        if intent == "out_of_range":
            return "human_escalation"
        if intent == "availability":
            return "availability_agent"
        if intent == "booking":
            return "booking_agent"
        if intent == "policy":
            return "policy_agent"
        return "inject_context"

    def availability_agent_node(state: RouterState) -> dict:
        context = state.get("combined_context", "")
        system = (
            "You are a villa availability assistant. "
            "Use find_villa_by_name or get_villas to locate the villa, then check_availability. "
            "Always call check_availability once you know the villa id."
        )
        if context:
            system = f"{system}\n\nConversation context:\n{context}"
        response = availability_model.invoke(
            [SystemMessage(content=system), *state["messages"]]
        )
        return {"messages": [response]}

    def booking_agent_node(state: RouterState) -> dict:
        context = state.get("combined_context", "")
        system = (
            "You are a villa booking assistant. "
            "Confirm villa and dates, then use booking_villa to complete the reservation."
        )
        if context:
            system = f"{system}\n\nConversation context:\n{context}"
        response = booking_model.invoke(
            [SystemMessage(content=system), *state["messages"]]
        )
        return {"messages": [response]}

    def policy_agent_node(state: RouterState) -> dict:
        context = state.get("combined_context", "")
        system = (
            "You are a villa policy assistant. "
            "Use get_villa_policy for cancellation, refund, and check-in questions."
        )
        if context:
            system = f"{system}\n\nConversation context:\n{context}"
        response = policy_model.invoke(
            [SystemMessage(content=system), *state["messages"]]
        )
        return {"messages": [response]}

    def suggest_alternatives_node(state: RouterState) -> dict:
        """When a villa is unavailable, suggest other villas in the same location."""
        villa_id: int | None = None
        villa_name = "the requested villa"

        for msg in reversed(state["messages"]):
            if isinstance(msg, ToolMessage) and msg.name == "check_availability":
                if str(msg.content).lower() not in ("false", "0"):
                    break
                for prev in reversed(state["messages"]):
                    if isinstance(prev, AIMessage) and prev.tool_calls:
                        for call in prev.tool_calls:
                            if call.get("name") == "check_availability":
                                args = call.get("args") or {}
                                villa_id = args.get("villa_id")
                                break
                    if villa_id is not None:
                        break
                break

        if villa_id is None:
            for msg in reversed(state["messages"]):
                if isinstance(msg, ToolMessage) and msg.name == "find_villa_by_name":
                    content = msg.content
                    if isinstance(content, dict):
                        villa_id = content.get("id")
                        villa_name = content.get("name", villa_name)
                    break

        if villa_id is None:
            return {
                "messages": [
                    AIMessage(
                        content=(
                            "That villa is not available right now. "
                            "I couldn't find alternatives automatically — please try another location or villa name."
                        )
                    )
                ]
            }

        alternatives = get_alternative_villas(villa_id)
        if not alternatives:
            return {
                "messages": [
                    AIMessage(
                        content=(
                            f"Sorry, {villa_name} is not available and there are no other "
                            "available villas in the same location at the moment."
                        )
                    )
                ]
            }

        alt_lines = [
            f"- {v['name']} ({v['location']}): {v['rooms_available']} rooms, "
            f"₹{v['price_per_night']}/night"
            for v in alternatives
        ]
        return {
            "messages": [
                AIMessage(
                    content=(
                        f"Sorry, {villa_name} is not available for your dates. "
                        f"Here are other available villas in the same location:\n"
                        + "\n".join(alt_lines)
                        + "\n\nWould you like to book one of these?"
                    )
                )
            ]
        }

    def human_escalation_node(state: RouterState) -> dict:
        last_user = next(
            (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
            None,
        )
        query = last_user.content if last_user else ""
        if isinstance(query, list):
            query = " ".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in query
            )

        review = interrupt(
            {
                "action": "human_review",
                "query": str(query),
                "prompt": (
                    "This request is outside automated handling. "
                    "Approve to escalate to a human agent."
                ),
            }
        )
        approved = False
        if isinstance(review, bool):
            approved = review
        elif isinstance(review, dict):
            approved = bool(review.get("approved"))

        if approved:
            text = (
                "Your request has been escalated to a human agent. "
                "Someone will follow up with you shortly."
            )
        else:
            text = (
                "This request could not be handled automatically. "
                "Please rephrase or ask about villa availability, booking, or policies."
            )
        return {"messages": [AIMessage(content=text)]}

    def availability_router(
        state: RouterState,
    ) -> Literal["availability_tools", "suggest_alternatives", "availability_agent", "__end__"]:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "availability_tools"
        if isinstance(last, ToolMessage) and last.name == "check_availability":
            if str(last.content).lower() in ("false", "0"):
                return "suggest_alternatives"
            return "availability_agent"
        if isinstance(last, ToolMessage):
            return "availability_agent"
        return END

    def booking_router(state: RouterState) -> Literal["booking_tools", "booking_agent", "__end__"]:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "booking_tools"
        if isinstance(last, ToolMessage):
            return "booking_agent"
        return END

    def policy_router(state: RouterState) -> Literal["policy_tools", "policy_agent", "__end__"]:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "policy_tools"
        if isinstance(last, ToolMessage):
            return "policy_agent"
        return END

    builder = StateGraph(RouterState)
    builder.add_node("classify", classify_intent)
    builder.add_node("inject_context", inject_context)
    builder.add_node("general_agent", general_agent)
    builder.add_node("availability_agent", availability_agent_node)
    builder.add_node("availability_tools", ToolNode(AVAILABILITY_TOOLS))
    builder.add_node("suggest_alternatives", suggest_alternatives_node)
    builder.add_node("booking_agent", booking_agent_node)
    builder.add_node("booking_tools", ToolNode(BOOKING_TOOLS))
    builder.add_node("policy_agent", policy_agent_node)
    builder.add_node("policy_tools", ToolNode(POLICY_TOOLS))
    builder.add_node("human_escalation", human_escalation_node)

    builder.add_edge(START, "classify")
    builder.add_conditional_edges(
        "classify",
        route_by_intent,
        {
            "inject_context": "inject_context",
            "availability_agent": "availability_agent",
            "booking_agent": "booking_agent",
            "policy_agent": "policy_agent",
            "human_escalation": "human_escalation",
        },
    )

    builder.add_edge("inject_context", "general_agent")
    builder.add_edge("general_agent", END)
    builder.add_edge("human_escalation", END)

    builder.add_conditional_edges(
        "availability_agent",
        availability_router,
        {
            "availability_tools": "availability_tools",
            "suggest_alternatives": "suggest_alternatives",
            "availability_agent": "availability_agent",
            END: END,
        },
    )
    builder.add_conditional_edges(
        "availability_tools",
        availability_router,
        {
            "availability_tools": "availability_tools",
            "suggest_alternatives": "suggest_alternatives",
            "availability_agent": "availability_agent",
            END: END,
        },
    )
    builder.add_edge("suggest_alternatives", END)

    builder.add_conditional_edges(
        "booking_agent",
        booking_router,
        {
            "booking_tools": "booking_tools",
            "booking_agent": "booking_agent",
            END: END,
        },
    )
    builder.add_conditional_edges(
        "booking_tools",
        booking_router,
        {
            "booking_tools": "booking_tools",
            "booking_agent": "booking_agent",
            END: END,
        },
    )

    builder.add_conditional_edges(
        "policy_agent",
        policy_router,
        {
            "policy_tools": "policy_tools",
            "policy_agent": "policy_agent",
            END: END,
        },
    )
    builder.add_conditional_edges(
        "policy_tools",
        policy_router,
        {
            "policy_tools": "policy_tools",
            "policy_agent": "policy_agent",
            END: END,
        },
    )

    return builder
