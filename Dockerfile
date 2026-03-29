# Use the official lightweight Python image
FROM python:3.14-slim

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
