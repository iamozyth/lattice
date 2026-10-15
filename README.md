# lattice

Self-hosted IP address management for homelabs and small networks. Flask, PostgreSQL, Docker.

- Subnets in CIDR notation, IPv4 and IPv6, with VLAN, gateway, DNS, location and environment
- An address map per subnet, colored by status, with DHCP pools marked
- Next free address that skips the gateway and DHCP pools
- Drift detection: hosts on the network that aren't documented, documented hosts that went quiet, duplicate MACs and hostnames
- nmap ping sweeps on a schedule, plus on-demand ping and full scans
- UniFi connector that pulls in every client, with a dry-run preview
- Viewer, editor and admin roles
- JSON export and import, REST API with Swagger UI

## 1. Configure

```sh
cp .env.example .env
```

Fill in the three secrets. Generate each one with `openssl rand -hex 32`.

| Variable              | Default    | Description                                            |
|-----------------------|------------|--------------------------------------------------------|
| `POSTGRES_PASSWORD`   | (required) | Database password                                      |
| `SECRET_KEY`          | (required) | Signs login sessions                                   |
| `CONNECTOR_SECRET`    | (required) | Encrypts stored connector credentials                  |
| `POSTGRES_USER`       | `lattice`  | Database user                                          |
| `POSTGRES_DB`         | `lattice`  | Database name                                          |
| `WEB_PORT`            | `5001`     | Host port for the web UI                               |
| `SCAN_INTERVAL_HOURS` | `6`        | How often subnets are ping-swept, `0` turns it off     |
| `STALE_DAYS`          | `30`       | After how many silent days an in-use address is offline |
| `COOKIE_SECURE`       | `false`    | Set to `true` when lattice is served over HTTPS        |
| `TRUST_PROXY`         | `false`    | Set to `true` behind a reverse proxy                   |

The database is only reachable on the internal Docker network.

## 2. Run

```sh
docker compose up -d
```

Open http://localhost:5001 and create the admin account. Database migrations run on every start.

To update:

```sh
git pull
docker compose up -d --build
```

## Users and roles

There is no sign-up page. The admin adds users under Settings and gives each one a role:

| Role     | Can                                                         |
|----------|-------------------------------------------------------------|
| `viewer` | See everything, change nothing                              |
| `editor` | Add, edit and delete subnets, addresses and DHCP ranges; scan |
| `admin`  | Also manage users and connectors, import data               |

Changing a password signs out every other session of that user.

## Subnet map and DHCP ranges

IPv4 subnets up to /22 get a map of every address. Click a free cell to document it, or a used one to edit it. Add your router's DHCP pool under DHCP ranges: next free never hands out an address inside it, and a static address placed inside it shows up as a conflict.

## Scanning and drift

The container ships with nmap and runs it as an unprivileged user with raw-socket capabilities. Every `SCAN_INTERVAL_HOURS` lattice ping-sweeps each IPv4 subnet up to /20. For larger subnets and IPv6 it pings only the documented addresses. You can change this per subnet.

Every host that answers is recorded. Documented addresses get their `last_seen` and missing MAC filled in. The Drift page then shows:

- **Undocumented**: hosts seen on the network with no record. Document or dismiss them.
- **Offline**: in-use addresses that haven't answered for `STALE_DAYS`.
- **Conflicts**: the same MAC or hostname on several records, a MAC that differs from what the network reports, and static addresses inside a DHCP pool.

Things to know:

- The container only sees networks it can reach. On the default bridge network, routed subnets work but MAC addresses don't. Use `network_mode: host` if you want them.
- Full scans (`nmap -sV -O`) are slow and can trip intrusion detection. Ping sweeps are quiet.

## UniFi connector

Under Connectors, add your console's URL and either an API key (UniFi OS: Settings → Control Plane → Integrations) or a local admin username and password. Sync shows a preview first. New clients are added as `in-use`; existing records only get empty fields filled in. Every client also counts as seen for drift.

## API

Docs are at `/openapi/swagger` once you're logged in. The API uses the same session cookie as the UI. Requests that change data need the header `X-Requested-With: lattice`.

## Remote access

Don't expose port 5001 to the internet. Bind it to localhost by changing the `ports` entry in `docker-compose.yml` to `"127.0.0.1:5001:5000"`, then put a TLS reverse proxy in front, for example Caddy:

```
ipam.example.com {
    reverse_proxy 127.0.0.1:5001
}
```

Set `COOKIE_SECURE=true` and `TRUST_PROXY=true` in that case.

## Development

```sh
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
docker compose -f docker-compose.test.yml up -d
.venv/bin/pytest
```

The tests run against the throwaway Postgres from `docker-compose.test.yml`. To run the app against it:

```sh
export DATABASE_URL=postgresql://lattice:lattice@127.0.0.1:55432/lattice_test SECRET_KEY=dev
.venv/bin/flask --app wsgi:app db upgrade
.venv/bin/flask --app wsgi:app run --debug
```

The frontend is plain ES modules and CSS under `app/static`, no build step.

## Upgrading

**From 1.0.0-beta.1:** self-registration is gone. Existing admins stay admins, every other user becomes an editor. Everyone has to log in again.

**From netdoc-ipam:** the data volume keeps its old name `ipam-db-data`, so your data stays. The defaults changed, though. Put your old values in `.env`:

```
POSTGRES_USER=netdoc_service
POSTGRES_DB=netdoc_prod
POSTGRES_PASSWORD=<your old password>
```

## License

MIT
