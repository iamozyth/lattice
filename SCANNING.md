# Network Scanning Feature

The IPAM tool now includes automatic network discovery and verification capabilities using Nmap.

## Features

### 1. **Subnet Network Scanning**
- Discovers live hosts in a subnet
- Supports two scan types:
  - **Ping scan** (fast): Uses ICMP ping to discover live hosts
  - **Full scan** (detailed): Includes OS detection, service discovery, and port scanning

### 2. **Intelligent IP Recommendations**
- Automatically recommends discovered IPs for inventory addition
- Enriches recommendations with:
  - Reverse DNS hostname resolution
  - MAC address identification
  - Device type inference (Router, Server, Printer, etc.)
  - Operating system detection
  - Open ports and running services
  - Confidence scoring (0.0-1.0)

### 3. **Automatic IP Enrichment**
When importing discovered IPs, the tool automatically populates:
- Hostname
- MAC address
- Device type
- Operating system information
- Description with enrichment details

### 4. **Periodic Verification**
Background scheduler automatically:
- Verifies all IPs in all subnets every 6 hours
- Updates `last_seen` timestamp for live IPs
- Marks IPs as "deprecated" if not seen for 30 days
- Runs stale detection daily at 2 AM UTC

## API Endpoints

### Check Scanner Availability
```http
GET /api/scanner/status
```

Response:
```json
{
  "available": true,
  "message": "Nmap is available"
}
```

### Scan a Subnet
```http
POST /api/scanner/scan-subnet/<subnet_id>
Content-Type: application/json

{
  "scan_type": "ping"
}
```

Response includes:
- Discovered hosts with enriched data
- Recommended IPs with confidence scores
- Device types and open ports

### Bulk Import Discovered IPs
```http
POST /api/scanner/bulk-import
Content-Type: application/json

{
  "subnet_id": 1,
  "auto_enrich": true,
  "ips": [
    {
      "address": "192.168.1.10",
      "hostname": "server1",
      "mac_address": "00:11:22:33:44:55",
      "device_type": "Server",
      "status": "in-use"
    }
  ]
}
```

### Verify All IPs in a Subnet
```http
POST /api/scanner/verify/<subnet_id>
```

Returns live/dead status for each IP and updates `last_seen` timestamps.

### Verify Single IP
```http
POST /api/scanner/verify-ip
Content-Type: application/json

{
  "address": "192.168.1.10",
  "subnet_id": 1
}
```

## Workflow Example

1. **Initial Scan**
   ```bash
   curl -X POST http://localhost:5000/api/scanner/scan-subnet/1 \
     -H "Content-Type: application/json" \
     -d '{"scan_type": "ping"}'
   ```

2. **Review Recommendations**
   - Check the returned recommendations sorted by confidence score
   - Filter by device type or other criteria

3. **Bulk Import**
   ```bash
   curl -X POST http://localhost:5000/api/scanner/bulk-import \
     -H "Content-Type: application/json" \
     -d '{
       "subnet_id": 1,
       "auto_enrich": true,
       "ips": [...]
     }'
   ```

4. **Automatic Verification**
   - System periodically verifies IPs automatically
   - Check status with: `GET /api/ips/<ip_id>`
   - Look for `last_seen` timestamp

## Configuration

### Scanner Requirements
- **Nmap** must be installed and in system PATH
- Requires network access to target subnets
- Some systems may require elevated privileges for certain scan types

### Scheduler Configuration
Edit `app/scheduler.py` to customize:
- Verification interval (default: 6 hours)
- Stale IP threshold (default: 30 days)
- Stale check schedule (default: daily at 2 AM UTC)

### Environment Requirements
The following packages are required:
- `nmap` (system package)
- `python-nmap` (Python wrapper)
- `APScheduler` (background job scheduler)

Install system package:
```bash
# Ubuntu/Debian
apt-get install nmap

# macOS
brew install nmap

# CentOS/RHEL
yum install nmap
```

## Limitations & Notes

1. **Permission Requirements**
   - Ping scans: Usually work with standard user privileges
   - Full scans with OS detection: May require elevated privileges

2. **Network Requirements**
   - Scanner must have network access to target subnets
   - Some organizations may block ICMP (ping)
   - Port scanning may trigger security alerts

3. **False Positives**
   - Some devices may not respond to pings but are active
   - MAC address vendor lookup may not always be accurate
   - Device type inference is heuristic-based

4. **Performance**
   - Scans can be slow on large subnets (/20 or larger)
   - Full scans are slower than ping scans
   - Background verification runs in parallel with web service

## Troubleshooting

### Nmap not available
If you get "Nmap not available" error:
1. Install nmap: `apt-get install nmap` (or equivalent for your OS)
2. Restart the application

### Permission denied
If running in Docker:
- Dockerfile already includes nmap installation
- May need to run container with appropriate capabilities

### Slow scans
- Use "ping" scan type for faster discovery
- Consider scanning subnet in smaller ranges
- Schedule scans during off-peak hours

### No hosts discovered
- Check network connectivity to subnet
- Verify firewall allows ICMP
- Try manual ping test first
- Check subnet CIDR format is valid
