#!/usr/bin/env python3
"""
ccdc_integrity_tool.py

A comprehensive tool for CCDC-style environments that:

1. Installs Docker (auto-install regardless of OS) and configures containers.
   - Deploys a container that either matches the host OS
     or emulates a critical service (e.g., an e-commerce platform).
   - Containers run in read-only mode as non-root.

2. Continuously performs integrity checks on a running container.
   - Computes a hash of the container's filesystem periodically.
   - If modifications are detected, restores the container from a snapshot (.tar file).

3. Optionally deploys a ModSecurity WAF reverse proxy linked to the deployed container.

Usage (Interactive Menu):
  Run the script with the '--menu' flag:
    python3 ccdc_integrity_tool.py --menu

Notes:
  - If Docker is missing or the user can’t run `docker`, the script attempts to fix it automatically:
    * Installs Docker (best-effort) on Linux, BSD, or Nix.
    * Adds the user to the 'docker' group.
    * Re-executes itself under `sg docker -c "..."` so the group membership is effective.
  - This avoids dropping you into a new shell prompt as `newgrp` does.
  - The logic is best-effort and may fail on less common distros or OSes.
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
# 1. Docker Auto-Installation & Group-Fix Logic
# -------------------------------------------------

def detect_linux_package_manager():
    """Detect common Linux package managers."""
    for pm in ["apt", "apt-get", "dnf", "yum", "zypper"]:
        if shutil.which(pm):
            return pm
    return None

def attempt_install_docker_linux():
    """Attempt to install Docker on Linux using a best-effort approach."""
    pm = detect_linux_package_manager()
    if not pm:
        print("[ERROR] No recognized package manager found on Linux. Cannot auto-install Docker.")
        return False

    print(f"[INFO] Attempting to install Docker using '{pm}' on Linux...")
    try:
        if pm in ("apt", "apt-get"):
            subprocess.check_call(["sudo", pm, "update", "-y"])
            subprocess.check_call(["sudo", pm, "install", "-y", "docker.io"])
        elif pm in ("yum", "dnf"):
            subprocess.check_call(["sudo", pm, "-y", "install", "docker"])
            subprocess.check_call(["sudo", "systemctl", "enable", "docker"])
            subprocess.check_call(["sudo", "systemctl", "start", "docker"])
        elif pm == "zypper":
            subprocess.check_call(["sudo", "zypper", "refresh"])
            subprocess.check_call(["sudo", "zypper", "--non-interactive", "install", "docker"])
            subprocess.check_call(["sudo", "systemctl", "enable", "docker"])
            subprocess.check_call(["sudo", "systemctl", "start", "docker"])
        else:
            print(f"[ERROR] Package manager '{pm}' is not fully supported for auto-installation.")
            return False
        print("[INFO] Docker installation attempt completed. Checking if Docker is now available.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Auto-installation of Docker on Linux failed: {e}")
        return False

def attempt_install_docker_bsd():
    """Attempt to install Docker on BSD using 'pkg' (best-effort)."""
    pkg_path = shutil.which("pkg")
    if not pkg_path:
        print("[ERROR] 'pkg' not found. Cannot auto-install Docker on BSD.")
        return False
    print("[INFO] Attempting to install Docker using 'pkg' on BSD (best-effort).")
    try:
        subprocess.check_call(["sudo", "pkg", "update"])
        subprocess.check_call(["sudo", "pkg", "install", "-y", "docker"])
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Auto-installation of Docker on BSD failed: {e}")
        return False

def attempt_install_docker_nix():
    """Attempt to install Docker on Nix-based systems using 'nix-env -i docker' (very best-effort)."""
    nixenv_path = shutil.which("nix-env")
    if not nixenv_path:
        print("[ERROR] 'nix-env' not found. Cannot auto-install Docker on Nix.")
        return False
    print("[INFO] Attempting to install Docker using 'nix-env -i docker' on Nix.")
    try:
        subprocess.check_call(["sudo", "nix-env", "-i", "docker"])
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Auto-installation of Docker on Nix failed: {e}")
        return False

def can_run_docker():
    """Return True if we can run 'docker ps' without error, else False."""
    try:
        subprocess.check_call(["docker", "ps"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

def fix_docker_group():
    """
    Attempt to add the current user to the 'docker' group, enable & start Docker,
    then re-exec the script under `sg docker -c "..."`.
    """
    try:
        current_user = os.getlogin()
    except Exception:
        current_user = os.environ.get("USER", "unknown")
    print(f"[INFO] Adding user '{current_user}' to docker group.")
    try:
        subprocess.check_call(["sudo", "usermod", "-aG", "docker", current_user])
    except subprocess.CalledProcessError as e:
        print(f"[WARN] Could not add user to docker group: {e}")

    # On Linux, attempt to enable/start Docker
    if platform.system().lower().startswith("linux"):
        try:
            subprocess.check_call(["sudo", "systemctl", "enable", "docker"])
            subprocess.check_call(["sudo", "systemctl", "start", "docker"])
        except subprocess.CalledProcessError as e:
            print(f"[WARN] Could not enable/start docker service: {e}")

    # Re-exec with 'sg docker' to avoid dropping user into an interactive shell
    print("[INFO] Re-executing script under 'sg docker' to activate group membership.")
    os.environ["CCDC_DOCKER_GROUP_FIX"] = "1"  # Avoid infinite loops
    script_path = os.path.abspath(sys.argv[0])
    script_args = sys.argv[1:]
    command_line = f'export CCDC_DOCKER_GROUP_FIX=1; exec "{sys.executable}" "{script_path}" ' + " ".join(f'"{arg}"' for arg in script_args)
    cmd = ["sg", "docker", "-c", command_line]
    os.execvp("sg", cmd)

def ensure_docker_installed():
    """
    Check if Docker is installed & if the user can run it.
    If missing, attempt auto-install. If the user isn't in docker group, fix that, then re-exec with sg.
    """
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
        return

    sysname = platform.system().lower()
    if sysname.startswith("linux"):
        installed = attempt_install_docker_linux()
        if not installed:
            print("[ERROR] Could not auto-install Docker on Linux. Please install it manually.")
            sys.exit(1)
        if not can_run_docker():
            fix_docker_group()
        else:
            print("[INFO] Docker is installed and accessible on Linux now.")
    elif "bsd" in sysname:
        installed = attempt_install_docker_bsd()
        if not installed:
            print("[ERROR] Could not auto-install Docker on BSD. Please install it manually.")
            sys.exit(1)
        if not can_run_docker():
            fix_docker_group()
        else:
            print("[INFO] Docker is installed and accessible on BSD now.")
    elif "nix" in sysname:
        installed = attempt_install_docker_nix()
        if not installed:
            print("[ERROR] Could not auto-install Docker on Nix. Please install manually.")
            sys.exit(1)
        if not can_run_docker():
            fix_docker_group()
        else:
            print("[INFO] Docker is installed and accessible on Nix now.")
    elif sysname == "windows":
        print("[ERROR] Docker not found, and auto-install is not supported on Windows. Please install Docker or Docker Desktop manually.")
        sys.exit(1)
    else:
        print(f"[ERROR] Unrecognized system '{sysname}'. Docker is missing. Please install it manually.")
        sys.exit(1)

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

def check_docker_compose():
    """Check if Docker Compose is installed (warn if not)."""
    try:
        subprocess.check_call(["docker-compose", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("[INFO] Docker Compose is installed.")
    except Exception:
        print("[WARN] Docker Compose not found. Some orchestration features may be unavailable.")

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
        except Exception:
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
        "centos": {"6": "centos:6", "7": "centos:7", "8": "centos:8", "9": "centos:stream9", "": "ubuntu:latest"},
        "ubuntu": {"14": "ubuntu:14.04", "16": "ubuntu:16.04", "18": "ubuntu:18.04", "20": "ubuntu:20.04", "22": "ubuntu:22.04"},
        "debian": {"7": "debian:7", "8": "debian:8", "9": "debian:9", "10": "debian:10", "11": "debian:11", "12": "debian:12"},
        "fedora": {"25": "fedora:25", "26": "fedora:26", "27": "fedora:27", "28": "fedora:28", "29": "fedora:29", "30": "fedora:30", "31": "fedora:31", "35": "fedora:35"},
        "opensuse leap": {"15": "opensuse/leap:15"},
        "opensuse tumbleweed": {"": "opensuse/tumbleweed"},
        "linux": {"": "ubuntu:latest"}
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

def run_generic_container(os_name, base_image, container_name="megatron"):
    """Launch a generic interactive container from the base image in read-only mode, non-root."""
    user = "nonroot" if os_name == "windows" else "nobody"
    shell_cmd = "cmd.exe" if os_name == "windows" else "/bin/bash"
    try:
        print(f"[INFO] Launching interactive container '{container_name}' from image '{base_image}' as user '{user}' in read-only mode.")
        subprocess.check_call([
            "docker", "run", "-it",
            "--read-only",
            "--user", user,
            "--name", container_name,
            base_image,
            shell_cmd
        ])
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not launch container '{container_name}': {e}")

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
        subprocess.check_call(["docker", "run", "-d", "--read-only", "--user", user, "--name", container_name, image_name])
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

# -------------------------------------------------
# 5. Web Container with Integrated ModSecurity WAF
# -------------------------------------------------

def deploy_web_with_waf():
    """
    Deploy a web container (matching host OS) with integrated ModSecurity WAF.
    The web container is a minimal OS-based container running a built-in web server (best-effort).
    """
    check_all_dependencies()
    os_name, version = detect_os()
    base_image = map_os_to_docker_image(os_name, version)
    print(f"[INFO] Detected OS: {os_name} (Version: {version}). Main web container base image: {base_image}")
    
    # Pull required images
    pull_docker_image(base_image)
    waf_image = "owasp/modsecurity-crs:nginx"
    pull_docker_image(waf_image)
    
    # Create a dedicated network
    network_name = "ccdc-web-net"
    try:
        subprocess.check_call(["docker", "network", "inspect", network_name],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[INFO] Docker network '{network_name}' already exists.")
    except subprocess.CalledProcessError:
        print(f"[INFO] Creating Docker network '{network_name}'.")
        subprocess.check_call(["docker", "network", "create", network_name])
    
    # Ask user for container names and ports
    web_container = input("Enter the main web container name (default 'web_container'): ").strip() or "web_container"
    waf_container = input("Enter the ModSecurity proxy container name (default 'modsec2-nginx'): ").strip() or "modsec2-nginx"
    host_web_port = input("Enter host port for the web container (default '8080'): ").strip() or "8080"
    host_waf_port = input("Enter host port for the WAF (default '80'): ").strip() or "80"
    
    # Pick a built-in server command based on OS
    user = "nonroot" if os_name == "windows" else "nobody"
    if os_name == "windows":
        server_cmd = ("powershell.exe -Command \"Write-Host 'Starting minimal web server...'; "
                     "while($true){echo 'HTTP/1.1 200 OK`r`n`r`nHello from Windows Container' | nc -l -p 80}\"")
        container_port = "80"
    else:
        server_cmd = ("/bin/sh -c 'which python3 && python3 -m http.server 80 || "
                      "(which busybox && busybox httpd -f -p 80 || echo \"No server found\" && sleep infinity)'")
        container_port = "80"
    
    # Launch web container
    try:
        print(f"[INFO] Launching web container '{web_container}' with a minimal built-in server (best-effort).")
        subprocess.check_call([
            "docker", "run", "-d",
            "--read-only",
            "--user", user,
            "--name", web_container,
            "--network", network_name,
            "-p", f"{host_web_port}:{container_port}",
            base_image,
            "sh", "-c", server_cmd
        ])
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not launch main web container '{web_container}': {e}")
        sys.exit(1)
    
    # Launch the WAF container
    tz = os.environ.get("TZ", "UTC")
    waf_env = [
        "PORT=8080",
        "PROXY=1",
        f"BACKEND=http://{web_container}:{container_port}",
        "MODSEC_RULE_ENGINE=off",
        "BLOCKING_PARANOIA=2",
        f"TZ={tz}",
        "MODSEC_TMP_DIR=/tmp",
        "MODSEC_RESP_BODY_ACCESS=On",
        "MODSEC_RESP_BODY_MIMETYPE=text/plain text/html text/xml application/json",
        "COMBINED_FILE_SIZES=65535"
    ]
    try:
        print(f"[INFO] Launching ModSecurity proxy container '{waf_container}' from image '{waf_image}'...")
        subprocess.check_call([
            "docker", "run", "-d",
            "--read-only",
            "--user", user,
            "--name", waf_container,
            "--network", network_name,
            "-p", f"{host_waf_port}:8080",
            "--env", waf_env[0],
            "--env", waf_env[1],
            "--env", waf_env[2],
            "--env", waf_env[3],
            "--env", waf_env[4],
            "--env", waf_env[5],
            "--env", waf_env[6],
            "--env", waf_env[7],
            "--env", waf_env[8],
            "--env", waf_env[9],
            waf_image
        ])
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not launch ModSecurity proxy container '{waf_container}': {e}")
        sys.exit(1)
    
    print(f"[INFO] Deployment complete. The web container '{web_container}' is running on container port {container_port} (mapped to host port {host_web_port}).")
    print(f"[INFO] The ModSecurity proxy '{waf_container}' is listening on host port {host_waf_port} and forwarding to '{web_container}:{container_port}'.")

# -------------------------------------------------
# 6. Service Container Deployment (New)
# -------------------------------------------------

def deploy_service_container():
    """
    Deploy a container for a critical service.
    Currently supports a submenu for e-commerce platforms.
    """
    print("==== Deploy Service Container ====")
    print("Select service type:")
    print("1. E-Commerce")
    service_choice = input("Enter your choice: ").strip()
    if service_choice == "1":
        deploy_ecomm_container()
    else:
        print("[ERROR] Service type not implemented. Exiting.")
        sys.exit(1)

def deploy_ecomm_container():
    """
    Deploy an e-commerce container.
    Allows selection from common platforms, optional dockerized DB,
    mounting configuration directories, and optionally adding a ModSecurity WAF.
    """
    print("Select an E-Commerce platform to deploy:")
    print("1. PrestaShop")
    print("2. OpenCart")
    print("3. Zen Cart")
    print("4. WordPress")
    print("5. LAMP / XAMPP")
    ecomm_choice = input("Enter your choice: ").strip()
    ecomm_images = {
        "1": ("PrestaShop", "prestashop/prestashop:latest"),
        "2": ("OpenCart", "opencart/opencart:latest"),
        "3": ("Zen Cart", "zencart/zencart:latest"),
        "4": ("WordPress", "wordpress:latest"),
        "5": ("LAMP", "linode/lamp:latest")
    }
    if ecomm_choice not in ecomm_images:
        print("[ERROR] Invalid choice. Exiting.")
        sys.exit(1)
    service_name, service_image = ecomm_images[ecomm_choice]
    print(f"[INFO] Selected {service_name} with image {service_image}")
    pull_docker_image(service_image)
    
    # Ask user about database option
    db_choice = input("Use dockerized database (D) or native OS database (N)? (D/N): ").strip().lower()
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
    
    # Set container names
    service_container = input("Enter a name for the service container (default 'service_container'): ").strip() or "service_container"
    if dockerized_db:
        db_container = input("Enter a name for the DB container (default 'mariadb'): ").strip() or "mariadb"
    else:
        db_container = None
         
    # Deploy dockerized DB if selected
    if dockerized_db:
        pull_docker_image("mariadb:latest")
        db_root_password = input("Enter MariaDB root password (default 'root'): ").strip() or "root"
        print(f"[INFO] Launching MariaDB container '{db_container}'.")
        try:
            subprocess.check_call([
                "docker", "run", "-d",
                "--name", db_container,
                "--network", network_name,
                "-e", f"MYSQL_ROOT_PASSWORD={db_root_password}",
                "mariadb:latest"
            ])
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Could not launch MariaDB container '{db_container}': {e}")
            sys.exit(1)
    
    # Ask for directories to mount (for configuration file integration)
    dirs_input = input("Enter directories to mount into the container (comma-separated, e.g., /var/www/html,/etc/apache2) or leave blank: ").strip()
    volume_opts = []
    if dirs_input:
        dirs = [d.strip() for d in dirs_input.split(",") if d.strip()]
        for d in dirs:
            volume_opts.extend(["-v", f"{d}:{d}"])
    
    # Build the docker run command for the service container
    cmd = [
        "docker", "run", "-d",
        "--read-only",
        "--network", network_name,
        "--name", service_container
    ]
    if volume_opts:
        cmd.extend(volume_opts)
    
    # If using dockerized DB, pass DB connection info as environment variables.
    if dockerized_db:
        cmd.extend(["-e", f"DB_HOST={db_container}"])
        cmd.extend(["-e", f"DB_ROOT_PASSWORD={db_root_password}"])
    
    cmd.append(service_image)
    
    print(f"[INFO] Launching service container '{service_container}' with image '{service_image}'.")
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not launch service container '{service_container}': {e}")
        sys.exit(1)
    
    # Optionally, deploy a ModSecurity WAF
    add_waf = input("Would you like to add a ModSecurity WAF? (y/n): ").strip().lower()
    if add_waf == "y":
        deploy_modsecurity_waf(network_name, service_container)
    
    # Optionally, run continuous integrity checking
    run_integrity = input("Would you like to run continuous integrity checking on the service container? (y/n): ").strip().lower()
    if run_integrity == "y":
        snapshot_tar = input("Enter the path to the snapshot .tar file for restoration: ").strip()
        check_interval_str = input("Enter integrity check interval in seconds (default 30): ").strip()
        try:
            check_interval = int(check_interval_str) if check_interval_str else 30
        except ValueError:
            check_interval = 30
        continuous_integrity_check(service_container, snapshot_tar, check_interval)

def deploy_modsecurity_waf(network_name, backend_container):
    """
    Deploy a ModSecurity-enabled reverse proxy container on the specified network,
    linking it to the given backend container.
    """
    waf_image = "owasp/modsecurity-crs:nginx"
    pull_docker_image(waf_image)
    waf_container = input("Enter the ModSecurity proxy container name (default 'modsec2-nginx'): ").strip() or "modsec2-nginx"
    host_waf_port = input("Enter host port for the WAF (default '80'): ").strip() or "80"
    tz = os.environ.get("TZ", "UTC")
    waf_env = [
        "PORT=8080",
        "PROXY=1",
        f"BACKEND=http://{backend_container}:80",
        "MODSEC_RULE_ENGINE=off",
        "BLOCKING_PARANOIA=2",
        f"TZ={tz}",
        "MODSEC_TMP_DIR=/tmp",
        "MODSEC_RESP_BODY_ACCESS=On",
        "MODSEC_RESP_BODY_MIMETYPE=text/plain text/html text/xml application/json",
        "COMBINED_FILE_SIZES=65535"
    ]
    print(f"[INFO] Launching ModSecurity proxy container '{waf_container}' from image '{waf_image}'...")
    try:
        subprocess.check_call([
            "docker", "run", "-d",
            "--read-only",
            "--network", network_name,
            "--name", waf_container,
            "-p", f"{host_waf_port}:8080",
            "--env", waf_env[0],
            "--env", waf_env[1],
            "--env", waf_env[2],
            "--env", waf_env[3],
            "--env", waf_env[4],
            "--env", waf_env[5],
            "--env", waf_env[6],
            "--env", waf_env[7],
            "--env", waf_env[8],
            "--env", waf_env[9],
            waf_image
        ])
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not launch ModSecurity proxy container '{waf_container}': {e}")

# -------------------------------------------------
# 7. Continuous Integrity Check Menu (Refactored)
# -------------------------------------------------

def run_integrity_check_menu():
    """Interactive prompt to run continuous integrity check on a container."""
    print("==== Continuous Integrity Check ====")
    container_name = input("Enter the container name to monitor: ").strip()
    snapshot_tar = input("Enter the path to the snapshot .tar file for restoration: ").strip()
    check_interval_str = input("Enter integrity check interval in seconds (default 30): ").strip()
    try:
        check_interval = int(check_interval_str) if check_interval_str else 30
    except ValueError:
        check_interval = 30
    check_all_dependencies()
    continuous_integrity_check(container_name, snapshot_tar, check_interval)

# -------------------------------------------------
# 8. Interactive Main Menu
# -------------------------------------------------

def interactive_menu():
    """Display the interactive menu for container deployment and integrity checking."""
    print("==== CCDC Container Deployment Tool ====")
    print("Select an option:")
    print("1. Install Matching OS Container")
    print("2. Install Matching Service Container")
    print("3. Run Continuous Integrity Check on a Container")
    print("4. Deploy OS-based Web Container + Integrated ModSecurity WAF")
    choice = input("Enter your choice (1/2/3/4): ").strip()
    check_all_dependencies()
    if choice == "1":
        print("[MODE 1] Installing & Configuring OS-Matched Container...")
        os_name, version = detect_os()
        base_image = map_os_to_docker_image(os_name, version)
        print(f"[INFO] Detected OS: {os_name} (Version: {version}). Using base image: {base_image}")
        pull_docker_image(base_image)
        run_generic_container(os_name, base_image)
    elif choice == "2":
        print("[MODE 2] Deploying Service Container...")
        deploy_service_container()
    elif choice == "3":
        run_integrity_check_menu()
    elif choice == "4":
        print("[MODE 4] Deploying OS-based Web Container with Integrated ModSecurity WAF...")
        deploy_web_with_waf()
    else:
        print("[ERROR] Invalid option. Exiting.")
        sys.exit(1)

# -------------------------------------------------
# 9. Main Entry Point
# -------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="CCDC OS-to-Container & Integrity Tool: auto-installs Docker if missing, deploys containers (OS- or service-matched), and integrates WAF and integrity checking."
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
