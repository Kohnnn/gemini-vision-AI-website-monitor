# Running AI Website Monitor with Docker

This guide explains how to run the AI Website Monitor application using Docker, which makes it easier to set up and ensures consistent operation across different environments.

## Prerequisites

- [Docker](https://www.docker.com/products/docker-desktop/) installed on your machine
- [Docker Compose](https://docs.docker.com/compose/install/) (usually comes with Docker Desktop)

## Quick Start

1. Clone or download this repository
2. Navigate to the project directory
3. Create a .env file with your configuration (see below)
4. Run the application with Docker Compose:

```bash
docker-compose up -d
```

This will start three services:
- Redis database (for task queue)
- Web application (Flask)
- RQ Worker (for background tasks)

## Environment Variables

Create a `.env` file in the project root with the following variables:

```
# Database and secret key
SECRET_KEY=your_secret_key_here

# Email configuration (for notifications)
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_USERNAME=your_email@example.com
EMAIL_PASSWORD=your_email_password
EMAIL_FROM=your_email@example.com
EMAIL_USE_TLS=True

# AI configuration (Gemini Vision API)
GEMINI_API_KEY=your_gemini_api_key

# Redis configuration (if using external Redis)
# REDIS_URL=redis://redis:6379
```

## Services

The Docker Compose setup includes:

1. **Redis**: For background job queue management
   - Port: 6379
   - Persists data to a Docker volume

2. **Web Application**: Flask API and web interface
   - Port: 5000 (access at http://localhost:5000)
   - Mounts the local code as a volume for easy development

3. **RQ Worker**: Background processing
   - Handles website checks and notification sending
   - Connected to Redis queue

## Monitoring and Management

- Web interface: http://localhost:5000
- Debug routes:
  - http://localhost:5000/debug/scheduler - Check scheduler status
  - http://localhost:5000/debug/test_rq - Test RQ worker functionality
  - http://localhost:5000/debug/run_scheduled_checks - Manually trigger scheduled checks

## Logs

View logs from all services:

```bash
docker-compose logs -f
```

Or for a specific service:

```bash
docker-compose logs -f web
docker-compose logs -f rq-worker
docker-compose logs -f redis
```

## Stopping the Application

```bash
docker-compose down
```

To remove volumes (will delete all data):

```bash
docker-compose down -v
```

## Rebuilding after Code Changes

If you make changes to the Dockerfile or requirements:

```bash
docker-compose up -d --build
```

## Troubleshooting

1. **Redis Connection Issues**:
   - Check if Redis container is running: `docker ps`
   - Try connecting to Redis manually: `docker exec -it ai_website_monitor_redis_1 redis-cli ping`

2. **RQ Worker Not Processing Jobs**:
   - Check worker logs: `docker-compose logs rq-worker`
   - Test with the debug route: http://localhost:5000/debug/test_rq

3. **Web Application Errors**:
   - Check web logs: `docker-compose logs web`
   - Look for error messages in the container logs

## Data Persistence

Your data is stored in a Docker volume and will persist between container restarts. 