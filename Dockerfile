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
    dos2unix \
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

# Create browser directory first and set permissions
RUN mkdir -p /app/ms-playwright && \
    chmod -R 777 /app/ms-playwright

# Set environment variables for Playwright
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/app/ms-playwright
ENV FLASK_APP=app.py
ENV DOCKER_ENV=true

# Install Playwright but don't install browsers yet (will be installed during runtime)
RUN pip install playwright

# Copy the application code
COPY . .

# Fix line endings for shell scripts and make them executable
RUN find . -type f -name "*.sh" -exec dos2unix {} \;
RUN chmod +x /app/start_playwright_server.sh

# Create data directory and ensure correct permissions
RUN mkdir -p data && \
    chmod -R 755 /app

# Expose the port
EXPOSE 5000

# Default command (will be overridden by docker-compose)
CMD ["waitress-serve", "--port=5000", "--call", "app:create_app"] 