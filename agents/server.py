"""FastAPI app exposing the LangGraph agent via the AG-UI protocol (CopilotKit-compatible)."""

import os

from ag_ui_langgraph import add_langgraph_fastapi_endpoint
from copilotkit import LangGraphAGUIAgent
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from main import build_graph

load_dotenv()

app = FastAPI(title="Cyber agent (AG-UI)")

_origins = os.environ.get("CORS_ORIGINS", "http://127.0.0.1:3000,http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_cyber_graph = build_graph()
agui_agent = LangGraphAGUIAgent(
    name="default",
    description="Cyber assistant powered by LangGraph + AG-UI",
    graph=_cyber_graph,
)

add_langgraph_fastapi_endpoint(app, agui_agent, path="/agui")
