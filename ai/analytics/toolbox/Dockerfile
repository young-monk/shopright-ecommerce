# MCP Toolbox for Databases sidecar — bakes tools.yaml into the official image.
# Runs on port 5000 (internal to the Cloud Run task, not exposed externally).
# The analytics FastAPI service reaches it at http://localhost:5000.
FROM us-central1-docker.pkg.dev/database-toolbox/toolbox/toolbox:latest
COPY tools.yaml /config/tools.yaml
EXPOSE 5000
ENTRYPOINT ["/toolbox/toolbox", "--tools_file", "/config/tools.yaml", "--address", "0.0.0.0"]
