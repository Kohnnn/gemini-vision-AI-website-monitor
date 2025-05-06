#!/bin/sh
echo "Starting Playwright setup for Docker..."

# Ensure correct path
export PLAYWRIGHT_BROWSERS_PATH=/app/ms-playwright

# Install browsers directly 
echo "Installing Playwright browsers..."
python -m playwright install chromium --with-deps
mkdir -p /app/ms-playwright
ls -la /app/ms-playwright

# Start MCP server if available
if [ -f "mcp_server/playwright-custom-server/server.js" ]; then
  echo "Starting Playwright MCP Server..."
  cd mcp_server/playwright-custom-server
  node server.js
else
  echo "MCP server not found, continuing with local Playwright"
fi 