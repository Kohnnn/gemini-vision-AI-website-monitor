# AI Website Monitor

A robust website monitoring solution with AI-powered change detection, screenshot capture, and multi-channel notifications.

---

## Features
- **Website Monitoring**: Check for changes on any website at custom intervals or scheduled times.
- **AI Change Detection**: Use Gemini Vision API (`gemini-1.5-flash-latest`) for intelligent change summaries, respecting user-defined focus areas.
- **Screenshots**: Capture full-page screenshots using a local Playwright server.
- **Notifications**: Receive alerts via Email, Telegram, and Microsoft Teams.
- **Manual & Scheduled Checks**: Trigger checks on demand (with immediate feedback) or automatically via background worker (manual start required).
- **Test URL & Analyze:** Pre-flight check on Add Website page to verify URL, screenshot, and AI analysis.
- **Data Cleanup**: Delete old check history and associated files.

---

## Quick Start

### 1. Prerequisites
- Python 3.8+
- Node.js (for Playwright server - required for screenshots/AI)
- Redis (native/WSL/Memurai recommended for Windows - required for background jobs)

### 2. Setup
```sh
# Clone the repository
# cd into the project directory
python -m venv venv
venv\Scripts\activate  # On Windows
pip install -r requirements.txt
```

### 3. Configuration
- Copy `.env.example` to `.env` and fill in your credentials:
  - `REDIS_URL=redis://localhost:6379` (Adjust if Redis is elsewhere)
  - Email SMTP settings (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `EMAIL_FROM`)
  - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (Optional, for Telegram notifications)
  - `TEAMS_WEBHOOK_URL` (Optional, for Teams notifications)
  - `GEMINI_API_KEY1` (Required for AI analysis)
  - `GEMINI_API_KEY2` (Support multiple API keys)
  - `ADMIN_KEY` (Optional, for accessing admin functions via API)
  - `SECRET_KEY` (For Flask session security)
  - `AI_COMPARE_SYSTEM_PROMPT` (Prompt for compare of websites)
  - `AI_NOTIFICATION_SYSTEM_PROMPT` (Prompt to summarizes the differences)
  - `AI_NOTIFICATION_SUMMARY_SYSTEM_PROMPT` (Prompt to generates a consolidated summary of changes)
- Ensure Redis is running.

### 4. Running the App (Manual Start Recommended)

The `run_all.bat` script is currently unreliable. Please start the services manually in separate terminals:

**Terminal 1: Playwright MCP Server**
```sh
cd mcp_server\playwright-custom-server
node server.js
```

**Terminal 2: RQ Worker (for scheduled checks)**
```sh
cd path\to\AI_WebsiteMonitor
venv\Scripts\activate
rq worker default --url redis://localhost:6379 --worker-class app.WindowsSimpleWorker --with-scheduler --burst
```

**Terminal 3: Flask App (Waitress)**
```sh
cd path\to\AI_WebsiteMonitor
venv\Scripts\activate
waitress-serve --host=0.0.0.0 --port=5000 app:init_app()
```

*(Alternatively, use `start_monitor.bat` to run only Terminal 3, assuming Redis and Playwright MCP are already running).* 

- Visit `http://localhost:5000` in your browser.

### 5. RQ Dashboard (Optional Job Monitoring)
To monitor background jobs, run:
```sh
rq-dashboard --redis-url=redis://localhost:6379
```
Then visit `http://localhost:9181`.

---

## Usage
- **User ID**: Create or select a User ID on the index page.
- **Add Websites**: Use the dashboard -> "Add Website". Test with "Test URL & Analyze" before saving. Set AI Focus Area if needed.
- **Manual Checks**: Click "Check Now" for immediate analysis and feedback.
- **Dashboard Views**: Toggle between List and Grid views.
- **Notifications**: Configure Email, Telegram, and Teams in Settings. Use "Test" buttons to verify.
- **History**: View change history, AI descriptions, and screenshots for each site.
- **Cleanup**: Use Settings page -> Data Management (requires Admin Key via API/manual trigger).

---

## Troubleshooting
- **Services Not Starting:** Ensure prerequisites (Python, Node, Redis) are installed and running. Start services manually as described above.
- **`run_all.bat` Errors:** Ignore this script, use manual start.
- **Redis Connection Errors**: Ensure Redis is running and `REDIS_URL` in `.env` is correct.
- **Playwright Errors / Screenshot Failures**: Check Terminal 1 (Playwright MCP) for errors. Ensure it's running and accessible (firewall?).
- **RQ Worker Not Processing:** Check Terminal 2 (RQ Worker) for errors. Ensure Redis is running.
- **Flask App Errors:** Check Terminal 3 (Waitress) or `backend_error.log` for errors.
- **Email/Telegram/Teams Failures**: Double-check credentials in `.env`. Use "Test" buttons and check `backend_error.log` for detailed errors.
- **AI Analysis Errors:** Ensure `GEMINI_API_KEY` is correct in `.env` and the key is valid/has quota.

---

## Customization & Advanced
- **Scheduling**: Supports both interval (every X minutes) and specific time (HH:MM) checks.
- **AI Models**: Plug in your own AI API key for advanced change detection.
- **Dark Mode**: Auto-detects system preference, toggle anytime.
- **Multi-User**: Basic support; extend as needed for your org.

---

## Security Notes
- **Redis**: Never expose Redis to the public internet without proper security (authentication, firewall).
- **`.env`**: Keep your credentials secret.
- **Admin Key**: Protect the `ADMIN_KEY` if set; it allows data deletion.
- **Production**: Waitress is used, but consider additional layers like a reverse proxy (Nginx, Caddy) for HTTPS, load balancing, etc., in a real production environment.

---

## Contributing
Pull requests and issues are welcome! Please see the [currentprogress.md](memory-bank/currentprogress.md) for the latest project status and roadmap.

---

## License
MIT License

## Database Migrations

The application now uses Flask-Migrate to handle database schema changes. When new models or schema changes are added, you need to run migrations to update your database without losing data.

### Using the Migration Batch File (Windows)

For Windows users, a batch file has been provided to simplify migration management:

1. To initialize migrations for the first time:
   ```
   migrate_db.bat init
   ```

2. To create a new migration after model changes:
   ```
   migrate_db.bat migrate
   ```

3. To apply pending migrations to your database:
   ```
   migrate_db.bat upgrade
   ```

4. To manually set the migration version:
   ```
   migrate_db.bat stamp
   ```

### Manual Migration Commands

If you prefer to run migrations manually, you can use the following commands:

1. Initialize migrations (first-time only):
   ```
   python -m flask db init
   ```

2. Create a new migration:
   ```
   python -m flask db migrate -m "Description of changes"
   ```

3. Apply migrations to update your database:
   ```
   python -m flask db upgrade
   ```

### Important Notes

- Always backup your database before running migrations
- The first time you run migrations on an existing database, you may need to use `stamp` to tell Flask-Migrate the current state
- If you experience issues, check the migration files in the `migrations` folder

## Included Script Files

For Windows users, several batch files are included for convenience:

- `run_all.bat` - Start all components (Flask app, Redis server, workers)
- `start_monitor.bat` - Start only the Flask application
- `start_playwright_server.bat` - Start the Playwright server for screenshots
- `install_requirements.bat` - Install Python dependencies
- `migrate_db.bat` - Manage database migrations

# Recent Updates

## UI Improvements (May 2024)
- Fixed timestamps to display in user's local timezone instead of UTC
- Updated status colors for website changes to use warning/orange for better visibility
- Improved responsive design for mobile and tablet users

## Scheduler and RQ Integration Improvements (May 2024)
- Fixed issue with scheduled tasks not being queued in RQ
- Enhanced error handling and logging for background jobs
- Improved queue management for more reliable task scheduling

## New Notification Preferences (May 2024)
- Added "Notify Only Changes" option in user settings
- Users can now choose to receive notifications only when changes are detected
- Different message templates for change vs. no-change notifications
- Updated database schema (run update_schema.py if upgrading from an earlier version)

## Docker Timezone Support (May 2024)
- Added support for proper timezone handling in Docker containers
- Container timezone now follows host system for accurate timestamps
- Improved time-based scheduling in containerized environments

## How to Start the Application
1. Ensure Redis is running
2. Run the `start_website_monitor.bat` script
3. Access the application at http://127.0.0.1:5000
