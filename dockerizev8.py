#!/usr/bin/env python3
"""
ccdc_integrity_tool.py
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
    except:
        return False

def fix_docker_group():
    """
    Attempt to add the current user to the 'docker' group, enable & start Docker,
    then re-exec the script under `sg docker -c "..."`.
    """
    try:
        current_user = os.getlogin()
    except:
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
        # Already tried group fix once. Let's see if we can run docker now.
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
                    # Prompt again
            elif choice == "c":
                # Loop again to prompt for a new name
                continue
            else:
                print("[INFO] Exiting.")
                sys.exit(1)

# -------------------------------------------------
# 5. Deploy Web Stack (DB + Web + Optional WAF)
# -------------------------------------------------

def deploy_web_stack():
    """
    Deploy a DB container (optional) + a web app container (e.g., PrestaShop) + optional ModSecurity WAF.
    Defaults to not using read-only for PrestaShop/WAF to keep them running.
    """
    print("==== Deploy Web Stack ====")
    check_all_dependencies()
    
    # Step 1: DB choice
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
        
        # Prompt for directories to mount
        volume_opts_db = []
        print("[NOTE] A database container typically needs write access.")
        print("Mount /var/lib/mysql or other directories if you want to store data on the host.")
        while True:
            dir_input = input("Directories to mount into the DB container (blank to finish): ").strip()
            if not dir_input:
                break
            volume_opts_db.extend(["-v", f"{dir_input}:{dir_input}"])
        
        # We'll default the DB container to not read-only:
        db_read_only = input("Should the DB container run in read-only mode? (y/n) [n]: ").strip().lower() == "y"
        
        pull_docker_image("mariadb:latest")
        
        db_password = input("Enter MariaDB root password (default 'root'): ").strip() or "root"
        db_user = "root"
        db_name = input("Enter a DB name to create (default 'prestashop'): ").strip() or "prestashop"
        
        cmd = [
            "docker", "run", "-d",
            "--name", db_container,
            "--network", network_name
        ]
        cmd.extend(volume_opts_db)
        
        cmd.extend([
            "-e", f"MYSQL_ROOT_PASSWORD={db_password}",
            "-e", f"MYSQL_DATABASE={db_name}"
        ])
        if db_read_only:
            cmd.append("--read-only")
        
        cmd.append("mariadb:latest")
        
        print(f"[INFO] Launching MariaDB container '{db_container}'.")
        try:
            subprocess.check_call(cmd)
            db_host = db_container  # We'll use the container name as the DB host inside Docker network
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Could not launch MariaDB container '{db_container}': {e}")
            sys.exit(1)
    
    # Step 3: Deploy the web app container
    print("Select an E-Commerce platform or web service to deploy:")
    print("1. PrestaShop")
    print("2. OpenCart")
    print("3. Zen Cart")
    print("4. WordPress")
    print("5. LAMP / XAMPP")
    ecomm_choice = input("Enter your choice (1-5): ").strip()
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
    
    default_web_name = "web_container"
    print("=== Web Application Container Setup ===")
    service_container = prompt_for_container_name(default_web_name)
    
    # Prompt for directories to mount in the web container
    volume_opts_web = []
    print("Mounting /var/www/html by default for PrestaShop or WordPress to store data.")
    volume_opts_web.extend(["-v", f"/var/www/html:/var/www/html"])
    
    while True:
        dir_input = input("Additional directories to mount into the web container (blank to finish): ").strip()
        if not dir_input:
            break
        volume_opts_web.extend(["-v", f"{dir_input}:{dir_input}"])
    
    # We'll default the web container to not read-only for PrestaShop, WAF, etc.
    web_read_only = input("Should the web container run in read-only mode? (y/n) [n]: ").strip().lower() == "y"
    
    # Additional environment variables for DB
    env_vars = []
    if ecomm_choice == "1":
        # PrestaShop: force auto-install so it doesn't exit
        env_vars.extend(["-e", "PS_INSTALL_AUTO=1"])
    
    if dockerized_db:
        env_vars.extend([
            "-e", f"DB_SERVER={db_host}",
            "-e", f"DB_USER={db_user}",
            "-e", f"DB_PASSWORD={db_password}",
            "-e", f"DB_NAME={db_name}"
        ])
    else:
        db_host = input("Enter the native DB host (default 'localhost'): ").strip() or "localhost"
        db_user = input("Enter DB user (default 'root'): ").strip() or "root"
        db_password = input("Enter DB password (default 'root'): ").strip() or "root"
        db_name = input("Enter DB name (default 'prestashop'): ").strip() or "prestashop"
        env_vars.extend([
            "-e", f"DB_SERVER={db_host}",
            "-e", f"DB_USER={db_user}",
            "-e", f"DB_PASSWORD={db_password}",
            "-e", f"DB_NAME={db_name}"
        ])
    
    cmd = [
        "docker", "run", "-d",
        "--name", service_container,
        "--network", network_name
    ]
    cmd.extend(volume_opts_web)
    cmd.extend(env_vars)
    
    if web_read_only:
        cmd.append("--read-only")
    
    cmd.append(service_image)
    
    print(f"[INFO] Launching service container '{service_container}' with image '{service_image}'.")
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not launch service container '{service_container}': {e}")
        sys.exit(1)
    
    # Step 4: Optionally deploy a ModSecurity WAF
    add_waf = input("Would you like to add a ModSecurity WAF? (y/n): ").strip().lower()
    if add_waf == "y":
        deploy_modsecurity_waf(network_name, service_container)
    
    # Step 5: Offer integrity checking
    run_integrity = input("Would you like to run continuous integrity checking on the web container? (y/n): ").strip().lower()
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
    linking it to the given backend container. Defaults to not read-only.
    """
    waf_image = "owasp/modsecurity-crs:nginx"
    pull_docker_image(waf_image)
    
    print("=== ModSecurity WAF Container Setup ===")
    default_waf_name = "modsec2-nginx"
    waf_container = prompt_for_container_name(default_waf_name)
    
    # We won't prompt for read-only by default, since the WAF may need to write logs.
    waf_read_only = input("Should the WAF container run in read-only mode? (y/n) [n]: ").strip().lower() == "y"
    host_waf_port = input("Enter host port for the WAF (default '8080'): ").strip() or "8080"
    
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
    
    cmd = [
        "docker", "run", "-d",
        "--network", network_name,
        "--name", waf_container,
        "-p", f"{host_waf_port}:8080"
    ]
    for env_var in waf_env:
        cmd.extend(["-e", env_var])
    
    if waf_read_only:
        cmd.append("--read-only")
    
    cmd.append(waf_image)
    
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not launch ModSecurity proxy container '{waf_container}': {e}")

# -------------------------------------------------
# 6. Additional Commands or Integrity Menus
# -------------------------------------------------

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
        
        # Let user pick all or just some
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
        
        # For each selected container, prompt for a snapshot path
        for container_name in selected:
            print(f"\n==== Setting up integrity check for container '{container_name}' ====")
            snapshot_tar = input("Enter the path to the snapshot .tar file for restoration (blank to skip): ").strip()
            if not snapshot_tar:
                print(f"[INFO] Skipping snapshot-based restoration for '{container_name}'. (Will just hash-check without restore.)")
                # We'll do a minimal integrity check loop that doesn't restore
                minimal_integrity_check(container_name, check_interval)
            else:
                # Full continuous check with restore
                continuous_integrity_check(container_name, snapshot_tar, check_interval)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not list running containers: {e}")

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
                # We could break or continue checking
                # Let's continue checking, but won't restore
                baseline_hash = current_hash
            else:
                print(f"[INFO] Container '{container_name}' is unchanged.")
    except KeyboardInterrupt:
        print("\n[INFO] Minimal integrity check interrupted by user.")

def run_integrity_check_menu():
    """Interactive prompt to run continuous integrity check."""
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

# -------------------------------------------------
# 7. Interactive Main Menu
# -------------------------------------------------

def interactive_menu():
    """Display the interactive menu for container deployment and integrity checking."""
    print("==== CCDC Container Deployment Tool ====")
    print("Select an option:")
    print("1. Deploy Web Stack (DB + Web App + Optional WAF)")
    print("2. Run Continuous Integrity Check")
    choice = input("Enter your choice (1/2): ").strip()
    
    if choice == "1":
        deploy_web_stack()
    elif choice == "2":
        run_integrity_check_menu()
    else:
        print("[ERROR] Invalid option. Exiting.")
        sys.exit(1)

# -------------------------------------------------
# 8. Main Entry Point
# -------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="CCDC OS-to-Container & Integrity Tool with multi-container checks, improved PrestaShop/WAF deployment, and better volume handling."
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
