# Renamed to dashboard_tool.py — kept for import compatibility only.
from tools.dashboard_tool import (  # noqa: F401
    get_dashboard_devops_url as get_looker_devops_url,
    get_dashboard_tech_url as get_looker_tech_url,
    get_dashboard_business_url as get_looker_business_url,
    get_all_dashboard_urls as get_all_looker_urls,
)
