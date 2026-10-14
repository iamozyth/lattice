FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        nmap \
        libcap2-bin \
    && setcap cap_net_raw,cap_net_admin,cap_net_bind_service+eip /usr/bin/nmap \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 1000 --home /app lattice

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=lattice:lattice . .
RUN chmod +x /app/start.sh

ENV FLASK_APP=wsgi:app \
    NMAP_PRIVILEGED=1 \
    PYTHONUNBUFFERED=1

USER lattice
EXPOSE 5000
ENTRYPOINT ["/app/start.sh"]
