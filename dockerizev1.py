#!/usr/bin/env python3
"""
ccdc_docker_hardener_expanded_os.py

A comprehensive tool for automating the hardening and containerization
of diverse environments in CCDC-style competitions.

Features:
  - Checks prerequisites (Python version, Docker, Docker Compose, WSL on Windows)
  - Detects a wide range of Linux distributions and legacy Windows versions.
  - Maps the detected OS to a recommended base Docker image.
      • Linux distros: CentOS (6, 7, 8, Stream9), Ubuntu (14.04, 16.04, 18.04, 20.04, 22.04),
        Debian (7–12), Fedora (25+), openSUSE (Leap, Tumbleweed)
      • Windows: XP, Vista, 7, Server 2008, Server 2012 (legacy – use custom images),
        Windows 10, Server 2016, 2019, 2022.
  - Provides a generic container launch mode (“dockerize” action without a service)
    so you can start a container matching the host OS and then build your service.
  - Provides a “migrate” action to mount host files (e.g. configuration directories)
    into the container for later customization.
  - Supports snapshot (backup), integrity check, and basic Docker security scanning.
  
Usage Examples:
  1) Check prerequisites and package manager:
       python3 ccdc_docker_hardener_expanded_os.py --action check

  2) Dockerize – launch a container matching the base OS (interactive shell):
       python3 ccdc_docker_hardener_expanded_os.py --action dockerize

  3) Dockerize a specific service (if you want to preconfigure one):
       python3 ccdc_docker_hardener_expanded_os.py --action dockerize --service ftp

  4) Migrate host files into a container (to later build/migrate your service):
       python3 ccdc_docker_hardener_expanded_os.py --action migrate --source /path/to/hostfiles --target /etc/hostfiles

  5) Create a snapshot of a running container:
       python3 ccdc_docker_hardener_expanded_os.py --action backup --container my_container --backup-tag my_container_backup

  6) Perform an integrity check:
       python3 ccdc_docker_hardener_expanded_os.py --action integrity --container my_container

  7) Run advanced security checks:
       python3 ccdc_docker_hardener_expanded_os.py --action security

  8) Show additional recommendations:
       python3 ccdc_docker_hardener_expanded_os.py --action recommendations
"""

import sys
import platform
import subprocess
import argparse
import os
import shutil

###############################################################################
# 1. Prerequisite Checks
###############################################################################
def check_python_version(min_major=3, min_minor=7):
    """Ensure we run on at least Python 3.7."""
    if sys.version_info < (min_major, min_minor):
        print(f"[ERROR] Python {min_major}.{min_minor}+ is required. Current: {sys.version_info.major}.{sys.version_info.minor}")
        sys.exit(1)
    else:
        print(f"[INFO] Python version check passed ({sys.version_info.major}.{sys.version_info.minor}).")

def check_docker():
    """Check that Docker is installed."""
    try:
        subprocess.check_call(["docker", "--version"], stdout=subprocess.DEVNULL)
        print("[INFO] Docker is installed.")
    except Exception:
        print("[ERROR] Docker not found. Please install Docker before running this script.")
        sys.exit(1)

def check_docker_compose():
    """Check if Docker Compose is installed (warn if not)."""
    try:
        subprocess.check_call(["docker-compose", "--version"], stdout=subprocess.DEVNULL)
        print("[INFO] Docker Compose is installed.")
    except Exception:
        print("[WARN] Docker Compose not found. Some orchestration features may be unavailable.")

def check_wsl_if_windows():
    """If on Windows, check for WSL (if required)."""
    if platform.system().lower() == "windows":
        try:
            subprocess.check_call(["wsl", "--version"], stdout=subprocess.DEVNULL)
            print("[INFO] WSL is installed. Docker with WSL2 backend should work.")
        except Exception:
            print("[WARN] WSL not found. If you're on a legacy Windows client OS, Docker containers may require custom setup.")

def check_all_dependencies():
    """Run all prerequisite checks."""
    check_python_version(3, 7)
    check_docker()
    check_docker_compose()
    check_wsl_if_windows()

def detect_package_manager():
    """
    Detect the package manager on Linux.
    Returns one of: apt, apt-get, dnf, yum, zypper; or None.
    """
    for pm in ["apt", "apt-get", "dnf", "yum", "zypper"]:
        if shutil.which(pm):
            return pm
    return None

###############################################################################
# 2. OS Detection and Mapping to Docker Base Images
###############################################################################
def detect_os():
    """
    Detect the host OS and version.
    Returns (os_name, version) as lowercase strings.
    """
    if sys.platform.startswith("linux"):
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
        except Exception as e:
            print(f"[WARN] Could not read /etc/os-release: {e}")
            return "linux", ""
    elif sys.platform == "win32":
        # Windows detection
        os_name = platform.system().lower()  # "windows"
        version = platform.release().lower()  # e.g., "xp", "7", "vista", "2008 server", "2012 server", etc.
        return os_name, version
    else:
        print("[ERROR] Only Linux and Windows systems are supported.")
        sys.exit(1)

def map_os_to_docker_image(os_name, version):
    """
    Map the detected OS to a recommended Docker base image.
    For Linux, many legacy images are provided.
    For Windows, legacy OSes (XP, Vista, 7, Server 2008, 2012) use placeholder images,
    while newer ones use official Microsoft images.
    """
    # Linux mappings (using examples from your list)
    linux_map = {
        "centos": {
            "6":  "centos:6",    # Note: May require a custom image if not available
            "7":  "centos:7",
            "8":  "centos:8",
            "9":  "centos:stream9",
            "":   "ubuntu:latest"  # fallback
        },
        "ubuntu": {
            "14": "ubuntu:14.04",
            "16": "ubuntu:16.04",
            "18": "ubuntu:18.04",
            "20": "ubuntu:20.04",
            "22": "ubuntu:22.04",
        },
        "debian": {
            "7":  "debian:7",
            "8":  "debian:8",
            "9":  "debian:9",
            "10": "debian:10",
            "11": "debian:11",
            "12": "debian:12",
        },
        "fedora": {
            "25": "fedora:25",
            "26": "fedora:26",
            "27": "fedora:27",
            "28": "fedora:28",
            "29": "fedora:29",
            "30": "fedora:30",
            "31": "fedora:31",
            "35": "fedora:35",
        },
        "opensuse leap": {
            "15": "opensuse/leap:15",
        },
        "opensuse tumbleweed": {
            "":   "opensuse/tumbleweed"
        },
        # Fallback for generic Linux
        "linux": {
            "":   "ubuntu:latest"
        },
    }

    # Windows mappings – note these are placeholders for legacy OSes:
    windows_map = {
        "xp":      "legacy-windows/xp:latest",       # Custom image required
        "vista":   "legacy-windows/vista:latest",    # Custom image required
        "7":       "legacy-windows/win7:latest",       # Custom image required
        "2008":    "legacy-windows/win2008:latest",    # Custom image required
        "2012":    "legacy-windows/win2012:latest",    # Custom image required
        "10":      "mcr.microsoft.com/windows/nanoserver:1809",
        "2016":    "mcr.microsoft.com/windows/servercore:2016",
        "2019":    "mcr.microsoft.com/windows/servercore:ltsc2019",
        "2022":    "mcr.microsoft.com/windows/servercore:ltsc2022"
    }

    if os_name == "windows":
        for key, img in windows_map.items():
            if key in version:
                return img
        # Fallback for Windows if no match is found
        return "mcr.microsoft.com/windows/servercore:ltsc2019"
    else:
        # For Linux, attempt to match the distro keyword in os_name
        for distro, ver_map in linux_map.items():
            if distro in os_name:
                short_ver = version.split(".")[0] if version else ""
                if short_ver in ver_map:
                    return ver_map[short_ver]
                if "" in ver_map:
                    return ver_map[""]
                return "ubuntu:latest"
        # If no distro matches, return a generic Linux image
        return "ubuntu:latest"

###############################################################################
# 3. Core Dockerization & Migration Functions
###############################################################################
def pull_docker_image(image):
    """Pull the given Docker image."""
    try:
        print(f"[INFO] Pulling Docker image: {image}")
        subprocess.check_call(["docker", "pull", image])
        print(f"[INFO] Successfully pulled image: {image}")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not pull image '{image}': {e}")

def run_generic_container(os_name, base_image, container_name="generic_container"):
    """
    Launch a generic container from the base image with an interactive shell.
    For Windows, use 'cmd.exe'; for Linux, use '/bin/bash'.
    """
    command = "cmd.exe" if os_name == "windows" else "/bin/bash"
    try:
        print(f"[INFO] Launching generic container '{container_name}' using image '{base_image}' with shell '{command}'")
        subprocess.check_call(["docker", "run", "-it", "--name", container_name, base_image, command])
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not launch generic container: {e}")

def run_service_container(service, container_name=None):
    """
    Run a container for a specific service.
    (Note: Instead of hardcoding service images, you might later allow dynamic builds.)
    """
    # A sample dictionary – you can expand this as needed.
    service_images = {
        "dns":   "internetsystemsconsortium/bind9:9.16",
        "ftp":   "fauria/vsftpd",
        "pop3":  "instrumentisto/dovecot",
        "smtp":  "namshi/smtp",
        "ntp":   "cturra/ntp",
        "http":  "httpd:2.4",
        "https": "httpd:2.4",
        "php5":  "php:5.6-apache",
        "db":    "mysql:5.7",
        "postgres": "postgres:9.6",
        "iis":   "mcr.microsoft.com/windows/servercore/iis:windowsservercore-ltsc2019"
    }
    image = service_images.get(service.lower())
    if not image:
        print(f"[WARN] No pre-built container mapping for service '{service}'.")
        return
    if not container_name:
        container_name = f"{service.lower()}_container"
    try:
        print(f"[INFO] Running service container for '{service}' using image '{image}'")
        subprocess.check_call(["docker", "run", "-d", "--name", container_name, image])
        print(f"[INFO] Service container '{container_name}' started.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not run container for service '{service}': {e}")

def run_service_with_config(service, host_config, container_config, container_name=None):
    """
    Run a service container with a host configuration file mounted.
    """
    service_images = {
        "dns": "internetsystemsconsortium/bind9:9.16",
        "ftp": "fauria/vsftpd",
        # Expand as needed...
    }
    image = service_images.get(service.lower())
    if not image:
        print(f"[WARN] No pre-built container mapping for service '{service}'.")
        return
    if not os.path.exists(host_config):
        print(f"[ERROR] Host configuration file '{host_config}' does not exist.")
        return
    if not container_name:
        container_name = f"{service.lower()}_container"
    try:
        print(f"[INFO] Running '{service}' container with configuration from '{host_config}'")
        subprocess.check_call([
            "docker", "run", "-d", "--name", container_name,
            "-v", f"{os.path.abspath(host_config)}:{container_config}",
            image
        ])
        print(f"[INFO] Service container '{container_name}' started with config mounted at '{container_config}'.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not run container for service '{service}' with config: {e}")

def run_migration_container(source_dir, target_dir, container_name="migrate_container", command=None):
    """
    Launch a container from the matched base OS image with a volume mount
    to migrate host files (e.g., configuration files) into the container.
    Optionally run a command inside the container.
    """
    os_name, version = detect_os()
    base_image = map_os_to_docker_image(os_name, version)
    pull_docker_image(base_image)
    # Build the docker run command with volume mapping.
    run_cmd = ["docker", "run", "-d", "--name", container_name, "-v", f"{os.path.abspath(source_dir)}:{target_dir}", base_image]
    if command:
        run_cmd.append(command)
    try:
        print(f"[INFO] Running migration container '{container_name}' with source '{source_dir}' mounted to '{target_dir}'")
        subprocess.check_call(run_cmd)
        print(f"[INFO] Migration container '{container_name}' launched.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not run migration container: {e}")

def dockerize(service=None, host_config=None, container_config="/etc/service.conf"):
    """
    If a service is specified, run that service container (with optional config).
    Otherwise, launch a generic container from the base OS image for manual service building.
    """
    os_name, version = detect_os()
    print(f"[INFO] Detected OS: {os_name} (Version: {version})")
    base_image = map_os_to_docker_image(os_name, version)
    pull_docker_image(base_image)
    if service:
        if host_config:
            run_service_with_config(service, host_config, container_config)
        else:
            run_service_container(service)
    else:
        # No service specified; launch an interactive container for manual configuration.
        run_generic_container(os_name, base_image)

###############################################################################
# 4. Snapshot, Integrity Check, and Security Functions
###############################################################################
def snapshot_container(container_name, backup_tag):
    """
    Create a snapshot of a running container by committing it to a new image tag.
    """
    try:
        print(f"[INFO] Creating snapshot for container '{container_name}'")
        subprocess.check_call(["docker", "commit", container_name, backup_tag])
        print(f"[INFO] Snapshot created with tag '{backup_tag}'")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not snapshot container '{container_name}': {e}")

def integrity_check(container_name):
    """
    Run 'docker diff' on a container to check for unexpected changes.
    """
    try:
        print(f"[INFO] Performing integrity check on container '{container_name}'")
        diff_output = subprocess.check_output(["docker", "diff", container_name]).decode("utf-8")
        if diff_output:
            print("[WARN] Integrity differences detected:")
            print(diff_output)
        else:
            print("[INFO] No differences detected; container integrity is intact.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not perform integrity check on container '{container_name}': {e}")

def advanced_security_check():
    """
    Check Docker version for vulnerabilities and output security recommendations.
    """
    try:
        version_output = subprocess.check_output(["docker", "--version"]).decode("utf-8").strip()
        print(f"[INFO] Docker version: {version_output}")
        known_bad_versions = ["18.09", "19.03"]
        if any(bad in version_output for bad in known_bad_versions):
            print("[WARN] Detected a Docker version with known container escape vulnerabilities. Consider upgrading.")
        else:
            print("[INFO] Docker version not flagged for major escapes in our database.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not check Docker version: {e}")

def show_recommendations():
    """
    Output additional recommendations for hardening containerized environments.
    """
    print("\n--- Additional Recommendations ---")
    print("1. After matching the base OS container to your host, consider building your service from scratch within the container.")
    print("   • Migrate host configuration files and binaries as needed.")
    print("   • This approach allows custom builds for apps like PrestaShop, OpenCart, WordPress, etc.")
    print("2. Integrate a WAF (e.g., ModSecurity) for HTTP/HTTPS containers.")
    print("3. Use Docker Bench for Security to audit your Docker host and containers.")
    print("4. Implement network segmentation and resource limits (CPU, memory, seccomp/AppArmor).")
    print("5. Automate backups (via cron on Linux or Task Scheduler on Windows) and integrity checks.")
    print("6. For legacy Windows OS (XP, Vista, 7, Server 2008, 2012), ensure you have custom base images available.")
    print("----------------------------------\n")

###############################################################################
# 5. Main Entry Point and Argument Parsing
###############################################################################
def main():
    parser = argparse.ArgumentParser(
        description="CCDC-Style Hardening & Containerization Tool (Expanded for Legacy Linux and Windows)"
    )
    parser.add_argument("--action", required=True,
                        choices=["check", "dockerize", "migrate", "backup", "integrity", "security", "recommendations"],
                        help="Action to perform: check, dockerize, migrate, backup, integrity, security, recommendations")
    parser.add_argument("--service", help="Name of the service to run (e.g., dns, ftp, pop3, etc.)")
    parser.add_argument("--config", help="Path to host configuration file to mount into the container")
    parser.add_argument("--container-config", default="/etc/service.conf",
                        help="Mount path inside the container for the configuration file")
    parser.add_argument("--container", help="Container name for backup or integrity check")
    parser.add_argument("--backup-tag", help="Tag name for container snapshot")
    # New arguments for migration mode:
    parser.add_argument("--source", help="Source directory on host to migrate into the container")
    parser.add_argument("--target", help="Target directory inside the container for migrated files")
    parser.add_argument("--cmd", help="Optional command to run in the migration container")
    parser.add_argument("--container-name", help="Name for the migration container", default="migrate_container")
    
    args = parser.parse_args()

    if args.action == "check":
        check_all_dependencies()
        pm = detect_package_manager()
        if pm:
            print(f"[INFO] Detected package manager: {pm}")
        else:
            print("[INFO] No recognized package manager (or non-Linux system).")
    elif args.action == "dockerize":
        check_all_dependencies()
        # If a service is specified, attempt to run that service.
        # Otherwise, run a generic container with an interactive shell.
        dockerize(service=args.service, host_config=args.config, container_config=args.container_config)
    elif args.action == "migrate":
        check_all_dependencies()
        if not args.source or not args.target:
            print("[ERROR] For migration, please specify both --source and --target directories.")
            sys.exit(1)
        run_migration_container(args.source, args.target, container_name=args.container_name, command=args.cmd)
    elif args.action == "backup":
        check_all_dependencies()
        if not args.container or not args.backup_tag:
            print("[ERROR] For backup, specify --container and --backup-tag.")
            sys.exit(1)
        snapshot_container(args.container, args.backup_tag)
    elif args.action == "integrity":
        check_all_dependencies()
        if not args.container:
            print("[ERROR] For integrity check, specify --container.")
            sys.exit(1)
        integrity_check(args.container)
    elif args.action == "security":
        check_all_dependencies()
        advanced_security_check()
    elif args.action == "recommendations":
        check_python_version(3, 7)
        show_recommendations()
    else:
        print("[ERROR] Unknown action.")

if __name__ == "__main__":
    main()
