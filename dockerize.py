#!/usr/bin/env python3
"""
CCDC Dockerization – Comprehensive Web Service Containerization

This script does the following:
1. Ensures Docker (and Docker Compose) are installed properly—including creating the
   docker group (if missing) and adding the current user.
2. Provides an interactive menu with these options:
   1. Dockerize Web Service (comprehensive): Copies website files (from /var/www/html and
      /etc/httpd or /etc/apache2), builds a Docker image (matching the OS), stops the
      local Apache/HTTPD service, and launches the container in secure mode (read-only, non-root).
   2. Dockerize Database: Sets up a Dockerized DB container (MariaDB).
   3. Dockerize WAF: Sets up a Dockerized ModSecurity WAF.
   4. Toggle Web Container Mode: Re-launches the web container in either secure or development mode.
   5. Run Continuous Integrity Check: Monitors running containers for filesystem changes.
   6. Exit
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
# 1. Docker & Docker Compose Installation Helpers
# -------------------------------------------------

def detect_linux_package_manager():
    """Detect common Linux package managers."""
    for pm in ["apt", "apt-get", "dnf", "yum", "zypper"]:
        if shutil.which(pm):
            return pm
    return None

def group_exists(group_name):
    """Return True if the group exists (using getent)."""
    try:
        subprocess.check_call(["getent", "group", group_name],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False

def user_in_group(username, group_name):
    """Return True if the given user is in the specified group."""
    try:
        groups_output = subprocess.check_output(["groups", username], text=True)
        return group_name in groups_output.split()
    except:
        return False

def create_docker_group_if_missing():
    """Create the 'docker' group if it does not exist."""
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
    """Add the specified user to the 'docker' group, if not already a member."""
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
    """Enable and start the Docker service via systemd, if available."""
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
    Attempt to install Docker on Linux using the detected package manager,
    ensure the docker group exists, add the current user, and start the service.
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
        print("[INFO] Docker installation attempt completed.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Auto-installation of Docker on Linux failed: {e}")
        return False

    if not create_docker_group_if_missing():
        return False
    try:
        current_user = os.getlogin()
    except:
        current_user = os.environ.get("USER", "unknown")
    if not add_user_to_docker_group(current_user):
        return False
    enable_and_start_docker_service()
    return True

def attempt_install_docker_compose_linux():
    """
    Attempt to install Docker Compose on Linux using the detected package manager.
    """
    pm = detect_linux_package_manager()
    if not pm:
        print("[ERROR] No recognized package manager found on Linux. Cannot auto-install Docker Compose.")
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
        print("[INFO] Docker Compose installation attempt completed.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Auto-installation of Docker Compose on Linux failed: {e}")
        return False

def can_run_docker():
    """Return True if 'docker ps' runs successfully; otherwise, False."""
    try:
        subprocess.check_call(["docker", "ps"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except:
        return False

def reexec_with_docker_group():
    """Re-exec the script under 'sg docker' to pick up group membership."""
    print("[INFO] Re-executing script under 'sg docker' to activate group membership.")
    os.environ["CCDC_DOCKER_GROUP_FIX"] = "1"  # avoid infinite loops
    script_path = os.path.abspath(sys.argv[0])
    script_args = sys.argv[1:]
    command_line = f'export CCDC_DOCKER_GROUP_FIX=1; exec "{sys.executable}" "{script_path}" ' + " ".join(f'"{arg}"' for arg in script_args)
    cmd = ["sg", "docker", "-c", command_line]
    os.execvp("sg", cmd)

def ensure_docker_installed():
    """
    Ensure Docker is installed and accessible. If not, attempt installation and fix group membership.
    """
    if "CCDC_DOCKER_GROUP_FIX" in os.environ:
        if can_run_docker():
            print("[INFO] Docker is accessible now after group fix.")
            return
        else:
            print("[ERROR] Docker still not accessible even after group fix. Exiting.")
            sys.exit(1)
    if shutil.which("docker") and can_run_docker():
        print("[INFO] Docker is installed and accessible.")
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
        sysname = platform.system().lower()
        if sysname.startswith("linux"):
            if not attempt_install_docker_linux():
                print("[ERROR] Could not auto-install Docker on Linux. Please install manually.")
                sys.exit(1)
            if not can_run_docker():
                reexec_with_docker_group()
            else:
                print("[INFO] Docker is installed and accessible on Linux now.")
        elif "bsd" in sysname or "nix" in sysname:
            print("[ERROR] Docker auto-install is not implemented for this system. Please install manually.")
            sys.exit(1)
        elif sysname == "windows":
            print("[ERROR] Docker not found, and auto-install is not supported on Windows. Please install Docker or Docker Desktop manually.")
            sys.exit(1)
        else:
            print(f"[ERROR] Unrecognized system '{sysname}'. Docker is missing. Please install manually.")
            sys.exit(1)

def check_docker_compose():
    """Check if Docker Compose is installed; if not, attempt to install it on Linux."""
    try:
        subprocess.check_call(["docker-compose", "--version"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("[INFO] Docker Compose is installed.")
    except Exception:
        print("[WARN] Docker Compose not found. Attempting auto-install (Linux only).")
        if platform.system().lower().startswith("linux"):
            if attempt_install_docker_compose_linux():
                try:
                    subprocess.check_call(["docker-compose", "--version"],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print("[INFO] Docker Compose installed successfully.")
                except:
                    print("[ERROR] Docker Compose still not available after attempted install.")
            else:
                print("[ERROR] Could not auto-install Docker Compose on Linux. Please install manually.")
        else:
            print("[ERROR] Docker Compose not found and auto-install is only supported on Linux.")

# -------------------------------------------------
# 2. Python & Docker Environment Checks
# -------------------------------------------------

def check_python_version(min_major=3, min_minor=7):
    """Ensure Python 3.7+ is used."""
    if sys.version_info < (min_major, min_minor):
        print(f"[ERROR] Python {min_major}.{min_minor}+ is required. You are running {sys.version_info.major}.{sys.version_info.minor}.")
        sys.exit(1)
    else:
        print(f"[INFO] Python version check passed: {sys.version_info.major}.{sys.version_info.minor}.")

def check_wsl_if_windows():
    """On Windows, check if WSL is installed (if needed)."""
    if platform.system().lower() == "windows":
        try:
            subprocess.check_call(["wsl", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("[INFO] WSL is installed.")
        except Exception:
            print("[WARN] WSL not found. If using legacy Windows, ensure Docker Desktop is set up appropriately.")

def check_all_dependencies():
    """Run all prerequisite checks."""
    check_python_version(3, 7)
    ensure_docker_installed()
    check_docker_compose()
    check_wsl_if_windows()

# -------------------------------------------------
# 3. OS Detection & Base Image Mapping
# -------------------------------------------------

def detect_os():
    """Detect host OS and version (best-effort)."""
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
    elif sysname in ["freebsd", "openbsd", "netbsd"]:
        return "bsd", ""
    elif "nix" in sysname:
        return "nix", ""
    elif sysname == "windows":
        return "windows", platform.release().lower()
    else:
        return sysname, ""

def map_os_to_docker_image(os_name, version):
    """Map the detected OS to a recommended Docker base image."""
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
        "xp": "legacy-windows/xp:latest", "vista": "legacy-windows/vista:latest",
        "7": "legacy-windows/win7:latest", "2008": "legacy-windows/win2008:latest",
        "2012": "legacy-windows/win2012:latest", "10": "mcr.microsoft.com/windows/nanoserver:1809",
        "2016": "mcr.microsoft.com/windows/servercore:2016", "2019": "mcr.microsoft.com/windows/servercore:ltsc2019",
        "2022": "mcr.microsoft.com/windows/servercore:ltsc2022"
    }
    if os_name in ["bsd", "nix"]:
        return "alpine:latest"
    elif os_name == "windows":
        for key, img in windows_map.items():
            if key in version:
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
# 4. Container Launch & Integrity Checking (Unchanged)
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
    """Compute a SHA256 hash of the container’s filesystem."""
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

def minimal_integrity_check(container_name, check_interval=30):
    """A minimal integrity check that only reports changes without restoration."""
    print(f"[INFO] Starting minimal integrity check on container '{container_name}' every {check_interval} seconds.")
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
# 5. Container Name Handling & Read-Only Option Helper
# -------------------------------------------------

def container_exists(name):
    """Return True if a container (running or exited) with the given name exists."""
    try:
        output = subprocess.check_output(["docker", "ps", "-a", "--format", "{{.Names}}"], text=True)
        existing_names = output.split()
        return name in existing_names
    except subprocess.CalledProcessError:
        return False

def prompt_for_container_name(default_name):
    """Prompt the user for a container name and ensure it is unique (or offer removal options)."""
    while True:
        name = input(f"Enter container name (default '{default_name}'): ").strip() or default_name
        if not container_exists(name):
            return name
        else:
            print(f"[ERROR] A container named '{name}' already exists.")
            choice = input("Options: [R]emove, [C]hoose another, or e[X]it: ").strip().lower()
            if choice == "r":
                try:
                    subprocess.check_call(["docker", "rm", "-f", name])
                    print(f"[INFO] Removed container '{name}'.")
                    return name
                except subprocess.CalledProcessError as e:
                    print(f"[ERROR] Could not remove container '{name}': {e}")
            elif choice == "c":
                continue
            else:
                print("[INFO] Exiting.")
                sys.exit(1)

def maybe_apply_read_only_and_nonroot(cmd_list):
    """
    Append flags for read-only and non-root operation.
    (In development mode, these can be omitted.)
    """
    read_only = input("Run container in secure mode? (y/n) [y]: ").strip().lower() != "n"
    if read_only:
        cmd_list.append("--read-only")
        if not platform.system().lower().startswith("windows"):
            cmd_list.extend(["--user", "nobody"])
    return cmd_list

# -------------------------------------------------
# 6. Dockerize Web Service (Comprehensive)
# -------------------------------------------------

def stop_local_web_service():
    """
    Attempt to stop the locally running Apache/httpd service so that
    the website is only served from the container.
    """
    services = ["apache2", "httpd"]
    for service in services:
        try:
            subprocess.check_call(["sudo", "systemctl", "is-active", "--quiet", service])
            print(f"[INFO] Stopping local service: {service}")
            subprocess.check_call(["sudo", "systemctl", "stop", service])
        except subprocess.CalledProcessError:
            pass
    print("[INFO] Local web service stopped (if it was running).")

def dockerize_web_service_comprehensive():
    """
    Containerize the website by copying necessary web files (/var/www/html and
    configuration directories from /etc/httpd or /etc/apache2) into a Docker image.
    Then stop the local web server and run the container in secure mode.
    """
    check_all_dependencies()
    os_name, version = detect_os()
    base_image = map_os_to_docker_image(os_name, version)
    print(f"[INFO] Using base image: {base_image} for web service containerization.")

    build_context = "web_service_build_context"
    if os.path.exists(build_context):
        print(f"[INFO] Removing existing build context '{build_context}'.")
        shutil.rmtree(build_context)
    os.makedirs(build_context)

    # Gather website files (web root and web server configuration)
    dirs_to_copy = {}
    if os.path.exists("/var/www/html"):
        dirs_to_copy["var_www_html"] = "/var/www/html"
    if os.path.exists("/etc/httpd"):
        dirs_to_copy["etc_httpd"] = "/etc/httpd"
    elif os.path.exists("/etc/apache2"):
        dirs_to_copy["etc_apache2"] = "/etc/apache2"

    if not dirs_to_copy:
        print("[ERROR] Required web directories not found.")
        return

    copied = []
    for subdir, src in dirs_to_copy.items():
        dest = os.path.join(build_context, subdir)
        try:
            print(f"[INFO] Copying '{src}' to '{dest}'.")
            shutil.copytree(src, dest)
            copied.append(subdir)
        except Exception as e:
            print(f"[WARN] Failed to copy {src}: {e}")

    # Create Dockerfile
    dockerfile_path = os.path.join(build_context, "Dockerfile")
    copy_lines = []
    if "var_www_html" in copied:
        copy_lines.append("COPY var_www_html/ /var/www/html/")
    if "etc_httpd" in copied:
        copy_lines.append("COPY etc_httpd/ /etc/httpd/")
    if "etc_apache2" in copied:
        copy_lines.append("COPY etc_apache2/ /etc/apache2/")

    dockerfile_content = f"""FROM {base_image}

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=America/Denver

# Copy website files and configurations
"""
    for line in copy_lines:
        dockerfile_content += line + "\n"

    dockerfile_content += """
EXPOSE 80

CMD ["/usr/sbin/httpd", "-D", "FOREGROUND"]
"""
    with open(dockerfile_path, "w") as f:
        f.write(dockerfile_content)
    print(f"[INFO] Dockerfile created at {dockerfile_path}")

    image_name = input("Enter the name for the web service image (default 'web_service_image'): ").strip() or "web_service_image"
    try:
        subprocess.check_call(["docker", "build", "-t", image_name, build_context])
        print(f"[INFO] Docker image '{image_name}' built successfully.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to build image: {e}")
        return

    # Stop local Apache/httpd service
    stop_local_web_service()

    container_name = prompt_for_container_name("web_service_container")
    cmd = ["docker", "run", "-d", "--name", container_name]
    # By default, run in secure mode
    cmd.append("--read-only")
    if not platform.system().lower().startswith("windows"):
        cmd.extend(["--user", "nobody"])
    cmd.append(image_name)
    try:
        subprocess.check_call(cmd)
        print(f"[INFO] Web service container '{container_name}' launched in secure mode.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to run container: {e}")

# -------------------------------------------------
# 7. Dockerize Database (Using Existing Functionality)
# -------------------------------------------------

def setup_docker_db():
    """
    Set up a Dockerized database (e.g. MariaDB).
    """
    check_all_dependencies()
    print("=== Database Container Setup ===")
    default_db_name = "web_db"
    db_container = prompt_for_container_name(default_db_name)
    volume_opts_db = []
    print("[NOTE] A DB container typically needs write access.")
    while True:
        dir_input = input("Enter a directory to mount into the DB container (blank to finish): ").strip()
        if not dir_input:
            break
        volume_opts_db.extend(["-v", f"{dir_input}:{dir_input}"])
    pull_docker_image("mariadb:latest")
    db_password = input("Enter MariaDB root password (default 'root'): ").strip() or "root"
    db_name = input("Enter a DB name to create (default 'mydb'): ").strip() or "mydb"
    cmd = ["docker", "run", "-d", "--name", db_container]
    network_name = input("Enter a Docker network to attach (default 'bridge'): ").strip() or "bridge"
    if network_name != "bridge":
        try:
            subprocess.check_call(["docker", "network", "inspect", network_name],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"[INFO] Using existing network '{network_name}'.")
        except subprocess.CalledProcessError:
            print(f"[INFO] Creating network '{network_name}'.")
            subprocess.check_call(["docker", "network", "create", network_name])
        cmd.extend(["--network", network_name])
    cmd = maybe_apply_read_only_and_nonroot(cmd)
    cmd.extend(volume_opts_db)
    cmd.extend(["-e", f"MYSQL_ROOT_PASSWORD={db_password}", "-e", f"MYSQL_DATABASE={db_name}", "mariadb:latest"])
    try:
        subprocess.check_call(cmd)
        print(f"[INFO] Database container '{db_container}' launched successfully.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not launch DB container '{db_container}': {e}")
        sys.exit(1)

# -------------------------------------------------
# 8. Dockerize WAF (Using Existing Functionality)
# -------------------------------------------------

def setup_docker_waf():
    """
    Set up a Dockerized WAF (e.g., ModSecurity with Nginx).
    """
    check_all_dependencies()
    waf_image = "owasp/modsecurity-crs:nginx"
    pull_docker_image(waf_image)
    print("=== WAF Container Setup ===")
    waf_container = prompt_for_container_name("modsec2-nginx")
    host_waf_port = input("Enter host port for WAF (default '8080'): ").strip() or "8080"
    network_name = input("Enter Docker network to attach (default 'bridge'): ").strip() or "bridge"
    if network_name != "bridge":
        try:
            subprocess.check_call(["docker", "network", "inspect", network_name],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"[INFO] Using network '{network_name}'.")
        except subprocess.CalledProcessError:
            print(f"[INFO] Creating network '{network_name}'.")
            subprocess.check_call(["docker", "network", "create", network_name])
    backend_container = input("Enter backend container name or IP (default 'web_service_container'): ").strip() or "web_service_container"
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
    cmd = ["docker", "run", "-d", "--network", network_name, "--name", waf_container, "-p", f"{host_waf_port}:8080"]
    cmd = maybe_apply_read_only_and_nonroot(cmd)
    for env_var in waf_env:
        cmd.extend(["-e", env_var])
    cmd.append(waf_image)
    try:
        subprocess.check_call(cmd)
        print(f"[INFO] WAF container '{waf_container}' launched successfully.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not launch WAF container '{waf_container}': {e}")
        sys.exit(1)

# -------------------------------------------------
# 9. Toggle Web Container Mode
# -------------------------------------------------

def toggle_web_container_mode():
    """
    Toggle the running web service container between secure (read-only, non-root)
    and development (writable) modes. This is done by stopping and re-launching the container
    with the desired flags.
    """
    container_name = input("Enter the name of the web service container to toggle: ").strip()
    image_name = input("Enter the image name used for this container: ").strip()
    desired_mode = input("Enter desired mode ('secure' or 'development'): ").strip().lower()
    if desired_mode not in ["secure", "development"]:
        print("[ERROR] Invalid mode specified.")
        return
    try:
        subprocess.check_call(["docker", "rm", "-f", container_name])
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not remove container '{container_name}': {e}")
        return
    cmd = ["docker", "run", "-d", "--name", container_name]
    if desired_mode == "secure":
        cmd.append("--read-only")
        if not platform.system().lower().startswith("windows"):
            cmd.extend(["--user", "nobody"])
    cmd.append(image_name)
    try:
        subprocess.check_call(cmd)
        print(f"[INFO] Container '{container_name}' re-launched in {desired_mode} mode.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to run container '{container_name}' in {desired_mode} mode: {e}")

# -------------------------------------------------
# 10. Continuous Integrity Check (Using Existing Functions)
# -------------------------------------------------
# (The functions continuous_integrity_check and minimal_integrity_check are defined above.)

def run_integrity_check_menu():
    """Interactive prompt for running integrity checks on containers."""
    print("==== Continuous Integrity Check ====")
    print("1. Integrity check for a single container")
    print("2. Integrity check for multiple containers")
    choice = input("Choose an option (1/2): ").strip()
    if choice == "1":
        container_name = input("Enter the container name to monitor: ").strip()
        snapshot_tar = input("Enter path to snapshot .tar for restoration (blank to skip): ").strip()
        interval_str = input("Enter check interval in seconds (default 30): ").strip()
        try:
            interval = int(interval_str) if interval_str else 30
        except ValueError:
            interval = 30
        check_all_dependencies()
        if snapshot_tar:
            continuous_integrity_check(container_name, snapshot_tar, interval)
        else:
            minimal_integrity_check(container_name, interval)
    elif choice == "2":
        try:
            output = subprocess.check_output(["docker", "ps", "--format", "{{.Names}}"], text=True)
            containers = output.split()
            if not containers:
                print("[INFO] No running containers found.")
                return
            print("[INFO] Running containers:")
            for idx, name in enumerate(containers, 1):
                print(f"  {idx}. {name}")
            sel = input("Enter 'all' or comma-separated indexes: ").strip().lower()
            if sel == "all":
                selected = containers
            else:
                indexes = [x.strip() for x in sel.split(",") if x.strip()]
                selected = []
                for i in indexes:
                    try:
                        idx = int(i)
                        if 1 <= idx <= len(containers):
                            selected.append(containers[idx-1])
                    except ValueError:
                        pass
            if not selected:
                print("[ERROR] No valid containers selected.")
                return
            interval_str = input("Enter check interval in seconds (default 30): ").strip()
            try:
                interval = int(interval_str) if interval_str else 30
            except ValueError:
                interval = 30
            for name in selected:
                print(f"\n==== Starting integrity check for container '{name}' ====")
                snapshot_tar = input(f"Enter snapshot .tar path for container '{name}' (blank to skip): ").strip()
                if snapshot_tar:
                    continuous_integrity_check(name, snapshot_tar, interval)
                else:
                    minimal_integrity_check(name, interval)
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Could not list running containers: {e}")
    else:
        print("[ERROR] Invalid option.")

# -------------------------------------------------
# 11. Interactive Menu
# -------------------------------------------------

def interactive_menu():
    """
    Interactive menu with the following options:
    1. Dockerize Web Service (Comprehensive)
    2. Dockerize Database
    3. Dockerize WAF
    4. Toggle Web Container Mode
    5. Run Continuous Integrity Check
    6. Exit
    """
    while True:
        print("\n==== CCDC Container Deployment Tool ====")
        print("1. Dockerize Web Service (Comprehensive)")
        print("2. Dockerize Database")
        print("3. Dockerize WAF")
        print("4. Toggle Web Container Mode")
        print("5. Run Continuous Integrity Check")
        print("6. Exit")
        choice = input("Enter your choice (1-6): ").strip()
        if choice == "1":
            dockerize_web_service_comprehensive()
        elif choice == "2":
            setup_docker_db()
        elif choice == "3":
            setup_docker_waf()
        elif choice == "4":
            toggle_web_container_mode()
        elif choice == "5":
            run_integrity_check_menu()
        elif choice == "6":
            print("[INFO] Exiting. Goodbye!")
            sys.exit(0)
        else:
            print("[ERROR] Invalid option. Please try again.")

# -------------------------------------------------
# 12. Main Function
# -------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="CCDC OS-to-Container & Integrity Tool (Web Service Focused)"
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
