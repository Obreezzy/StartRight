FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# Install dependencies first so Docker can cache this layer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src

# Run as a normal user, not root (security good practice)
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "startright.api:app", "--host", "0.0.0.0", "--port", "8000"]