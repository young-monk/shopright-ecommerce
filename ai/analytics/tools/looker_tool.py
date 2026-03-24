"""
Looker Studio dashboard URL tool.
Returns the pre-configured Looker Studio dashboard link for each audience.
Set the env vars LOOKER_STUDIO_DEVOPS_URL / TECH_URL / BUSINESS_URL to activate.
"""
import os

_DEVOPS_URL   = os.getenv("LOOKER_STUDIO_DEVOPS_URL", "")
_TECH_URL     = os.getenv("LOOKER_STUDIO_TECH_URL", "")
_BUSINESS_URL = os.getenv("LOOKER_STUDIO_BUSINESS_URL", "")

_SETUP_HINT = (
    "To enable this link, set the {var} environment variable to your "
    "Looker Studio dashboard URL."
)


def get_looker_devops_url() -> dict:
    """
    Return the Looker Studio dashboard URL for the DevOps/infrastructure audience.
    The dashboard should be connected to the chat_analytics BigQuery dataset and
    include tiles for request volume, error rate, latency, and security events.
    """
    if _DEVOPS_URL:
        return {"url": _DEVOPS_URL, "audience": "devops", "configured": True}
    return {
        "url": "",
        "audience": "devops",
        "configured": False,
        "hint": _SETUP_HINT.format(var="LOOKER_STUDIO_DEVOPS_URL"),
    }


def get_looker_tech_url() -> dict:
    """
    Return the Looker Studio dashboard URL for the Technical/ML audience.
    The dashboard should cover RAG confidence, embedding quality, token cost,
    intent distribution, and catalog gap analysis.
    """
    if _TECH_URL:
        return {"url": _TECH_URL, "audience": "tech", "configured": True}
    return {
        "url": "",
        "audience": "tech",
        "configured": False,
        "hint": _SETUP_HINT.format(var="LOOKER_STUDIO_TECH_URL"),
    }


def get_looker_business_url() -> dict:
    """
    Return the Looker Studio dashboard URL for the Business/executive audience.
    The dashboard should cover satisfaction scores, chip-click conversion,
    session outcomes, and top product engagement.
    """
    if _BUSINESS_URL:
        return {"url": _BUSINESS_URL, "audience": "business", "configured": True}
    return {
        "url": "",
        "audience": "business",
        "configured": False,
        "hint": _SETUP_HINT.format(var="LOOKER_STUDIO_BUSINESS_URL"),
    }


def get_all_looker_urls() -> dict:
    """Return all three Looker Studio dashboard URLs in a single call."""
    return {
        "devops":   get_looker_devops_url(),
        "tech":     get_looker_tech_url(),
        "business": get_looker_business_url(),
    }
