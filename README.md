# lattice

Self-hosted IP address management for homelabs and small networks. Flask, PostgreSQL, Docker.

- Subnets in CIDR notation, IPv4 and IPv6, with VLAN, gateway, DNS, location and environment
- IP records with hostname, FQDN, MAC, device, owner and status
- Global search, IP lookup, next free IP, bulk add
- Network discovery with nmap and periodic checks that keep `last_seen` current
- UniFi connector to sync clients into your subnets, with a dry-run preview
- JSON export and import for backups
- REST API with Swagger UI

## 1. Configure

```sh
cp .env.example .env
```

Fill in the secrets. Generate each one with `openssl rand -hex 32`.

| Variable            | Default    | Description                                  |
|---------------------|------------|----------------------------------------------|
| `POSTGRES_PASSWORD` | (required) | Database password                            |
| `SECRET_KEY`        | (required) | Signs login sessions                         |
| `CONNECTOR_SECRET`  | (required) | Encrypts stored connector credentials        |
| `POSTGRES_USER`     | `lattice`  | Database user                                |
| `POSTGRES_DB`       | `lattice`  | Database name                                |
| `WEB_PORT`          | `5001`     | Host port for the web UI                     |

The database is only reachable on the internal Docker network.

## 2. Run

```sh
docker compose up -d
```

Open http://localhost:5001. On first start you create the admin account.

To update:

```sh
git pull
docker compose up -d --build
```

Database migrations run automatically on start.

## Network scanning

The container ships with nmap. From a subnet you can run:

- **Ping scan**: fast discovery of live hosts (`nmap -sn`)
- **Full scan**: adds OS and service detection (`nmap -sV -O`), slower

Discovered hosts come back as suggestions with reverse DNS, MAC, a guessed device type and a confidence score. Pick the ones you want and import them.

In the background, lattice checks every known IP every 6 hours and updates `last_seen`. Once a day it marks IPs not seen for 30 days as `deprecated`. Both intervals are set in `app/scheduler.py`.

Notes:

- The container can only scan networks it can reach. For a bridge network that usually means routed subnets work and layer-2 details like MAC addresses do not. Use `network_mode: host` if you need them.
- OS detection needs raw sockets. Add `cap_add: [NET_RAW, NET_ADMIN]` to `lattice-web` if full scans fail.
- Port scans may trigger IDS alerts. Tell your security team first.

## API

Every action in the UI is available over the REST API. Docs are at http://localhost:5001/openapi/swagger (or `/openapi/scalar`). All endpoints except initial setup and registration need a logged-in session.

## Remote access

Do not expose port 5001 directly to the internet. Put lattice behind a TLS reverse proxy, for example Caddy:

```
ipam.example.com {
    reverse_proxy 127.0.0.1:5001
}
```

and bind the port to localhost by setting the `ports` entry in `docker-compose.yml` to `"127.0.0.1:5001:5000"`.

## Development

```sh
python -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql://user:pass@localhost:5432/lattice
export SECRET_KEY=dev
flask --app wsgi:app db upgrade
flask --app wsgi:app run --debug
```

## Upgrading from netdoc-ipam

The data volume keeps its old name `ipam-db-data`, so your data stays. The defaults changed, though. Put your old values in `.env`:

```
POSTGRES_USER=netdoc_service
POSTGRES_DB=netdoc_prod
POSTGRES_PASSWORD=<your old password>
```

Connector credentials were encrypted with a fallback key. After setting `CONNECTOR_SECRET`, enter them again under Settings → Connectors.

## License

MIT
