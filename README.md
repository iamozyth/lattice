# lattice

Self-hosted IP address management for homelabs and small networks. Flask, PostgreSQL, Docker.

- Subnets in CIDR notation, IPv4 and IPv6, nested as a tree, with gateway, DNS, location and environment
- Free space per subnet: carve out the next free /24 (or any size) in one click
- VLANs and tags as real objects, with filters on both
- An address map per subnet, colored by status, with DHCP pools marked
- Next free address that skips the gateway and DHCP pools
- Drift detection: hosts on the network that aren't documented, documented hosts that went quiet, duplicate MACs and hostnames
- nmap ping sweeps on a schedule, plus on-demand ping and full scans
- UniFi connector that pulls in every client, with a dry-run preview
- Change history: who changed what and when, for every subnet, address, VLAN and setting
- Bulk edit of addresses, CSV import (with preview) and export, including phpIPAM and NetBox column names
- Command palette: Ctrl/⌘ K or `/` to jump to any subnet, find an address or run an action
- Viewer, editor and admin roles, local accounts or single sign-on (authentik or any OIDC provider)
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
| `HISTORY_DAYS`        | `365`      | How long the change history is kept                    |
| `COOKIE_SECURE`       | `false`    | Set to `true` when lattice is served over HTTPS        |
| `TRUST_PROXY`         | `false`    | Set to `true` behind a reverse proxy                   |
| `PUBLIC_URL`          | (request)  | lattice's own URL, e.g. `https://ipam.example.com`; used for the SSO redirect |
| `OIDC_ISSUER` / `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | (none) | [Single sign-on](#single-sign-on-authentik); the secret can also come from `OIDC_CLIENT_SECRET_FILE` |
| `OIDC_NAME`           | `SSO`      | Button label: "Continue with authentik"                |
| `OIDC_ADMIN_GROUPS` / `OIDC_EDITOR_GROUPS` / `OIDC_VIEWER_GROUPS` | `lattice-admins` / `lattice-editors` / `lattice-viewers` | Provider groups (comma-separated) for each role |
| `OIDC_SESSION_HOURS`  | `12`       | SSO sessions end after this long                       |
| `LOCAL_LOGIN`         | `on`       | `off` hides the username/password form (SSO only)      |

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

## Single sign-on (authentik)

lattice can hand sign-in to an OpenID Connect provider: [authentik](https://goauthentik.io), Keycloak, Pocket ID and others. The login page then shows **Continue with authentik**, the provider handles passwords, passkeys and MFA, and the role comes from the person's groups at every sign-in. Local accounts stay as a fallback unless you turn them off.

**In authentik** (Admin interface):

1. **Applications → Providers → Create → OAuth2/OpenID Provider**: client type **Confidential**, redirect URI **strict** `https://ipam.example.com/auth/oidc/callback`, and a **Signing Key** (the built-in self-signed certificate is fine; without one authentik signs with the client secret, which lattice refuses). Under advanced settings, allow the **authorization code** grant.
2. **Applications → Applications → Create**: name `lattice`, with that provider.
3. **Directory → Groups**: `lattice-admins`, `lattice-editors`, `lattice-viewers`, and add people.

**In lattice**: **Settings → Single sign-on**. Switch it on, copy the redirect URI shown there into authentik, paste the issuer URL (`https://auth.example.com/application/o/lattice/`), client ID and secret, and press **Save and test**. It checks that the provider is reachable and is on right away. Try it in a private window before you sign out. You can turn local accounts off once you have signed in with SSO.

Or set `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` and `OIDC_NAME=authentik` in `.env`; values set there show as locked in Settings.

- **Groups decide**: someone in none of the groups is refused and gets no account. A changed group changes the role at the next sign-in and ends sessions with the old role.
- **Accounts**: the first sign-in creates an account named after the provider username, tied to the provider's user ID. It never takes over a local account with the same name; that gets a `-2` suffix instead.
- **Sign out** also ends the provider session.

## Subnets inside subnets

A subnet that sits inside another one shows up under it. Nothing is stored for this: lattice works it out from the CIDRs, so changing a network never leaves a stale parent behind ([why](docs/adr/0001-derived-subnet-hierarchy.md)).

On a subnet's page, "Inside this subnet" lists its children and the free blocks between them. New subnet → Inside → Next free picks the first free block of the size you want. Creating a child moves the documented addresses in its range from the parent into it; deleting the child moves them back.

The words lattice uses are in the [glossary](GLOSSARY.md).

## VLANs, tags and history

VLANs have their own page with the subnets on each one. Tags work on subnets and addresses; unknown tags are created as you type them. Rename, merge or delete them under Settings → Tags.

Every change is recorded with who made it, and passwords and API keys are never stored in it. Activity shows everything, and each subnet and address has its own history. Entries older than `HISTORY_DAYS` are removed daily.

## Bulk edit and CSV

Tick addresses in any table to set their status or owner, add or remove tags, or delete them together. Export CSV on the Subnets and Addresses pages downloads what you're filtering on.

Import CSV accepts files separated by commas, semicolons or tabs, and understands the column names of phpIPAM and NetBox exports (`ip_addr`, `IP Address`, `mac`, …). Addresses are matched to their most specific subnet, and existing ones are updated; empty cells leave a field as it is. You see what will be created, updated or rejected before anything is written, and the import only runs once every row is valid.

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

The frontend is plain ES modules and CSS under `app/static`, no build step. The design follows rconsole's design system with a blue accent.

### Local stack in Docker (OrbStack)

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

Runs the real image at http://localhost:5001 with `app/` mounted, so code changes reload without a rebuild. It uses its own volume, `lattice-dev-data`.

To try single sign-on locally, start the bundled authentik first. A blueprint creates the lattice provider, the three groups and test users (alice: admin, bob: viewer, carol: no group):

```sh
dev/authentik/setup.sh
docker compose -f dev/authentik/compose.yml up -d
```

Then use issuer `http://authentik.localhost:9000/application/o/lattice/`, client ID `lattice` and the `LATTICE_CLIENT_SECRET` from `dev/authentik/.env`. Test users share `LATTICE_TEST_PASSWORD`; the authentik admin is `akadmin` with `AUTHENTIK_BOOTSTRAP_PASSWORD`. The dev stack allows a plain-http provider (`OIDC_ALLOW_HTTP=1`); production needs https.

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
