"""
Analytics dashboard URL tool.
Returns deep-link URLs to the Streamlit analytics dashboard for each audience.
Set DASHBOARD_URL to the deployed Streamlit service URL to activate.
"""
import os

_DASHBOARD_URL = os.getenv("DASHBOARD_URL", "").rstrip("/")

_SETUP_HINT = (
    "Set the DASHBOARD_URL environment variable to the deployed "
    "Streamlit analytics dashboard URL to enable this link."
)


def _url(section: str) -> dict:
    if _DASHBOARD_URL:
        return {
            "url": f"{_DASHBOARD_URL}?section={section}",
            "audience": section,
            "configured": True,
        }
    return {"url": "", "audience": section, "configured": False, "hint": _SETUP_HINT}


def get_dashboard_devops_url() -> dict:
    """
    Return the Streamlit dashboard URL for the DevOps/infrastructure audience.
    Links to the DevOps section covering request volume, error rate, latency,
    TTFT, unanswered rate, and security events.
    """
    return _url("devops")


def get_dashboard_tech_url() -> dict:
    """
    Return the Streamlit dashboard URL for the Technical/ML audience.
    Links to the Technical section covering RAG confidence, embedding quality,
    token cost, frustration rate, intent distribution, and catalog gaps.
    """
    return _url("tech")


def get_dashboard_business_url() -> dict:
    """
    Return the Streamlit dashboard URL for the Business/executive audience.
    Links to the Business section covering satisfaction scores, chip-click
    conversion, session outcomes, and top product engagement.
    """
    return _url("business")


def get_all_dashboard_urls() -> dict:
    """Return all three Streamlit dashboard section URLs in a single call."""
    return {
        "devops": get_dashboard_devops_url(),
        "tech": get_dashboard_tech_url(),
        "business": get_dashboard_business_url(),
    }
