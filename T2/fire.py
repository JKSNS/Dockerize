#!/usr/bin/env python3
"""
CCDC dockerization - Revised to robustly handle Docker group creation, user membership,
and systemd-based service enablement.
"""

import sys
import platform
import subprocess
import argparse
import os
import hashlib
import time
import shutil

# -------------------------------------------------
# 1. Docker & Docker Compose Auto-Installation
# -------------------------------------------------

def detect_linux_package_manager():
    """Detect common Linux package managers."""
    for pm in ["apt", "apt-get", "dnf", "yum", "zypper"]:
        if shutil.which(pm):
            return pm
    return None

def group_exists(group_name):
    """
    Return True if the specified group exists on the system,
    determined via 'getent group <group>'.
    """
    try:
        subprocess.check_call(["getent", "group", group_name],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False

def user_in_group(username, group_name):
    """
    Return True if the given username is already in the specified group.
    """
    try:
        groups_output = subprocess.check_output(["groups", username], text=True)
        # "groups" output might look like: "username : username wheel docker"
        # We'll just check if ' docker' or 'docker ' is in there
        return group_name in groups_output.split()
    except:
        return False

def create_docker_group_if_missing():
    """
    Create the 'docker' group if it does not exist.
    """
    if not group_exists("docker"):
        print("[INFO] 'docker' group does not exist. Creating it now...")
        try:
            subprocess.check_call(["sudo", "groupadd", "docker"])
            print("[INFO] Created 'docker' group.")
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Could not create 'docker' group: {e}")
            return False
    return True

def add_user_to_docker_group(username):
    """
    Add the specified user to the 'docker' group, if not already a member.
    """
    if user_in_group(username, "docker"):
        print(f"[INFO] User '{username}' is already in 'docker' group.")
        return True
    try:
        print(f"[INFO] Adding user '{username}' to 'docker' group.")
        subprocess.check_call(["sudo", "usermod", "-aG", "docker", username])
        print(f"[INFO] User '{username}' added to 'docker' group successfully.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not add user '{username}' to 'docker' group: {e}")
        return False

def enable_and_start_docker_service():
    """
    Attempt to enable and start Docker via systemd if available.
    """
    if shutil.which("systemctl"):
        try:
            subprocess.check_call(["sudo", "systemctl", "enable", "docker"])
            subprocess.check_call(["sudo", "systemctl", "start", "docker"])
            print("[INFO] Docker service enabled and started via systemd.")
        except subprocess.CalledProcessError as e:
            print(f"[WARN] Could not enable/start Docker service via systemd: {e}")
    else:
        print("[WARN] systemctl not found. If you are on WSL or a non-systemd distro, start Docker manually.")

def attempt_install_docker_linux():
    """
    Attempt to install Docker on Linux using a best-effort approach, then
    ensure the 'docker' group is present, add the user, enable the service, etc.
    """
    pm = detect_linux_package_manager()
    if not pm:
        print("[ERROR] No recognized package manager found on Linux. Cannot auto-install Docker.")
        return False

    print(f"[INFO] Attempting to install Docker using '{pm}' on Linux...")
    try:
        env = os.environ.copy()
        env["DEBIAN_FRONTEND"] = "noninteractive"
        env["TZ"] = "America/Denver"

        if pm in ("apt", "apt-get"):
            subprocess.check_call(["sudo", pm, "update", "-y"], env=env)
            subprocess.check_call(["sudo", pm, "install", "-y", "docker.io"], env=env)
        elif pm in ("yum", "dnf"):
            subprocess.check_call(["sudo", pm, "-y", "install", "docker"], env=env)
        elif pm == "zypper":
            subprocess.check_call(["sudo", "zypper", "refresh"], env=env)
            subprocess.check_call(["sudo", "zypper", "--non-interactive", "install", "docker"], env=env)
        else:
            print(f"[ERROR] Package manager '{pm}' is not fully supported for auto-installation.")
            return False

        print("[INFO] Docker installation attempt completed. Checking if Docker is now available.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Auto-installation of Docker on Linux failed: {e}")
        return False

    # Now ensure the 'docker' group exists and the user is in it
    if not create_docker_group_if_missing():
        return False

    # Attempt to add the current user to the docker group
    try:
        current_user = os.getlogin()
    except:
        current_user = os.environ.get("USER", "unknown")

    if not add_user_to_docker_group(current_user):
        return False

    # Enable and start Docker (if systemd is available)
    enable_and_start_docker_service()

    return True

def attempt_install_docker_compose_linux():
    """
    Attempt to install Docker Compose on Linux (best effort).
    We'll try apt-get or yum/dnf or zypper, similar to Docker auto-install logic,
    also in noninteractive mode with TZ=America/Denver.
    """
    pm = detect_linux_package_manager()
    if not pm:
        print("[ERROR] No recognized package manager found. Cannot auto-install Docker Compose.")
        return False
    
    print(f"[INFO] Attempting to install Docker Compose using '{pm}' on Linux...")
    try:
        env = os.environ.copy()
        env["DEBIAN_FRONTEND"] = "noninteractive"
        env["TZ"] = "America/Denver"

        if pm in ("apt", "apt-get"):
            subprocess.check_call(["sudo", pm, "update", "-y"], env=env)
            subprocess.check_call(["sudo", pm, "install", "-y", "docker-compose"], env=env)
        elif pm in ("yum", "dnf"):
            subprocess.check_call(["sudo", pm, "-y", "install", "docker-compose"], env=env)
        elif pm == "zypper":
            subprocess.check_call(["sudo", "zypper", "refresh"], env=env)
            subprocess.check_call(["sudo", "zypper", "--non-interactive", "install", "docker-compose"], env=env)
        else:
            print(f"[ERROR] Package manager '{pm}' is not fully supported for Docker Compose auto-install.")
            return False
        
        print("[INFO] Docker Compose installation attempt completed. Checking if it is now available.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Auto-installation of Docker Compose on Linux failed: {e}")
        return False

def can_run_docker():
    """Return True if we can run 'docker ps' without error, else False."""
    try:
        subprocess.check_call(["docker", "ps"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except:
        return False

def ensure_docker_installed():
    """
    Check if Docker is installed & if the user can run it.
    If missing, attempt auto-install. If the user isn't in the docker group,
    fix that, then re-exec with sg if necessary.
    """
    # If we've already re-executed once under sg docker, don't do it again
    if "CCDC_DOCKER_GROUP_FIX" in os.environ:
        if can_run_docker():
            print("[INFO] Docker is accessible now after group fix.")
            return
        else:
            print("[ERROR] Docker still not accessible even after group fix. Exiting.")
            sys.exit(1)

    docker_path = shutil.which("docker")
    if docker_path and can_run_docker():
        print("[INFO] Docker is installed and accessible.")
        # Make sure the group is created and the user is in it, just in case
        if not group_exists("docker"):
            create_docker_group_if_missing()
        try:
            current_user = os.getlogin()
        except:
            current_user = os.environ.get("USER", "unknown")
        add_user_to_docker_group(current_user)
        enable_and_start_docker_service()
        return
    else:
        # Docker either not installed or not accessible
        sysname = platform.system().lower()
        if sysname.startswith("linux"):
            installed = attempt_install_docker_linux()
            if not installed:
                print("[ERROR] Could not auto-install Docker on Linux. Please install it manually.")
                sys.exit(1)

            # If we still can't run Docker, we re-exec with 'sg docker'
            if not can_run_docker():
                reexec_with_docker_group()
            else:
                print("[INFO] Docker is installed and accessible on Linux now.")
        elif "bsd" in sysname:
            print("[ERROR] Docker auto-install is not implemented for BSD. Please install manually.")
            sys.exit(1)
        elif "nix" in sysname:
            print("[ERROR] Docker auto-install is not implemented for Nix. Please install manually.")
            sys.exit(1)
        elif sysname == "windows":
            print("[ERROR] Docker not found, and auto-install is not supported on Windows. Please install Docker or Docker Desktop manually.")
            sys.exit(1)
        else:
            print(f"[ERROR] Unrecognized system '{sysname}'. Docker is missing. Please install it manually.")
            sys.exit(1)

def reexec_with_docker_group():
    """
    Re-exec the script under 'sg docker' to activate group membership.
    This avoids dropping the user into an interactive shell.
    """
    print("[INFO] Re-executing script under 'sg docker' to activate group membership.")
    os.environ["CCDC_DOCKER_GROUP_FIX"] = "1"  # Avoid infinite loops
    script_path = os.path.abspath(sys.argv[0])
    script_args = sys.argv[1:]
    command_line = f'export CCDC_DOCKER_GROUP_FIX=1; exec "{sys.executable}" "{script_path}" ' + " ".join(f'"{arg}"' for arg in script_args)
    cmd = ["sg", "docker", "-c", command_line]
    os.execvp("sg", cmd)

def check_docker_compose():
    """Check if Docker Compose is installed. If not, try to auto-install on Linux."""
    try:
        subprocess.check_call(["docker-compose", "--version"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("[INFO] Docker Compose is installed.")
    except Exception:
        print("[WARN] Docker Compose not found. Attempting auto-install (Linux only).")
        sysname = platform.system().lower()
        if sysname.startswith("linux"):
            installed = attempt_install_docker_compose_linux()
            if installed:
                try:
                    # Verify again
                    subprocess.check_call(["docker-compose", "--version"],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print("[INFO] Docker Compose installed successfully.")
                except:
                    print("[ERROR] Docker Compose still not available after attempted install.")
            else:
                print("[ERROR] Could not auto-install Docker Compose on Linux. Please install manually.")
        else:
            print("[ERROR] Docker Compose not found, and auto-install is only supported on Linux. Please install manually.")

# -------------------------------------------------
# 2. Python & Docker Checks
# -------------------------------------------------

def check_python_version(min_major=3, min_minor=7):
    """Ensure Python 3.7+ is being used."""
    if sys.version_info < (min_major, min_minor):
        print(f"[ERROR] Python {min_major}.{min_minor}+ is required. You are running {sys.version_info.major}.{sys.version_info.minor}.")
        sys.exit(1)
    else:
        print(f"[INFO] Python version check passed: {sys.version_info.major}.{sys.version_info.minor}.")

def check_wsl_if_windows():
    """On Windows, check for WSL if needed (for non-Docker Desktop)."""
    if platform.system().lower() == "windows":
        try:
            subprocess.check_call(["wsl", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("[INFO] WSL is installed.")
        except Exception:
            print("[WARN] WSL not found. Running Docker containers as non-root on legacy Windows may require custom images.")

def check_all_dependencies():
    """Run all prerequisite checks."""
    check_python_version(3, 7)
    ensure_docker_installed()
    check_docker_compose()
    check_wsl_if_windows()

# -------------------------------------------------
# 3. OS Detection & Docker Image Mapping
# -------------------------------------------------

def detect_os():
    """Detect the host OS and version. Best-effort for Linux, BSD, Nix, Windows."""
    sysname = platform.system().lower()
    if sysname.startswith("linux"):
        try:
            with open("/etc/os-release") as f:
                lines = f.readlines()
            os_info = {}
            for line in lines:
                if "=" in line:
                    key, value = line.strip().split("=", 1)
                    os_info[key.lower()] = value.strip('"').lower()
            os_name = os_info.get("name", "linux")
            version_id = os_info.get("version_id", "")
            return os_name, version_id
        except:
            return "linux", ""
    elif sysname.startswith("freebsd") or sysname.startswith("openbsd") or sysname.startswith("netbsd"):
        return "bsd", ""
    elif "nix" in sysname:
        return "nix", ""
    elif sysname == "windows":
        version = platform.release().lower()
        return "windows", version
    else:
        return sysname, ""

def map_os_to_docker_image(os_name, version):
    """Map the detected OS to a recommended Docker base image (best-effort)."""
    linux_map = {
        "centos": {
            "6": "centos:6",
            "7": "centos:7",
            "8": "centos:8",
            "9": "centos:stream9",
            "": "ubuntu:latest"
        },
        "ubuntu": {
            "14": "ubuntu:14.04",
            "16": "ubuntu:16.04",
            "18": "ubuntu:18.04",
            "20": "ubuntu:20.04",
            "22": "ubuntu:22.04"
        },
        "debian": {
            "7": "debian:7",
            "8": "debian:8",
            "9": "debian:9",
            "10": "debian:10",
            "11": "debian:11",
            "12": "debian:12"
        },
        "fedora": {
            "25": "fedora:25",
            "26": "fedora:26",
            "27": "fedora:27",
            "28": "fedora:28",
            "29": "fedora:29",
            "30": "fedora:30",
            "31": "fedora:31",
            "35": "fedora:35"
        },
        "opensuse leap": {
            "15": "opensuse/leap:15"
        },
        "opensuse tumbleweed": {
            "": "opensuse/tumbleweed"
        },
        "linux": {
            "": "ubuntu:latest"
        }
    }
    windows_map = {
        "xp":      "legacy-windows/xp:latest",
        "vista":   "legacy-windows/vista:latest",
        "7":       "legacy-windows/win7:latest",
        "2008":    "legacy-windows/win2008:latest",
        "2012":    "legacy-windows/win2012:latest",
        "10":      "mcr.microsoft.com/windows/nanoserver:1809",
        "2016":    "mcr.microsoft.com/windows/servercore:2016",
        "2019":    "mcr.microsoft.com/windows/servercore:ltsc2019",
        "2022":    "mcr.microsoft.com/windows/servercore:ltsc2022"
    }
    if os_name == "bsd":
        return "alpine:latest"
    elif os_name == "nix":
        return "alpine:latest"
    elif os_name == "windows":
        for k, img in windows_map.items():
            if k in version:
                return img
        return "mcr.microsoft.com/windows/servercore:ltsc2019"
    else:
        # assume some Linux distro
        for distro, ver_map in linux_map.items():
            if distro in os_name:
                short_ver = version.split(".")[0] if version else ""
                if short_ver in ver_map:
                    return ver_map[short_ver]
                if "" in ver_map:
                    return ver_map[""]
                return "ubuntu:latest"
        return "ubuntu:latest"

# -------------------------------------------------
# 4. Container Launch & Integrity Checking
# -------------------------------------------------

def pull_docker_image(image):
    """Pull the specified Docker image."""
    try:
        print(f"[INFO] Pulling Docker image: {image}")
        subprocess.check_call(["docker", "pull", image])
        print(f"[INFO] Successfully pulled image: {image}")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not pull image '{image}': {e}")

def compute_container_hash(container_name):
    """Compute a SHA256 hash of the container's filesystem by exporting it."""
    try:
        proc = subprocess.Popen(["docker", "export", container_name], stdout=subprocess.PIPE)
        hasher = hashlib.sha256()
        while True:
            chunk = proc.stdout.read(4096)
            if not chunk:
                break
            hasher.update(chunk)
        proc.stdout.close()
        proc.wait()
        hash_val = hasher.hexdigest()
        print(f"[INFO] Computed hash for container '{container_name}': {hash_val}")
        return hash_val
    except Exception as e:
        print(f"[ERROR] Could not compute hash for container '{container_name}': {e}")
        return None

def restore_container_from_snapshot(snapshot_tar, container_name):
    """Restore a container from a snapshot tar file in detached mode."""
    try:
        print(f"[INFO] Restoring container '{container_name}' from snapshot '{snapshot_tar}'")
        subprocess.check_call(["docker", "load", "-i", snapshot_tar])
        image_name = os.path.splitext(os.path.basename(snapshot_tar))[0]
        os_name, _ = detect_os()
        user = "nonroot" if os_name == "windows" else "nobody"
        subprocess.check_call([
            "docker", "run", "-d",
            "--read-only",
            "--user", user,
            "--name", container_name,
            image_name
        ])
        print(f"[INFO] Container '{container_name}' restored and launched.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not restore container '{container_name}' from snapshot: {e}")

def continuous_integrity_check(container_name, snapshot_tar, check_interval=30):
    """Continuously monitor the integrity of a running container."""
    print(f"[INFO] Starting continuous integrity check on container '{container_name}' (interval: {check_interval} seconds).")
    baseline_hash = compute_container_hash(container_name)
    if not baseline_hash:
        print("[ERROR] Failed to obtain baseline hash. Exiting integrity check.")
        return
    try:
        while True:
            time.sleep(check_interval)
            current_hash = compute_container_hash(container_name)
            if current_hash != baseline_hash:
                print("[WARN] Integrity violation detected! Restoring container from snapshot.")
                subprocess.check_call(["docker", "rm", "-f", container_name])
                restore_container_from_snapshot(snapshot_tar, container_name)
                baseline_hash = compute_container_hash(container_name)
            else:
                print("[INFO] Integrity check passed; no changes detected.")
    except KeyboardInterrupt:
        print("\n[INFO] Continuous integrity check interrupted by user.")

def minimal_integrity_check(container_name, check_interval=30):
    """
    A simplified integrity check that only compares hashes but does not restore.
    """
    print(f"[INFO] Starting minimal integrity check on '{container_name}' (no restore) every {check_interval} seconds.")
    baseline_hash = compute_container_hash(container_name)
    if not baseline_hash:
        print("[ERROR] Failed to obtain baseline hash. Exiting integrity check.")
        return
    try:
        while True:
            time.sleep(check_interval)
            current_hash = compute_container_hash(container_name)
            if current_hash != baseline_hash:
                print(f"[WARN] Integrity violation detected in container '{container_name}'!")
                print("[INFO] No restoration configured. Please investigate manually.")
                baseline_hash = current_hash
            else:
                print(f"[INFO] Container '{container_name}' is unchanged.")
    except KeyboardInterrupt:
        print("\n[INFO] Minimal integrity check interrupted by user.")

# -------------------------------------------------
# 4A. Container Name Handling
# -------------------------------------------------

def container_exists(name):
    """
    Returns True if a container (running or exited) with the given name exists.
    """
    try:
        output = subprocess.check_output(["docker", "ps", "-a", "--format", "{{.Names}}"], text=True)
        existing_names = output.split()
        return name in existing_names
    except subprocess.CalledProcessError:
        return False

def prompt_for_container_name(default_name):
    """
    Prompt the user for a container name, checking if it already exists.
    If it exists, offer options to remove it, choose a new name, or exit.
    """
    while True:
        name = input(f"Enter container name (default '{default_name}'): ").strip() or default_name
        if not container_exists(name):
            return name  # Name is available
        else:
            print(f"[ERROR] A container named '{name}' already exists.")
            choice = input("Options:\n"
                           "  [R] Remove the existing container\n"
                           "  [C] Choose another name\n"
                           "  [X] Exit\n"
                           "Enter your choice (R/C/X): ").strip().lower()
            if choice == "r":
                try:
                    subprocess.check_call(["docker", "rm", "-f", name])
                    print(f"[INFO] Removed container '{name}'. Now you can use that name.")
                    return name
                except subprocess.CalledProcessError as e:
                    print(f"[ERROR] Could not remove container '{name}': {e}")
            elif choice == "c":
                continue
            else:
                print("[INFO] Exiting.")
                sys.exit(1)

# -------------------------------------------------
# Helper: Apply Read-Only + Non-Root
# -------------------------------------------------

def maybe_apply_read_only_and_nonroot(cmd_list):
    """
    If the user chooses read-only, enforce --read-only and --user nobody (on Linux-like).
    If on Windows, just do --read-only. This ensures the container is truly read-only and not root.
    """
    read_only = input("Should this container run in read-only mode? (y/n) [n]: ").strip().lower() == "y"
    if read_only:
        sysname = platform.system().lower()
        cmd_list.append("--read-only")
        if not sysname.startswith("windows"):
            cmd_list.extend(["--user", "nobody"])
    return cmd_list

# -------------------------------------------------
# 5. Setup Docker DB, Web, WAF
# -------------------------------------------------

def setup_docker_db():
    """
    Set up a Dockerized database (e.g., MariaDB) with optional read-only + non-root.
    """
    check_all_dependencies()
    print("=== Database Container Setup ===")
    default_db_name = "web_db"
    db_container = prompt_for_container_name(default_db_name)
    
    volume_opts_db = []
    print("[NOTE] A database container typically needs write access.")
    print("Mount /var/lib/mysql or other directories if you want to store data on the host.")
    while True:
        dir_input = input("Directories to mount into the DB container (blank to finish): ").strip()
        if not dir_input:
            break
        volume_opts_db.extend(["-v", f"{dir_input}:{dir_input}"])
    
    pull_docker_image("mariadb:latest")
    
    db_password = input("Enter MariaDB root password (default 'root'): ").strip() or "root"
    db_name = input("Enter a DB name to create (default 'mydb'): ").strip() or "mydb"
    
    cmd = [
        "docker", "run", "-d",
        "--name", db_container
    ]
    # Choose network or default to 'bridge'
    network_name = input("Enter a Docker network name to attach (default 'bridge'): ").strip() or "bridge"
    if network_name != "bridge":
        try:
            subprocess.check_call(["docker", "network", "inspect", network_name],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"[INFO] Using existing network '{network_name}'.")
        except subprocess.CalledProcessError:
            print(f"[INFO] Creating Docker network '{network_name}'.")
            subprocess.check_call(["docker", "network", "create", network_name])
        cmd.extend(["--network", network_name])
    
    # Enforce read-only + non-root if chosen
    cmd = maybe_apply_read_only_and_nonroot(cmd)
    
    cmd.extend(volume_opts_db)
    cmd.extend([
        "-e", f"MYSQL_ROOT_PASSWORD={db_password}",
        "-e", f"MYSQL_DATABASE={db_name}"
    ])
    
    cmd.append("mariadb:latest")
    
    print(f"[INFO] Launching MariaDB container '{db_container}'.")
    try:
        subprocess.check_call(cmd)
        print(f"[INFO] Database container '{db_container}' launched successfully.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not launch MariaDB container '{db_container}': {e}")
        sys.exit(1)

def setup_docker_waf():
    """
    Set up a Dockerized WAF (e.g., ModSecurity) with optional read-only + non-root.
    """
    check_all_dependencies()
    waf_image = "owasp/modsecurity-crs:nginx"
    pull_docker_image(waf_image)
    
    print("=== ModSecurity WAF Container Setup ===")
    default_waf_name = "modsec2-nginx"
    waf_container = prompt_for_container_name(default_waf_name)
    
    host_waf_port = input("Enter host port for the WAF (default '8080'): ").strip() or "8080"
    
    # Connect to an existing Docker network:
    network_name = input("Enter the Docker network to attach (default 'bridge'): ").strip() or "bridge"
    if network_name != "bridge":
        try:
            subprocess.check_call(["docker", "network", "inspect", network_name],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"[INFO] Using existing network '{network_name}'.")
        except subprocess.CalledProcessError:
            print(f"[INFO] Creating Docker network '{network_name}'.")
            subprocess.check_call(["docker", "network", "create", network_name])
    
    # The user must provide the backend container name or IP
    backend_container = input("Enter the backend container name or IP (default 'web_container'): ").strip() or "web_container"
    
    tz = os.environ.get("TZ", "America/Denver")
    waf_env = [
        "PORT=8080",
        "PROXY=1",
        f"BACKEND=http://{backend_container}:80",
        "MODSEC_RULE_ENGINE=on",
        "BLOCKING_PARANOIA=4",
        f"TZ={tz}",
        "MODSEC_TMP_DIR=/tmp",
        "MODSEC_RESP_BODY_ACCESS=On",
        "MODSEC_RESP_BODY_MIMETYPE=text/plain text/html text/xml application/json",
        "COMBINED_FILE_SIZES=65535"
    ]
    
    print(f"[INFO] Launching ModSecurity proxy container '{waf_container}' from image '{waf_image}'...")
    cmd = [
        "docker", "run", "-d",
        "--network", network_name,
        "--name", waf_container,
        "-p", f"{host_waf_port}:8080"
    ]
    
    # Enforce read-only + non-root if chosen
    cmd = maybe_apply_read_only_and_nonroot(cmd)
    
    for env_var in waf_env:
        cmd.extend(["-e", env_var])
    
    cmd.append(waf_image)
    
    try:
        subprocess.check_call(cmd)
        print(f"[INFO] WAF container '{waf_container}' launched successfully.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not launch ModSecurity proxy container '{waf_container}': {e}")
        sys.exit(1)

# -------------------------------------------------
# 6. Web Stack Deployment (Modified Legacy Mode)
# -------------------------------------------------

def containerize_web_app():
    """
    Containerize the web application by copying web files and configurations
    into a Docker image. This replaces pulling a prebuilt e-commerce container.
    The resulting container will run the web server with the migrated files,
    while the database remains external.
    """
    check_all_dependencies()
    os_name, version = detect_os()
    base_image = map_os_to_docker_image(os_name, version)
    print(f"[INFO] Containerizing web app using base Docker image: {base_image}")

    build_context = "web_app_build_context"
    if os.path.exists(build_context):
        print(f"[INFO] Removing existing build context '{build_context}'.")
        shutil.rmtree(build_context)
    os.makedirs(build_context)
    
    # Define the directories to copy: web root and common web server configurations.
    directories_to_copy = {
        "var_www_html": "/var/www/html",
        "etc_httpd": "/etc/httpd",
        "etc_apache2": "/etc/apache2"
    }
    
    copied_subdirs = []
    
    for subdir, src in directories_to_copy.items():
        if os.path.exists(src):
            dest = os.path.join(build_context, subdir)
            try:
                print(f"[INFO] Copying '{src}' to build context as '{dest}'.")
                shutil.copytree(src, dest)
                copied_subdirs.append(subdir)
            except Exception as e:
                print(f"[WARN] Failed to copy {src}: {e}")
        else:
            print(f"[WARN] Source directory {src} does not exist. Skipping.")
    
    # Create a Dockerfile in the build context
    dockerfile_path = os.path.join(build_context, "Dockerfile")
    
    # Generate COPY lines only for the subdirs that were successfully copied
    copy_lines = []
    if "var_www_html" in copied_subdirs:
        copy_lines.append("COPY var_www_html/ /var/www/html/")
    if "etc_httpd" in copied_subdirs:
        copy_lines.append("COPY etc_httpd/ /etc/httpd/")
    if "etc_apache2" in copied_subdirs:
        copy_lines.append("COPY etc_apache2/ /etc/apache2/")
    
    dockerfile_content = f"""FROM {base_image}

# Avoid interactive tzdata config
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=America/Denver

# Copy web files and configurations
"""
    for line in copy_lines:
        dockerfile_content += line + "\n"

    dockerfile_content += """
# Expose web port
EXPOSE 80

# Default command to start web server (adjust as necessary)
CMD ["/usr/sbin/httpd", "-D", "FOREGROUND"]
"""

    with open(dockerfile_path, "w") as f:
        f.write(dockerfile_content)
    print(f"[INFO] Dockerfile created at {dockerfile_path}")
    
    image_name = input("Enter the name for the Docker image (default 'web_app_image'): ").strip() or "web_app_image"
    try:
        subprocess.check_call(["docker", "build", "-t", image_name, build_context])
        print(f"[INFO] Docker image '{image_name}' built successfully.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to build Docker image: {e}")
        sys.exit(1)
    
    run_container = input("Would you like to run a container from this image? (y/n): ").strip().lower() == "y"
    if run_container:
        container_name = input("Enter a name for the container (default 'web_app_container'): ").strip() or "web_app_container"
        cmd = ["docker", "run", "-d", "--name", container_name]
        cmd = maybe_apply_read_only_and_nonroot(cmd)
        cmd.append(image_name)
        
        try:
            subprocess.check_call(cmd)
            print(f"[INFO] Container '{container_name}' launched from image '{image_name}'.")
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Failed to run container '{container_name}': {e}")
    else:
        print("[INFO] Web app container build process completed. You can run the image later using 'docker run'.")

def deploy_entire_web_stack_legacy():
    """
    [Modified Legacy Mode] Deploy a DB container (optional) and containerize the current
    web application environment. In this mode, the web app is not pulled from a prebuilt image
    (e.g. Prestashop) but is instead built from the host's web files using an OS-specific base image.
    The website will leverage the DB in the underlying OS or in a separate DB container.
    """
    check_all_dependencies()
    
    # Step 1: DB choice
    db_choice = input("Use dockerized database (D) or skip DB setup (S)? (D/S): ").strip().lower()
    dockerized_db = (db_choice == "d")
    
    network_name = "ccdc-service-net"
    # Create network if not exists
    try:
        subprocess.check_call(["docker", "network", "inspect", network_name],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[INFO] Docker network '{network_name}' already exists.")
    except subprocess.CalledProcessError:
        print(f"[INFO] Creating Docker network '{network_name}'.")
        subprocess.check_call(["docker", "network", "create", network_name])
    
    db_container = None
    db_host = "localhost"
    db_user = ""
    db_password = ""
    db_name = ""
    
    # Step 2: Deploy DB container if needed
    if dockerized_db:
        default_db_name = "web_db"
        print("=== Database Container Setup ===")
        db_container = prompt_for_container_name(default_db_name)
        
        volume_opts_db = []
        print("[NOTE] A database container typically needs write access.")
        print("Mount /var/lib/mysql or other directories if you want to store data on the host.")
        while True:
            dir_input = input("Directories to mount into the DB container (blank to finish): ").strip()
            if not dir_input:
                break
            volume_opts_db.extend(["-v", f"{dir_input}:{dir_input}"])
        
        pull_docker_image("mariadb:latest")
        
        db_password = input("Enter MariaDB root password (default 'root'): ").strip() or "root"
        db_user = "root"
        db_name = input("Enter a DB name to create (default 'prestashop'): ").strip() or "prestashop"
        
        cmd = [
            "docker", "run", "-d",
            "--name", db_container,
            "--network", network_name
        ]
        
        # Enforce read-only + non-root if chosen
        cmd = maybe_apply_read_only_and_nonroot(cmd)
        
        cmd.extend(volume_opts_db)
        cmd.extend([
            "-e", f"MYSQL_ROOT_PASSWORD={db_password}",
            "-e", f"MYSQL_DATABASE={db_name}"
        ])
        
        cmd.append("mariadb:latest")
        
        print(f"[INFO] Launching MariaDB container '{db_container}'.")
        try:
            subprocess.check_call(cmd)
            db_host = db_container  # Use container name as the DB host within Docker network
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Could not launch MariaDB container '{db_container}': {e}")
            sys.exit(1)
    else:
        db_host = input("Enter the native DB host (default 'localhost'): ").strip() or "localhost"
        db_user = input("Enter DB user (default 'root'): ").strip() or "root"
        db_password = input("Enter DB password (default 'root'): ").strip() or "root"
        db_name = input("Enter DB name (default 'prestashop'): ").strip() or "prestashop"
    
    # Step 3: Containerize the web application (instead of pulling a prebuilt image)
    print("=== Web Application Containerization ===")
    print("Containerizing the current web app environment based on the host OS and migrating web files.")
    containerize_web_app()
    
    # Step 4: Optionally offer integrity checking on the web container
    run_integrity = input("Would you like to run continuous integrity checking on the web container? (y/n): ").strip().lower()
    if run_integrity == "y":
        snapshot_tar = input("Enter the path to the snapshot .tar file for restoration: ").strip()
        check_interval_str = input("Enter integrity check interval in seconds (default 30): ").strip()
        try:
            check_interval = int(check_interval_str) if check_interval_str else 30
        except ValueError:
            check_interval = 30
        web_container = input("Enter the name of the web container to monitor (default 'web_app_container'): ").strip() or "web_app_container"
        if snapshot_tar:
            continuous_integrity_check(web_container, snapshot_tar, check_interval)
        else:
            minimal_integrity_check(web_container, check_interval)

# -------------------------------------------------
# 7. Containerize Current Service Environment
# -------------------------------------------------

def containerize_service():
    """
    Encapsulate the current service into a Docker container by copying directories
    and generating a Dockerfile. We skip directories that don't exist, so Docker won't fail.
    """
    check_all_dependencies()
    
    # Determine base image using host OS info
    os_name, version = detect_os()
    base_image = map_os_to_docker_image(os_name, version)
    print(f"[INFO] Using base Docker image: {base_image}")

    build_context = "container_build_context"
    if os.path.exists(build_context):
        print(f"[INFO] Removing existing build context '{build_context}'.")
        shutil.rmtree(build_context)
    os.makedirs(build_context)
    
    # Additional critical directories for web services:
    directories_to_copy = {
        "var_lib_mysql": "/var/lib/mysql",
        "etc_httpd": "/etc/httpd",
        "etc_apache2": "/etc/apache2",
        "var_www_html": "/var/www/html",
        "etc_php": "/etc/php",
        "etc_ssl": "/etc/ssl",
        "var_log_apache2": "/var/log/apache2",
        "var_log_httpd": "/var/log/httpd"
    }
    
    # We'll track which subdirs actually got copied
    copied_subdirs = []
    
    for subdir, src in directories_to_copy.items():
        if os.path.exists(src):
            dest = os.path.join(build_context, subdir)
            try:
                print(f"[INFO] Copying '{src}' to build context as '{dest}'.")
                shutil.copytree(src, dest)
                copied_subdirs.append(subdir)
            except Exception as e:
                print(f"[WARN] Failed to copy {src}: {e}")
        else:
            print(f"[WARN] Source directory {src} does not exist. Skipping.")
    
    # Create a Dockerfile in the build context
    dockerfile_path = os.path.join(build_context, "Dockerfile")
    
    # We'll generate COPY lines only for subdirs we actually copied
    copy_lines = []
    for subdir in copied_subdirs:
        # We'll guess the container path based on subdir
        if subdir == "var_lib_mysql":
            copy_lines.append(f"COPY {subdir}/ /var/lib/mysql/")
        elif subdir == "etc_httpd":
            copy_lines.append(f"COPY {subdir}/ /etc/httpd/")
        elif subdir == "etc_apache2":
            copy_lines.append(f"COPY {subdir}/ /etc/apache2/")
        elif subdir == "var_www_html":
            copy_lines.append(f"COPY {subdir}/ /var/www/html/")
        elif subdir == "etc_php":
            copy_lines.append(f"COPY {subdir}/ /etc/php/")
        elif subdir == "etc_ssl":
            copy_lines.append(f"COPY {subdir}/ /etc/ssl/")
        elif subdir == "var_log_apache2":
            copy_lines.append(f"COPY {subdir}/ /var/log/apache2/")
        elif subdir == "var_log_httpd":
            copy_lines.append(f"COPY {subdir}/ /var/log/httpd/")
    
    # Build the Dockerfile content
    dockerfile_content = f"""FROM {base_image}

# Avoid interactive tzdata config
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=America/Denver

# Copy service configuration and data
"""
    for line in copy_lines:
        dockerfile_content += line + "\n"

    dockerfile_content += """
# Expose common ports (adjust as needed)
EXPOSE 80 3306

# Default command (adjust if necessary)
CMD ["/usr/sbin/httpd", "-D", "FOREGROUND"]
"""

    with open(dockerfile_path, "w") as f:
        f.write(dockerfile_content)
    print(f"[INFO] Dockerfile created at", dockerfile_path)
    
    # Build the Docker image
    image_name = input("Enter the name for the Docker image (default 'encapsulated_service'): ").strip() or "encapsulated_service"
    try:
        subprocess.check_call(["docker", "build", "-t", image_name, build_context])
        print(f"[INFO] Docker image '{image_name}' built successfully.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to build Docker image: {e}")
        sys.exit(1)
    
    # Optionally run the container from the newly built image
    run_container = input("Would you like to run a container from this image? (y/n): ").strip().lower() == "y"
    if run_container:
        container_name = input("Enter a name for the container (default 'service_container'): ").strip() or "service_container"
        cmd = ["docker", "run", "-d", "--name", container_name]
        # Enforce read-only + non-root if chosen
        cmd = maybe_apply_read_only_and_nonroot(cmd)
        cmd.append(image_name)
        
        try:
            subprocess.check_call(cmd)
            print(f"[INFO] Container '{container_name}' launched from image '{image_name}'.")
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Failed to run container '{container_name}': {e}")
    else:
        print("[INFO] Container build process completed. You can run the image later using 'docker run'.")

# -------------------------------------------------
# 8. Integrity Check Menu
# -------------------------------------------------

def run_integrity_check_menu():
    """Interactive prompt to run continuous integrity checks."""
    print("==== Continuous Integrity Check ====")
    print("1. Integrity check for a single container")
    print("2. Integrity check for multiple/all containers")
    choice = input("Choose an option (1/2): ").strip()
    
    if choice == "1":
        container_name = input("Enter the container name to monitor: ").strip()
        snapshot_tar = input("Enter the path to the snapshot .tar file for restoration (or blank to skip): ").strip()
        check_interval_str = input("Enter integrity check interval in seconds (default 30): ").strip()
        try:
            check_interval = int(check_interval_str) if check_interval_str else 30
        except ValueError:
            check_interval = 30
        check_all_dependencies()
        if snapshot_tar:
            continuous_integrity_check(container_name, snapshot_tar, check_interval)
        else:
            minimal_integrity_check(container_name, check_interval)
    elif choice == "2":
        run_integrity_check_for_all()
    else:
        print("[ERROR] Invalid choice. Exiting.")

def run_integrity_check_for_all():
    """
    Apply continuous integrity check to all running containers (or let user pick).
    Each container needs its own snapshot .tar if you want to restore from changes.
    """
    check_all_dependencies()
    try:
        output = subprocess.check_output(["docker", "ps", "--format", "{{.Names}}"], text=True)
        running_containers = output.split()
        if not running_containers:
            print("[INFO] No running containers found.")
            return
        print("[INFO] The following containers are running:")
        for idx, c in enumerate(running_containers, 1):
            print(f"  {idx}. {c}")
        
        choice = input("Enter 'all' to run integrity checks on all, or comma-separated indexes: ").strip().lower()
        if choice == "all":
            selected = running_containers
        else:
            indexes = [x.strip() for x in choice.split(",") if x.strip()]
            selected = []
            for i in indexes:
                try:
                    idx = int(i)
                    if 1 <= idx <= len(running_containers):
                        selected.append(running_containers[idx - 1])
                except ValueError:
                    pass
        if not selected:
            print("[ERROR] No valid containers selected. Exiting.")
            return
        
        check_interval_str = input("Enter integrity check interval in seconds (default 30): ").strip()
        try:
            check_interval = int(check_interval_str) if check_interval_str else 30
        except ValueError:
            check_interval = 30
        
        for container_name in selected:
            print(f"\n==== Setting up integrity check for container '{container_name}' ====")
            snapshot_tar = input("Enter the path to the snapshot .tar file for restoration (blank to skip): ").strip()
            if not snapshot_tar:
                print(f"[INFO] Skipping snapshot-based restoration for '{container_name}'. (Will just hash-check without restore.)")
                minimal_integrity_check(container_name, check_interval)
            else:
                continuous_integrity_check(container_name, snapshot_tar, check_interval)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not list running containers: {e}")

# -------------------------------------------------
# 9. Advanced OS-Based Containerization
# -------------------------------------------------

def advanced_os_containerize_service():
    """
    Similar to containerize_service(), but attempts to detect installed packages
    and replicate them in the container. We skip directories that don't exist,
    so it won't fail if e.g. /etc/httpd is missing.
    """
    check_all_dependencies()
    os_name, version = detect_os()
    base_image = map_os_to_docker_image(os_name, version)
    print(f"[INFO] Advanced OS-based containerization. Using base image: {base_image}")

    build_context = "advanced_os_build_context"
    if os.path.exists(build_context):
        print(f"[INFO] Removing existing build context '{build_context}'.")
        shutil.rmtree(build_context)
    os.makedirs(build_context)

    # 1) Attempt to detect installed packages (best-effort).
    packages_to_install = []
    sysname = platform.system().lower()

    if sysname.startswith("linux"):
        if shutil.which("rpm"):
            # Check for some typical RPM packages
            common_rpm_packages = ["httpd", "php", "php-mysql", "mariadb-server"]
            for pkg in common_rpm_packages:
                try:
                    ret = subprocess.call(["rpm", "-q", pkg],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if ret == 0:
                        packages_to_install.append(pkg)
                except:
                    pass
        elif shutil.which("dpkg"):
            # Check for some typical Debian/Ubuntu packages
            common_deb_packages = ["apache2", "php", "php-mysql", "mariadb-server"]
            for pkg in common_deb_packages:
                try:
                    ret = subprocess.call(["dpkg", "-l", pkg],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if ret == 0:
                        packages_to_install.append(pkg)
                except:
                    pass

    print(f"[INFO] Detected packages on host that might need installing: {packages_to_install}")

    # 2) Copy critical directories (skip if missing).
    directories_to_copy = {
        "var_lib_mysql": "/var/lib/mysql",
        "etc_httpd": "/etc/httpd",
        "etc_apache2": "/etc/apache2",
        "var_www_html": "/var/www/html",
        "etc_php": "/etc/php",
        "etc_ssl": "/etc/ssl",
        "var_log_apache2": "/var/log/apache2",
        "var_log_httpd": "/var/log/httpd"
    }

    copied_subdirs = []
    for subdir, src in directories_to_copy.items():
        if os.path.exists(src):
            dest = os.path.join(build_context, subdir)
            try:
                print(f"[INFO] Copying '{src}' to build context as '{dest}'.")
                shutil.copytree(src, dest)
                copied_subdirs.append(subdir)
            except Exception as e:
                print(f"[WARN] Failed to copy {src}: {e}")
        else:
            print(f"[WARN] Source directory {src} does not exist. Skipping.")

    # 3) Generate Dockerfile
    dockerfile_path = os.path.join(build_context, "Dockerfile")
    install_cmd = ""
    if packages_to_install:
        if any(x in base_image for x in ["centos", "fedora"]):
            pkgs_str = " ".join(packages_to_install)
            install_cmd = (
                "RUN yum -y install " + pkgs_str + " && yum clean all"
            )
        elif any(x in base_image for x in ["ubuntu", "debian"]):
            pkgs_str = " ".join(packages_to_install)
            install_cmd = (
                "RUN apt-get update && "
                "DEBIAN_FRONTEND=noninteractive "
                "TZ=America/Denver "
                f"apt-get install -y {pkgs_str} && "
                "apt-get clean"
            )
        else:
            install_cmd = "# (No recognized distro for auto-install)"

    # Generate COPY lines only for subdirs we actually copied
    copy_lines = []
    for subdir in copied_subdirs:
        if subdir == "var_lib_mysql":
            copy_lines.append("COPY var_lib_mysql/ /var/lib/mysql/")
        elif subdir == "etc_httpd":
            copy_lines.append("COPY etc_httpd/ /etc/httpd/")
        elif subdir == "etc_apache2":
            copy_lines.append("COPY etc_apache2/ /etc/apache2/")
        elif subdir == "var_www_html":
            copy_lines.append("COPY var_www_html/ /var/www/html/")
        elif subdir == "etc_php":
            copy_lines.append("COPY etc_php/ /etc/php/")
        elif subdir == "etc_ssl":
            copy_lines.append("COPY etc_ssl/ /etc/ssl/")
        elif subdir == "var_log_apache2":
            copy_lines.append("COPY var_log_apache2/ /var/log/apache2/")
        elif subdir == "var_log_httpd":
            copy_lines.append("COPY var_log_httpd/ /var/log/httpd/")

    dockerfile_content = f"""FROM {base_image}

# Avoid interactive tzdata config
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=America/Denver

{install_cmd}

# Copy service configuration and data
"""
    for line in copy_lines:
        dockerfile_content += line + "\n"

    dockerfile_content += """
# Expose typical web ports (adjust as needed)
EXPOSE 80

# Default command - if httpd is installed, try to run it
CMD ["httpd", "-D", "FOREGROUND"]
"""

    with open(dockerfile_path, "w") as f:
        f.write(dockerfile_content)
    print(f"[INFO] Dockerfile created at", dockerfile_path)

    # 4) Build the Docker image
    image_name = input("Enter the name for the advanced OS-based Docker image (default 'os_based_service'): ").strip() or "os_based_service"
    try:
        subprocess.check_call(["docker", "build", "-t", image_name, build_context])
        print(f"[INFO] Docker image '{image_name}' built successfully.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to build Docker image: {e}")
        sys.exit(1)

    # 5) Optionally run the container
    run_container = input("Would you like to run a container from this advanced image? (y/n): ").strip().lower() == "y"
    if run_container:
        container_name = input("Enter a name for the container (default 'advanced_service_container'): ").strip() or "advanced_service_container"
        cmd = ["docker", "run", "-d", "--name", container_name]
        cmd = maybe_apply_read_only_and_nonroot(cmd)
        cmd.append(image_name)
        try:
            subprocess.check_call(cmd)
            print(f"[INFO] Container '{container_name}' launched from image '{image_name}'.")
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Failed to run container '{container_name}': {e}")
    else:
        print("[INFO] Build completed. You can run the image later using 'docker run'.")

# -------------------------------------------------
# 10. Main Interactive Menu
# -------------------------------------------------

def interactive_menu():
    """
    Display the interactive menu for each major step.
    You can choose to run only the parts you want, one at a time.
    """
    while True:
        print("\n==== CCDC Container Deployment Tool ====")
        print("1. Containerize Current Service Environment (simple copy of expanded directories)")
        print("2. Setup Docker Database (e.g., MariaDB)")
        print("3. Setup Docker WAF (e.g., ModSecurity)")
        print("4. Run Continuous Integrity Check (single or multiple containers)")
        print("5. Deploy Entire Web Stack (DB + Containerized Web App) [Modified Legacy]")
        print("6. Advanced OS-Based Containerization (migrate host OS & packages)")
        print("7. Exit")
        choice = input("Enter your choice (1-7): ").strip()
        
        if choice == "1":
            containerize_service()
        elif choice == "2":
            setup_docker_db()
        elif choice == "3":
            setup_docker_waf()
        elif choice == "4":
            run_integrity_check_menu()
        elif choice == "5":
            deploy_entire_web_stack_legacy()
        elif choice == "6":
            advanced_os_containerize_service()
        elif choice == "7":
            print("[INFO] Exiting. Goodbye!")
            sys.exit(0)
        else:
            print("[ERROR] Invalid option. Please try again.")

def main():
    parser = argparse.ArgumentParser(
        description="CCDC OS-to-Container & Integrity Tool with robust Docker group checks."
    )
    parser.add_argument("--menu", action="store_true", help="Launch interactive menu")
    args = parser.parse_args()
    if args.menu:
        interactive_menu()
    else:
        print("Usage: Run the script with '--menu' to launch the interactive menu.")
        sys.exit(0)

if __name__ == "__main__":
    main()
