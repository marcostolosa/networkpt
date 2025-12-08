#!/usr/bin/env python3

"""
NetworkPT by Ravi Solanki - Enhanced Multi-User Platform with Individual Scan Control

NEW FEATURES V2:
- Individual scan pause/delete controls
- Live project dashboard with scan status
- Enhanced API endpoints for selected scan control
- Improved theme and font sizing
- Copy results activation on live results tab

Enhanced Features:
- Multi-user support with user-specific projects  
- Individual screen sessions for each scan
- ENHANCED: Multiple scans of same type (HTTPx_1, HTTPx_2, etc.)
- ENHANCED: Individual pause and delete for selected scans
- Never delete previous scans - keep all scan history
- Blue, white, orange color theme
- Larger font sizes for better readability
"""

from flask import Flask, jsonify, request, send_file, render_template_string, Response, send_from_directory, session, make_response
from flask_cors import CORS
import os
import subprocess
import json
import uuid
import time
import re
import threading
import signal
from datetime import datetime, timedelta
import csv
import io
import zipfile
import base64
import shutil
import hashlib
import html
import ssl
import traceback

# Initialize Flask app with proper configuration
app = Flask(__name__, static_folder="static")

def process_output_for_live_display(content):
    """Process output to handle progress updates in single line and preserve ANSI colors"""
    if not content:
        return content

    lines = content.split('\n')
    processed_lines = []

    for line in lines:
        # Handle progress patterns like [1/1333] [2/1333] etc. for cloud_enum and dirsearch
        if re.search(r'\[\d+/\d+\]', line):
            # Check if this is a progress update line that should replace previous
            if processed_lines and re.search(r'\[\d+/\d+\]', processed_lines[-1]):
                # Replace the last progress line instead of adding new line
                processed_lines[-1] = line
            else:
                processed_lines.append(line)
        else:
            processed_lines.append(line)

    return '\n'.join(processed_lines)

app.secret_key = "networkpt_ravi_solanki_secure_key_2024_9f8e7d6c5b4a3210"
CORS(app)

# Route for root
@app.route('/')
def home():
    return send_from_directory(app.static_folder, 'index.html')

# Configuration
# Use the directory where the script is started (current working directory)
BASE_DIR = os.path.abspath(os.getcwd())
USERS_DIR = os.path.join(BASE_DIR, "users")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

# Ensure base and users directories exist
os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(USERS_DIR, exist_ok=True)

app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=4)
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

@app.after_request
def set_security_headers(response):
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Strict-Transport-Security'] = 'max-age=63072000; includeSubDomains; preload'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    response.headers['Cross-Origin-Embedder-Policy'] = 'require-corp'
    response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
    return response

# DEFAULT_USERS (replaced with single common default user)
DEFAULT_USERS = {
    "ravi": {"password": "ravi", "role": "admin"}
}

# ENHANCED: Global scan tracking with better organization for multiple scans
ACTIVE_SCANS = {}
SCAN_OUTPUTS = {}
SCAN_COUNTERS = {}  # Track scan numbers per project/user/scan_type

# Ensure directories
os.makedirs(USERS_DIR, exist_ok=True)
os.makedirs(BASE_DIR, exist_ok=True)

def sanitize_name(name):
    """Sanitize project name for filesystem use"""
    sanitized = re.sub(r'[^\w\s-]', '', name)
    sanitized = re.sub(r'[-\s]+', '_', sanitized)
    return sanitized.strip('_')

def get_user_projects_dir(username):
    """Get user-specific projects directory"""
    user_dir = os.path.join(USERS_DIR, username, "projects")
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except:
        config = {"platform": "NetworkPT", "version": "2.0"}
        save_config(config)
        return config

# --- User Authentication ---
def authenticate_user(username, password):
    return username in DEFAULT_USERS and DEFAULT_USERS[username]["password"] == password

def get_current_user():
    return session.get('username', None)

def require_authentication():
    return 'username' in session

@app.before_request
def check_auth():
    public_endpoints = ['/api/login', '/api/health', '/', '/static/']
    
    for endpoint in public_endpoints:
        if request.path.startswith(endpoint):
            return None
    
    if request.path.startswith('/api/'):
        if not require_authentication():
            return jsonify({"error": "Authentication required", "code": "AUTH_REQUIRED"}), 401

# --- Login/Logout endpoints ---
@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({"success": False, "error": "Username and password required"})
        
        if authenticate_user(username, password):
            session['username'] = username
            session['role'] = DEFAULT_USERS[username]['role']
            app.permanent_session_lifetime = timedelta(hours=4)
            return jsonify({
                "success": True,
                "username": username,
                "role": DEFAULT_USERS[username]['role']
            })
        else:
            return jsonify({"success": False, "error": "Invalid credentials"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/logout', methods=['POST'])
def logout():
    username = get_current_user()
    session.clear()

    # Pause all running scans for this user
    if username:
        for scan_id, scan_data in list(ACTIVE_SCANS.items()):
            try:
                if scan_data.get('username') == username and scan_data.get('status') == 'running':
                    session_name = scan_data.get('session')
                    if session_name:
                        # pause the underlying processes (not just screen)
                        pause_screen_session(session_name)
                    ACTIVE_SCANS[scan_id]['status'] = 'paused'
                    ACTIVE_SCANS[scan_id]['paused_at'] = datetime.now().isoformat()
                    # update disk
                    update_project_scan_status_on_disk(username, scan_data.get('project_id'), scan_id, 'paused')
            except Exception as e:
                print(f"Error pausing scan {scan_id} on logout: {e}")

    return jsonify({"success": True, "message": "Logged out and paused active scans"})

def get_project_info(username, project_id):
    try:
        projects_dir = get_user_projects_dir(username)
        project_path = os.path.join(projects_dir, project_id)
        info_file = os.path.join(project_path, 'info.json')
        if os.path.exists(info_file):
            with open(info_file, 'r') as f:
                return json.load(f)
        return None
    except Exception as e:
        print(f"Error getting project info: {e}")
        return None

def write_project_info(username, project_id, project_info):
    try:
        projects_dir = get_user_projects_dir(username)
        project_path = os.path.join(projects_dir, project_id)
        info_file = os.path.join(project_path, 'info.json')
        with open(info_file, 'w') as f:
            json.dump(project_info, f, indent=2)
        return True
    except Exception as e:
        print(f"Error writing project info: {e}")
        return False

# ENHANCED: Get next scan number for multiple scans of same type
def get_next_scan_number(project_id, scan_type, username):
    """Get the next scan number for a given scan type in a project"""
    existing_count = 0
    processed_scan_ids = set()
    
    # Count from ACTIVE_SCANS first
    for scan_id, scan_data in ACTIVE_SCANS.items():
        if (scan_data.get('project_id') == project_id and
            scan_data.get('scan_type') == scan_type and
            scan_data.get('username') == username):
            existing_count += 1
            processed_scan_ids.add(scan_id)
    
    # Count from project_info, but avoid double counting by checking scan IDs
    project_info = get_project_info(username, project_id)
    if project_info and 'scans' in project_info:
        for scan in project_info['scans']:
            scan_id = scan.get('id')
            if (scan_id not in processed_scan_ids and 
                (scan.get('type') == scan_type or scan.get('scan_type') == scan_type)):
                existing_count += 1
                processed_scan_ids.add(scan_id)
    
    return existing_count + 1


# ENHANCED: Generate unique scan ID with proper numbering
def generate_scan_id_with_number(project_id, scan_type, username):
    """Generate a unique scan ID with proper numbering (e.g., HTTPx_1, HTTPx_2)"""
    scan_number = get_next_scan_number(project_id, scan_type, username)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_suffix = str(uuid.uuid4())[:6]
    
    # Create scan ID with number
    scan_id = f"{project_id}_{scan_type}_{scan_number}_{timestamp}_{unique_suffix}"
    
    # Ensure uniqueness
    counter = 1
    base_scan_id = scan_id
    while scan_id in ACTIVE_SCANS or scan_id in SCAN_OUTPUTS:
        scan_id = f"{base_scan_id}_{counter}"
        counter += 1
        if counter > 100:  # Prevent infinite loop
            break
    
    return scan_id, scan_number

# --- Screen helpers ---
def session_name_for_scan(scan_id):
    s = re.sub(r'[^A-Za-z0-9_\-]', '_', scan_id)
    return f"npt_{s}"

def get_screen_pid(session_name):
    try:
        out = subprocess.check_output(['ps', '-eo', 'pid,cmd'], text=True)
        for line in out.splitlines():
            if 'SCREEN' in line or 'screen' in line:
                if session_name in line:
                    parts = line.strip().split(None, 1)
                    pid = int(parts[0])
                    return pid
    except Exception as e:
        print(f"get_screen_pid error: {e}")
    return None

def start_screen_session(scan_id, cmd, project_path, output_file, latest_file):
    try:
        session = session_name_for_scan(scan_id)
        shell_cmd = f'cd "{project_path}" && {cmd} > "{output_file}" 2>&1; echo "__SCAN_EXIT__" >> "{latest_file}"'
        subprocess.run(['screen', '-dmS', session, 'bash', '-lc', shell_cmd], check=False)
        return session
    except Exception as e:
        print(f"Error starting screen session: {e}")
        return None

def stop_screen_session(session):
    try:
        subprocess.run(['screen', '-S', session, '-X', 'quit'], check=False)
        return True
    except Exception as e:
        print(f"Error stopping screen session: {e}")
        return False

def get_all_descendant_pids(parent_pid):
    try:
        output = subprocess.check_output(
            ["pstree", "-p", str(parent_pid)],
            text=True, stderr=subprocess.DEVNULL
        )
        pids = re.findall(r'\((\d+)\)', output)
        return [int(pid) for pid in pids if int(pid) != parent_pid]
    except:
        try:
            output = subprocess.check_output(
                ["ps", "-eo", "pid,ppid", "--no-headers"], text=True
            )
            all_pids = {}
            for line in output.strip().split("\n"):
                if line.strip():
                    pid, ppid = map(int, line.split())
                    all_pids.setdefault(ppid, []).append(pid)
            
            def recurse(pid):
                res = []
                for c in all_pids.get(pid, []):
                    res.append(c)
                    res.extend(recurse(c))
                return res
            
            return recurse(parent_pid)
        except:
            return []

def pause_screen_session(session):
    screen_pid = get_screen_pid(session)
    if not screen_pid:
        return False
    
    paused = False
    for pid in get_all_descendant_pids(screen_pid):
        try:
            stat = subprocess.check_output(
                ["ps", "-o", "stat=", "-p", str(pid)], text=True
            ).strip()
            if "T" not in stat:
                os.kill(pid, signal.SIGSTOP)
                paused = True
        except:
            pass
    return paused

def resume_screen_session(session):
    screen_pid = get_screen_pid(session)
    if not screen_pid:
        return False
    
    resumed = False
    for pid in get_all_descendant_pids(screen_pid):
        try:
            stat = subprocess.check_output(
                ["ps", "-o", "stat=", "-p", str(pid)], text=True
            ).strip()
            if "T" in stat:
                os.kill(pid, signal.SIGCONT)
                time.sleep(0.1)
                resumed = True
        except:
            pass
    return resumed

def restore_scans_from_projects():
    """Restore scans from info.json into ACTIVE_SCANS and SCAN_OUTPUTS"""
    try:
        for user in os.listdir(USERS_DIR):
            user_projects = os.path.join(USERS_DIR, user, "projects")
            if not os.path.isdir(user_projects):
                continue

            for project_id in os.listdir(user_projects):
                project_path = os.path.join(user_projects, project_id)
                info_file = os.path.join(project_path, "info.json")

                if os.path.exists(info_file):
                    with open(info_file, "r") as f:
                        project_info = json.load(f)

                    for scan in project_info.get("scans", []):
                        scan_id = scan.get("id")
                        if not scan_id:
                            continue

                        # If scan was running before restart, mark as stopped
                        status = scan.get("status", "completed")
                        if status == "running":
                            status = "stopped"

                        # Restore minimal scan info
                        ACTIVE_SCANS[scan_id] = {
                            "status": status,
                            "started": scan.get("started"),
                            "completed": scan.get("completed", None),
                            "project_id": project_id,
                            "scan_type": scan.get("scan_type", scan.get("type")),
                            "scan_number": scan.get("scan_number"),
                            "display_name": scan.get("display_name"),
                            "session": None,  # Sessions don't survive restart
                            "output_file": scan.get("output_file"),
                            "username": project_info.get("username", user),
                            "command": scan.get("command")
                        }

                        # Load last output if available
                        output_file = scan.get("output_file")
                        if output_file and os.path.exists(output_file):
                            try:
                                with open(output_file, "r", encoding="utf-8", errors="ignore") as of:
                                    SCAN_OUTPUTS[scan_id] = of.read()
                            except:
                                SCAN_OUTPUTS[scan_id] = ""
    except Exception as e:
        print(f"❌ Error restoring scans: {e}")
def update_project_scan_status_on_disk(username, project_id, scan_id, new_status):
    """Update the scan status in project's info.json if present."""
    try:
        projects_dir = get_user_projects_dir(username)
        project_path = os.path.join(projects_dir, project_id)
        info_file = os.path.join(project_path, 'info.json')
        if not os.path.exists(info_file):
            return False
        with open(info_file, 'r') as f:
            proj = json.load(f)
        changed = False
        for s in proj.get('scans', []):
            if s.get('id') == scan_id:
                if s.get('status') != new_status:
                    s['status'] = new_status
                    if new_status == 'paused':
                        s['paused_at'] = datetime.now().isoformat()
                    if new_status in ('stopped','completed','deleted'):
                        s['completed'] = datetime.now().isoformat()
                    changed = True
        if changed:
            write_project_info(username, project_id, proj)
        return changed
    except Exception as e:
        print(f"update disk status error: {e}")
        return False


def remove_scan_from_disk_record(username, project_id, scan_id):
    """Remove scan entry from project's info.json (used for purge)."""
    try:
        projects_dir = get_user_projects_dir(username)
        project_path = os.path.join(projects_dir, project_id)
        info_file = os.path.join(project_path, 'info.json')
        if not os.path.exists(info_file):
            return False
        with open(info_file, 'r') as f:
            proj = json.load(f)
        original_len = len(proj.get('scans', []))
        proj['scans'] = [s for s in proj.get('scans', []) if s.get('id') != scan_id]
        if len(proj['scans']) != original_len:
            write_project_info(username, project_id, proj)
            return True
        return False
    except Exception as e:
        print(f"remove_scan_from_disk_record error: {e}")
        return False


# Background maintenance: pause removal after 7 days, project deletion after 7 months
def maintenance_worker():
    """Runs daily to enforce retention rules:
       - If a scan has been paused for >7 days: stop screen, remove ACTIVE_SCANS/SCAN_OUTPUTS, and update disk
       - If a project was created >7 months ago: delete project directory
    """
    while True:
        try:
            now = datetime.now()

            # 1) Clean paused scans older than 7 days
            cutoff_paused = now - timedelta(days=7)
            for scan_id, scan_data in list(ACTIVE_SCANS.items()):
                try:
                    if scan_data.get('status') == 'paused':
                        paused_at = scan_data.get('paused_at') or scan_data.get('paused_at_disk')
                        if paused_at:
                            paused_dt = datetime.fromisoformat(paused_at)
                            if paused_dt < cutoff_paused:
                                # stop screen session (if any) and remove
                                session_name = scan_data.get('session')
                                if session_name:
                                    stop_screen_session(session_name)
                                username = scan_data.get('username')
                                project_id = scan_data.get('project_id')
                                # update disk to mark deleted
                                update_project_scan_status_on_disk(username, project_id, scan_id, 'deleted')
                                # remove from memory
                                if scan_id in ACTIVE_SCANS:
                                    del ACTIVE_SCANS[scan_id]
                                if scan_id in SCAN_OUTPUTS:
                                    del SCAN_OUTPUTS[scan_id]
                                print(f"Maintenance: removed paused scan {scan_id} (older than 7 days)")
                except Exception as e:
                    print(f"Error cleaning paused scan {scan_id}: {e}")

            # 2) Delete projects older than 7 months
            cutoff_projects = now - timedelta(days=30 * 7)  # approx 7 months
            for user in os.listdir(USERS_DIR):
                user_projects = os.path.join(USERS_DIR, user, 'projects')
                if not os.path.isdir(user_projects):
                    continue
                for project_id in os.listdir(user_projects):
                    try:
                        project_path = os.path.join(user_projects, project_id)
                        info_file = os.path.join(project_path, 'info.json')
                        if os.path.exists(info_file):
                            with open(info_file, 'r') as f:
                                proj = json.load(f)
                            created = proj.get('created')
                            if created:
                                created_dt = datetime.fromisoformat(created)
                                if created_dt < cutoff_projects:
                                    # stop active scans for project
                                    for scan_id, scan_data in list(ACTIVE_SCANS.items()):
                                        if scan_data.get('project_id') == project_id:
                                            session_name = scan_data.get('session')
                                            if session_name:
                                                stop_screen_session(session_name)
                                            del ACTIVE_SCANS[scan_id]
                                            if scan_id in SCAN_OUTPUTS:
                                                del SCAN_OUTPUTS[scan_id]
                                    # delete project directory
                                    shutil.rmtree(project_path)
                                    print(f"Maintenance: deleted project {project_id} for user {user} (older than 7 months)")
                    except Exception as e:
                        print(f"Error cleaning project {project_id}: {e}")

        except Exception as e:
            print(f"Maintenance worker error: {e}")

        # Sleep 24 hours
        time.sleep(60 * 60 * 24)

# Start maintenance thread
maintenance_thread = threading.Thread(target=maintenance_worker, daemon=True)
maintenance_thread.start()


# ENHANCED: Run command with proper scan numbering and tracking
def run_command_live_via_screen(cmd, project_path, project_name, scan_type, scan_id, scan_number, username):
    """Start command in screen and track output files with proper numbering"""
    try:
        safe_project_name = sanitize_name(project_name)
        output_dir = os.path.join(project_path, safe_project_name, scan_type)
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # ENHANCED: Include scan number in file names
        output_file = os.path.join(output_dir, f"NP_{scan_type}_{scan_number}_output_{timestamp}.txt")
        latest_file = os.path.join(output_dir, f"{scan_type}_{scan_number}_latest.txt")
        
        # Initialize scan tracking with enhanced metadata
        ACTIVE_SCANS[scan_id] = {
            'status': 'running',
            'started': datetime.now().isoformat(),
            'project_id': project_path.split('/')[-1],
            'scan_type': scan_type,
            'scan_number': scan_number,
            'display_name': f"{scan_type.upper()}_{scan_number}",
            'session': None,
            'output_file': output_file,
            'latest_file': latest_file,
            'output_dir': output_dir,
            'username': username,
            'command': cmd
        }
        
        SCAN_OUTPUTS[scan_id] = ""
        
        # Start screen session
        session_name = start_screen_session(scan_id, cmd, project_path, output_file, latest_file)
        ACTIVE_SCANS[scan_id]['session'] = session_name
        
        # Save PID if possible
        pid = get_screen_pid(session_name) if session_name else None
        ACTIVE_SCANS[scan_id]['pid'] = pid
        
        # ENHANCED: Update project info with scan numbering
        project_info = get_project_info(username, ACTIVE_SCANS[scan_id]['project_id'])
        if project_info is None:
            project_info = {"id": ACTIVE_SCANS[scan_id]['project_id'], "name": project_name, "scans": []}
        
        scan_entry = {
            "id": scan_id,
            "type": scan_type,
            "scan_type": scan_type,
            "scan_number": scan_number,
            "display_name": f"{scan_type.upper()}_{scan_number}",
            "status": "running",
            "started": ACTIVE_SCANS[scan_id]['started'],
            "command": cmd,
            "session": session_name,
            "output_file": output_file
        }
        
        project_info.setdefault('scans', []).append(scan_entry)
        write_project_info(username, ACTIVE_SCANS[scan_id]['project_id'], project_info)
        
        # Start watcher thread
        def watcher():
            try:
                while True:
                    if scan_id not in ACTIVE_SCANS:
                        break
                    
                    if os.path.exists(output_file):
                        try:
                            with open(output_file, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read()
                                SCAN_OUTPUTS[scan_id] = process_output_for_live_display(content)
                        except:
                            pass
                    
                    finished = False
                    if os.path.exists(latest_file):
                        try:
                            with open(latest_file, 'r', encoding='utf-8', errors='ignore') as f:
                                latest_content = f.read()
                                finished = "__SCAN_EXIT__" in latest_content
                        except:
                            pass
                    
                    if finished:
                        ACTIVE_SCANS[scan_id]['status'] = 'completed'
                        ACTIVE_SCANS[scan_id]['completed'] = datetime.now().isoformat()
                        
                        proj = get_project_info(username, ACTIVE_SCANS[scan_id]['project_id'])
                        if proj:
                            for s in proj.get('scans', []):
                                if s.get('id') == scan_id:
                                    s['status'] = 'completed'
                                    s['completed'] = ACTIVE_SCANS[scan_id]['completed']
                            write_project_info(username, ACTIVE_SCANS[scan_id]['project_id'], proj)
                        break
                    
                    time.sleep(2)  # Check every 2 seconds
                    
            except Exception as e:
                print(f"Watcher error for scan {scan_id}: {e}")
        
        t = threading.Thread(target=watcher, daemon=True)
        t.start()
        
        return {"success": True, "output_file": output_file, "latest_file": latest_file, "output_dir": output_dir}
        
    except Exception as e:
        print(f"Error in run_command_live_via_screen: {e}")
        if scan_id in ACTIVE_SCANS:
            ACTIVE_SCANS[scan_id]['status'] = 'error'
            ACTIVE_SCANS[scan_id]['error'] = str(e)
        return {"success": False, "error": str(e)}

def start_scan_thread(cmd, project_path, project_name, scan_type, scan_id, scan_number, username):
    """Start scan using screen in a separate thread"""
    thread = threading.Thread(
        target=run_command_live_via_screen,
        args=(cmd, project_path, project_name, scan_type, scan_id, scan_number, username)
    )
    thread.daemon = True
    thread.start()

# API Endpoints
@app.route('/api/config', methods=['GET', 'POST'])
def config():
    try:
        if request.method == 'GET':
            return jsonify(load_config())
        
        config_data = request.get_json()
        if not config_data:
            return jsonify({"success": False, "error": "No configuration data provided"})
        
        save_config(config_data)
        return jsonify({"success": True})
    except Exception as e:
        print(f"Config error: {e}")
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/projects', methods=['GET', 'POST'])
def projects():
    try:
        username = get_current_user()
        if not username:
            return jsonify({"error": "Authentication required"}), 401
        
        projects_dir = get_user_projects_dir(username)
        
        if request.method == 'GET':
            projects = []
            if os.path.exists(projects_dir):
                for item in os.listdir(projects_dir):
                    project_path = os.path.join(projects_dir, item)
                    if os.path.isdir(project_path):
                        info_file = os.path.join(project_path, 'info.json')
                        if os.path.exists(info_file):
                            with open(info_file, 'r') as f:
                                project_data = json.load(f)
                            
                            targets_file = os.path.join(project_path, 'targets.txt')
                            if os.path.exists(targets_file):
                                with open(targets_file, 'r') as tf:
                                    targets = [line.strip() for line in tf.readlines() if line.strip()]
                                    project_data['targets_count'] = len(targets)
                            else:
                                project_data['targets_count'] = 0
                            
                            projects.append(project_data)
            
            return jsonify({"projects": projects})
        
        # POST request - create project
        data = request.get_json()
        if not data or not data.get('name'):
            return jsonify({"success": False, "error": "Project name is required"})
        
        project_id = str(uuid.uuid4())[:8]
        project_name = data['name']
        sanitized_name = sanitize_name(project_name)
        project_path = os.path.join(projects_dir, project_id)
        os.makedirs(project_path, exist_ok=True)
        
        # Create tool directories
        tools = [
            'nmap', 'nuclei', 'testssl', 'nikto', 'dirsearch', 'httpx',
            'udp_proto_scan', 'sslscan', 'ssh_audit', 'cloud_enum',
            'nmap_full_tcp', 'aquatone', 'eyewitness', 'nmap_selective_port'
        ]
        
        for tool in tools:
            tool_dir = os.path.join(project_path, sanitized_name, tool)
            os.makedirs(tool_dir, exist_ok=True)
        
        project_info = {
            "id": project_id,
            "name": project_name,
            "sanitized_name": sanitized_name,
            "description": data.get('description', ''),
            "created": datetime.now().isoformat(),
            "scans": [],
            "username": username
        }
        
        with open(os.path.join(project_path, 'info.json'), 'w') as f:
            json.dump(project_info, f, indent=2)
        
        return jsonify({"success": True, "project_id": project_id})
        
    except Exception as e:
        print(f"Projects error: {e}")
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/projects/<project_id>/targets', methods=['GET', 'POST'])
def targets(project_id):
    try:
        username = get_current_user()
        if not username:
            return jsonify({"error": "Authentication required"}), 401
        
        projects_dir = get_user_projects_dir(username)
        project_path = os.path.join(projects_dir, project_id)
        targets_file = os.path.join(project_path, 'targets.txt')
        
        if request.method == 'GET':
            try:
                with open(targets_file, 'r') as f:
                    targets = [line.strip() for line in f.readlines() if line.strip()]
                return jsonify({"targets": targets})
            except:
                return jsonify({"targets": []})
        
        # POST request - add/update targets
        data = request.get_json()
        if not data or not data.get('targets'):
            return jsonify({"success": False, "error": "No targets provided"})
        
        new_targets = data['targets'].strip().split('\n')
        mode = data.get('mode', 'replace')
        
        clean_targets = []
        for target in new_targets:
            target = target.strip()
            if target and not target.startswith('#'):
                clean_targets.append(target)
        
        if mode == 'update':
            existing_targets = []
            if os.path.exists(targets_file):
                with open(targets_file, 'r') as f:
                    existing_targets = [line.strip() for line in f.readlines() if line.strip()]
            all_targets = list(set(existing_targets + clean_targets))
        else:
            all_targets = clean_targets
        
        os.makedirs(project_path, exist_ok=True)
        with open(targets_file, 'w') as f:
            for target in all_targets:
                f.write(target + '\n')
        
        return jsonify({"success": True, "total_targets": len(all_targets), "new_targets": len(clean_targets)})
        
    except Exception as e:
        print(f"Targets error: {e}")
        return jsonify({"success": False, "error": str(e)})

# ENHANCED: Start scan with proper numbering
@app.route('/api/projects/<project_id>/scan', methods=['POST'])
def start_scan(project_id):
    try:
        username = get_current_user()
        if not username:
            return jsonify({"error": "Authentication required"}), 401
        
        data = request.get_json()
        if not data or not data.get('scan_type'):
            return jsonify({"success": False, "error": "Scan type is required"})
        
        scan_type = data['scan_type']
        
        # ENHANCED: Generate scan ID with proper numbering
        scan_id, scan_number = generate_scan_id_with_number(project_id, scan_type, username)
        
        projects_dir = get_user_projects_dir(username)
        project_path = os.path.join(projects_dir, project_id)
        targets_file = os.path.join(project_path, 'targets.txt')
        
        project_info = get_project_info(username, project_id)
        if not project_info:
            return jsonify({"success": False, "error": "Project not found"})
        
        project_name = project_info['name']
        
        if not os.path.exists(targets_file):
            return jsonify({"success": False, "error": "No targets found. Please add targets first."})
        
        with open(targets_file, 'r') as f:
            targets_list = [line.strip() for line in f.readlines() if line.strip()]
        
        if not targets_list:
            return jsonify({"success": False, "error": "No valid targets found."})
        
        safe_project_name = sanitize_name(project_name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S");
        
        # ENHANCED: Commands with scan number in output paths
        commands = {
            'ssh_audit': f"ssh-audit -T {project_path}/targets.txt --no-colors",
            'nmap_selective_port': f"nmap -Pn -sV -sC -p 110,11211,119,123,137,138,139,143,1433,1434,1521,161,162,1873,20,2049,21,22,23,25,27017,27018,27019,3306,3389,3690,389,4000,443,445,465,50000,50070,50075,514,53,5432,587,5900,5984,61616,631,636,6379,6660,6661,6662,6663,6664,6665,6666,6667,6668,6669,67,68,80,8000,8080,8443,8888,9000,9092,9200,9300,9443,993,995,8843,8880,2022,20022,1935,2379,2380,6443,10250,10256,30138,30459,30514,30565,30888,31340,32408,32541,50001,9080 -T4 -iL {project_path}/targets.txt -oA {project_path}/{safe_project_name}/nmap_selective_port/nmap_selective_port_{scan_number}_{timestamp}",
            'nmap_default_scan': f"nmap -Pn -sV -sC -iL {project_path}/targets.txt -oA {project_path}/{safe_project_name}/nmap/nmap_default_scan_{scan_number}_{timestamp}",
            'nmap_full_tcp': f"nmap -sV -sC -T4 -p- -iL {project_path}/targets.txt -oA {project_path}/{safe_project_name}/nmap_full_tcp/nmap-full-tcp_{scan_number}_{timestamp}",
            'nuclei': f"nuclei -l {project_path}/targets.txt -nc -no-mhe -o {project_path}/{safe_project_name}/nuclei/nuclei-output_{scan_number}_{timestamp}.txt",
            'testssl': f"testssl -iL {project_path}/targets.txt --color 0 -oA {project_path}/{safe_project_name}/testssl/testssl-output_{scan_number}_{timestamp}",
            'sslscan': f"sslscan --targets={project_path}/targets.txt --no-colour --xml={project_path}/{safe_project_name}/sslscan/sslscan_{scan_number}_{timestamp}.xml",
            'nikto': f"nikto -h {project_path}/targets.txt -o {project_path}/{safe_project_name}/nikto/nikto-output_{scan_number}_{timestamp}.txt",
            'dirsearch': f"dirsearch -l {project_path}/targets.txt --no-color -o {project_path}/{safe_project_name}/dirsearch/dirsearch-output_{scan_number}_{timestamp}.txt",
            'httpx': f"httpx -l {project_path}/targets.txt -o {project_path}/{safe_project_name}/httpx/httpx-output_{scan_number}_{timestamp}.txt",
            'udp_proto_scan': f"udp-proto-scanner.pl -f {project_path}/targets.txt",
            'cloud_enum': f"cloud_enum -kf {project_path}/targets.txt -t 100 -l {project_path}/{safe_project_name}/cloud_enum/cloud_enum_{scan_number}_{timestamp}.txt",
            'aquatone': f"cat {project_path}/targets.txt | aquatone -out {project_path}/{safe_project_name}/aquatone/aquatone-output_{scan_number}_{timestamp}",
            'eyewitness': f"eyewitness -f {project_path}/targets.txt --no-prompt --prepend-https --max-retries 15 -d {project_path}/{safe_project_name}/eyewitness/eyewitness_{scan_number}_{timestamp} --web"
        }
        
        if scan_type not in commands:
            return jsonify({"success": False, "error": "Invalid scan type"})
        
        # Start scan with scan number
        start_scan_thread(commands[scan_type], project_path, project_name, scan_type, scan_id, scan_number, username)
        
        return jsonify({
            "success": True, 
            "scan_id": scan_id,
            "scan_number": scan_number,
            "display_name": f"{scan_type.upper()}_{scan_number}"
        })
        
    except Exception as e:
        print(f"Start scan error: {e}")
        return jsonify({"success": False, "error": str(e)})

# NEW: Pause selected scan endpoint
@app.route('/api/scan/pause', methods=['POST'])
def pause_selected_scan():
    try:
        username = get_current_user()
        if not username:
            return jsonify({"error": "Authentication required"}), 401
        
        data = request.get_json()
        scan_id = data.get('scan_id')
        
        if not scan_id:
            return jsonify({"success": False, "error": "Scan ID is required"})
        
        if scan_id not in ACTIVE_SCANS:
            return jsonify({"success": False, "error": "Scan not found"})
        
        scan_data = ACTIVE_SCANS[scan_id]
        
        # Check if user owns this scan
        if scan_data.get('username') != username:
            return jsonify({"success": False, "error": "Access denied"})
        
        if scan_data.get('status') != 'running':
            return jsonify({"success": False, "error": f"Cannot pause scan in '{scan_data.get('status')}' status"})
        
        session_name = scan_data.get('session')
        if not session_name:
            return jsonify({"success": False, "error": "No session found for this scan"})
        
        if pause_screen_session(session_name):
            ACTIVE_SCANS[scan_id]['status'] = 'paused'
            ACTIVE_SCANS[scan_id]['paused_at'] = datetime.now().isoformat()
            
            return jsonify({
                "success": True,
                "message": f"Scan {scan_data.get('display_name', scan_id)} paused successfully"
            })
        else:
            return jsonify({"success": False, "error": "Failed to pause scan"})
        
    except Exception as e:
        print(f"Pause scan error: {e}")
        return jsonify({"success": False, "error": str(e)})


# Improve delete_selected_scan to also update disk record
@app.route('/api/scan/delete', methods=['POST'])
def delete_selected_scan():
    try:
        username = get_current_user()
        if not username:
            return jsonify({"error": "Authentication required"}), 401

        data = request.get_json()
        scan_id = data.get('scan_id')

        if not scan_id:
            return jsonify({"success": False, "error": "Scan ID is required"})

        if scan_id not in ACTIVE_SCANS:
            # if not in memory, still try to remove from disk
            # search across user's projects
            for proj in os.listdir(get_user_projects_dir(username)) if os.path.exists(get_user_projects_dir(username)) else []:
                removed = remove_scan_from_disk_record(username, proj, scan_id)
                if removed:
                    return jsonify({"success": True, "message": f"Scan {scan_id} removed from disk record"})
            return jsonify({"success": False, "error": "Scan not found"})

        scan_data = ACTIVE_SCANS[scan_id]

        # Check if user owns this scan
        if scan_data.get('username') != username:
            return jsonify({"success": False, "error": "Access denied"})

        # Stop the scan first if it's running
        session_name = scan_data.get('session')
        if session_name and scan_data.get('status') in ('running', 'paused'):
            stop_screen_session(session_name)

        # Remove from active scans and outputs
        display_name = scan_data.get('display_name', scan_id)
        project_id = scan_data.get('project_id')

        del ACTIVE_SCANS[scan_id]
        if scan_id in SCAN_OUTPUTS:
            del SCAN_OUTPUTS[scan_id]

        # update disk to mark deleted or remove entry
        update_project_scan_status_on_disk(username, project_id, scan_id, 'deleted')

        return jsonify({
            "success": True,
            "message": f"Scan {display_name} deleted successfully"
        })

    except Exception as e:
        print(f"Delete scan error: {e}")
        return jsonify({"success": False, "error": str(e)})
import html

@app.route('/api/projects/<project_id>/live-output-by-scan')
def get_live_output_by_scan(project_id):
    """Get live output separated by individual scans, always escaped (raw view)."""
    try:
        username = get_current_user()
        if not username:
            return jsonify({"error": "Authentication required"}), 401

        scan_outputs = {}

        for scan_id, output in SCAN_OUTPUTS.items():
            scan_info = ACTIVE_SCANS.get(scan_id, {})
            if ((scan_info.get('project_id') == project_id or scan_id.startswith(project_id)) and 
                scan_info.get('username') == username):
                
                scan_type = scan_info.get('scan_type', 'unknown')
                status = scan_info.get('status', 'unknown')
                scan_number = scan_info.get('scan_number', 1)
                display_name = scan_info.get('display_name', f"{scan_type.upper()}_{scan_number}")

                # Escape everything → tags & styles show as raw
                safe_output = html.escape(output or "")

                scan_outputs[scan_id] = {
                    'output': safe_output,
                    'status': status,
                    'scan_type': scan_type,
                    'scan_number': scan_number,
                    'display_name': display_name,
                    'started': scan_info.get('started'),
                    'pid': scan_info.get('pid'),
                    'tab_name': f"{scan_type}_{scan_id}"
                }

        return jsonify({"scan_outputs": scan_outputs})

    except Exception as e:
        print(f"Live output by scan error: {e}")
        return jsonify({"scan_outputs": {}, "error": str(e)})

        


# Continue with other endpoints (start all, pause all, resume all, stop all, export, etc.)
@app.route('/api/projects/<project_id>/scans/start-all', methods=['POST'])
def start_all_scans(project_id):
    try:
        username = get_current_user()
        if not username:
            return jsonify({"error": "Authentication required"}), 401
        
        project_info = get_project_info(username, project_id)
        if not project_info:
            return jsonify({"success": False, "message": "Project not found"})
        
        projects_dir = get_user_projects_dir(username)
        project_path = os.path.join(projects_dir, project_id)
        targets_file = os.path.join(project_path, 'targets.txt')
        
        if not os.path.exists(targets_file):
            return jsonify({"success": False, "message": "No targets found. Please add targets first."})
        
        with open(targets_file, 'r') as f:
            targets = [line.strip() for line in f if line.strip()]
        
        if not targets:
            return jsonify({"success": False, "message": "No valid targets found."})
        
        project_name = project_info['name']
        safe_project_name = sanitize_name(project_name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # All available scan types
        scan_types = [
            'ssh_audit', 'nmap_selective_port', 'nmap_default_scan', 'nmap_full_tcp',
            'nuclei', 'testssl', 'sslscan', 'nikto', 'dirsearch', 'httpx',
            'udp_proto_scan', 'cloud_enum', 'aquatone', 'eyewitness'
        ]
        
        started = 0
        for scan_type in scan_types:
            scan_id, scan_number = generate_scan_id_with_number(project_id, scan_type, username)
            
            commands = {
                'ssh_audit': f"ssh-audit -T {project_path}/targets.txt --no-colors -l fail",
                'nmap_selective_port': f"nmap -Pn -sV -sC -p 21,22,23,25,53,80,110,111,135,139,143,443,993,995,1723,3389,5900,8080,8443 -T4 -iL {project_path}/targets.txt -oA {project_path}/{safe_project_name}/nmap_selective_port/nmap_selective_port_{scan_number}_{timestamp}",
                'nmap_default_scan': f"nmap -Pn -sV -sC -iL {project_path}/targets.txt -oA {project_path}/{safe_project_name}/nmap/nmap_default_scan_{scan_number}_{timestamp}",
                'nmap_full_tcp': f"nmap -sV -sC -T4 -p- -iL {project_path}/targets.txt -oA {project_path}/{safe_project_name}/nmap_full_tcp/nmap-full-tcp_{scan_number}_{timestamp}",
                'nuclei': f"nuclei -l {project_path}/targets.txt -nc -no-mhe -o {project_path}/{safe_project_name}/nuclei/nuclei-output_{scan_number}_{timestamp}.txt",
                'testssl': f"testssl -iL {project_path}/targets.txt --color 0 -oA {project_path}/{safe_project_name}/testssl/testssl-output_{scan_number}_{timestamp}",
                'sslscan': f"sslscan --targets={project_path}/targets.txt --no-colour --xml={project_path}/{safe_project_name}/sslscan/sslscan_{scan_number}_{timestamp}.xml",
                'nikto': f"nikto -h {project_path}/targets.txt -o {project_path}/{safe_project_name}/nikto/nikto-output_{scan_number}_{timestamp}.txt",
                'dirsearch': f"dirsearch -l {project_path}/targets.txt --no-color -q -o {project_path}/{safe_project_name}/dirsearch/dirsearch-output_{scan_number}_{timestamp}.txt",
                'httpx': f"httpx -l {project_path}/targets.txt -o {project_path}/{safe_project_name}/httpx/httpx-output_{scan_number}_{timestamp}.txt",
                'udp_proto_scan': f"udp-proto-scanner.pl -f {project_path}/targets.txt",
                'cloud_enum': f"cloud_enum -kf {project_path}/targets.txt -t 100 -l {project_path}/{safe_project_name}/cloud_enum/cloud_enum_{scan_number}_{timestamp}.txt",
                'aquatone': f"cat {project_path}/targets.txt | aquatone -out {project_path}/{safe_project_name}/aquatone/aquatone-output_{scan_number}_{timestamp}",
                'eyewitness': f"eyewitness -f {project_path}/targets.txt --no-prompt --prepend-https --max-retries 15 -d {project_path}/{safe_project_name}/eyewitness/eyewitness_{scan_number}_{timestamp} --web"
            }
            
            if scan_type in commands:
                start_scan_thread(commands[scan_type], project_path, project_name, scan_type, scan_id, scan_number, username)
                started += 1
        
        return jsonify({"success": True, "message": f"Started {started} scans with proper numbering"})
        
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/projects/<project_id>/scans/pause-all', methods=['POST'])
def pause_all_project_scans(project_id):
    try:
        username = get_current_user()
        if not username:
            return jsonify({"error": "Authentication required"}), 401
        
        paused_count = 0
        for scan_id, scan_data in ACTIVE_SCANS.items():
            if (scan_data.get('project_id') == project_id and 
                scan_data.get('username') == username and 
                scan_data.get('status') == 'running'):
                
                session_name = scan_data.get('session')
                if session_name and pause_screen_session(session_name):
                    ACTIVE_SCANS[scan_id]['status'] = 'paused'
                    paused_count += 1
        
        return jsonify({"success": True, "message": f"Paused {paused_count} scans"})
        
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/projects/<project_id>/scans/resume-all', methods=['POST'])
def resume_all_project_scans(project_id):
    try:
        username = get_current_user()
        if not username:
            return jsonify({"error": "Authentication required"}), 401
        
        resumed_count = 0
        for scan_id, scan_data in ACTIVE_SCANS.items():
            if (scan_data.get('project_id') == project_id and 
                scan_data.get('username') == username and 
                scan_data.get('status') == 'paused'):
                
                session_name = scan_data.get('session')
                if session_name and resume_screen_session(session_name):
                    ACTIVE_SCANS[scan_id]['status'] = 'running'
                    resumed_count += 1
        
        return jsonify({"success": True, "message": f"Resumed {resumed_count} scans"})
        
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/scans/stop-all', methods=['POST'])
def stop_all_scans():
    try:
        username = get_current_user()
        if not username:
            return jsonify({"error": "Authentication required"}), 401
        
        data = request.get_json(silent=True) or {}
        project_id = data.get('project_id')
        
        stopped_count = 0
        for scan_id, scan_data in list(ACTIVE_SCANS.items()):
            if scan_data.get('username') == username:
                if not project_id or scan_data.get('project_id') == project_id:
                    if scan_data['status'] in ('running', 'paused'):
                        session_name = scan_data.get('session')
                        if session_name:
                            stop_screen_session(session_name)
                        scan_data['status'] = 'stopped'
                        stopped_count += 1
        
        return jsonify({"success": True, "message": f"Stopped {stopped_count} scans"})
        
    except Exception as e:
        return jsonify({"success": False, "message": f"Error stopping scans: {str(e)}"})

# ENHANCED: Export with separate scan reports
@app.route('/api/projects/<project_id>/export/<format>')
def export_project(project_id, format):
    try:
        username = get_current_user()
        if not username:
            return jsonify({"error": "Authentication required"}), 401
        
        project_info = get_project_info(username, project_id)
        if not project_info:
            return jsonify({"error": "Project not found"}), 404
        
        projects_dir = get_user_projects_dir(username)
        project_path = os.path.join(projects_dir, project_id)
        project_name = project_info['name']
        sanitized_name = project_info.get('sanitized_name', sanitize_name(project_name))
        
        if format == 'csv':
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['Tool', 'Scan_Number', 'Status', 'Started', 'PID', 'Project', 'Display_Name'])
            
            for scan_id, scan_data in ACTIVE_SCANS.items():
                if (scan_data.get('username') == username and 
                    (scan_data.get('project_id') == project_id or scan_id.startswith(project_id))):
                    writer.writerow([
                        scan_data.get('scan_type', 'unknown'),
                        scan_data.get('scan_number', 1),
                        scan_data['status'],
                        scan_data['started'],
                        scan_data.get('pid', ''),
                        project_name,
                        scan_data.get('display_name', scan_data.get('scan_type', 'unknown'))
                    ])
            
            output.seek(0)
            return send_file(
                io.BytesIO(output.getvalue().encode()),
                mimetype='text/csv',
                as_attachment=True,
                download_name=f'{sanitized_name}_results.csv'
            )
        
        elif format == 'html':
            # ENHANCED: HTML export with separate sections for each scan
            html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>{html.escape(project_name)} - NetworkPT Results</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; background: #f8f9fa; }}
        .header {{ background: linear-gradient(135deg, #3b82f6 0%, #1e40af 100%); color: white; padding: 30px; border-radius: 10px; text-align: center; }}
        .scan-section {{ margin: 30px 0; padding: 25px; background: white; border-radius: 10px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }}
        .scan-header {{ background: #f1f5f9; padding: 15px; border-radius: 8px; margin-bottom: 20px; border-left: 5px solid #3b82f6; }}
        pre {{ background: #1e293b; color: #22d3ee; padding: 20px; border-radius: 8px; overflow-x: auto; font-size: 13px; }}
        .status {{ padding: 5px 15px; border-radius: 15px; font-weight: bold; text-transform: uppercase; }}
        .status-running {{ background: #dcfce7; color: #166534; }}
        .status-completed {{ background: #dbeafe; color: #1e40af; }}
        .status-paused {{ background: #fef3c7; color: #a16207; }}
        .status-stopped {{ background: #fecaca; color: #dc2626; }}
        .status-error {{ background: #fecaca; color: #dc2626; }}
        .footer {{ text-align: center; margin-top: 40px; padding: 20px; background: #e5e7eb; border-radius: 10px; }}
        .scan-meta {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(50px, 1fr)); gap: 15px; margin-bottom: 15px; }}
        .meta-item {{ background: #f3f4f6; padding: 5px; border-radius: 2px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🛡️ NetworkPT - Penetration Testing Report</h1>
        <h2>Project Name : {html.escape(project_name.upper())}</h2>
        <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <p>Report Generated By {username.upper()}</p>
    </div>
"""
            
            # Group scans by type and sort by scan number
            scans_by_type = {}
            for scan_id, output in SCAN_OUTPUTS.items():
                scan_info = ACTIVE_SCANS.get(scan_id, {})
                if (scan_info.get('username') == username and output and 
                    (scan_info.get('project_id') == project_id or scan_id.startswith(project_id))):
                    
                    scan_type = scan_info.get('scan_type', 'unknown')
                    if scan_type not in scans_by_type:
                        scans_by_type[scan_type] = []
                    
                    scans_by_type[scan_type].append((scan_id, scan_info, output))
            
            # Sort scans within each type by scan number
            for scan_type in scans_by_type:
                scans_by_type[scan_type].sort(key=lambda x: x[1].get('scan_number', 1))
            
            # Generate HTML for each scan type
            for scan_type, scans in scans_by_type.items():
                html_content += f"""
    <div class="scan-section">
        <h2>📊 {scan_type.upper()} Scans ({len(scans)} total)</h2>
"""
                
                for scan_id, scan_info, output in scans:
                    display_name = scan_info.get('display_name', f"{scan_type.upper()}_{scan_info.get('scan_number', 1)}")
                    status = scan_info.get('status', 'unknown')
                    started = scan_info.get('started', 'unknown')
                    scan_number = scan_info.get('scan_number', 1)
                    
                    html_content += f"""
        <div class="scan-header">
            <h3>🔧 {html.escape(display_name)}</h3>
            <div class="scan-meta">
                <div class="meta-item">
                    <strong>Status:</strong> 
                    <span class="status status-{status}">{html.escape(status)}</span>
                </div>
                <div class="meta-item">
                    <strong>Started:</strong> {html.escape(started)}
                </div>
                <div class="meta-item">
                    <strong>Scan ID:</strong> {html.escape(scan_id)}
                </div>
            </div>
        </div>
        <pre>{html.escape(output.replace("__SCAN_EXIT__", ""))}</pre>
"""
                
                html_content += "</div>"
            
            html_content += """
    <div class="footer">
        <p><strong>Report Generated on NetworkPT</strong></p>
        <p>Professional Penetration Testing Platform by Ravi Solanki</p>
    </div>
</body>
</html>
"""
            
            return send_file(
                io.BytesIO(html_content.encode('utf-8')),
                mimetype='text/html',
                as_attachment=True,
                download_name=f'{sanitized_name}_enhanced_report.html'
            )
        
        elif format == 'txt':
            content = f"NetworkPT  - Enhanced Multi-Scan Export\nProject: {project_name}\nGenerated: {datetime.now().isoformat()}\n" + "=" * 80 + "\n\n"
            
            # Group and sort scans
            scans_by_type = {}
            for scan_id, output in SCAN_OUTPUTS.items():
                scan_info = ACTIVE_SCANS.get(scan_id, {})
                if (scan_info.get('username') == username and output and 
                    (scan_info.get('project_id') == project_id or scan_id.startswith(project_id))):
                    
                    scan_type = scan_info.get('scan_type', 'unknown')
                    if scan_type not in scans_by_type:
                        scans_by_type[scan_type] = []
                    
                    scans_by_type[scan_type].append((scan_id, scan_info, output))
            
            for scan_type in scans_by_type:
                scans_by_type[scan_type].sort(key=lambda x: x[1].get('scan_number', 1))
            
            for scan_type, scans in scans_by_type.items():
                content += f"\n{'='*20} {scan_type.upper()} SCANS ({'='*20}\n\n"
                
                for scan_id, scan_info, output in scans:
                    display_name = scan_info.get('display_name', f"{scan_type.upper()}_{scan_info.get('scan_number', 1)}")
                    started = scan_info.get('started', 'unknown')
                    status = scan_info.get('status', 'unknown')
                    
                    content += f"--- {display_name} ---\n"
                    content += f"Status: {status}\n"
                    content += f"Started: {started}\n"
                    content += f"Scan ID: {scan_id}\n\n"
                    content += output + "\n\n" + "-" * 60 + "\n\n"
            
            return send_file(
                io.BytesIO(content.encode()),
                mimetype='text/plain',
                as_attachment=True,
                download_name=f'{sanitized_name}_enhanced_results.txt'
            )
        
        elif format == 'zip':
            memory_file = io.BytesIO()
            with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
                # Add project files
                if os.path.exists(project_path):
                    for root, dirs, files in os.walk(project_path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arc_name = os.path.relpath(file_path, project_path)
                            zf.write(file_path, arc_name)
                
                # Add live outputs with proper organization
                scans_by_type = {}
                for scan_id, output in SCAN_OUTPUTS.items():
                    scan_info = ACTIVE_SCANS.get(scan_id, {})
                    if (scan_info.get('username') == username and output and 
                        (scan_info.get('project_id') == project_id or scan_id.startswith(project_id))):
                        
                        scan_type = scan_info.get('scan_type', 'unknown')
                        scan_number = scan_info.get('scan_number', 1)
                        display_name = scan_info.get('display_name', f"{scan_type}_{scan_number}")
                        
                        filename = f'live_outputs/{scan_type}/{display_name}_{scan_id}.txt'
                        zf.writestr(filename, output)
            
            memory_file.seek(0)
            return send_file(
                memory_file,
                mimetype='application/zip',
                as_attachment=True,
                download_name=f'{sanitized_name}_enhanced_complete.zip'
            )
        
        else:
            return jsonify({"error": "Invalid export format"}), 400
            
    except Exception as e:
        print(f"Export error: {e}")
        return jsonify({"error": str(e)}), 500

# Continue with remaining endpoints (copy, delete project, etc.)
@app.route('/api/projects/<project_id>/copy_output', methods=['POST'])
def copy_project_output(project_id):
    try:
        username = get_current_user()
        if not username:
            return jsonify({"error": "Authentication required"}), 401
        
        project_info = get_project_info(username, project_id)
        if not project_info:
            return jsonify({"success": False, "message": "Project not found"})
        
        projects_dir = get_user_projects_dir(username)
        project_path = os.path.join(projects_dir, project_id)
        
        data = request.get_json()
        dest_path = data.get('dest_path')
        if not dest_path:
            return jsonify({"success": False, "message": "Destination path is required."})
        
        # Enhanced copy with better error handling
        try:
            shutil.copytree(project_path, dest_path, dirs_exist_ok=True)
            return jsonify({"success": True, "message": f"Project copied to {dest_path}"})
        except FileExistsError:
            return jsonify({"success": False, "message": "Destination already exists. Use a different path or remove the existing directory."})
        except PermissionError:
            return jsonify({"success": False, "message": "Permission denied. Check if you have write access to the destination path."})
        except FileNotFoundError:
            return jsonify({"success": False, "message": "Destination directory path does not exist. Please create the parent directories first."})
        
    except Exception as e:
        print(f"Copy Output error: {e}")
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/projects/<project_id>', methods=['DELETE'])
def delete_project(project_id):
    try:
        username = get_current_user()
        if not username:
            return jsonify({"error": "Authentication required"}), 401

        projects_dir = get_user_projects_dir(username)
        project_path = os.path.join(projects_dir, project_id)

        if not os.path.exists(project_path):
            return jsonify({"success": False, "error": "Project not found"})

        # Stop all active scans for this project first
        stopped_scans = []
        for scan_id, scan_data in list(ACTIVE_SCANS.items()):
            if (scan_data.get('username') == username and 
                (scan_data.get('project_id') == project_id or str(scan_id).startswith(str(project_id)))):

                session_name = scan_data.get('session')
                if session_name:
                    stop_screen_session(session_name)

                del ACTIVE_SCANS[scan_id]
                if scan_id in SCAN_OUTPUTS:
                    del SCAN_OUTPUTS[scan_id]
                stopped_scans.append(scan_id)

        # Remove project directory and all files
        shutil.rmtree(project_path)

        return jsonify({
            "success": True,
            "message": f"Project deleted successfully. Stopped {len(stopped_scans)} active scans."
        })

    except Exception as e:
        print(f"Delete project error: {e}")
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/system-status')
def system_status():
    try:
        username = get_current_user()
        if not username:
            return jsonify({"error": "Authentication required"}), 401
        
        tools_status = {}
        tools_to_check = [
            'nmap', 'nuclei', 'httpx', 'testssl', 'nikto', 'curl', 'wget', 'screen',
            'udp-proto-scanner.pl', 'sslscan', 'ssh-audit', 'cloud_enum', 'aquatone',
            'dirsearch', 'eyewitness'
        ]
        
        for tool in tools_to_check:
            try:
                result = subprocess.run(['which', tool], capture_output=True, text=True, timeout=2)
                tools_status[tool] = {
                    'available': result.returncode == 0,
                    'path': result.stdout.strip() if result.returncode == 0 else None
                }
            except:
                tools_status[tool] = {'available': False, 'path': None}
        
        projects_dir = get_user_projects_dir(username)
        project_count = len([d for d in os.listdir(projects_dir) 
                           if os.path.isdir(os.path.join(projects_dir, d))]) if os.path.exists(projects_dir) else 0
        
        running_scans = {
            scan_id: {
                'scan_type': scan_data.get('scan_type'),
                'scan_number': scan_data.get('scan_number'),
                'display_name': scan_data.get('display_name'),
                'status': scan_data.get('status'),
                'started': scan_data.get('started')
            }
            for scan_id, scan_data in ACTIVE_SCANS.items()
            if scan_data.get('username') == username
        }
        
        return jsonify({
            'tools': tools_status,
            'project_count': project_count,
            'active_scans': len(running_scans),
            'running_scans': running_scans,
            'version': '2.0',
            'features': [
                'Individual scan controls (pause/delete selected)',
                'Live project dashboard with scan status',
                'Blue, white, orange color scheme',
                'Increased font sizes',
                'Copy results activation'
            ]
        })
        
    except Exception as e:
        print(f"System status error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth-status', methods=['GET'])
def check_auth_status():
    """Check if user is currently authenticated"""
    try:
        username = get_current_user()
        if username:
            return jsonify({
                'authenticated': True,
                'username': username,
                'role': DEFAULT_USERS.get(username, {}).get('role', 'user')
            })
        return jsonify({'authenticated': False})
    except Exception as e:
        return jsonify({
            'authenticated': False,
            'error': str(e)
        })

@app.route('/api/health')
def health():
    return jsonify({
        "status": "healthy", 
        "version": "2.0",
        "features": "individual_scan_controls,live_dashboard,blue_orange_theme,larger_fonts,copy_activation"
    })

def restore_scans_from_projects():
    """Restore scans from info.json into ACTIVE_SCANS and SCAN_OUTPUTS
       Also normalizes 'running' -> 'stopped' and writes back to disk
    """
    try:
        for user in os.listdir(USERS_DIR):
            user_projects = os.path.join(USERS_DIR, user, "projects")
            if not os.path.isdir(user_projects):
                continue

            for project_id in os.listdir(user_projects):
                project_path = os.path.join(user_projects, project_id)
                info_file = os.path.join(project_path, "info.json")

                if os.path.exists(info_file):
                    with open(info_file, "r") as f:
                        project_info = json.load(f)

                    changed = False
                    for scan in project_info.get("scans", []):
                        scan_id = scan.get("id")
                        if not scan_id:
                            continue

                        # Normalize running -> stopped since screen sessions won't survive restart
                        status = scan.get("status", "completed")
                        if status == 'running':
                            status = 'stopped'
                            scan['status'] = 'stopped'
                            scan['completed'] = datetime.now().isoformat()
                            changed = True

                        # Restore minimal scan info
                        ACTIVE_SCANS[scan_id] = {
                            "status": status,
                            "started": scan.get("started"),
                            "completed": scan.get("completed", None),
                            "project_id": project_id,
                            "scan_type": scan.get("scan_type", scan.get("type")),
                            "scan_number": scan.get("scan_number"),
                            "display_name": scan.get("display_name"),
                            "session": None,
                            "output_file": scan.get("output_file"),
                            "username": project_info.get("username", user),
                            "command": scan.get("command"),
                            "paused_at_disk": scan.get("paused_at")
                        }

                        # Load last output if available
                        output_file = scan.get("output_file")
                        if output_file and os.path.exists(output_file):
                            try:
                                with open(output_file, "r", encoding="utf-8", errors="ignore") as of:
                                    SCAN_OUTPUTS[scan_id] = of.read()
                            except:
                                SCAN_OUTPUTS[scan_id] = ""

                    if changed:
                        # write back normalized info.json
                        write_project_info(user, project_id, project_info)
    except Exception as e:
        print(f"❌ Error restoring scans: {e}")

# NEW: Resume selected scan endpoint
@app.route('/api/scan/resume', methods=['POST'])
def resume_selected_scan():
    try:
        username = get_current_user()
        if not username:
            return jsonify({"error": "Authentication required"}), 401

        data = request.get_json()
        scan_id = data.get('scan_id')

        if not scan_id:
            return jsonify({"success": False, "error": "Scan ID is required"})

        if scan_id not in ACTIVE_SCANS:
            return jsonify({"success": False, "error": "Scan not found"})

        scan_data = ACTIVE_SCANS[scan_id]

        # Check ownership
        if scan_data.get('username') != username:
            return jsonify({"success": False, "error": "Access denied"})

        if scan_data.get('status') != 'paused':
            return jsonify({"success": False, "error": f"Cannot resume scan in '{scan_data.get('status')}' status"})

        session_name = scan_data.get('session')
        if not session_name:
            return jsonify({"success": False, "error": "No session found for this scan"})

        # Attempt to resume underlying processes
        if resume_screen_session(session_name):
            ACTIVE_SCANS[scan_id]['status'] = 'running'
            ACTIVE_SCANS[scan_id].pop('paused_at', None)
            # update disk record if present
            try:
                update_project_scan_status_on_disk(username, scan_data.get('project_id'), scan_id, 'running')
            except Exception:
                pass

            return jsonify({
                "success": True,
                "message": f"Scan {scan_data.get('display_name', scan_id)} resumed successfully"
            })
        else:
            return jsonify({"success": False, "error": "Failed to resume scan"})
    except Exception as e:
        print(f"Resume scan error: {e}")
        return jsonify({"success": False, "error": str(e)})

if __name__ == '__main__':
    print("🚀 Starting NetworkPT - Enhanced Multi-Scan")
    print("📊 Dashboard: https://localhost:29525")
    print("🔧 Features: Multiple scans of same type, proper numbering, enhanced export")

    restore_scans_from_projects()

    CERT_FILE = 'cert.pem'
    KEY_FILE = 'key.pem'

    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)
            app.run(ssl_context=context, host='0.0.0.0', port=29525, debug=False)
        except Exception as e:
            print(f"❌ Failed to start server with SSL: {e}")
            print("📊 Falling back to HTTP mode on port 29525")
            app.run(host='0.0.0.0', port=29525, debug=False)
    else:
        print("⚠️ SSL certificates not found, running in HTTP mode")
        print("📊 Dashboard: http://localhost:29525")
        app.run(host='0.0.0.0', port=29525, debug=False)