# NetDoc IPAM

**Professional IP Address Management System**

A self-hosted, Docker-based application for documenting and managing IP addresses, subnets, and network infrastructure.

![Version](https://img.shields.io/badge/version-1.0.0--beta.1-blue)
![License](https://img.shields.io/badge/license-BSL%201.1-orange)
![Docker](https://img.shields.io/badge/docker-ready-blue)

## 🚀 Features

### Core Functionality
- 🌐 **Subnet Management**: Create, edit, and delete subnets with CIDR notation (IPv4 & IPv6 support)
- 📋 **IP Address Tracking**: Document IPs with comprehensive details including hostname, FQDN, MAC, device info, and ownership
- 🔍 **Global Search**: Quickly find subnets and IPs across your entire network
- 📊 **Dashboard Statistics**: Real-time overview of utilization, capacity, and distribution

### Advanced Features
- ✅ **IP Validation**: Automatic validation ensures IPs are within subnet range
- 🔢 **Proper IP Sorting**: Numerically sorted IP addresses (192.168.1.2 < 192.168.1.10)
- 🚫 **Duplicate Prevention**: Prevents duplicate IP entries per subnet
- 🎯 **Next Available IP**: Automatically suggests the next available IP when adding
- 📦 **Bulk Operations**: Add multiple IPs at once with CSV-style input
- 💾 **Export/Import**: Full JSON export and import for backup and migration
- 🔎 **IP Lookup**: Find which subnet contains any IP address

### User Experience
- 🎨 **Modern UI**: Clean, responsive interface built with Tailwind CSS
- 🌓 **Environment Color Coding**: Visual distinction for prod/staging/dev/test
- 📈 **Utilization Bars**: Visual progress indicators for subnet capacity
- 🔔 **Toast Notifications**: Non-intrusive feedback for all actions
- ⌨️ **Keyboard Shortcuts**: Ctrl+K for search, Ctrl+N for new subnet, Esc to close
- 📱 **Mobile Responsive**: Works on all device sizes

### Data Model
- **Subnets**: Name, CIDR, VLAN, gateway, DNS, location, environment, tags
- **IPs**: Address, hostname, FQDN, status, MAC, device type, manufacturer, model, owner, department, notes

## 📖 Quick Start

### Prerequisites
- Docker and Docker Compose installed

### Installation

1. Clone or download the repository:
```bash
git clone <repository-url> netdoc-ipam
cd netdoc-ipam
```

2. (Optional) Copy the environment template and set credentials locally (never commit the real .env). For Portainer stacks you can also set env vars directly in the UI:
```bash
cp .env.example .env
# edit .env with strong, org-approved values
# generate a fresh password: openssl rand -base64 24
# if your password contains @ / : or other special chars, URL-encode it before putting in DATABASE_URL
```
	- Portainer: either set the variables in the stack form or upload/place `.env` alongside the compose file.

3. Start the application:
```bash
docker-compose up -d
```

4. Open your browser: `http://localhost:5000`

5. Start documenting your network!

### Stopping the Application

```bash
docker-compose down
```

### Updating

```bash
docker-compose down
docker-compose pull
docker-compose build --no-cache
docker-compose up -d
```

## 🐳 Docker Configuration

### Container Names
- `ipam-web` - Web application server
- `ipam-db` - PostgreSQL database

### Volumes
- `ipam_db_data` - Persistent database storage

### Networks
- `ipam-network` - Internal bridge network

### Exposure
- Database is not published to the host; it is only reachable on the internal docker network (5432 exposed internally only)

### Environment Variables

All sensitive values are loaded from `.env` (see `.env.example`).

| Variable | Default (from docker-compose) | Description |
|----------|------------------------------|-------------|
| `POSTGRES_USER` | `netdoc_service` | Database role used by the app |
| `POSTGRES_PASSWORD` | `S3cureNetdocP4ssw0rd2026` | Strong URL-safe placeholder (replace per deployment) |
| `POSTGRES_DB` | `netdoc_prod` | Database name |
| `DATABASE_URL` | `postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@ipam-db:5432/${POSTGRES_DB}` | Full connection string consumed by the app |
| `FLASK_ENV` | `production` | Flask environment mode |
| `FLASK_RUN_HOST` | `0.0.0.0` | Bind address inside the container |

## 🔌 API Documentation

**Complete API documentation is available via Swagger UI:**

```
http://localhost:5001/openapi/swagger
```

The interactive Swagger UI allows you to:
- ✅ View all 40 API endpoints
- ✅ See request/response schemas
- ✅ Test endpoints directly from the browser
- ✅ View authentication requirements
- ✅ Download OpenAPI specification (JSON)

Alternative API documentation viewer available at `/openapi/scalar`

### Quick API Overview

**All endpoints require authentication (login first)** except:
- `POST /api/auth/setup` - Initial system setup
- `POST /api/auth/register` - User registration

**Main endpoint categories:**
- Statistics - Dashboard metrics
- Subnets - Subnet management
- IPs - IP address management  
- Scanner - Network discovery
- Import/Export - Data migration
- Lookup - IP utilities
- Authentication - User management

## 📁 Project Structure

```
netdoc-ipam/
├── app/
│   ├── __init__.py          # Flask app factory
│   ├── models.py            # Database models with validation
│   ├── routes.py            # API and web routes
│   ├── static/
│   │   └── js/
│   │       └── app.js       # Frontend JavaScript
│   └── templates/
│       └── index.html       # Web interface
├── Dockerfile               # Container definition
├── docker-compose.yml       # Multi-container setup
├── requirements.txt         # Python dependencies
└── README.md               # This file
```

## 🛠 Technology Stack

| Component | Technology |
|-----------|------------|
| Backend | Python 3.11, Flask, SQLAlchemy |
| Database | PostgreSQL 15 |
| Frontend | HTML5, Tailwind CSS, Vanilla JS |
| Server | Gunicorn WSGI |
| Container | Docker & Docker Compose |

## 📝 IP Statuses

| Status | Description | Color |
|--------|-------------|-------|
| `available` | IP is free for allocation | Green |
| `in-use` | IP is actively assigned | Blue |
| `reserved` | IP is reserved for future use | Amber |
| `blocked` | IP should not be used | Red |
| `dhcp` | IP is managed by DHCP | Purple |
| `deprecated` | IP is being phased out | Gray |

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl/Cmd + K` | Focus global search |
| `Ctrl/Cmd + N` | Open new subnet modal |
| `Escape` | Close any open modal |

## 🔧 Development

### Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Set environment variable
export DATABASE_URL="postgresql://user:pass@localhost:5432/ipam_db"

# Run development server
flask run --debug
```

### Building Custom Images

```bash
docker-compose build --no-cache
```

## 🔒 Security Considerations

- Change default database credentials in production
- Use environment variables for sensitive configuration
- Consider placing behind a reverse proxy with HTTPS
- Implement authentication for production deployments
- Store secrets only in `.env` (never commit it) and rotate the database password regularly

## 📊 Version History

### v2.0.0 (Current)
- Complete UI redesign with dashboard
- IPv6 support
- IP validation and duplicate prevention
- Bulk operations
- Export/Import functionality
- IP Lookup feature
- Environment and location tracking
- Toast notifications
- Keyboard shortcuts
- Mobile responsive design
- Gunicorn production server
- Professional branding (NetDoc IPAM)

### v1.0.0
- Initial release
- Basic subnet and IP management
- Search functionality
- Docker deployment

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

## 📄 License

**Business Source License 1.1 (BSL 1.1)**

This project is licensed under the Business Source License 1.1, with the Change Date set to January 25, 2030.

### What This Means

✅ **You CAN:**
- Use NetDoc IPAM for non-commercial purposes (internal use, research, evaluation)
- Modify the source code for your own non-commercial use
- Deploy it internally for your organization
- Contribute improvements back to the project

❌ **You CANNOT:**
- Use it for commercial purposes without a commercial license
- Offer it as a service to customers or clients
- Resell it or bundle it with commercial products
- Generate revenue directly or indirectly from it

### Commercial Licensing

If you want to use NetDoc IPAM commercially or in a production SaaS environment, please contact the licensor for a commercial license agreement.

### Automatic Conversion

On **January 25, 2030**, this license will automatically convert to **Apache License 2.0** (fully open source with no commercial restrictions).

---

**NetDoc IPAM** - Professional IP Address Management for Modern Networks

MIT
