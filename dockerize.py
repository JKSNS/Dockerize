#!/usr/bin/env python3
"""
ccdc_docker_hardener.py

A modular Python script to assist with automating the hardening and containerization
of outdated infrastructure environments for cyber defense competitions.

Features:
  - Detects the host operating system and maps to a legacy Docker base image.
  - Pulls the base OS image and additional service containers.
  - Supports mounting configuration files from the host to replicate legacy setups.
  - Checks for dependencies: Docker, Docker Compose (if applicable) and, on Windows, WSL.
  - Provides functions for snapshotting containers and performing basic integrity checks.
  - Runs an advanced security check to warn about Docker version vulnerabilities.
  - Offers additional recommendations for further hardening (e.g., logging, network segmentation).

Usage:
  Basic OS dockerization:
      python3 ccdc_docker_hardener.py --action dockerize

  Run a service container (e.g., FTP):
      python3 ccdc_docker_hardener.py --action dockerize --service ftp

  Run a service container with a configuration file mounted:
      python3 ccdc_docker_hardener.py --action dockerize --service ftp --config /path/to/config.conf --container-config /etc/vsftpd.conf

  Create a snapshot backup of a running container:
      python3 ccdc_docker_hardener.py --action backup --container my_container --backup-tag my_container_snapshot

  Perform an integrity check on a container:
      python3 ccdc_docker_hardener.py --action integrity --container my_container

  Run advanced security checks:
      python3 ccdc_docker_hardener.py --action security

  Show additional recommendations:
      python3 ccdc_docker_hardener.py --action recommendations
"""

import sys
import platform
import subprocess
import argparse
import os
import shutil

def detect_os():
    """
    Detect the host operating system and version.
    For Linux, read /etc/os-release; for Windows/macOS use platform module.
    Returns (os_name, version).
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
            return os_info.get("NAME", "Linux"), os_info.get("VERSION_ID", "")
        except Exception as e:
            print(f"Error reading /etc/os-release: {e}")
            return "Linux", ""
    elif sys.platform == "win32":
        return platform.system(), platform.release()
    elif sys.platform == "darwin":
        return "macOS", platform.mac_ver()[0]
    else:
        return "Unknown", ""

def map_os_to_docker_image(os_name, version):
    """
    Map the detected OS to a corresponding Docker base image.
    Modify these mappings as necessary for legacy/competition-specific requirements.
    """
    os_lower = os_name.lower()
    if "ubuntu" in os_lower:
        if version.startswith("14"):
            return "ubuntu:14.04"
        elif version.startswith("16"):
            return "ubuntu:16.04"
        elif version.startswith("18"):
            return "ubuntu:18.04"
        elif version.startswith("20"):
            return "ubuntu:20.04"
        else:
            return "ubuntu:latest"
    elif "debian" in os_lower:
        return f"debian:{version}" if version else "debian:latest"
    elif "windows" in os_lower:
        # Use a Windows Server Core image as an example
        return "mcr.microsoft.com/windows/servercore:ltsc2019"
    elif "macos" in os_lower:
        print("No official Docker images for macOS exist. Please use a Linux/Windows base image.")
        return None
    else:
        return None

def pull_docker_image(image):
    """
    Pull the specified Docker image.
    """
    try:
        print(f"Pulling Docker image: {image}")
        subprocess.check_call(["docker", "pull", image])
        print(f"Successfully pulled image: {image}")
    except subprocess.CalledProcessError as e:
        print(f"Error pulling image {image}: {e}")

def run_service_container(service):
    """
    Run a container for the specified service.
    Maps a service name to a pre-built Docker image.
    """
    service_images = {
        "ftp": "fauria/vsftpd",      # Example FTP server container
        "pop3": "radicalpop3server",  # Replace with a valid POP3 image
        "ecommerce": "php:apache",    # Simple container for a LAMP-like ecommerce setup
        # Add more mappings as needed...
    }
    image = service_images.get(service.lower())
    if not image:
        print(f"No pre-built container available for service '{service}'.")
        return
    try:
        print(f"Running service container for {service} using image {image}")
        subprocess.check_call(["docker", "run", "-d", "--name", f"{service}_container", image])
        print(f"Service container for {service} started.")
    except subprocess.CalledProcessError as e:
        print(f"Error running container for service {service}: {e}")

def run_service_with_config(service, host_config, container_config):
    """
    Run a service container while mounting a configuration file from the host.
    """
    service_images = {
        "ftp": "fauria/vsftpd",
        # Add other mappings as needed.
    }
    image = service_images.get(service.lower())
    if not image:
        print(f"No pre-built container available for service '{service}'.")
        return
    if not os.path.exists(host_config):
        print(f"Host configuration file {host_config} does not exist.")
        return

    try:
        print(f"Running {service} container with configuration from {host_config}")
        subprocess.check_call([
            "docker", "run", "-d", "--name", f"{service}_container",
            "-v", f"{os.path.abspath(host_config)}:{container_config}",
            image
        ])
        print(f"Service container for {service} started with config mounted at {container_config}.")
    except subprocess.CalledProcessError as e:
        print(f"Error running container for service {service} with config: {e}")

def check_dependencies():
    """
    Check for required dependencies: Docker, Docker Compose (if applicable),
    and for Windows, check if WSL is installed.
    """
    # Check Docker
    try:
        subprocess.check_call(["docker", "--version"], stdout=subprocess.DEVNULL)
    except Exception:
        print("Docker is not installed or not in PATH. Please install Docker.")
        sys.exit(1)

    # Check Docker Compose
    try:
        subprocess.check_call(["docker-compose", "--version"], stdout=subprocess.DEVNULL)
    except Exception:
        print("Docker Compose is not available. If your OS does not support it, consider alternative orchestration methods.")

    # Windows-specific check for WSL
    if platform.system() == "Windows":
        try:
            subprocess.check_call(["wsl", "--version"], stdout=subprocess.DEVNULL)
        except Exception:
            print("WSL is required to run Docker on Windows. Please install WSL from Microsoft Store or via PowerShell.")

def snapshot_container(container_name, backup_tag):
    """
    Create a snapshot (backup) of a running container by committing it.
    """
    try:
        print(f"Creating snapshot for container: {container_name}")
        subprocess.check_call(["docker", "commit", container_name, backup_tag])
        print(f"Snapshot created with tag: {backup_tag}")
    except subprocess.CalledProcessError as e:
        print(f"Error snapshotting container {container_name}: {e}")

def integrity_check(container_name):
    """
    Perform a basic integrity check on a container by running 'docker diff'.
    Compare against a stored baseline (if available) or simply display differences.
    """
    try:
        print(f"Performing integrity check on container: {container_name}")
        diff_output = subprocess.check_output(["docker", "diff", container_name]).decode("utf-8")
        if diff_output:
            print("Integrity differences detected:")
            print(diff_output)
        else:
            print("No differences detected. Container integrity is intact.")
    except subprocess.CalledProcessError as e:
        print(f"Error performing integrity check on container {container_name}: {e}")

def advanced_security_check():
    """
    Check Docker version for vulnerabilities and provide security recommendations.
    """
    try:
        version_output = subprocess.check_output(["docker", "--version"]).decode("utf-8").strip()
        print(f"Docker version: {version_output}")
        # Dummy check: warn if Docker version contains '19.03' (example vulnerable version)
        if "19.03" in version_output:
            print("WARNING: Docker version 19.03 has known container escape vulnerabilities. Please consider upgrading or applying hardening patches.")
        else:
            print("Docker version appears secure based on this basic check.")
    except subprocess.CalledProcessError as e:
        print(f"Error checking Docker version: {e}")

def show_recommendations():
    """
    Output additional recommendations for securing containerized legacy environments.
    """
    print("\n--- Additional Recommendations ---")
    print("1. Implement logging enhancements to capture container and host activity.")
    print("2. Enforce network segmentation and resource limitations (e.g., CPU, memory) on containers.")
    print("3. Regularly update and patch your Docker host and container images where possible.")
    print("4. Use tools like 'Docker Bench for Security' to audit your container configurations.")
    print("5. Consider integrating a Web Application Firewall (WAF) like ModSecurity in front of web services.")
    print("6. Automate backups and integrity checks with scheduled tasks (cron for Linux, Task Scheduler for Windows).")
    print("----------------------------------\n")

def dockerize(os_only=False, service=None, host_config=None, container_config="/etc/service.conf"):
    """
    Handle OS detection, base image pull, and optionally run a service container.
    """
    os_name, version = detect_os()
    print(f"Detected OS: {os_name} (Version: {version})")
    base_image = map_os_to_docker_image(os_name, version)
    if base_image:
        pull_docker_image(base_image)
    else:
        print("Could not determine a suitable Docker image for this OS.")
    
    if service:
        if host_config:
            run_service_with_config(service, host_config, container_config)
        else:
            run_service_container(service)

def main():
    check_dependencies()
    
    parser = argparse.ArgumentParser(
        description="Automated Hardening and Containerization Tool for CCDC-Style Environments"
    )
    parser.add_argument("--action", required=True,
                        choices=["dockerize", "backup", "integrity", "security", "recommendations"],
                        help="Action to perform: dockerize, backup, integrity, security, recommendations")
    parser.add_argument("--service", help="Name of the service to run (e.g., ftp, pop3, ecommerce)")
    parser.add_argument("--config", help="Path to the host configuration file to import")
    parser.add_argument("--container-config", default="/etc/service.conf",
                        help="Mount path inside the container for the configuration file")
    parser.add_argument("--container", help="Name or ID of the container for backup/integrity checks")
    parser.add_argument("--backup-tag", help="Tag name for the container snapshot backup")
    
    args = parser.parse_args()
    
    if args.action == "dockerize":
        dockerize(service=args.service, host_config=args.config, container_config=args.container_config)
    elif args.action == "backup":
        if not args.container or not args.backup_tag:
            print("For backup action, please specify --container and --backup-tag.")
        else:
            snapshot_container(args.container, args.backup_tag)
    elif args.action == "integrity":
        if not args.container:
            print("For integrity action, please specify --container.")
        else:
            integrity_check(args.container)
    elif args.action == "security":
        advanced_security_check()
    elif args.action == "recommendations":
        show_recommendations()
    else:
        print("Unknown action.")

if __name__ == "__main__":
    main()
