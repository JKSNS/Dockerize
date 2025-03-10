#!/usr/bin/env python3
"""
ccdc_docker_hardener_expanded.py

A more comprehensive Python script for automating the hardening and containerization
of outdated or diverse infrastructure environments for cyber defense competitions.

Features:
  - Extensive OS detection (multiple Linux distros + Windows Server).
  - Expanded service support: DNS, FTP, POP3, SMTP, NTP, HTTP, DB, etc.
  - Fallback logic if Docker Compose is unavailable or the OS is unsupported.
  - Snapshot/backup and integrity checks for containers.
  - Basic advanced security checks, including container escape warnings.
  - Example Windows container usage for Windows-based hosts.
  - Additional recommendations for multi-platform usage.

Usage (examples):
  1) Dockerize base OS:
     python3 ccdc_docker_hardener_expanded.py --action dockerize

  2) Launch a DNS service container:
     python3 ccdc_docker_hardener_expanded.py --action dockerize --service dns

  3) Launch a service container with host config:
     python3 ccdc_docker_hardener_expanded.py --action dockerize --service ftp \
       --config /path/to/vsftpd.conf --container-config /etc/vsftpd.conf

  4) Snapshot a running container:
     python3 ccdc_docker_hardener_expanded.py --action backup --container ftp_container --backup-tag ftp_backup_v1

  5) Integrity check a container:
     python3 ccdc_docker_hardener_expanded.py --action integrity --container ftp_container

  6) Advanced security checks:
     python3 ccdc_docker_hardener_expanded.py --action security

  7) Additional recommendations:
     python3 ccdc_docker_hardener_expanded.py --action recommendations
"""

import sys
import platform
import subprocess
import argparse
import os

def detect_os():
    """
    Detect the host operating system and version.
    For Linux: /etc/os-release
    For Windows: platform.release() or other heuristics
    For macOS: platform.mac_ver()
    """
    if sys.platform.startswith("linux"):
        try:
            with open("/etc/os-release") as f:
                lines = f.readlines()
            os_info = {}
            for line in lines:
                if "=" in line:
                    key, value = line.strip().split("=", 1)
                    os_info[key] = value.strip('"')
            os_name = os_info.get("NAME", "Linux").lower()
            version_id = os_info.get("VERSION_ID", "")
            return os_name, version_id
        except Exception as e:
            print(f"[WARN] Error reading /etc/os-release: {e}")
            return "linux", ""
    elif sys.platform == "win32":
        # Windows detection
        os_name = platform.system().lower()  # "windows"
        version = platform.release().lower() # e.g. "10", "2019server", etc.
        return os_name, version
    elif sys.platform == "darwin":
        # macOS detection
        return "macos", platform.mac_ver()[0]
    else:
        return "unknown", ""

def map_os_to_docker_image(os_name, version):
    """
    Return a suitable Docker base image for the detected OS.
    Includes expansions for multiple Linux distros and Windows versions.
    Adjust to suit your environment or add new mappings.
    """
    # Some fallback images for older or unknown versions
    # Feel free to expand or refine as needed.
    linux_map = {
        # Ubuntu
        ("ubuntu", "14"): "ubuntu:14.04",
        ("ubuntu", "16"): "ubuntu:16.04",
        ("ubuntu", "18"): "ubuntu:18.04",
        ("ubuntu", "20"): "ubuntu:20.04",
        ("ubuntu", ""):   "ubuntu:latest",
        # Debian
        ("debian", "9"):  "debian:9",
        ("debian", "10"): "debian:10",
        ("debian", "11"): "debian:11",
        ("debian", ""):   "debian:latest",
        # CentOS (for example)
        ("centos", "7"):  "centos:7",
        ("centos", "8"):  "centos:8",
        # Generic fallback
        ("linux", ""):    "ubuntu:latest"
    }

    # Windows base images
    # Only run on Windows hosts that support containers
    # (Hyper-V isolation or Windows Server with container feature)
    windows_map = {
        "10":    "mcr.microsoft.com/windows/nanoserver:1809",   # Example
        "2016":  "mcr.microsoft.com/windows/servercore:2016",
        "2019":  "mcr.microsoft.com/windows/servercore:ltsc2019",
        "2022":  "mcr.microsoft.com/windows/servercore:ltsc2022"
    }

    # Normalize
    os_key = (os_name, version[:2])  # e.g. ("ubuntu", "14")
    if os_name == "windows":
        # Attempt to find the best match in windows_map
        for wver, img in windows_map.items():
            if wver in version:
                return img
        # Fallback to a default if version not found
        return "mcr.microsoft.com/windows/servercore:ltsc2019"
    elif os_name == "macos":
        # macOS cannot run macOS Docker images natively, fallback to Linux container
        print("[WARN] No official macOS container images. Fallback to a Linux image (ubuntu:latest).")
        return "ubuntu:latest"
    else:
        # Attempt to match from the linux_map
        return linux_map.get(os_key, linux_map.get(("linux", ""), "ubuntu:latest"))

def pull_docker_image(image):
    """
    Pull the specified Docker image.
    """
    try:
        print(f"[INFO] Pulling Docker image: {image}")
        subprocess.check_call(["docker", "pull", image])
        print(f"[INFO] Successfully pulled image: {image}")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not pull image {image}: {e}")

def run_service_container(service, container_name=None):
    """
    Run a container for the specified service.
    The dictionary below maps service names to commonly used images.
    Expand this as needed for your environment.
    """
    service_images = {
        "dns":      "internetsystemsconsortium/bind9:9.16",  # Example DNS (Bind9)
        "ftp":      "fauria/vsftpd",
        "pop3":     "instrumentisto/dovecot",                # Example Dovecot container
        "smtp":     "namshi/smtp",                           # Example SMTP
        "ntp":      "cturra/ntp",                            # Example NTP server
        "http":     "httpd:2.4",                             # Apache HTTP
        "https":    "httpd:2.4",                             # or use an SSL-enabled variant
        "php":      "php:5.6-apache",                        # Outdated PHP 5.6 with Apache
        "db":       "mysql:5.7",                             # Example MySQL 5.7
        "postgres": "postgres:9.6",                          # Example Postgres 9.6
        "iis":      "mcr.microsoft.com/windows/servercore/iis:windowsservercore-ltsc2019", # Windows-based
        # Add more as needed
    }

    image = service_images.get(service.lower())
    if not image:
        print(f"[WARN] No pre-built container mapping for service '{service}'.")
        return

    # Container name
    if not container_name:
        container_name = f"{service.lower()}_container"

    try:
        print(f"[INFO] Running service container for {service} using image {image}")
        subprocess.check_call(["docker", "run", "-d", "--name", container_name, image])
        print(f"[INFO] Service container '{container_name}' started.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not run container for service '{service}': {e}")

def run_service_with_config(service, host_config, container_config, container_name=None):
    """
    Run a service container while mounting a configuration file from the host.
    """
    # For simplicity, re-use run_service_container's dictionary or define a new one:
    service_images = {
        "ftp":      "fauria/vsftpd",
        "dns":      "internetsystemsconsortium/bind9:9.16",
        # ... add more
    }

    image = service_images.get(service.lower())
    if not image:
        print(f"[WARN] No pre-built container mapping for service '{service}'.")
        return

    if not os.path.exists(host_config):
        print(f"[ERROR] Host configuration file {host_config} does not exist.")
        return

    if not container_name:
        container_name = f"{service.lower()}_container"

    try:
        print(f"[INFO] Running {service} container with configuration from {host_config}")
        subprocess.check_call([
            "docker", "run", "-d", "--name", container_name,
            "-v", f"{os.path.abspath(host_config)}:{container_config}",
            image
        ])
        print(f"[INFO] Service container '{container_name}' started with config mounted at {container_config}.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not run container for service '{service}' with config: {e}")

def check_dependencies():
    """
    Check for required dependencies: Docker, possibly Docker Compose.
    On Windows, check for WSL if required.
    """
    # Check Docker
    try:
        subprocess.check_call(["docker", "--version"], stdout=subprocess.DEVNULL)
    except Exception:
        print("[ERROR] Docker is not installed or not in PATH. Please install Docker.")
        sys.exit(1)

    # Check Docker Compose
    try:
        subprocess.check_call(["docker-compose", "--version"], stdout=subprocess.DEVNULL)
    except Exception:
        # For many outdated OS or certain Windows environments, docker-compose might be unavailable.
        print("[WARN] Docker Compose not found. Some orchestration features may not be available.")

    # Windows-specific check for WSL
    if platform.system().lower() == "windows":
        try:
            subprocess.check_call(["wsl", "--version"], stdout=subprocess.DEVNULL)
        except Exception:
            print("[WARN] WSL not found. If you're on Windows 10/11 Home, Docker may require WSL2. Please install WSL if needed.")

def snapshot_container(container_name, backup_tag):
    """
    Create a snapshot (backup) of a running container by committing it to a new image tag.
    """
    try:
        print(f"[INFO] Creating snapshot for container: {container_name}")
        subprocess.check_call(["docker", "commit", container_name, backup_tag])
        print(f"[INFO] Snapshot created with tag: {backup_tag}")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not snapshot container '{container_name}': {e}")

def integrity_check(container_name):
    """
    Perform a basic integrity check on a container by running 'docker diff'.
    Compare the output with a baseline or simply display differences.
    """
    try:
        print(f"[INFO] Performing integrity check on container: {container_name}")
        diff_output = subprocess.check_output(["docker", "diff", container_name]).decode("utf-8")
        if diff_output:
            print("[WARN] Integrity differences detected:")
            print(diff_output)
            # Potentially auto-restore from snapshot here if needed
        else:
            print("[INFO] No differences detected. Container integrity is intact.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not perform integrity check on container '{container_name}': {e}")

def advanced_security_check():
    """
    Check Docker version for known vulnerabilities and provide basic security recommendations.
    """
    try:
        version_output = subprocess.check_output(["docker", "--version"]).decode("utf-8").strip()
        print(f"[INFO] Docker version: {version_output}")
        # Example naive check for older Docker versions
        known_bad_versions = ["18.09", "19.03"]
        if any(bad in version_output for bad in known_bad_versions):
            print("[WARN] Detected a Docker version with known container escape vulnerabilities. Consider upgrading.")
        else:
            print("[INFO] Docker version not flagged for known major escapes in this script's database.")
        # Additional checks (CVE scanning) could be integrated here.
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not check Docker version: {e}")

def show_recommendations():
    """
    Print additional recommendations for container security and environment hardening.
    """
    print("\n--- Additional Recommendations ---")
    print("1. Integrate ModSecurity or other WAF for your web services (HTTP/HTTPS containers).")
    print("2. Use 'Docker Bench for Security' or similar tools to audit your Docker host and containers.")
    print("3. Employ network segmentation (user-defined networks) and restrict container inter-communication.")
    print("4. Configure resource limits (CPU, memory) and seccomp/apparmor profiles for each container.")
    print("5. Automate backups and integrity checks via cron (Linux) or Task Scheduler (Windows).")
    print("6. Keep host OS and Docker engine patched. For Windows containers, ensure Windows updates are applied.")
    print("7. Log container activity (via syslog or centralized logging) for auditing and incident response.")
    print("----------------------------------\n")

def dockerize(service=None, host_config=None, container_config="/etc/service.conf"):
    """
    Main function for OS detection, base image pulling, and optional service containerization.
    """
    os_name, version = detect_os()
    print(f"[INFO] Detected OS: {os_name} (Version: {version})")
    base_image = map_os_to_docker_image(os_name, version)
    if base_image:
        pull_docker_image(base_image)
    else:
        print("[WARN] No suitable Docker image found for this OS. Proceeding without pulling a base image.")

    # If a service is specified, run it
    if service:
        if host_config:
            run_service_with_config(service, host_config, container_config)
        else:
            run_service_container(service)

def main():
    check_dependencies()
    
    parser = argparse.ArgumentParser(
        description="Expanded Hardening & Containerization Tool for CCDC Environments"
    )
    parser.add_argument("--action", required=True,
                        choices=["dockerize", "backup", "integrity", "security", "recommendations"],
                        help="Action to perform: dockerize, backup, integrity, security, recommendations")
    parser.add_argument("--service", help="Name of the service to run (e.g. dns, ftp, pop3, smtp, ntp, http, db, etc.)")
    parser.add_argument("--config", help="Path to host config file to mount into the container")
    parser.add_argument("--container-config", default="/etc/service.conf",
                        help="Mount path inside the container for the configuration file")
    parser.add_argument("--container", help="Name of container to backup or integrity-check")
    parser.add_argument("--backup-tag", help="Tag name for container snapshot")

    args = parser.parse_args()

    if args.action == "dockerize":
        dockerize(service=args.service, host_config=args.config, container_config=args.container_config)
    elif args.action == "backup":
        if not args.container or not args.backup_tag:
            print("[ERROR] For backup, specify --container and --backup-tag.")
            sys.exit(1)
        snapshot_container(args.container, args.backup_tag)
    elif args.action == "integrity":
        if not args.container:
            print("[ERROR] For integrity check, specify --container.")
            sys.exit(1)
        integrity_check(args.container)
    elif args.action == "security":
        advanced_security_check()
    elif args.action == "recommendations":
        show_recommendations()
    else:
        print("[ERROR] Unknown action.")

if __name__ == "__main__":
    main()
