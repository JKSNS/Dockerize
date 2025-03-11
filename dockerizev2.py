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

3. Deploys a web container (matching the host OS) with an integrated ModSecurity WAF.
   - The script detects the OS and picks a matching Docker base image for the "web" container.
   - It tries to run a minimal built-in web server if possible (Python http.server, busybox httpd, or Windows PowerShell).
   - A ModSecurity-enabled reverse proxy container is also launched to forward traffic from host port 80 to the web container's port.

Usage (Interactive Menu):
  Run the script with the '--menu' flag:
    python3 ccdc_integrity_tool.py --menu

Requirements:
  - Python 3.7+
  - If Docker is missing, the script attempts to install it automatically on Linux, BSD, or Nix. 
  - (Optional) A pre-saved snapshot tar file for restoration in integrity-check mode
  - A ModSecurity-enabled image (here we use the placeholder "owasp/modsecurity-crs:nginx")

Notes:
  - The script is best-effort for auto-installing Docker on various distros. 
  - Matching an OS-based container with a built-in web server in read-only mode can fail if needed packages are missing.
  - You can remove the `--read-only` flag if ephemeral installation of packages is required inside the container.
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
# 1. Docker Auto-Installation Logic
# -------------------------------

def detect_linux_package_manager():
    """Detect common Linux package managers."""
    for pm in ["apt", "apt-get", "dnf", "yum", "zypper"]:
        if shutil.which(pm):
            return pm
    return None

def attempt_install_docker_linux():
    """
    Attempt to install Docker on Linux using a best-effort approach.
    This function requires sudo privileges.
    """
    pm = detect_linux_package_manager()
    if not pm:
        print("[ERROR] No recognized package manager found on Linux. Cannot auto-install Docker.")
        return False

    print(f"[INFO] Attempting to install Docker using '{pm}' on Linux...")

    try:
        if pm in ("apt", "apt-get"):
            # Minimal example for Debian/Ubuntu
            subprocess.check_call(["sudo", pm, "update", "-y"])
            subprocess.check_call(["sudo", pm, "install", "-y", "docker.io"])
        elif pm in ("yum", "dnf"):
            # Minimal example for RHEL/CentOS
            subprocess.check_call(["sudo", pm, "-y", "install", "docker"])
            subprocess.check_call(["sudo", "systemctl", "enable", "docker"])
            subprocess.check_call(["sudo", "systemctl", "start", "docker"])
        elif pm == "zypper":
            # Minimal example for openSUSE
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
    """
    Attempt to install Docker on *BSD using a best-effort approach with 'pkg'.
    Docker on BSD is not officially supported in many cases, so this may fail.
    """
    pkg_path = shutil.which("pkg")
    if not pkg_path:
        print("[ERROR] 'pkg' not found. Cannot auto-install Docker on BSD.")
        return False
    print("[INFO] Attempting to install Docker using 'pkg' on BSD (best-effort).")
    try:
        subprocess.check_call(["sudo", "pkg", "update"])
        # Some BSD variants do not have official Docker packages, but let's do a best-effort
        subprocess.check_call(["sudo", "pkg", "install", "-y", "docker"])
        print("[INFO] Docker installation attempt completed for BSD. Checking if Docker is now available.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Auto-installation of Docker on BSD failed: {e}")
        return False

def attempt_install_docker_nix():
    """
    Attempt to install Docker on NixOS or Nix-based systems using 'nix-env -i docker'.
    This is highly experimental and may require extra config in /etc/nixos/configuration.nix.
    """
    nixenv_path = shutil.which("nix-env")
    if not nixenv_path:
        print("[ERROR] 'nix-env' not found. Cannot auto-install Docker on Nix.")
        return False
    print("[INFO] Attempting to install Docker using 'nix-env -i docker' on Nix.")
    try:
        subprocess.check_call(["sudo", "nix-env", "-i", "docker"])
        # Additional steps might be needed to enable the Docker daemon on NixOS
        # Typically you'd configure `services.docker.enable = true;` in /etc/nixos/configuration.nix
        print("[INFO] Docker installation attempt completed for Nix. Checking if Docker is now available.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Auto-installation of Docker on Nix failed: {e}")
        return False

def ensure_docker_installed():
    """
    Check if Docker is installed. If not, attempt to auto-install on Linux, BSD, or Nix.
    If the script cannot install Docker, it exits with an error.
    """
    docker_path = shutil.which("docker")
    if docker_path:
        print("[INFO] Docker appears to be installed.")
        return

    # Check platform
    sysname = platform.system().lower()
    if sysname.startswith("linux"):
        # Attempt normal Linux install
        success = attempt_install_docker_linux()
        if not success:
            # Maybe it's a Nix-based system
            # We'll do a naive approach: if /etc/os-release has "nixos", try attempt_install_docker_nix
            try:
                with open("/etc/os-release") as f:
                    content = f.read().lower()
                if "nixos" in content:
                    print("[INFO] Detected possible NixOS. Trying Nix-based install.")
                    success = attempt_install_docker_nix()
                else:
                    # Try a fallback approach?
                    pass
            except:
                pass
        if not success:
            print("[ERROR] Could not auto-install Docker on Linux. Please install it manually.")
            sys.exit(1)
        docker_path = shutil.which("docker")
        if not docker_path:
            print("[ERROR] Docker still not found after auto-install attempt.")
            sys.exit(1)
        print("[INFO] Docker is now installed on Linux.")
    elif "bsd" in sysname:
        # Attempt to install with pkg
        success = attempt_install_docker_bsd()
        if not success:
            print("[ERROR] Could not auto-install Docker on BSD. Please install it manually.")
            sys.exit(1)
        docker_path = shutil.which("docker")
        if not docker_path:
            print("[ERROR] Docker still not found after auto-install attempt on BSD.")
            sys.exit(1)
        print("[INFO] Docker is now installed on BSD.")
    elif "nix" in sysname:
        # Attempt direct Nix approach
        success = attempt_install_docker_nix()
        if not success:
            print("[ERROR] Could not auto-install Docker on Nix. Please install it manually.")
            sys.exit(1)
        docker_path = shutil.which("docker")
        if not docker_path:
            print("[ERROR] Docker still not found after auto-install attempt on Nix.")
            sys.exit(1)
        print("[INFO] Docker is now installed on Nix.")
    elif sysname == "windows":
        # On Windows, we do not attempt auto-install
        print("[ERROR] Docker not found, and auto-install is not supported on Windows. Please install Docker or Docker Desktop manually.")
        sys.exit(1)
    else:
        print(f"[ERROR] Unrecognized system '{sysname}'. Docker is missing. Please install it manually.")
        sys.exit(1)

# -------------------------------
# 2. Python & Docker Checks
# -------------------------------

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
    ensure_docker_installed()  # If Docker is missing, try to install automatically
    check_docker_compose()
    check_wsl_if_windows()

# -------------------------------
# 3. OS Detection & Mapping
# -------------------------------

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
    elif sys.platform.startswith("freebsd") or sys.platform.startswith("openbsd") or sys.platform.startswith("netbsd"):
        return "bsd", ""
    elif "nix" in sys.platform.lower():
        return "nix", ""
    elif sys.platform == "win32":
        os_name = platform.system().lower()
        version = platform.release().lower()
        return os_name, version
    else:
        # Attempt fallback
        return platform.system().lower(), ""

def map_os_to_docker_image(os_name, version):
    """
    Map the detected OS to a recommended Docker base image.
    For the web container scenario, we try to pick a minimal base image that might have a built-in server.
    We'll do best-effort. 
    """
    # For demonstration, we reuse the same mapping logic as before, but you can customize further.
    # We disclaim that "matching OS" plus "has built-in web server" is not guaranteed.
    # We'll do the same mapping as before, but we might choose an Alpine-based or busybox-based image if possible.
    
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

    # For "bsd" or "nix", let's just default to "alpine:latest" (best-effort).
    if os_name in ("bsd", "nix"):
        return "alpine:latest"

    # For standard "windows" approach:
    if os_name == "windows":
        for key, img in windows_map.items():
            if key in version:
                return img
        return "mcr.microsoft.com/windows/servercore:ltsc2019"

    # Otherwise assume some Linux distribution
    # Attempt to parse distro name from os_name
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
# 4. Container Launch & Integrity Checking
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
# 5. Web Container with Integrated ModSecurity WAF
# -------------------------------

def deploy_web_with_waf():
    """
    Deploy a web container (matching host OS) with integrated ModSecurity WAF.
    1. Detect the OS, map to a base image for the web container.
    2. Attempt to run a minimal built-in web server if possible (python -m http.server, busybox httpd, etc.).
    3. Launch a ModSecurity container as reverse proxy on port 80 -> web container's port 8080 (or 80).
    """
    check_all_dependencies()
    
    # Detect OS for the main web container
    os_name, version = detect_os()
    base_image = map_os_to_docker_image(os_name, version)
    print(f"[INFO] Detected OS: {os_name} (Version: {version}). Main web container base image: {base_image}")
    
    # Pull required images
    pull_docker_image(base_image)
    waf_image = "owasp/modsecurity-crs:nginx"
    pull_docker_image(waf_image)
    
    # Create a dedicated network
    network_name = "ccdc-web-net"
    try:
        subprocess.check_call(["docker", "network", "inspect", network_name],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[INFO] Docker network '{network_name}' already exists.")
    except subprocess.CalledProcessError:
        print(f"[INFO] Creating Docker network '{network_name}'.")
        subprocess.check_call(["docker", "network", "create", network_name])
    
    # Ask user for container names, ports
    web_container = input("Enter the main web container name (default 'web_container'): ").strip() or "web_container"
    waf_container = input("Enter the ModSecurity proxy container name (default 'modsec2-nginx'): ").strip() or "modsec2-nginx"
    host_web_port = input("Enter host port for the web container (default '8080'): ").strip() or "8080"
    host_waf_port = input("Enter host port for the WAF (default '80'): ").strip() or "80"
    
    # Attempt to pick a built-in server command based on the base image
    # We'll guess a minimal approach. If we find python in the base image, we run python -m http.server ...
    # Otherwise we try busybox httpd, or a Windows powershell approach, etc.
    # This is best-effort. Real usage might require custom images with pre-installed servers.
    
    user = "nonroot" if os_name == "windows" else "nobody"
    
    # Compose a minimal server command:
    if os_name == "windows":
        # We'll attempt powershell approach
        # This is purely illustrative
        server_cmd = "powershell.exe -Command \"Write-Host 'Starting minimal web server...'; while($true){echo 'HTTP/1.1 200 OK`r`n`r`nHello from Windows Container' | nc -l -p 80}\""
        container_port = "80"
    else:
        # On Linux/bsd/nix, try python3 -m http.server 80, fallback to busybox httpd
        # We'll do python approach first
        server_cmd = "/bin/sh -c 'which python3 && python3 -m http.server 80 || (which busybox && busybox httpd -f -p 80 || echo \"No built-in server found\" && sleep infinity)'"
        container_port = "80"
    
    # Launch web container
    try:
        print(f"[INFO] Launching web container '{web_container}' with a minimal built-in server (best-effort).")
        subprocess.check_call([
            "docker", "run", "-d",
            "--read-only",
            "--user", user,
            "--name", web_container,
            "--network", network_name,
            "-p", f"{host_web_port}:{container_port}",
            base_image,
            "sh", "-c", server_cmd
        ])
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not launch main web container '{web_container}': {e}")
        sys.exit(1)
    
    # Next, launch the WAF container
    tz = os.environ.get("TZ", "UTC")
    waf_env = [
        "PORT=8080",
        "PROXY=1",
        f"BACKEND=http://{web_container}:{container_port}",
        "MODSEC_RULE_ENGINE=off",
        "BLOCKING_PARANOIA=2",
        f"TZ={tz}",
        "MODSEC_TMP_DIR=/tmp",
        "MODSEC_RESP_BODY_ACCESS=On",
        "MODSEC_RESP_BODY_MIMETYPE=text/plain text/html text/xml application/json",
        "COMBINED_FILE_SIZES=65535"
    ]
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
    
    print(f"[INFO] Deployment complete. The web container '{web_container}' is running on container port {container_port} (mapped to host port {host_web_port}).")
    print(f"[INFO] The ModSecurity proxy '{waf_container}' is listening on host port {host_waf_port} and forwarding to '{web_container}:{container_port}'.")

# -------------------------------
# 6. Interactive Menu
# -------------------------------

def interactive_menu():
    """Display an interactive menu for the user to choose an operation."""
    print("==== CCDC OS-to-Container & Integrity Tool ====")
    print("Select an option:")
    print("1. Install & Configure Container (match OS, read-only, non-root)")
    print("2. Run Continuous Integrity Check (restore on changes)")
    print("3. Deploy OS-based Web Container + Integrated ModSecurity WAF")
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
        check_all_dependencies()
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
        print("[MODE 3] Deploying OS-based Web Container + Integrated ModSecurity WAF...")
        deploy_web_with_waf()
    else:
        print("[ERROR] Invalid option. Exiting.")
        sys.exit(1)

# -------------------------------
# 7. Main Entry Point
# -------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="CCDC OS-to-Container & Integrity Tool: Auto-installs Docker if missing, matches OS for container, and integrates WAF."
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
