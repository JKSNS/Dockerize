#!/usr/bin/env python3
"""
CCDC Container Deployment & Integrity Tool
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
# Docker & Docker Compose Installation & Checks
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
    """Attempt to install Docker Compose on Linux (best effort)."""
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
    """Return True if 'docker ps' runs without error, else False."""
    try:
        subprocess.check_call(["docker", "ps"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except:
        return False

def fix_docker_group():
    """Add the current user to the docker group, enable/start Docker, and re-exec the script under proper group."""
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
    """Check Docker installation; if missing, attempt auto-installation or fix group issues."""
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
            print("[ERROR] Could not auto-install Docker on Linux. Please install manually.")
            sys.exit(1)
        if not can_run_docker():
            fix_docker_group()
        else:
            print("[INFO] Docker is installed and accessible on Linux now.")
    elif "bsd" in sysname or "nix" in sysname:
        print("[ERROR] Docker auto-install is not implemented for your OS. Please install manually.")
        sys.exit(1)
    elif sysname == "windows":
        print("[ERROR] Docker auto-install is not supported on Windows. Please install Docker Desktop manually.")
        sys.exit(1)
    else:
        print(f"[ERROR] Unrecognized system '{sysname}'. Please install Docker manually.")
        sys.exit(1)

def check_docker_compose():
    """Verify Docker Compose installation; if missing, attempt auto-install on Linux."""
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
                    print("[ERROR] Docker Compose still not available after install attempt.")
            else:
                print("[ERROR] Could not auto-install Docker Compose on Linux. Please install manually.")
        else:
            print("[ERROR] Docker Compose not found and auto-install is only supported on Linux. Please install manually.")

# -------------------------------------------------
# Python & Dependency Checks
# -------------------------------------------------

def check_python_version(min_major=3, min_minor=7):
    """Ensure Python 3.7+ is being used."""
    if sys.version_info < (min_major, min_minor):
        print(f"[ERROR] Python {min_major}.{min_minor}+ is required. You are running {sys.version_info.major}.{sys.version_info.minor}.")
        sys.exit(1)
    else:
        print(f"[INFO] Python version check passed: {sys.version_info.major}.{sys.version_info.minor}.")

def check_wsl_if_windows():
    """On Windows, check for WSL if needed (for non-Docker Desktop environments)."""
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
# OS Detection & Base Image Mapping
# -------------------------------------------------

def detect_os():
    """Detect the host OS and version."""
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
    """Map the detected OS to a recommended Docker base image."""
    linux_map = {
        "centos": {"7": "centos:7", "8": "centos:8", "9": "centos:stream9", "": "ubuntu:latest"},
        "ubuntu": {"18": "ubuntu:18.04", "20": "ubuntu:20.04", "22": "ubuntu:22.04"},
        "debian": {"10": "debian:10", "11": "debian:11", "12": "debian:12"},
        "fedora": {"35": "fedora:35"},
        "linux": {"": "ubuntu:latest"}
    }
    windows_map = {
        "10": "mcr.microsoft.com/windows/nanoserver:1809",
        "2016": "mcr.microsoft.com/windows/servercore:2016",
        "2019": "mcr.microsoft.com/windows/servercore:ltsc2019",
        "2022": "mcr.microsoft.com/windows/servercore:ltsc2022"
    }
    if os_name in ["bsd", "nix"]:
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
                return ver_map.get(short_ver, ver_map.get("", "ubuntu:latest"))
        return "ubuntu:latest"

# -------------------------------------------------
# Docker Image & Integrity Functions
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
    """Compute a SHA256 hash of a container’s filesystem."""
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

def continuous_integrity_check(container_name, snapshot_tar, check_interval=30):
    """Continuously monitor the integrity of a container."""
    print(f"[INFO] Starting continuous integrity check on container '{container_name}' every {check_interval} seconds.")
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
    """Perform a minimal integrity check (hash comparison only) without restoration."""
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
                baseline_hash = current_hash
            else:
                print(f"[INFO] Container '{container_name}' remains unchanged.")
    except KeyboardInterrupt:
        print("\n[INFO] Minimal integrity check interrupted by user.")

def restore_container_from_snapshot(snapshot_tar, container_name):
    """Restore a container from a snapshot tar file."""
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

# -------------------------------------------------
# Container Name Handling & Read-Only Enforcement
# -------------------------------------------------

def container_exists(name):
    """Return True if a container with the given name exists."""
    try:
        output = subprocess.check_output(["docker", "ps", "-a", "--format", "{{.Names}}"], text=True)
        return name in output.split()
    except subprocess.CalledProcessError:
        return False

def prompt_for_container_name(default_name):
    """Prompt the user for a container name, avoiding duplicates."""
    while True:
        name = input(f"Enter container name (default '{default_name}'): ").strip() or default_name
        if not container_exists(name):
            return name
        else:
            print(f"[ERROR] A container named '{name}' already exists.")
            choice = input("Options:\n  [R] Remove existing\n  [C] Choose another\n  [X] Exit\nEnter your choice (R/C/X): ").strip().lower()
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
    Ask if the container should run in read-only mode.
    If yes, add --read-only (and --user nobody on non-Windows) to the command.
    """
    read_only = input("Should this container run in read-only mode? (y/n) [n]: ").strip().lower() == "y"
    if read_only:
        cmd_list.append("--read-only")
        if not platform.system().lower().startswith("windows"):
            cmd_list.extend(["--user", "nobody"])
    return cmd_list

# -------------------------------------------------
# Option Functions
# -------------------------------------------------

def option_comprehensive():
    """
    Comprehensive Run:
    1. Check prerequisites.
    2. Detect OS and select base image.
    3. Pull the base image.
    4. Detect common web directories (/etc/httpd, /etc/apache2, /var/www/html, etc.) and copy them into a build context.
    5. Generate a Dockerfile that installs the required web service (if needed) and copies these files.
    6. Build the Docker image.
    7. Stop current web services (httpd/apache2) on the host.
    8. Launch the new container in non-root, read-only mode.
    """
    check_all_dependencies()
    os_name, version = detect_os()
    base_image = map_os_to_docker_image(os_name, version)
    print(f"[INFO] Comprehensive Run: Using base image '{base_image}'")
    pull_docker_image(base_image)

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
                print(f"[WARN] Could not copy {src}: {e}")
        else:
            print(f"[WARN] {src} does not exist. Skipping.")

    dockerfile_path = os.path.join(build_context, "Dockerfile")
    dockerfile_content = f"FROM {base_image}\n"
    dockerfile_content += "ENV DEBIAN_FRONTEND=noninteractive\nENV TZ=America/Denver\n\n"
    # Add installation of a web server if base image is Debian/Ubuntu or CentOS/Fedora
    if "ubuntu" in base_image or "debian" in base_image:
        dockerfile_content += "RUN apt-get update && apt-get install -y apache2 && apt-get clean\n"
        default_cmd = '["apache2ctl", "-D", "FOREGROUND"]'
    elif "centos" in base_image or "fedora" in base_image:
        dockerfile_content += "RUN yum -y install httpd && yum clean all\n"
        default_cmd = '["/usr/sbin/httpd", "-D", "FOREGROUND"]'
    else:
        default_cmd = '["/usr/sbin/httpd", "-D", "FOREGROUND"]'
    for subdir in copied_subdirs:
        if subdir == "etc_httpd":
            dockerfile_content += f"COPY {subdir}/ /etc/httpd/\n"
        elif subdir == "etc_apache2":
            dockerfile_content += f"COPY {subdir}/ /etc/apache2/\n"
        elif subdir == "var_www_html":
            dockerfile_content += f"COPY {subdir}/ /var/www/html/\n"
        elif subdir == "etc_php":
            dockerfile_content += f"COPY {subdir}/ /etc/php/\n"
        elif subdir == "etc_ssl":
            dockerfile_content += f"COPY {subdir}/ /etc/ssl/\n"
    dockerfile_content += "EXPOSE 80\n"
    dockerfile_content += f"CMD {default_cmd}\n"
    with open(dockerfile_path, "w") as f:
        f.write(dockerfile_content)
    print(f"[INFO] Dockerfile created at {dockerfile_path}.")

    image_name = input("Enter a name for the comprehensive Docker image (default 'comprehensive_service'): ").strip() or "comprehensive_service"
    try:
        subprocess.check_call(["docker", "build", "-t", image_name, build_context])
        print(f"[INFO] Docker image '{image_name}' built successfully.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to build Docker image: {e}")
        return

    print("[INFO] Stopping current web services (httpd and apache2) on the host.")
    try:
        subprocess.call(["sudo", "systemctl", "stop", "httpd"])
    except:
        print("[WARN] Could not stop httpd (it may not be running).")
    try:
        subprocess.call(["sudo", "systemctl", "stop", "apache2"])
    except:
        print("[WARN] Could not stop apache2 (it may not be running).")

    container_name = input("Enter a name for the new container (default 'comprehensive_container'): ").strip() or "comprehensive_container"
    cmd = ["docker", "run", "-d", "--name", container_name]
    cmd = maybe_apply_read_only_and_nonroot(cmd)
    cmd.append(image_name)
    try:
        subprocess.check_call(cmd)
        print(f"[INFO] Comprehensive container '{container_name}' started successfully.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to run container '{container_name}': {e}")

def containerize_service():
    """
    Containerize website: Copy common website directories into a build context,
    generate a Dockerfile, build the image, and optionally run a container.
    """
    check_all_dependencies()
    os_name, version = detect_os()
    base_image = map_os_to_docker_image(os_name, version)
    print(f"[INFO] Using base Docker image: {base_image}")

    build_context = "container_build_context"
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
                print(f"[WARN] Could not copy {src}: {e}")
        else:
            print(f"[WARN] {src} does not exist. Skipping.")

    dockerfile_path = os.path.join(build_context, "Dockerfile")
    dockerfile_content = f"FROM {base_image}\n"
    dockerfile_content += "ENV DEBIAN_FRONTEND=noninteractive\nENV TZ=America/Denver\n\n"
    for subdir in copied_subdirs:
        if subdir == "etc_httpd":
            dockerfile_content += f"COPY {subdir}/ /etc/httpd/\n"
        elif subdir == "etc_apache2":
            dockerfile_content += f"COPY {subdir}/ /etc/apache2/\n"
        elif subdir == "var_www_html":
            dockerfile_content += f"COPY {subdir}/ /var/www/html/\n"
        elif subdir == "etc_php":
            dockerfile_content += f"COPY {subdir}/ /etc/php/\n"
        elif subdir == "etc_ssl":
            dockerfile_content += f"COPY {subdir}/ /etc/ssl/\n"
    dockerfile_content += "EXPOSE 80\n"
    dockerfile_content += 'CMD ["/usr/sbin/httpd", "-D", "FOREGROUND"]\n'
    with open(dockerfile_path, "w") as f:
        f.write(dockerfile_content)
    print(f"[INFO] Dockerfile created at {dockerfile_path}.")

    image_name = input("Enter a name for the Docker image (default 'encapsulated_service'): ").strip() or "encapsulated_service"
    try:
        subprocess.check_call(["docker", "build", "-t", image_name, build_context])
        print(f"[INFO] Docker image '{image_name}' built successfully.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to build Docker image: {e}")
        sys.exit(1)

    run_container = input("Would you like to run a container from this image? (y/n): ").strip().lower() == "y"
    if run_container:
        container_name = prompt_for_container_name("service_container")
        cmd = ["docker", "run", "-d", "--name", container_name]
        cmd = maybe_apply_read_only_and_nonroot(cmd)
        cmd.append(image_name)
        try:
            subprocess.check_call(cmd)
            print(f"[INFO] Container '{container_name}' launched from image '{image_name}'.")
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Failed to run container '{container_name}': {e}")
    else:
        print("[INFO] Container build completed. You can run the image later using 'docker run'.")

def setup_docker_db():
    """
    Setup Docker DB: Launch a MariaDB container with optional volume mounts and network configuration.
    """
    check_all_dependencies()
    print("=== Dockerized Database Setup ===")
    default_db_name = "web_db"
    db_container = prompt_for_container_name(default_db_name)
    volume_opts = []
    print("[NOTE] A database container typically needs write access. You may mount directories if desired.")
    while True:
        dir_input = input("Enter a directory to mount (blank to finish): ").strip()
        if not dir_input:
            break
        volume_opts.extend(["-v", f"{dir_input}:{dir_input}"])
    pull_docker_image("mariadb:latest")
    db_password = input("Enter MariaDB root password (default 'root'): ").strip() or "root"
    db_name = input("Enter a DB name to create (default 'mydb'): ").strip() or "mydb"
    network_name = input("Enter a Docker network name to attach (default 'bridge'): ").strip() or "bridge"
    try:
        subprocess.check_call(["docker", "network", "inspect", network_name],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[INFO] Using existing network '{network_name}'.")
    except subprocess.CalledProcessError:
        print(f"[INFO] Creating Docker network '{network_name}'.")
        subprocess.check_call(["docker", "network", "create", network_name])
    cmd = ["docker", "run", "-d", "--name", db_container, "--network", network_name]
    cmd = maybe_apply_read_only_and_nonroot(cmd)
    cmd.extend(volume_opts)
    cmd.extend(["-e", f"MYSQL_ROOT_PASSWORD={db_password}", "-e", f"MYSQL_DATABASE={db_name}", "mariadb:latest"])
    print(f"[INFO] Launching MariaDB container '{db_container}'.")
    try:
        subprocess.check_call(cmd)
        print(f"[INFO] Database container '{db_container}' launched successfully.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not launch MariaDB container '{db_container}': {e}")
        sys.exit(1)

def setup_docker_waf():
    """
    Setup Docker WAF: Launch a ModSecurity (OWASP) WAF container with configurable network and port.
    """
    check_all_dependencies()
    waf_image = "owasp/modsecurity-crs:nginx"
    pull_docker_image(waf_image)
    print("=== Dockerized WAF Setup ===")
    default_waf_name = "modsec2-nginx"
    waf_container = prompt_for_container_name(default_waf_name)
    host_waf_port = input("Enter host port for the WAF (default '8080'): ").strip() or "8080"
    network_name = input("Enter Docker network to attach (default 'bridge'): ").strip() or "bridge"
    try:
        subprocess.check_call(["docker", "network", "inspect", network_name],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[INFO] Using existing network '{network_name}'.")
    except subprocess.CalledProcessError:
        print(f"[INFO] Creating Docker network '{network_name}'.")
        subprocess.check_call(["docker", "network", "create", network_name])
    backend = input("Enter the backend container name or IP (default 'web_container'): ").strip() or "web_container"
    tz = os.environ.get("TZ", "America/Denver")
    waf_env = [
        "PORT=8080",
        "PROXY=1",
        f"BACKEND=http://{backend}:80",
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
    print(f"[INFO] Launching WAF container '{waf_container}'.")
    try:
        subprocess.check_call(cmd)
        print(f"[INFO] WAF container '{waf_container}' launched successfully.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not launch WAF container '{waf_container}': {e}")
        sys.exit(1)

def run_continuous_integrity_check():
    """
    Run continuous integrity check on a specified container.
    Prompts the user for the container name, snapshot file, and check interval.
    """
    print("=== Continuous Integrity Check ===")
    container_name = input("Enter the container name to monitor: ").strip()
    snapshot_tar = input("Enter the path to the snapshot .tar file for restoration (or leave blank for minimal check): ").strip()
    check_interval_str = input("Enter check interval in seconds (default 30): ").strip()
    try:
        check_interval = int(check_interval_str) if check_interval_str else 30
    except ValueError:
        check_interval = 30
    check_all_dependencies()
    if snapshot_tar:
        continuous_integrity_check(container_name, snapshot_tar, check_interval)
    else:
        minimal_integrity_check(container_name, check_interval)

def get_sudo_prefix():
    """Return ['sudo'] if sudo is available, else an empty list."""
    return ["sudo"] if shutil.which("sudo") else []

def option_purge_docker():
    """
    Purge Docker: Remove all containers, images, volumes, networks, and uninstall Docker/Docker Compose (Linux only).
    WARNING: This operation is destructive and irreversible.
    """
    print("[WARNING] Purging Docker will remove ALL Docker data and uninstall Docker/Docker Compose.")
    confirm = input("Type 'PURGE DOCKER' to proceed: ").strip()
    if confirm != "PURGE DOCKER":
        print("[INFO] Purge cancelled.")
        return
    try:
        print("[INFO] Stopping all running containers...")
        subprocess.run("docker kill $(docker ps -q)", shell=True, check=False)
        print("[INFO] Removing all containers...")
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
        print("[WARN] Purge operation is only fully supported on Linux. Please manually purge Docker if needed.")
    print("[INFO] Docker purge complete.")

# -------------------------------------------------
# Main Interactive Menu
# -------------------------------------------------

def interactive_menu():
    """Display the interactive menu with seven options."""
    while True:
        print("\n==== CCDC Container Deployment Tool ====")
        print("1. Comprehensive Run")
        print("2. Containerize website")
        print("3. Setup Docker DB")
        print("4. Setup Docker WAF")
        print("5. Run continuous integrity check")
        print("6. Purge Docker")
        print("7. Exit")
        choice = input("Enter your choice (1-7): ").strip()
        if choice == "1":
            option_comprehensive()
        elif choice == "2":
            containerize_service()
        elif choice == "3":
            setup_docker_db()
        elif choice == "4":
            setup_docker_waf()
        elif choice == "5":
            run_continuous_integrity_check()
        elif choice == "6":
            option_purge_docker()
        elif choice == "7":
            print("[INFO] Exiting. Goodbye!")
            sys.exit(0)
        else:
            print("[ERROR] Invalid choice. Please try again.")

def main():
    parser = argparse.ArgumentParser(
        description="CCDC OS-to-Container & Integrity Tool"
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
