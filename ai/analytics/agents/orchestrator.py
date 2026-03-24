"""
Root orchestrator — built lazily at app startup after the MCP Toolbox client
loads the three audience toolsets from the sidecar server.

Flow:
  /analyze/run  → composite report functions (query BQ + chart + email)
  /analyze/chat → toolbox BQ tools + Looker URLs for ad-hoc natural language questions
"""
from __future__ import annotations

import logging
import os

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.agent_tool import AgentTool
from google.genai.types import Content, Part
from toolbox_core import ToolboxClient

from agents.devops_agent import make_devops_agent
from agents.tech_agent import make_tech_agent
from agents.business_agent import make_business_agent

logger = logging.getLogger(__name__)

TOOLBOX_URL = os.getenv("TOOLBOX_URL", "http://localhost:5000")

# Module-level singletons — populated by init_orchestrator() at app startup.
_runner: Runner | None = None
_session_service: InMemorySessionService | None = None


async def init_orchestrator() -> None:
    """
    Load all MCP Toolbox toolsets from the sidecar, build sub-agents, wire up
    the root orchestrator and Runner.  Called once from FastAPI lifespan.
    """
    global _runner, _session_service

    logger.info("Connecting to MCP Toolbox at %s", TOOLBOX_URL)
    toolbox = ToolboxClient(TOOLBOX_URL)

    try:
        devops_tools   = await toolbox.load_toolset("devops")
        tech_tools     = await toolbox.load_toolset("tech")
        business_tools = await toolbox.load_toolset("business")
        logger.info("Loaded %d devops / %d tech / %d business tools",
                    len(devops_tools), len(tech_tools), len(business_tools))
    except Exception as exc:
        logger.warning("MCP Toolbox unavailable (%s) — running without ad-hoc BQ tools", exc)
        devops_tools = tech_tools = business_tools = []

    devops_agent   = make_devops_agent(devops_tools)
    tech_agent     = make_tech_agent(tech_tools)
    business_agent = make_business_agent(business_tools)

    root_agent = LlmAgent(
        name="analytics_orchestrator",
        model="gemini-2.5-flash",
        description="ShopRight Analytics Orchestrator — routes requests to DevOps, Tech, or Business agents.",
        instruction="""You are the ShopRight Analytics Orchestrator.

You have three specialist sub-agents:

1. **devops_agent** — infrastructure health (error rates, latency, TTFT, security events).
   Audience: engineers, on-call SREs.

2. **tech_agent** — ML/AI performance (RAG quality, embeddings, token cost, intent, frustration).
   Audience: ML engineers, data scientists, technical stakeholders.

3. **business_agent** — business performance (satisfaction, chip-click conversion, session outcomes, top products).
   Audience: product managers, executives.

Routing rules:
- audience = "all"      → call all three agents sequentially
- audience = "devops"   → devops_agent only
- audience = "tech"     → tech_agent only
- audience = "business" → business_agent only
- ad-hoc question       → route to the most relevant agent(s)

Always pass the `days` parameter to each agent.
After sub-agents complete, briefly summarise what was done and any headline findings.
""",
        tools=[
            AgentTool(agent=devops_agent),
            AgentTool(agent=tech_agent),
            AgentTool(agent=business_agent),
        ],
    )

    _session_service = InMemorySessionService()
    _runner = Runner(
        agent=root_agent,
        app_name="shopright_analytics",
        session_service=_session_service,
    )
    logger.info("Analytics orchestrator ready")


async def run_analytics(prompt: str, user_id: str = "scheduler") -> str:
    """
    Run the orchestrator with a natural language prompt.
    Returns the final text response.  Raises RuntimeError if not initialised.
    """
    if _runner is None or _session_service is None:
        raise RuntimeError("Orchestrator not initialised — call init_orchestrator() first")

    session = await _session_service.create_session(
        app_name="shopright_analytics", user_id=user_id
    )
    final_text = ""
    async for event in _runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=Content(role="user", parts=[Part(text=prompt)]),
    ):
        if event.is_final_response() and event.content and event.content.parts:
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    final_text += part.text
    return final_text or "Analytics run completed."
