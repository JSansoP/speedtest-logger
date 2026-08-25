# Use the official lightweight Python image
FROM python:3.14-slim

# Install system dependencies, Chromium, and Node.js 20 for fast-cli (Puppeteer-based)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    chromium \
    fonts-liberation \
    libgbm1 \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g fast-cli \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Configure Puppeteer to use the system Chromium with sandboxing disabled for Docker
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
ENV PUPPETEER_EXECUTABLE_PATH=/usr/local/bin/chromium-custom

RUN printf '#!/bin/sh\nexec /usr/bin/chromium --no-sandbox --disable-setuid-sandbox --disable-dev-shm-usage --disable-gpu "$@"\n' > /usr/local/bin/chromium-custom \
    && chmod +x /usr/local/bin/chromium-custom

# Copy the uv binary from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy project files first to leverage Docker layer caching for dependencies
COPY pyproject.toml uv.lock ./

# Install dependencies using uv
# We use --frozen to ensure the lockfile is respected
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Copy the rest of the application code
COPY . .

# Final sync to install the project itself
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Create a data directory for the SQLite database
RUN mkdir -p /app/data

# Expose ports for Flask (5000) and Streamlit (8501)
EXPOSE 5000 8501

# The default command will be overridden by docker-compose for each service
CMD ["uv", "run", "python", "main.py"]

