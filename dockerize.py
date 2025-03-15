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
# 1. Docker & Docker Compose Auto-Installation
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
        env = os.environ.copy()
        env["DEBIAN_FRONTEND"] = "noninteractive"
        env["TZ"] = "America/Denver"

        if pm in ("apt", "apt-get"):
            subprocess.check_call(["sudo", pm, "update", "-y"], env=env)
            subprocess.check_call(["sudo", pm, "install", "-y", "docker.io"], env=env)
        elif pm in ("yum", "dnf"):
            subprocess.check_call(["sudo", pm, "-y", "install", "docker"], env=env)
            subprocess.check_call(["sudo", "systemctl", "enable", "docker"], env=env)
            subprocess.check_call(["sudo", "systemctl", "start", "docker"], env=env)
        elif pm == "zypper":
            subprocess.check_call(["sudo", "zypper", "refresh"], env=env)
            subprocess.check_call(["sudo", "zypper", "--non-interactive", "install", "docker"], env=env)
            subprocess.check_call(["sudo", "systemctl", "enable", "docker"], env=env)
            subprocess.check_call(["sudo", "systemctl", "start", "docker"], env=env)
        else:
            print(f"[ERROR] Package manager '{pm}' is not fully supported for auto-installation.")
            return False

        print("[INFO] Docker installation attempt completed. Checking if Docker is now available.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Auto-installation of Docker on Linux failed: {e}")
        return False

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

    if platform.system().lower().startswith("linux"):
        try:
            subprocess.check_call(["sudo", "systemctl", "enable", "docker"])
            subprocess.check_call(["sudo", "systemctl", "start", "docker"])
        except subprocess.CalledProcessError as e:
            print(f"[WARN] Could not enable/start docker service: {e}")

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
        print("[ERROR] Docker auto-install is not implemented for BSD in this script. Please install manually.")
        sys.exit(1)
    elif "nix" in sysname:
        print("[ERROR] Docker auto-install is not implemented for Nix in this script. Please install manually.")
        sys.exit(1)
    elif sysname == "windows":
        print("[ERROR] Docker not found, and auto-install is not supported on Windows. Please install Docker or Docker Desktop manually.")
        sys.exit(1)
    else:
        print(f"[ERROR] Unrecognized system '{sysname}'. Docker is missing. Please install it manually.")
        sys.exit(1)

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
            return name
        else:
            print(f"[ERROR] A container named '{name}' already exists.")
            choice = input("Options:\n  [R] Remove the existing container\n  [C] Choose another name\n  [X] Exit\nEnter your choice (R/C/X): ").strip().lower()
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
    If on Windows, just do --read-only.
    """
    read_only = input("Should this container run in read-only mode? (y/n) [n]: ").strip().lower() == "y"
    if read_only:
        sysname = platform.system().lower()
        cmd_list.append("--read-only")
        if not sysname.startswith("windows"):
            cmd_list.extend(["--user", "nobody"])
    return cmd_list

# -------------------------------------------------
# 5. Setup Docker DB & WAF (Existing Functions)
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
    
    network_name = input("Enter the Docker network to attach (default 'bridge'): ").strip() or "bridge"
    if network_name != "bridge":
        try:
            subprocess.check_call(["docker", "network", "inspect", network_name],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"[INFO] Using existing network '{network_name}'.")
        except subprocess.CalledProcessError:
            print(f"[INFO] Creating Docker network '{network_name}'.")
            subprocess.check_call(["docker", "network", "create", network_name])
    
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
# 6. Web Stack Containerization Options
# -------------------------------------------------

def option_comprehensive():
    """
    Comprehensive Run:
      - Install prerequisites
      - Detect OS and pull a matching base image
      - Detect website files in common directories and copy them into a build context
      - Generate a Dockerfile that installs the chosen web server and copies the website files
      - Build the image, stop host web services, and run the container in read-only, non-root mode
    """
    check_all_dependencies()
    os_name, version = detect_os()
    base_image = map_os_to_docker_image(os_name, version)
    print(f"[INFO] Detected OS: {os_name} {version}, using base image: {base_image}")
    pull_docker_image(base_image)
    
    web_server = input("Enter the web server to install in container (apache2/httpd) [apache2]: ").strip().lower() or "apache2"
    
    build_context = "comprehensive_build_context"
    if os.path.exists(build_context):
        print(f"[INFO] Removing existing build context '{build_context}'.")
        shutil.rmtree(build_context)
    os.makedirs(build_context)
    
    directories_to_copy = {
        "etc_httpd": "/etc/httpd",
        "etc_apache2": "/etc/apache2",
        "var_www_html": "/var/www/html",
        "etc_php": "/etc/php",
        "etc_ssl": "/etc/ssl"
    }
    
    copied_subdirs = []
    for subdir, src in directories_to_copy.items():
        if os.path.exists(src):
            dest = os.path.join(build_context, subdir)
            try:
                print(f"[INFO] Copying '{src}' to '{dest}'.")
                shutil.copytree(src, dest)
                copied_subdirs.append(subdir)
            except Exception as e:
                print(f"[WARN] Failed to copy {src}: {e}")
        else:
            print(f"[WARN] {src} not found; skipping.")
    
    dockerfile_path = os.path.join(build_context, "Dockerfile")
    dockerfile_lines = []
    dockerfile_lines.append(f"FROM {base_image}")
    dockerfile_lines.append("")
    dockerfile_lines.append("# Set noninteractive mode and timezone")
    dockerfile_lines.append("ENV DEBIAN_FRONTEND=noninteractive")
    dockerfile_lines.append("ENV TZ=America/Denver")
    dockerfile_lines.append("")
    # Add web server installation based on base image and user choice
    if "ubuntu" in base_image or "debian" in base_image:
        if web_server == "apache2":
            dockerfile_lines.append("RUN apt-get update && apt-get install -y apache2 && apt-get clean")
        else:
            dockerfile_lines.append("RUN apt-get update && apt-get install -y apache2 && apt-get clean")
    elif "centos" in base_image or "fedora" in base_image:
        if web_server == "httpd":
            dockerfile_lines.append("RUN yum install -y httpd && yum clean all")
        else:
            dockerfile_lines.append("RUN yum install -y httpd && yum clean all")
    else:
        dockerfile_lines.append("# Add web server installation command here as needed")
    
    dockerfile_lines.append("")
    dockerfile_lines.append("# Copy website files into container")
    for subdir in copied_subdirs:
        if subdir == "etc_httpd":
            dockerfile_lines.append("COPY etc_httpd/ /etc/httpd/")
        elif subdir == "etc_apache2":
            dockerfile_lines.append("COPY etc_apache2/ /etc/apache2/")
        elif subdir == "var_www_html":
            dockerfile_lines.append("COPY var_www_html/ /var/www/html/")
        elif subdir == "etc_php":
            dockerfile_lines.append("COPY etc_php/ /etc/php/")
        elif subdir == "etc_ssl":
            dockerfile_lines.append("COPY etc_ssl/ /etc/ssl/")
    dockerfile_lines.append("")
    dockerfile_lines.append("EXPOSE 80")
    dockerfile_lines.append("")
    if web_server == "apache2":
        dockerfile_lines.append('CMD ["apachectl", "-D", "FOREGROUND"]')
    elif web_server == "httpd":
        dockerfile_lines.append('CMD ["/usr/sbin/httpd", "-D", "FOREGROUND"]')
    else:
        dockerfile_lines.append('CMD ["sh"]')
    
    with open(dockerfile_path, "w") as f:
        f.write("\n".join(dockerfile_lines))
    print(f"[INFO] Dockerfile created at {dockerfile_path}")
    
    image_name = input("Enter name for the new container image (default 'comprehensive_website'): ").strip() or "comprehensive_website"
    try:
        subprocess.check_call(["docker", "build", "-t", image_name, build_context])
        print(f"[INFO] Docker image '{image_name}' built successfully.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to build Docker image: {e}")
        return
    
    print("[INFO] Stopping host web services (if running)...")
    for service in ["apache2", "httpd"]:
        try:
            subprocess.call(["sudo", "systemctl", "stop", service])
        except Exception as e:
            print(f"[WARN] Could not stop {service}: {e}")
    
    container_name = input("Enter a name for the new container (default 'website_container'): ").strip() or "website_container"
    cmd = ["docker", "run", "-d", "--name", container_name]
    cmd = maybe_apply_read_only_and_nonroot(cmd)
    cmd.append(image_name)
    try:
        subprocess.check_call(cmd)
        print(f"[INFO] Container '{container_name}' started successfully.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to start container '{container_name}': {e}")

def option_pull_container_to_match_os():
    """
    Pull container to match OS:
      Detect the host OS and pull the corresponding Docker image.
    """
    check_all_dependencies()
    os_name, version = detect_os()
    base_image = map_os_to_docker_image(os_name, version)
    print(f"[INFO] Detected OS: {os_name} {version}, pulling image: {base_image}")
    pull_docker_image(base_image)

def option_containerize_website():
    """
    Containerize website:
      Copy website-related files from host into a new Docker image and optionally run the container.
    """
    check_all_dependencies()
    os_name, version = detect_os()
    base_image = map_os_to_docker_image(os_name, version)
    print(f"[INFO] Using base image: {base_image} for website containerization.")
    
    build_context = "website_build_context"
    if os.path.exists(build_context):
        print(f"[INFO] Removing existing build context '{build_context}'.")
        shutil.rmtree(build_context)
    os.makedirs(build_context)
    
    directories_to_copy = {
        "etc_httpd": "/etc/httpd",
        "etc_apache2": "/etc/apache2",
        "var_www_html": "/var/www/html",
        "etc_php": "/etc/php",
        "etc_ssl": "/etc/ssl"
    }
    
    copied_subdirs = []
    for subdir, src in directories_to_copy.items():
        if os.path.exists(src):
            dest = os.path.join(build_context, subdir)
            try:
                print(f"[INFO] Copying '{src}' to '{dest}'.")
                shutil.copytree(src, dest)
                copied_subdirs.append(subdir)
            except Exception as e:
                print(f"[WARN] Failed to copy {src}: {e}")
        else:
            print(f"[WARN] {src} not found; skipping.")
    
    dockerfile_path = os.path.join(build_context, "Dockerfile")
    dockerfile_lines = []
    dockerfile_lines.append(f"FROM {base_image}")
    dockerfile_lines.append("")
    dockerfile_lines.append("ENV DEBIAN_FRONTEND=noninteractive")
    dockerfile_lines.append("ENV TZ=America/Denver")
    dockerfile_lines.append("")
    dockerfile_lines.append("# Copy website files")
    for subdir in copied_subdirs:
        if subdir == "etc_httpd":
            dockerfile_lines.append("COPY etc_httpd/ /etc/httpd/")
        elif subdir == "etc_apache2":
            dockerfile_lines.append("COPY etc_apache2/ /etc/apache2/")
        elif subdir == "var_www_html":
            dockerfile_lines.append("COPY var_www_html/ /var/www/html/")
        elif subdir == "etc_php":
            dockerfile_lines.append("COPY etc_php/ /etc/php/")
        elif subdir == "etc_ssl":
            dockerfile_lines.append("COPY etc_ssl/ /etc/ssl/")
    dockerfile_lines.append("")
    dockerfile_lines.append("EXPOSE 80")
    dockerfile_lines.append('CMD ["sh"]')
    
    with open(dockerfile_path, "w") as f:
        f.write("\n".join(dockerfile_lines))
    print(f"[INFO] Dockerfile created at {dockerfile_path}")
    
    image_name = input("Enter name for the website container image (default 'website_container'): ").strip() or "website_container"
    try:
        subprocess.check_call(["docker", "build", "-t", image_name, build_context])
        print(f"[INFO] Docker image '{image_name}' built successfully.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to build Docker image: {e}")
        return
    
    run_now = input("Would you like to run the container now? (y/n): ").strip().lower() == "y"
    if run_now:
        container_name = input("Enter a name for the container (default 'website_instance'): ").strip() or "website_instance"
        cmd = ["docker", "run", "-d", "--name", container_name]
        cmd = maybe_apply_read_only_and_nonroot(cmd)
        cmd.append(image_name)
        try:
            subprocess.check_call(cmd)
            print(f"[INFO] Container '{container_name}' started successfully.")
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Failed to start container '{container_name}': {e}")

# -------------------------------------------------
# 7. Purge Docker
# -------------------------------------------------

def get_sudo_prefix():
    """Return sudo prefix if available, else an empty list."""
    return ["sudo"] if shutil.which("sudo") else []

def option_purge_docker():
    """
    Purge Docker:
      Remove all Docker containers, images, volumes, networks,
      uninstall Docker and Docker Compose (on Linux) and remove associated files.
      WARNING: This operation is destructive and irreversible.
    """
    print("[WARNING] Purging Docker will remove ALL Docker data, images, containers, volumes, networks, and uninstall Docker.")
    confirm = input("Type 'PURGE DOCKER' (without quotes) to proceed: ").strip()
    if confirm != "PURGE DOCKER":
        print("[INFO] Purge cancelled.")
        return

    try:
        print("[INFO] Stopping all running Docker containers...")
        subprocess.run("docker kill $(docker ps -q)", shell=True, check=False)
        print("[INFO] Removing all Docker containers...")
        subprocess.run("docker rm -f $(docker ps -aq)", shell=True, check=False)
        print("[INFO] Pruning Docker system (images, volumes, networks)...")
        subprocess.check_call(["docker", "system", "prune", "-a", "--volumes", "-f"])
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Docker cleanup failed: {e}")

    if platform.system().lower().startswith("linux"):
        pm = detect_linux_package_manager()
        sudo_prefix = get_sudo_prefix()
        if pm:
            try:
                print(f"[INFO] Removing Docker using {pm}...")
                if pm in ("apt", "apt-get"):
                    subprocess.check_call(sudo_prefix + [pm, "remove", "-y", "docker.io"])
                    subprocess.check_call(sudo_prefix + [pm, "autoremove", "-y"])
                elif pm in ("yum", "dnf"):
                    subprocess.check_call(sudo_prefix + [pm, "remove", "-y", "docker"])
                elif pm == "zypper":
                    subprocess.check_call(sudo_prefix + ["zypper", "--non-interactive", "remove", "docker"])
            except subprocess.CalledProcessError as e:
                print(f"[ERROR] Failed to remove Docker via package manager: {e}")
        else:
            print("[WARN] No supported package manager found to remove Docker.")

        try:
            print("[INFO] Removing Docker Compose...")
            if shutil.which("docker-compose"):
                if pm and pm in ("apt", "apt-get"):
                    subprocess.check_call(sudo_prefix + [pm, "remove", "-y", "docker-compose"])
                    subprocess.check_call(sudo_prefix + [pm, "autoremove", "-y"])
                else:
                    subprocess.check_call(sudo_prefix + ["rm", "-f", "$(which docker-compose)"], shell=True)
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Failed to remove Docker Compose: {e}")

        docker_dirs = ["/var/lib/docker", "/etc/docker", "/var/run/docker", "/var/log/docker"]
        for d in docker_dirs:
            if os.path.exists(d):
                try:
                    print(f"[INFO] Removing directory {d}...")
                    subprocess.check_call(sudo_prefix + ["rm", "-rf", d])
                except subprocess.CalledProcessError as e:
                    print(f"[ERROR] Failed to remove {d}: {e}")

        try:
            print("[INFO] Removing docker group...")
            subprocess.check_call(sudo_prefix + ["groupdel", "docker"], stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            print("[WARN] Docker group could not be removed (it may not exist).")
    else:
        print("[WARN] Purge operation is only fully supported on Linux. Please manually purge Docker on your system if needed.")

    print("[INFO] Docker purge complete. Disk space should be freed.")

# -------------------------------------------------
# 8. Main Interactive Menu
# -------------------------------------------------

def interactive_menu():
    while True:
        print("\n==== CCDC Container Deployment Tool ====")
        print("1. Comprehensive Run")
        print("2. Pull container to match OS")
        print("3. Containerize website")
        print("4. Setup Docker DB")
        print("5. Setup Docker WAF")
        print("6. Run continuous integrity check")
        print("7. Purge Docker")
        print("8. Exit")
        choice = input("Enter your choice (1-8): ").strip()
        if choice == "1":
            option_comprehensive()
        elif choice == "2":
            option_pull_container_to_match_os()
        elif choice == "3":
            option_containerize_website()
        elif choice == "4":
            setup_docker_db()
        elif choice == "5":
            setup_docker_waf()
        elif choice == "6":
            run_integrity_check_menu()
        elif choice == "7":
            option_purge_docker()
        elif choice == "8":
            print("[INFO] Exiting. Goodbye!")
            sys.exit(0)
        else:
            print("[ERROR] Invalid option. Please try again.")

# -------------------------------------------------
# 9. Main Function
# -------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="CCDC OS-to-Container & Integrity Tool with auto-install, containerization, and integrity checking."
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
