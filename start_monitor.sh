#!/bin/bash

echo "======================================"
echo " AI Website Monitor - Startup Script"
echo "======================================"

# --- Setup variables ---
export FLASK_APP=app:app
export REDIS_URL=redis://localhost:6379
export APP_PORT=5000
export APP_HOST=127.0.0.1

# --- Ensure we're in the right directory ---
cd "$(dirname "$0")"

# --- Activate virtual environment ---
echo "Activating virtual environment..."
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "[ERROR] Virtual environment not found."
    echo "Make sure your virtual environment is set up properly."
    exit 1
fi

# --- Check Redis connection ---
echo "Testing Redis connection..."
python check_redis.py
if [ $? -ne 0 ]; then
    echo "[ERROR] Redis connection failed."
    echo "Make sure Redis is running at $REDIS_URL"
    echo "Redis is required for background tasks and scheduled checks."
    exit 1
fi
echo "Redis connection successful."

# --- Start RQ Worker ---
echo "Starting RQ Worker in new terminal..."
if [ "$(uname)" == "Darwin" ]; then
    # macOS
    osascript -e "tell application \"Terminal\" to do script \"cd $(pwd) && source venv/bin/activate && python -m rq.cli worker default --url $REDIS_URL --with-scheduler\""
else
    # Linux
    gnome-terminal -- bash -c "cd $(pwd) && source venv/bin/activate && python -m rq.cli worker default --url $REDIS_URL --with-scheduler; exec bash" || \
    xterm -e "cd $(pwd) && source venv/bin/activate && python -m rq.cli worker default --url $REDIS_URL --with-scheduler" || \
    konsole -e "cd $(pwd) && source venv/bin/activate && python -m rq.cli worker default --url $REDIS_URL --with-scheduler" || \
    echo "[WARNING] Could not open a new terminal for RQ worker. Please start the worker manually in a separate terminal."
fi

# --- Wait for worker to start ---
echo "Waiting for worker to initialize..."
sleep 3

# --- Start Playwright server ---
echo "Starting Playwright server..."
if [ "$(uname)" == "Darwin" ]; then
    # macOS
    osascript -e "tell application \"Terminal\" to do script \"cd $(pwd) && source venv/bin/activate && python -m playwright install && python start_playwright_server.py\""
else
    # Linux
    gnome-terminal -- bash -c "cd $(pwd) && source venv/bin/activate && python -m playwright install && python start_playwright_server.py; exec bash" || \
    xterm -e "cd $(pwd) && source venv/bin/activate && python -m playwright install && python start_playwright_server.py" || \
    konsole -e "cd $(pwd) && source venv/bin/activate && python -m playwright install && python start_playwright_server.py" || \
    echo "[WARNING] Could not open a new terminal for Playwright server. Please start the server manually in a separate terminal."
fi

# --- Wait for server to start ---
echo "Waiting for Playwright server to initialize..."
sleep 3

# --- Start Flask app with Waitress ---
echo "Starting Flask application with Waitress..."
echo "Server will be available at: http://$APP_HOST:$APP_PORT"
echo "Press Ctrl+C to stop the application."
echo "(Remember to close the worker and server terminals too)"
echo "======================================"

python -m waitress --host=$APP_HOST --port=$APP_PORT $FLASK_APP

echo "Application stopped." 