# NetworkPT — Enhanced Multi-Scan Platform

NetworkPT is an enhanced multi-scan penetration testing dashboard by Ravi Solanki.  
It supports multi-user projects, numbered multiple scan instances (e.g., HTTPx_1, HTTPx_2), individual scan controls (pause/resume/delete), live per-scan output, and enhanced exports (HTML/CSV/TXT/ZIP).

---

## Key Features
- Multi-user projects with per-user storage.
- Multiple instances of the same scan type with automatic numbering.
- Individual scan controls: pause, resume, delete selected scans.
- Live per-scan output (ANSI → HTML rendering in UI).
- Exports: enhanced HTML, CSV, TXT, ZIP with scans grouped by type/number.
- Runs scans in detached screen sessions; preserves full scan history.
- Copy project results server-side to a specified destination (with validation).

---

## Requirements
- OS: Kali Linux (recommended) or other Debian-based Linux.
- Python 3.8+
- screen
- git
- pip
- OpenSSL for HTTPS (cert.pem & key.pem)

Recommended tools (some are Go-based):
- nmap, nuclei, httpx, testssl.sh, nikto, dirsearch, sslscan, ssh-audit, cloud_enum, aquatone, eyewitness

---

## Quick Kali setup
1. Update system:
```bash
sudo apt update && sudo apt upgrade -y
```

2. Install runtime essentials:
```bash
sudo apt install -y python3 python3-venv python3-pip screen git wget unzip
```

3. Create and activate virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install flask flask-cors
```

4. Generate self-signed TLS certs:
```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout key.pem -out cert.pem -subj "/CN=localhost"
```
Place `cert.pem` and `key.pem` beside `NetworkPT.py` to enable HTTPS.

---

## Common tools installation (Kali / apt / go)
Kali often includes many tools. Use apt or Go for missing ones.

Install via apt:
```bash
sudo apt install -y nmap nikto sslscan dirsearch screen
```

Install Go-based tools (requires Go):
```bash
sudo apt install -y golang
export PATH=$PATH:$(go env GOPATH)/bin

go install -v github.com/projectdiscovery/httpx/cmd/httpx@latest
go install -v github.com/projectdiscovery/nuclei/v2/cmd/nuclei@latest
go install github.com/assetnote/cloud_enum@latest
# install other Go tools as needed
```

Install testssl.sh, ssh-audit, aquatone, eyewitness per their repos:
- testssl: https://github.com/drwetter/testssl.sh
- ssh-audit: https://github.com/arthepsy/ssh-audit
- aquatone / eyewitness: follow upstream docs

---

## Run NetworkPT
1. Clone or place the project in a directory:
```bash
cd xyx/xx/x/NetworkPT   # or Linux path where repo lives
source venv/bin/activate                  # if using venv
```

2. Start the server:
- With HTTPS (if certs present):
```bash
sudo python3 NetworkPT.py
# Server will try to start on 0.0.0.0:29525 with SSL if certs exist
```


3. Open the UI:
- HTTPS: https://localhost:29525

Default demo credentials:
- username: `ravi`
- password: `ravi`

Change these credentials in the code or add user-management as needed.

---

## Basic Usage
1. Login.
2. Create a project.
3. Add targets (one per line) in Project → Targets.
4. Start scans per tool or Start All. Each start creates a numbered instance.
5. Go to Live Results to view per-scan output, pause/resume/delete individual scans.
6. Export project results (ZIP/HTML/CSV/TXT) or Copy All Results to a server path.

Notes:
- Scan outputs are stored in: users/<username>/projects/<project_id>/<sanitized_name>/<tool>/
- Each scan creates output files with timestamps and numbered instances to avoid overwriting.

---

## Export & Copy Instructions
- Export buttons produce ZIP/HTML/CSV/TXT downloads grouping scans by type and instance.
- Copy All Results accepts a server-side destination path (validated to avoid traversal). Example:
  - /home/your_user/pentest_results
- Ensure the server process has write permission to the destination path.

---

## Security & Account Guidance
- Some scans (e.g., raw socket nmap full) may require root privileges.
- Protect the server — avoid exposing to untrusted networks without HTTPS and proper auth.
- Use HTTPS in production and secure session cookies.
- Treat scan outputs as sensitive data; store and copy them to secure locations.
- The provided default username/password is for demo — change before production use.

---

## Session Management
### Automatic session pause & auto-delete (application behavior)
- Automatic pause on logout/expiry/inactivity
  - When a session ends (explicit logout) or expires (default 4 hours), NetworkPT will attempt to pause any running scans owned by that user. The server issues SIGSTOP to descendant PIDs of the scan's screen session and marks the scan status as "paused" with a timestamp (paused_at). This prevents orphaned CPU/network activity tied to a logged-out user.
  - Short client-side inactivity is handled by the frontend which warns 5 minutes before expiry and auto-logs out at expiry. Server-side pause happens at logout/expiry to ensure scans do not continue unintentionally.

- Automatic cleanup / auto-delete of paused scans and old projects
  - A background maintenance_worker enforces retention:
    - Paused scans older than 7 days are stopped/removed and marked 'deleted' on disk; their screen sessions (if any) are terminated and in-memory records cleared.
    - Projects older than ~7 months are automatically deleted (including associated files and any active scans).
  - These windows are defaults and can be changed by editing maintenance_worker() in NetworkPT.py:
    - change cutoff_paused = now - timedelta(days=7)
    - change cutoff_projects = now - timedelta(days=30 * 7)
  - Recommendation: shorten or lengthen retention according to storage and compliance needs. For production, consider archiving outputs before automatic deletion.

---

## Other Information
- Maintenance and tuning
  - To adjust automatic pause/cleanup behavior edit maintenance_worker() in NetworkPT.py. Restart the service after changes.
  - For safer production behavior, consider:
    - Lowering session lifetime
    - Increasing pause-to-delete window if you need longer retention
    - Adding an archiving step (copy to long-term storage) before deletion

---

## Troubleshooting
- If screen sessions aren’t created, ensure `screen` is installed and in PATH.
- After a server restart, scan metadata is restored, but screen sessions do not persist — scans will show stopped/stale; re-run if needed.
- If export or copy fails, check server logs for permission or path errors.

---




