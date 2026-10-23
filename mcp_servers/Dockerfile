FROM python:3.12-slim-bookworm

WORKDIR /srv
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY mcp_servers /srv
ENV PYTHONUNBUFFERED=1 \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8092
EXPOSE 8092
CMD ["python", "-m", "manufacturer"]
