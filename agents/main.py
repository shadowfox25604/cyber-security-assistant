import os
from typing import Literal, NotRequired, Optional

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import MessagesState

from system_prompt import (
    APPLICATION_SECURITY_QA_SYSTEM_PROMPT,
    CANNOT_ANSWER_MESSAGE,
    DEFAULT_SYSTEM_PROMPT,
    FORMAT_RESPONSE_PROMPT_TEMPLATE,
    INTENT_CLASSIFIER_PROMPT_TEMPLATE,
    NETWORK_SECURITY_QA_SYSTEM_PROMPT,
    NON_CYBER_REFUSAL_MESSAGE,
    QUERY_CLASSIFIER_PROMPT_TEMPLATE,
)

load_dotenv()

OPENAI_MODEL = os.getenv("OPENAI_MODEL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")


def resolved_system_prompt() -> str:
    """SYSTEM_PROMPT env overrides `system_prompt.DEFAULT_SYSTEM_PROMPT`; empty env disables the system prompt."""
    raw = os.getenv("SYSTEM_PROMPT")
    if raw is not None:
        return raw.strip()
    return DEFAULT_SYSTEM_PROMPT


class CyberState(MessagesState):
    """Conversation state for AG-UI / CopilotKit."""

    question: NotRequired[str]
    intent: NotRequired[Optional[str]]
    category: NotRequired[Optional[str]]
    route: NotRequired[Optional[str]]
    answer: NotRequired[Optional[str]]
    can_answer: NotRequired[Optional[bool]]


def get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=OPENAI_MODEL,
        api_key=OPENAI_API_KEY,
        reasoning_effort="low",
        stream_usage=True,
    )


def get_last_human_question(messages: list) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            c = m.content
            return c if isinstance(c, str) else str(c)
    return ""


def intent_classifier_node(state: CyberState) -> dict:
    messages = state.get("messages") or []
    question = get_last_human_question(messages)
    llm = get_llm()
    prompt = INTENT_CLASSIFIER_PROMPT_TEMPLATE.format(question=question)
    result = llm.invoke([HumanMessage(content=prompt)])
    label = str(result.content).strip().lower()
    intent = "cybersecurity" if "cybersecurity" in label else "irrelevant"
    if intent == "irrelevant":
        refusal = NON_CYBER_REFUSAL_MESSAGE
        return {
            "question": question,
            "intent": intent,
            "answer": refusal,
            "messages": [AIMessage(content=refusal)],
        }
    return {"question": question, "intent": intent}


def query_classifier_node(state: CyberState) -> dict:
    question = state.get("question") or ""
    llm = get_llm()
    prompt = QUERY_CLASSIFIER_PROMPT_TEMPLATE.format(question=question)
    result = llm.invoke([HumanMessage(content=prompt)])
    label = str(result.content).strip().lower()
    if "network security" in label:
        return {"category": "network security", "route": "network"}
    if "application security" in label:
        return {"category": "application security", "route": "application"}
    return {"category": "unknown", "route": "cannot_answer"}


def network_security_qa_node(state: CyberState) -> dict:
    question = state.get("question") or ""
    llm = get_llm()
    sys_text = NETWORK_SECURITY_QA_SYSTEM_PROMPT
    result = llm.invoke([SystemMessage(content=sys_text), HumanMessage(content=question)])
    text = str(result.content).strip()
    if "CANNOT_ANSWER" in text.upper():
        return {"can_answer": False, "answer": "I couldn't confidently answer that from the network security path."}
    return {"can_answer": True, "answer": text}


def application_security_qa_node(state: CyberState) -> dict:
    question = state.get("question") or ""
    llm = get_llm()
    sys_text = APPLICATION_SECURITY_QA_SYSTEM_PROMPT
    result = llm.invoke([SystemMessage(content=sys_text), HumanMessage(content=question)])
    text = str(result.content).strip()
    if "CANNOT_ANSWER" in text.upper():
        return {"can_answer": False, "answer": "I couldn't confidently answer that from the application security path."}
    return {"can_answer": True, "answer": text}


def format_response_node(state: CyberState) -> dict:
    question = state.get("question") or ""
    category = state.get("category") or "cybersecurity"
    answer = state.get("answer") or ""
    llm = get_llm()
    sys_text = resolved_system_prompt()
    formatter_prompt = FORMAT_RESPONSE_PROMPT_TEMPLATE.format(
        category=category,
        question=question,
        answer=answer,
    )
    llm_messages = [HumanMessage(content=formatter_prompt)]
    if sys_text:
        llm_messages.insert(0, SystemMessage(content=sys_text))
    result = llm.invoke(llm_messages)
    final = str(result.content).strip()
    return {"messages": [AIMessage(content=final)], "answer": final}


def cannot_answer_node(state: CyberState) -> dict:
    msg = CANNOT_ANSWER_MESSAGE
    return {"messages": [AIMessage(content=msg)], "answer": msg, "can_answer": False}


def route_after_intent(state: CyberState) -> Literal["query_classifier", "__end__"]:
    if state.get("intent") == "cybersecurity":
        return "query_classifier"
    return "__end__"


def route_after_query_classifier(state: CyberState) -> Literal["network_security_qa", "application_security_qa", "cannot_answer"]:
    route = state.get("route")
    if route == "network":
        return "network_security_qa"
    if route == "application":
        return "application_security_qa"
    return "cannot_answer"


def route_after_qa(state: CyberState) -> Literal["format_response", "cannot_answer"]:
    if state.get("can_answer"):
        return "format_response"
    return "cannot_answer"


def build_graph():
    graph_builder = StateGraph(CyberState)
    graph_builder.add_node("intent_classifier", intent_classifier_node)
    graph_builder.add_node("query_classifier", query_classifier_node)
    graph_builder.add_node("network_security_qa", network_security_qa_node)
    graph_builder.add_node("application_security_qa", application_security_qa_node)
    graph_builder.add_node("format_response", format_response_node)
    graph_builder.add_node("cannot_answer", cannot_answer_node)

    graph_builder.add_edge(START, "intent_classifier")
    graph_builder.add_conditional_edges("intent_classifier", route_after_intent)
    graph_builder.add_conditional_edges("query_classifier", route_after_query_classifier)
    graph_builder.add_conditional_edges("network_security_qa", route_after_qa)
    graph_builder.add_conditional_edges("application_security_qa", route_after_qa)
    graph_builder.add_edge("format_response", END)
    graph_builder.add_edge("cannot_answer", END)
    return graph_builder.compile(checkpointer=MemorySaver())


def main():
    graph = build_graph()
    cfg = {"configurable": {"thread_id": "cli-demo"}}
    out = graph.invoke(
        {"messages": [HumanMessage(content="How does SQL injection happen and how to prevent it?")]},
        cfg,
    )
    print(out)


if __name__ == "__main__":
    main()
