#!/usr/bin/env python3
"""
ccdc_integrity_tool.py

A comprehensive tool for CCDC-style environments that:

1. Installs & configures a container matching the detected OS.
   - Runs as a non-root user and in read-only mode.
   - Use this mode to build/migrate your service inside a container that mirrors the legacy OS.

2. Continuously performs integrity checks on a running container.
   - Computes a hash of the container's filesystem periodically.
   - If modifications are detected, restores the container from a snapshot (.tar file).

3. Deploys a web container with an integrated ModSecurity WAF.
   - Launches two containers on a dedicated network: a web container (e.g. Juice Shop) and a reverse-proxy container with ModSecurity.
   - The proxy forwards traffic (on host port 80) to the web container (on port 3000).

Usage (Interactive Menu):
  Run the script with the '--menu' flag:
    python3 ccdc_integrity_tool.py --menu

Requirements:
  - Python 3.7+
  - Docker Engine installed (preferably Docker CE rather than Docker Desktop for strict UID mapping)
  - (Optional) A pre-saved snapshot tar file for restoration in integrity-check mode
  - A ModSecurity-enabled image (here we use the placeholder "owasp/modsecurity-crs:nginx")

Note: Customize image names, container names, and network settings as needed.
"""

import sys
import platform
import subprocess
import argparse
import os
import hashlib
import time
import shutil

# -------------------------------
# 1. Prerequisite Checks
# -------------------------------

def check_python_version(min_major=3, min_minor=7):
    """Ensure Python 3.7+ is being used."""
    if sys.version_info < (min_major, min_minor):
        print(f"[ERROR] Python {min_major}.{min_minor}+ is required. You are running {sys.version_info.major}.{sys.version_info.minor}.")
        sys.exit(1)
    else:
        print(f"[INFO] Python version check passed: {sys.version_info.major}.{sys.version_info.minor}.")

def check_docker():
    """Check that Docker is installed and accessible."""
    try:
        subprocess.check_call(["docker", "--version"], stdout=subprocess.DEVNULL)
        print("[INFO] Docker is installed.")
    except Exception as e:
        print("[ERROR] Docker not found. Please install Docker Engine.")
        sys.exit(1)

def check_docker_compose():
    """Check if Docker Compose is installed (warn if not)."""
    try:
        subprocess.check_call(["docker-compose", "--version"], stdout=subprocess.DEVNULL)
        print("[INFO] Docker Compose is installed.")
    except Exception:
        print("[WARN] Docker Compose not found. Some orchestration features may be unavailable.")

def check_wsl_if_windows():
    """On Windows, check for WSL if needed (for non-Docker Desktop environments)."""
    if platform.system().lower() == "windows":
        try:
            subprocess.check_call(["wsl", "--version"], stdout=subprocess.DEVNULL)
            print("[INFO] WSL is installed.")
        except Exception:
            print("[WARN] WSL not found. Running Docker containers as non-root on legacy Windows may require custom images.")

def check_all_dependencies():
    """Run all prerequisite checks."""
    check_python_version(3, 7)
    check_docker()
    check_docker_compose()
    check_wsl_if_windows()

def detect_package_manager():
    """Detect Linux package manager (apt, apt-get, dnf, yum, or zypper)."""
    for pm in ["apt", "apt-get", "dnf", "yum", "zypper"]:
        if shutil.which(pm):
            return pm
    return None

# -------------------------------
# 2. OS Detection & Mapping to Docker Base Image
# -------------------------------

def detect_os():
    """
    Detect the host OS and version.
    Returns (os_name, version) as lowercase strings.
    Supports Linux and Windows.
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
        os_name = platform.system().lower()  # "windows"
        version = platform.release().lower()  # e.g., "xp", "vista", "7", "2008", "2012", "10", etc.
        return os_name, version
    else:
        print("[ERROR] Only Linux and Windows systems are supported.")
        sys.exit(1)

def map_os_to_docker_image(os_name, version):
    """
    Map the detected OS to a recommended Docker base image.
    Linux mappings include CentOS, Ubuntu, Debian, Fedora, openSUSE.
    Windows mappings include legacy versions (XP, Vista, 7, Server 2008, 2012)
    and newer versions (10, Server 2016, 2019, 2022).
    (Legacy Windows images are placeholders that you must build/maintain.)
    """
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
    if os_name == "windows":
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

# -------------------------------
# 3. Container Launch & Integrity Checking Functions
# -------------------------------

def pull_docker_image(image):
    """Pull the specified Docker image."""
    try:
        print(f"[INFO] Pulling Docker image: {image}")
        subprocess.check_call(["docker", "pull", image])
        print(f"[INFO] Successfully pulled image: {image}")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not pull image '{image}': {e}")

def run_generic_container(os_name, base_image, container_name="generic_container"):
    """
    Launch a generic interactive container from the base image.
    The container is launched in read-only mode and as a non-root user.
    For Linux, uses 'nobody'; for Windows, uses 'nonroot'.
    """
    user = "nonroot" if os_name == "windows" else "nobody"
    shell_cmd = "cmd.exe" if os_name == "windows" else "/bin/bash"
    try:
        print(f"[INFO] Launching interactive container '{container_name}' from image '{base_image}' as user '{user}' in read-only mode.")
        subprocess.check_call(["docker", "run", "-it", "--read-only", "--user", user, "--name", container_name, base_image, shell_cmd])
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not launch container '{container_name}': {e}")

def compute_container_hash(container_name):
    """
    Compute a SHA256 hash of the container's filesystem by exporting it.
    Returns the hexadecimal hash string.
    """
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
    """
    Restore a container from a snapshot tar file.
    Loads the snapshot image and re-launches the container in detached mode.
    """
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
    """
    Continuously monitor the integrity of a running container.
    Every 'check_interval' seconds, compute a hash of the container's filesystem.
    If the hash differs from the baseline, the container is restored from the snapshot.
    """
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

# -------------------------------
# 4. Web Container with Integrated ModSecurity WAF Integration
# -------------------------------

def deploy_web_with_waf():
    """
    Deploy a web container protected by an integrated ModSecurity WAF.
    This function launches:
      - A web container (default: Juice Shop) exposing port 3000 inside the container, mapped to host port 1234.
      - A ModSecurity-enabled reverse-proxy container using the image 'owasp/modsecurity-crs:nginx'.
        It is configured with environment variables:
          PORT: "8080"
          PROXY: 1
          BACKEND: http://<web_container_name>:3000
          MODSEC_RULE_ENGINE: off
          BLOCKING_PARANOIA: 2
          TZ: value from the environment or default
          MODSEC_TMP_DIR: "/tmp"
          MODSEC_RESP_BODY_ACCESS: "On"
          MODSEC_RESP_BODY_MIMETYPE: "text/plain text/html text/xml application/json"
          COMBINED_FILE_SIZES: "65535"
        The reverse proxy maps its internal port 8080 to host port 80.
    Both containers are attached to a dedicated Docker network.
    """
    check_all_dependencies()
    # Define default image names
    web_image = "bkimminich/juice-shop"
    waf_image = "owasp/modsecurity-crs:nginx"
    
    # Pull required images
    pull_docker_image(web_image)
    pull_docker_image(waf_image)
    
    # Create a dedicated network for web and WAF containers
    network_name = "ccdc-web-net"
    try:
        subprocess.check_call(["docker", "network", "inspect", network_name],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[INFO] Docker network '{network_name}' already exists.")
    except subprocess.CalledProcessError:
        print(f"[INFO] Creating Docker network '{network_name}'.")
        subprocess.check_call(["docker", "network", "create", network_name])
    
    # Get user inputs (with defaults)
    web_container = input("Enter the web container name (default 'juice-shop'): ").strip() or "juice-shop"
    waf_container = input("Enter the ModSecurity proxy container name (default 'modsec2-nginx'): ").strip() or "modsec2-nginx"
    host_web_port = input("Enter host port for web container (default '1234'): ").strip() or "1234"
    host_waf_port = input("Enter host port for WAF (default '80'): ").strip() or "80"
    tz = os.environ.get("TZ", "UTC")
    
    # Launch web container in detached mode (non-root, read-only)
    user = "nonroot" if platform.system().lower() == "windows" else "nobody"
    try:
        print(f"[INFO] Launching web container '{web_container}' from image '{web_image}'...")
        subprocess.check_call([
            "docker", "run", "-d",
            "--read-only",
            "--user", user,
            "--name", web_container,
            "--network", network_name,
            "-p", f"{host_web_port}:3000",
            web_image
        ])
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not launch web container '{web_container}': {e}")
        sys.exit(1)
    
    # Set environment variables for the WAF container; BACKEND points to the web container.
    waf_env = [
        "PORT=8080",
        "PROXY=1",
        f"BACKEND=http://{web_container}:3000",
        "MODSEC_RULE_ENGINE=off",
        "BLOCKING_PARANOIA=2",
        f"TZ={tz}",
        "MODSEC_TMP_DIR=/tmp",
        "MODSEC_RESP_BODY_ACCESS=On",
        "MODSEC_RESP_BODY_MIMETYPE=text/plain text/html text/xml application/json",
        "COMBINED_FILE_SIZES=65535"
    ]
    # Launch the ModSecurity proxy container in detached mode
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
    
    print(f"[INFO] Deployment complete. The web container '{web_container}' is running (port 3000 internally, mapped to host port {host_web_port}).")
    print(f"[INFO] The ModSecurity-enabled proxy '{waf_container}' is listening on host port {host_waf_port} and forwarding to '{web_container}:3000'.")

# -------------------------------
# 5. Interactive Menu Interface
# -------------------------------

def interactive_menu():
    """Display an interactive menu for the user to choose an operation."""
    print("==== CCDC OS-to-Container & Integrity Tool ====")
    print("Select an option:")
    print("1. Install & Configure Container")
    print("2. Run Continuous Integrity Check")
    print("3. Deploy Web Container with Integrated ModSecurity WAF")
    choice = input("Enter your choice (1/2/3): ").strip()
    if choice == "1":
        print("[MODE 1] Installing & Configuring Container...")
        check_all_dependencies()
        os_name, version = detect_os()
        base_image = map_os_to_docker_image(os_name, version)
        print(f"[INFO] Detected OS: {os_name} (Version: {version}). Using base image: {base_image}")
        pull_docker_image(base_image)
        run_generic_container(os_name, base_image)
    elif choice == "2":
        print("[MODE 2] Running Continuous Integrity Check...")
        container_name = input("Enter the container name to monitor: ").strip()
        snapshot_tar = input("Enter the path to the snapshot .tar file for restoration: ").strip()
        check_interval_str = input("Enter integrity check interval in seconds (default 30): ").strip()
        try:
            check_interval = int(check_interval_str) if check_interval_str else 30
        except ValueError:
            check_interval = 30
        os_name, version = detect_os()
        base_image = map_os_to_docker_image(os_name, version)
        pull_docker_image(base_image)
        user = "nonroot" if os_name == "windows" else "nobody"
        print(f"[INFO] Launching container '{container_name}' in detached mode as user '{user}' in read-only mode.")
        try:
            subprocess.check_call([
                "docker", "run", "-d",
                "--read-only",
                "--user", user,
                "--name", container_name,
                base_image
            ])
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Could not launch container '{container_name}': {e}")
            sys.exit(1)
        continuous_integrity_check(container_name, snapshot_tar, check_interval)
    elif choice == "3":
        print("[MODE 3] Deploying Web Container with Integrated ModSecurity WAF...")
        deploy_web_with_waf()
    else:
        print("[ERROR] Invalid option. Exiting.")
        sys.exit(1)

# -------------------------------
# 6. Main Entry Point
# -------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="CCDC OS-to-Container & Integrity Tool: Map legacy OS to container, perform integrity checks, and integrate ModSecurity WAF for web containers."
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
