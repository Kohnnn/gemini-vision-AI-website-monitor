#!/bin/bash
echo "Starting Playwright MCP server..."

# Configuration
MCP_SERVER_DIR="mcp_server/playwright-custom-server"
MCP_SERVER_SCRIPT="server.js"
MCP_SERVER_PORT=11435

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo "[ERROR] Node.js not found in PATH. Playwright server cannot start."
    echo "Install Node.js first."
    echo
    echo "Attempting to use local Playwright as fallback..."
    echo "Make sure 'pip install playwright' and 'python -m playwright install chromium' have been run."
    exit 1
fi

# Check if the server script exists
if [ ! -f "${MCP_SERVER_DIR}/${MCP_SERVER_SCRIPT}" ]; then
    echo "[ERROR] Playwright server script not found at ${MCP_SERVER_DIR}/${MCP_SERVER_SCRIPT}"
    echo
    echo "Attempting to use local Playwright as fallback..."
    echo "Make sure 'pip install playwright' and 'python -m playwright install chromium' have been run."
    exit 1
fi

# Install Playwright browsers if needed
echo "Ensuring Playwright browsers are installed..."
playwright install chromium
python -m playwright install chromium

# Start the server
echo "Starting Playwright MCP Server on port ${MCP_SERVER_PORT}..."
echo "Press Ctrl+C to stop the server."
cd "${MCP_SERVER_DIR}" || exit
node "${MCP_SERVER_SCRIPT}"

# This line is reached only if the server stops
echo "Server stopped." 