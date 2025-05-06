# AI Website Monitor - Installation Guide

This document provides step-by-step instructions for installing and setting up the AI Website Monitor application.

## Prerequisites

1. **Python 3.9+**: The application requires Python 3.9 or newer.
2. **Redis**: Redis is required for task queuing and scheduling.
3. **Playwright**: Required for capturing website screenshots.

## Installation Steps

### 1. Clone the Repository

```bash
git clone https://github.com/your-repo/AI_WebsiteMonitor1.git
cd AI_WebsiteMonitor1
```

### 2. Create a Virtual Environment

```bash
python -m venv venv
```

### 3. Activate the Virtual Environment

On Windows:
```
venv\Scripts\activate
```

On macOS/Linux:
```bash
source venv/bin/activate
```

### 4. Install Required Packages

```bash
pip install -r requirements.txt
```

### 5. Install Playwright Browsers

```bash
playwright install
```

### 6. Set Up Environment Variables

Create a `.env` file in the root directory with the following variables:

```
FLASK_APP=app:app
SECRET_KEY=your_secret_key_here
SMTP_HOST=your_smtp_host
SMTP_PORT=587
SMTP_USER=your_email@example.com
SMTP_PASS=your_email_password
EMAIL_FROM=your_email@example.com
GEMINI_API_KEY=your_gemini_api_key_here
ADMIN_KEY=your_admin_key_here
```

### 7. Initialize the Database

```bash
python -m flask db init
python -m flask db migrate -m "Initial migration"
python -m flask db upgrade
```

### 8. Update Database Schema

```bash
python update_schema.py
```

## Running the Application

### Start Redis (if not already running)

Ensure Redis is running on your system. The default configuration expects Redis to be available at `redis://localhost:6379`.

### Start the Application

On Windows, simply run:
```
start_website_monitor.bat
```

Manually (alternative method):
```bash
# Terminal 1: Start RQ Worker
python -m rq.cli worker default --url redis://localhost:6379 --worker-class app.WindowsSimpleWorker --with-scheduler

# Terminal 2: Start Playwright Server
python -m playwright install
python start_playwright_server.py

# Terminal 3: Start Flask app with Waitress
python -m waitress --host=127.0.0.1 --port=5000 "app:app"
```

### Access the Application

Open your web browser and navigate to:
```
http://127.0.0.1:5000
```

## Troubleshooting

### Redis Connection Issues
- Ensure Redis is installed and running
- Run `python check_redis.py` to test the connection

### Screenshot Capture Issues
- Ensure Playwright is installed with `playwright install`
- Verify the Playwright server is running

### Database Issues
- Check that SQLite database file exists in the `instance` directory
- Run `python update_schema.py` to ensure all schema updates are applied 