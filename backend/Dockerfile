FROM python:3.12-slim

# curl is used by the compose healthcheck; git installs Timestral from its repository.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt requirements-forecast.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# Timestral (CPU torch) for the Strategic Horizon forecast. Build with --build-arg WITH_TIMESTRAL=false to skip it;
# the forecast then uses its statistical fallback.
ARG WITH_TIMESTRAL=true
RUN if [ "$WITH_TIMESTRAL" = "true" ]; then pip install --no-cache-dir -r requirements-forecast.txt; fi
COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
