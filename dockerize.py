#!/usr/bin/env python3
"""
ccdc_docker_hardener_expanded_os.py

A comprehensive script for automating the containerization and hardening of
various outdated or diverse environments (Linux + Windows) for CCDC-style competitions.

Features:
  - Checks Python version, Docker, Docker Compose, WSL (on Windows).
  - Detects a wide range of Linux distributions (CentOS, Ubuntu, Debian, Fedora, openSUSE, etc.)
    and Windows versions (2016, 2019, 2022).
  - Maps each OS to a recommended Docker base image (where available).
  - Detects and uses the appropriate package manager on Linux if needed (apt, yum, dnf, zypper).
  - Provides service containerization for DNS, FTP, POP3, SMTP, NTP, HTTP, PHP5, DB, etc.
  - Supports mounting host config files into containers.
  - Allows container snapshots and integrity checks.
  - Performs a basic Docker security check and prints best-practice recommendations.

Usage Examples:
  1) Just check prerequisites:
     python3 ccdc_docker_hardener_expanded_os.py --action check

  2) Dockerize base OS:
     python3 ccdc_docker_hardener_expanded_os.py --action dockerize

  3) Launch a DNS service container:
     python3 ccdc_docker_hardener_expanded_os.py --action dockerize --service dns

  4) Launch a service container with a host config:
     python3 ccdc_docker_hardener_expanded_os.py --action dockerize --service ftp \
       --config /path/to/vsftpd.conf --container-config /etc/vsftpd.conf

  5) Snapshot a running container:
     python3 ccdc_docker_hardener_expanded_os.py --action backup --container ftp_container --backup-tag ftp_backup_v1

  6) Integrity check a container:
     python3 ccdc_docker_hardener_expanded_os.py --action integrity --container ftp_container

  7) Advanced security checks:
     python3 ccdc_docker_hardener_expanded_os.py --action security

  8) Additional recommendations:
     python3 ccdc_docker_hardener_expanded_os.py --action recommendations
"""

import sys
import platform
import subprocess
import argparse
import os

###############################################################################
# 1. Python Version Check
###############################################################################
def check_python_version(min_major=3, min_minor=7):
    """
    Ensure the script is running on at least Python 3.7.
    If not, exit with an error message.
    """
    if sys.version_info < (min_major, min_minor):
        print(f"[ERROR] Python {min_major}.{min_minor}+ is required. Current: {sys.version_info.major}.{sys.version_info.minor}")
        sys.exit(1)
    else:
        print(f"[INFO] Python version check passed ({sys.version_info.major}.{sys.version_info.minor}).")

###############################################################################
# 2. OS Detection + Mapping to Docker Images
###############################################################################
def detect_os():
    """
    Attempt to detect the host OS and version.
    Returns (os_name, version), both in lowercase for consistency.
    """
    if sys.platform.startswith("linux"):
        try:
            with open("/etc/os-release") as f:
                lines = f.readlines()
            os_info = {}
            for line in lines:
                if "=" in line:
                    key, value = line.strip().split("=", 1)
                    os_info[key] = value.strip('"').lower()
            os_name = os_info.get("name", "linux").lower()
            version_id = os_info.get("version_id", "")
            return os_name, version_id
        except Exception as e:
            print(f"[WARN] Could not read /etc/os-release: {e}")
            return "linux", ""
    elif sys.platform == "win32":
        # Windows detection
        os_name = platform.system().lower()  # "windows"
        version = platform.release().lower() # e.g. "10", "2016server", "2019server"
        return os_name, version
    elif sys.platform == "darwin":
        # macOS detection
        return "macos", platform.mac_ver()[0].lower()
    else:
        return "unknown", ""

def map_os_to_docker_image(os_name, version):
    """
    Map a wide variety of Linux distributions and Windows versions
    to recommended Docker base images. Some older images may be EOL.
    Adjust as needed for real CCDC usage.
    """

    # Dictionary-of-dictionaries approach for Linux
    # Keys are the distro (in lowercase) -> nested dict of version -> image
    linux_map = {
        "centos": {
            "6":  "centos:6",    # EOL, might not exist on Docker Hub anymore
            "7":  "centos:7",
            "8":  "centos:8",
            "9":  "centos:stream9",  # CentOS Stream 9
        },
        "ubuntu": {
            "14": "ubuntu:14.04",
            "16": "ubuntu:16.04",
            "18": "ubuntu:18.04",
            "20": "ubuntu:20.04",
            "22": "ubuntu:22.04",
        },
        "debian": {
            "7":  "debian:7",   # EOL
            "8":  "debian:8",
            "9":  "debian:9",
            "10": "debian:10",
            "11": "debian:11",
            "12": "debian:12",
        },
        "fedora": {
            # Many releases, example
            "25": "fedora:25",
            "26": "fedora:26",
            "27": "fedora:27",
            "28": "fedora:28",
            "29": "fedora:29",
            "30": "fedora:30",
            "31": "fedora:31",
            "35": "fedora:35",  # example of a newer release
        },
        "opensuse leap": {
            "15": "opensuse/leap:15",  # might be 15.3, 15.4, etc.
        },
        "opensuse tumbleweed": {
            "":   "opensuse/tumbleweed"
        },
        "kali": {
            "":   "kalilinux/kali-rolling"
        },
        "parrot": {
            # Parrot OS official container might differ
            "":   "parrotsec/core:latest"
        },
        # Fallback for "linux"
        "linux": {
            "":   "ubuntu:latest"
        },
    }

    # Windows base images
    # Docker Windows containers only work on Windows hosts in Windows container mode
    windows_map = {
        # We'll do a simplistic approach: check if any of these strings are in 'version'
        "2016":  "mcr.microsoft.com/windows/servercore:2016",
        "2019":  "mcr.microsoft.com/windows/servercore:ltsc2019",
        "2022":  "mcr.microsoft.com/windows/servercore:ltsc2022",
        # Possibly also older versions or Nano server variants
        "10":    "mcr.microsoft.com/windows/nanoserver:1809"
    }

    # macOS fallback
    if os_name == "macos":
        print("[WARN] macOS host detected; no official macOS container images exist. Fallback to Ubuntu.")
        return "ubuntu:latest"

    # Windows
    if os_name == "windows":
        for key, img in windows_map.items():
            if key in version:
                return img
        # fallback
        return "mcr.microsoft.com/windows/servercore:ltsc2019"

    # Generic Linux
    # Try to find a distro match in the dictionary
    # We'll do a simple approach: see if the 'os_name' contains known keywords
    for distro, version_map in linux_map.items():
        if distro in os_name:
            # If we found the distro, see if we have a direct version match
            short_ver = version.split(".")[0] if version else ""
            if short_ver in version_map:
                return version_map[short_ver]
            # fallback to distro's empty version if present
            if "" in version_map:
                return version_map[""]
            # fallback to ubuntu:latest if not found
            return "ubuntu:latest"

    # If we didn't match any known distro, fallback to generic
    return "ubuntu:latest"

###############################################################################
# 3. Detect Package Manager (for potential installation of Docker, etc.)
###############################################################################
def detect_package_manager():
    """
    Attempt to detect which package manager is present on a Linux system:
      - apt (Debian/Ubuntu)
      - yum (CentOS 6, older RHEL)
      - dnf (Fedora, CentOS 8+)
      - zypper (openSUSE)
    Returns a string indicating the package manager command.
    If none detected or on Windows/macOS, returns None.
    """
    # Quick checks for existence
    for pm in ["apt", "apt-get", "dnf", "yum", "zypper"]:
        if shutil.which(pm):
            return pm
    return None

###############################################################################
# 4. Docker & Other Dependency Checks
###############################################################################
import shutil  # for shutil.which in detect_package_manager()

def check_docker():
    """Check if Docker is installed and accessible."""
    try:
        subprocess.check_call(["docker", "--version"], stdout=subprocess.DEVNULL)
        print("[INFO] Docker is installed.")
    except Exception:
        print("[ERROR] Docker not found. Please install Docker before running this script.")
        sys.exit(1)

def check_docker_compose():
    """Check if Docker Compose is installed."""
    try:
        subprocess.check_call(["docker-compose", "--version"], stdout=subprocess.DEVNULL)
        print("[INFO] Docker Compose is installed.")
    except Exception:
        print("[WARN] Docker Compose not found. Some orchestration features may be unavailable.")

def check_wsl_if_windows():
    """On Windows, check if WSL is installed if Docker Desktop w/ WSL2 is required."""
    if platform.system().lower() == "windows":
        try:
            subprocess.check_call(["wsl", "--version"], stdout=subprocess.DEVNULL)
            print("[INFO] WSL is installed. Docker with WSL2 backend should be supported.")
        except Exception:
            print("[WARN] WSL not found. If you're on Windows 10/11 Home, Docker may require WSL2. Please install it if needed.")

def check_all_dependencies():
    """
    Master function to check:
      - Python version
      - Docker
      - Docker Compose
      - WSL on Windows
    """
    check_python_version(3, 7)
    check_docker()
    check_docker_compose()
    check_wsl_if_windows()

###############################################################################
# 5. Core Dockerization Logic
###############################################################################
def pull_docker_image(image):
    """Pull the specified Docker image."""
    try:
        print(f"[INFO] Pulling Docker image: {image}")
        subprocess.check_call(["docker", "pull", image])
        print(f"[INFO] Successfully pulled image: {image}")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not pull image '{image}': {e}")

def run_service_container(service, container_name=None):
    """
    Run a container for the specified service.
    Expand or modify this dictionary for your competition's typical services.
    """
    service_images = {
        "dns":      "internetsystemsconsortium/bind9:9.16",  # DNS
        "ftp":      "fauria/vsftpd",
        "pop3":     "instrumentisto/dovecot",
        "smtp":     "namshi/smtp",
        "ntp":      "cturra/ntp",
        "http":     "httpd:2.4",
        "https":    "httpd:2.4",  # or an SSL variant
        "php5":     "php:5.6-apache",   # EOL but used in some competitions
        "db":       "mysql:5.7",        # or older MySQL, etc.
        "postgres": "postgres:9.6",
        "iis":      "mcr.microsoft.com/windows/servercore/iis:windowsservercore-ltsc2019",  # Windows-based
        # Add more services as needed (LDAP, Samba, etc.)
    }

    image = service_images.get(service.lower())
    if not image:
        print(f"[WARN] No pre-built container mapping for service '{service}'.")
        return

    if not container_name:
        container_name = f"{service.lower()}_container"

    try:
        print(f"[INFO] Running service container for {service} using image '{image}'")
        subprocess.check_call(["docker", "run", "-d", "--name", container_name, image])
        print(f"[INFO] Service container '{container_name}' started.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not run container for service '{service}': {e}")

def run_service_with_config(service, host_config, container_config, container_name=None):
    """
    Run a service container while mounting a configuration file from the host.
    Expand the dictionary below as needed.
    """
    service_images = {
        "dns": "internetsystemsconsortium/bind9:9.16",
        "ftp": "fauria/vsftpd",
        # ...
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
        print(f"[INFO] Running {service} container with config from '{host_config}'")
        subprocess.check_call([
            "docker", "run", "-d", "--name", container_name,
            "-v", f"{os.path.abspath(host_config)}:{container_config}",
            image
        ])
        print(f"[INFO] Service container '{container_name}' started, config mounted at '{container_config}'.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not run container for service '{service}' with config: {e}")

def dockerize(service=None, host_config=None, container_config="/etc/service.conf"):
    """
    1) Detect OS & version
    2) Map to Docker base image
    3) Pull image
    4) Optionally launch a service container (with or without config)
    """
    os_name, version = detect_os()
    print(f"[INFO] Detected OS: {os_name} (Version: {version})")

    base_image = map_os_to_docker_image(os_name, version)
    if base_image:
        pull_docker_image(base_image)
    else:
        print("[WARN] No suitable Docker image found for this OS. Proceeding without pulling a base image.")

    if service:
        if host_config:
            run_service_with_config(service, host_config, container_config)
        else:
            run_service_container(service)

###############################################################################
# 6. Snapshots, Integrity Checks, and Security
###############################################################################
def snapshot_container(container_name, backup_tag):
    """
    Create a snapshot (backup) of a running container by committing it to a new image tag.
    """
    try:
        print(f"[INFO] Creating snapshot for container: '{container_name}'")
        subprocess.check_call(["docker", "commit", container_name, backup_tag])
        print(f"[INFO] Snapshot created with tag: '{backup_tag}'")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not snapshot container '{container_name}': {e}")

def integrity_check(container_name):
    """
    Perform a basic integrity check on a container by running 'docker diff'.
    You can compare the output with a baseline or just display it.
    """
    try:
        print(f"[INFO] Performing integrity check on container: '{container_name}'")
        diff_output = subprocess.check_output(["docker", "diff", container_name]).decode("utf-8")
        if diff_output:
            print("[WARN] Integrity differences detected:")
            print(diff_output)
            # Potentially auto-restore from snapshot here if desired
        else:
            print("[INFO] No differences detected. Container integrity is intact.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not perform integrity check on container '{container_name}': {e}")

def advanced_security_check():
    """
    Check Docker version for known vulnerabilities, print security recommendations.
    """
    try:
        version_output = subprocess.check_output(["docker", "--version"]).decode("utf-8").strip()
        print(f"[INFO] Docker version: {version_output}")
        known_bad_versions = ["18.09", "19.03"]  # example
        if any(bad in version_output for bad in known_bad_versions):
            print("[WARN] Detected a Docker version with known container escape vulnerabilities. Consider upgrading.")
        else:
            print("[INFO] Docker version not flagged for major escapes in this script's database.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not check Docker version: {e}")

def show_recommendations():
    """
    Print additional recommendations for container security and environment hardening.
    """
    print("\n--- Additional Recommendations ---")
    print("1. Integrate ModSecurity or another WAF for your HTTP/HTTPS containers.")
    print("2. Use 'Docker Bench for Security' to audit your Docker host and containers.")
    print("3. Employ network segmentation (Docker networks) and restrict inter-container traffic.")
    print("4. Configure resource limits (CPU, memory) and seccomp/AppArmor profiles for each container.")
    print("5. Automate backups and integrity checks (cron on Linux, Task Scheduler on Windows).")
    print("6. Keep host OS and Docker engine patched. For Windows containers, ensure Windows updates are applied.")
    print("7. Log container activity (syslog or centralized logging) for auditing and incident response.")
    print("----------------------------------\n")

###############################################################################
# 7. Main Entry Point
###############################################################################
def main():
    parser = argparse.ArgumentParser(
        description="CCDC-Style Hardening & Containerization Tool (Expanded OS + Windows + Package Manager Detection)"
    )
    parser.add_argument("--action", required=True,
                        choices=["check", "dockerize", "backup", "integrity", "security", "recommendations"],
                        help="Action: check (prereqs), dockerize, backup, integrity, security, recommendations")
    parser.add_argument("--service", help="Name of service to run (dns, ftp, pop3, smtp, ntp, http, etc.)")
    parser.add_argument("--config", help="Path to host config file to mount")
    parser.add_argument("--container-config", default="/etc/service.conf",
                        help="Mount path in container for the config file")
    parser.add_argument("--container", help="Container name for backup/integrity checks")
    parser.add_argument("--backup-tag", help="Tag name for container snapshot")

    args = parser.parse_args()

    if args.action == "check":
        # Check all prerequisites
        check_all_dependencies()
        # Also demonstrate package manager detection (on Linux)
        pm = detect_package_manager()
        if pm:
            print(f"[INFO] Detected package manager: {pm}")
        else:
            print("[INFO] No recognized package manager or non-Linux system.")
    elif args.action == "dockerize":
        check_all_dependencies()
        dockerize(service=args.service, host_config=args.config, container_config=args.container_config)
    elif args.action == "backup":
        check_all_dependencies()
        if not args.container or not args.backup_tag:
            print("[ERROR] For backup, specify --container and --backup-tag.")
            sys.exit(1)
        snapshot_container(args.container, args.backup_tag)
    elif args.action == "integrity":
        check_all_dependencies()
        if not args.container:
            print("[ERROR] For integrity, specify --container.")
            sys.exit(1)
        integrity_check(args.container)
    elif args.action == "security":
        check_all_dependencies()
        advanced_security_check()
    elif args.action == "recommendations":
        # We won't require Docker installed just to show recommendations,
        # but let's still do a partial check for Python version.
        check_python_version(3, 7)
        show_recommendations()
    else:
        print("[ERROR] Unknown action.")

if __name__ == "__main__":
    main()
