#!/usr/bin/env python3
import sys
import platform
import subprocess
import argparse
import os

def detect_os():
    """
    Detect the host operating system and version.
    For Linux, we read /etc/os-release.
    For Windows and macOS, we use the platform module.
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
    Adjust the mappings as needed for legacy or competition-specific environments.
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
        # Use a Windows Server Core image as an example (adjust version as needed)
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
    Run a container for a specified service.
    Maps a service name to a pre-built Docker image.
    """
    # Example mappings – adjust these to point to your pre-built images or Docker Hub repositories.
    service_images = {
        "ftp": "fauria/vsftpd",      # Example FTP server container
        "pop3": "radicalpop3server",  # Replace with an actual POP3 server image
        "ecommerce": "php:apache",    # Simplest container for a LAMP-like setup
    }
    image = service_images.get(service.lower())
    if not image:
        print(f"No pre-built container available for service '{service}'.")
        return
    try:
        print(f"Running service container for {service} using image {image}")
        subprocess.check_call(["docker", "run", "-d", image])
        print(f"Service container for {service} started.")
    except subprocess.CalledProcessError as e:
        print(f"Error running container for service {service}: {e}")

def run_service_with_config(service, host_config, container_config):
    """
    Run a service container while mounting a configuration file from the host.
    This simulates migrating a configuration file into the container.
    """
    # For this example, we use the same image mappings as above.
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
            "docker", "run", "-d",
            "-v", f"{os.path.abspath(host_config)}:{container_config}",
            image
        ])
        print(f"Service container for {service} started with config mounted at {container_config}.")
    except subprocess.CalledProcessError as e:
        print(f"Error running container for service {service} with config: {e}")

def main():
    os_name, version = detect_os()
    print(f"Detected OS: {os_name} (Version: {version})")
    base_image = map_os_to_docker_image(os_name, version)
    if base_image:
        pull_docker_image(base_image)
    else:
        print("Could not determine a suitable Docker image for this OS.")
    
    parser = argparse.ArgumentParser(
        description="Automated Dockerization Helper Script for CCDC-Style Environments"
    )
    parser.add_argument("--service", help="Name of the service to run as a Docker container (e.g., ftp, pop3, ecommerce)")
    parser.add_argument("--config", help="Path to the host configuration file to migrate (optional)")
    parser.add_argument("--container-config", default="/etc/service.conf", 
                        help="Path inside the container where the configuration file should be mounted (default: /etc/service.conf)")
    args = parser.parse_args()

    if args.service:
        if args.config:
            # Run the service container with configuration file mounted
            run_service_with_config(args.service, args.config, args.container_config)
        else:
            # Run the service container without a custom configuration mount
            run_service_container(args.service)

if __name__ == "__main__":
    main()
