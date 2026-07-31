FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       git \
       ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd --gid "${APP_GID}" foodassistant \
    && useradd \
       --uid "${APP_UID}" \
       --gid "${APP_GID}" \
       --create-home \
       --shell /usr/sbin/nologin \
       foodassistant

WORKDIR /opt/food-assistant

COPY requirements.txt ./

RUN pip install --no-cache-dir --requirement requirements.txt

COPY app ./app

RUN mkdir -p /data \
    && chown -R foodassistant:foodassistant /data

USER foodassistant

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
