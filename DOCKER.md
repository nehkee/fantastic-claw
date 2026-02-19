# Docker Deployment Guide

## Files Included

- **Dockerfile**: Multi-stage Docker image for the LangChain agent
- **.dockerignore**: Excludes unnecessary files from Docker build context
- **docker-compose.yml**: Orchestration file for running containers easily

## Building the Image

### Option 1: Using Docker CLI

```bash
# Build the image
docker build -t langchain-agent .

# Tag for registry (optional)
docker tag langchain-agent myregistry/langchain-agent:latest
```

### Option 2: Using Docker Compose

```bash
# Build images for both services
docker-compose build
```

## Running the Container

### Option 1: Run the Demo (No API Key Required)

```bash
docker run --rm langchain-agent
# or with compose:
docker-compose run demo
```

### Option 2: Run Interactive Agent (Requires API Key)

First, create `.env` file with your API key:

```bash
cp .env.example .env
# Edit .env and add OPENAI_API_KEY or ANTHROPIC_API_KEY
```

Then run:

```bash
docker run --rm \
  -e OPENAI_API_KEY=$(cat .env | grep OPENAI_API_KEY | cut -d '=' -f 2) \
  -it langchain-agent python agent.py
```

Or with compose:

```bash
docker-compose run --rm agent
```

### Option 3: Run with .env File Mounted

```bash
docker run --rm \
  --env-file .env \
  -it langchain-agent python agent.py
```

## Docker Compose Usage

### Run Demo

```bash
docker-compose run --rm demo
```

### Run Interactive Agent

```bash
docker-compose run --rm agent
```

### Keep Container Running (for interactive use)

```bash
docker-compose run --rm -it agent
```

### Run in Background

```bash
docker-compose up -d agent
```

### View Logs

```bash
docker-compose logs -f agent
```

### Stop and Clean Up

```bash
docker-compose down
```

## Image Details

### Base Image
- `python:3.11-slim` - Lightweight Python 3.11 image

### Multi-Stage Build
- **Stage 1 (builder)**: Installs build tools and Python dependencies
- **Stage 2 (final)**: Only includes runtime dependencies, keeping image size small

### Image Size
- Final image: ~500-600 MB (depending on dependencies)

### Environment Variables

The container respects these environment variables:

```bash
OPENAI_API_KEY      # OpenAI API key
ANTHROPIC_API_KEY   # Anthropic (Claude) API key
PYTHONUNBUFFERED=1  # Show real-time logs
```

## Advanced Usage

### Copy .env into Image (Production)

```dockerfile
# Modify Dockerfile to include:
COPY .env .
```

Then build and run:

```bash
docker build -t langchain-agent-prod .
docker run --rm langchain-agent-prod
```

### Custom Command

Override the default command:

```bash
# Run a different Python script
docker run --rm langchain-agent python your_script.py

# Run interactively
docker run --rm -it langchain-agent /bin/bash
```

### Mount Local Volume for Development

```bash
docker run --rm \
  -v $(pwd):/app \
  -e OPENAI_API_KEY=${OPENAI_API_KEY} \
  -it langchain-agent python agent.py
```

### Set Memory/CPU Limits

```bash
docker run --rm \
  -m 2g \
  --cpus="1" \
  --env-file .env \
  -it langchain-agent
```

## Troubleshooting

### Image Too Large

The multi-stage build optimizes size. Further optimization:

```dockerfile
RUN pip install --user --no-cache-dir -r requirements.txt
```

### API Key Not Found

Ensure `.env` file exists and is properly passed:

```bash
docker run --rm --env-file .env -it langchain-agent python agent.py
```

### Container Exits Immediately

Check logs:

```bash
docker compose logs agent
```

### Permission Denied

Add `--user` flag:

```bash
docker run --rm --user 1000:1000 langchain-agent
```

## Production Deployment

### Push to Registry

```bash
# Tag image
docker tag langchain-agent myregistry/langchain-agent:latest

# Push to registry
docker push myregistry/langchain-agent:latest

# Pull and run
docker pull myregistry/langchain-agent:latest
docker run --rm --env-file .env -it myregistry/langchain-agent:latest
```

### Kubernetes Deployment

Create a simple deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: langchain-agent
spec:
  replicas: 1
  selector:
    matchLabels:
      app: langchain-agent
  template:
    metadata:
      labels:
        app: langchain-agent
    spec:
      containers:
      - name: agent
        image: langchain-agent:latest
        env:
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: api-keys
              key: openai
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
```

## Cleaning Up

### Remove Image

```bash
docker rmi langchain-agent
```

### Remove All Unused Docker Objects

```bash
docker system prune -a
```

### Remove Volumes

```bash
docker-compose down -v
```

## Performance Tips

1. **Use slim base image**: `python:3.11-slim` is already optimized
2. **Cache layers**: Order Dockerfile commands by change frequency
3. **Multi-stage builds**: Already implemented to reduce final size
4. **Use .dockerignore**: Reduces build context size

## Security Best Practices

1. **Don't commit .env**: It's in `.dockerignore`
2. **Read-only .env**: Use `:ro` flag when mounting
3. **Non-root user** (production):

```dockerfile
RUN useradd -m -u 1000 appuser
USER appuser
```

4. **Health checks**: Already included in Dockerfile

## Next Steps

1. Build: `docker build -t langchain-agent .`
2. Test demo: `docker run --rm langchain-agent`
3. Add API key to `.env`
4. Run agent: `docker run --rm --env-file .env -it langchain-agent python agent.py`
