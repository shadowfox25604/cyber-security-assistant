import os
from typing import NotRequired, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import MessagesState
from dotenv import load_dotenv

load_dotenv()

from system_prompt import DEFAULT_SYSTEM_PROMPT

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
    """Conversation state for AG-UI / CopilotKit (requires `messages` + cyber fields)."""

    question: NotRequired[str]
    category: NotRequired[Optional[str]]
    prompt: NotRequired[Optional[str]]
    answer: NotRequired[Optional[str]]
    validated: NotRequired[Optional[bool]]


def assistant_node(state: CyberState) -> dict:
    """Single LLM turn: reads chat history, updates `question` / `answer`, appends assistant message."""
    llm = ChatOpenAI(
        model=OPENAI_MODEL,
        api_key=OPENAI_API_KEY,
        reasoning_effort="low",
        stream_usage=True,
    )
    messages = state.get("messages") or []

    last_question = ""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            c = m.content
            last_question = c if isinstance(c, str) else str(c)
            break

    sys_text = resolved_system_prompt()
    llm_messages = [SystemMessage(content=sys_text), *messages] if sys_text else list(messages)
    response = llm.invoke(llm_messages)
    content = response.content
    text = content if isinstance(content, str) else str(content)

    return {
        "messages": [AIMessage(content=text)],
        "question": last_question,
        "answer": text,
    }


def build_graph():
    graph_builder = StateGraph(CyberState)
    graph_builder.add_node("assistant", assistant_node)
    graph_builder.add_edge(START, "assistant")
    graph_builder.add_edge("assistant", END)
    return graph_builder.compile(checkpointer=MemorySaver())


def main():
    graph = build_graph()
    cfg = {"configurable": {"thread_id": "cli-demo"}}
    out = graph.invoke(
        {"messages": [HumanMessage(content="Say hello in one short sentence.")]},
        cfg,
    )
    print(out)


if __name__ == "__main__":
    main()
