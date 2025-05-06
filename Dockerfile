FROM python:3.11-slim

WORKDIR /app

# Set timezone to GMT+7 (Hanoi)
ENV TZ=Asia/Ho_Chi_Minh
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Install entropy generation tools first to prevent hanging during builds
RUN apt-get update && apt-get install -y haveged rng-tools && \
    service haveged start

# Install system dependencies including Node.js and npm for Playwright
RUN apt-get update && apt-get install -y \
    build-essential \
    wget \
    gnupg \
    curl \
    libgconf-2-4 \
    ca-certificates \
    fonts-liberation \
    libappindicator3-1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libc6 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libexpat1 \
    libfontconfig1 \
    libgbm1 \
    libgcc1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libstdc++6 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    lsb-release \
    xdg-utils \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Set environment variable for Playwright browser path - MUST be before installation
ENV PLAYWRIGHT_BROWSERS_PATH=/app/ms-playwright

# Install Playwright with browsers - ensure correct install location
RUN pip install playwright && \
    python -m playwright install chromium && \
    python -m playwright install-deps chromium

# Make start_playwright_server.sh executable
COPY start_playwright_server.sh /app/
RUN chmod +x /app/start_playwright_server.sh && \
    # Convert Windows line endings to Unix
    sed -i 's/\r$//' /app/start_playwright_server.sh

# Install Playwright using npm for server mode (redundant but for compatibility)
RUN npm init -y && \
    npm install playwright@latest && \
    mkdir -p /app/ms-playwright && \
    npx playwright install chromium && \
    npx playwright install-deps chromium

# Copy the application code
COPY . .

# Create data directory and ensure correct permissions
RUN mkdir -p data && \
    chmod -R 755 /app

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app.py
ENV DOCKER_ENV=true

# Additional Playwright check
RUN ls -la /app/ms-playwright || echo "Playwright browser directory not found"
RUN python -c "from playwright.sync_api import sync_playwright; print('Playwright works!')" || echo "Playwright check failed"

# Expose the port
EXPOSE 5000

# Database initialization will be done at runtime, not during build
# since Redis connection is needed but Redis service isn't available during build

# Default command (will be overridden by docker-compose)
CMD ["waitress-serve", "--port=5000", "--call", "app:create_app"] 