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
   - Attempts to run a minimal built-in web server in read-only mode (best-effort).
   - Launches a ModSecurity-enabled reverse proxy container as well.

Usage (Interactive Menu):
  Run the script with the '--menu' flag:
    python3 ccdc_integrity_tool.py --menu

Notes:
  - If Docker is missing or the user can’t run `docker`, the script tries to fix it automatically:
    * Installs Docker (best-effort) on Linux, BSD, or Nix
    * Adds the user to the 'docker' group
    * Re-executes itself under `sg docker -c "..."` so the group membership is effective
  - This avoids dropping you into a new shell prompt as `newgrp` does.
  - The logic is best-effort and may fail on less common distros or OSes.
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
# 1. Docker Auto-Installation & Group-Fix Logic
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
        if pm in ("apt", "apt-get"):
            subprocess.check_call(["sudo", pm, "update", "-y"])
            subprocess.check_call(["sudo", pm, "install", "-y", "docker.io"])
        elif pm in ("yum", "dnf"):
            subprocess.check_call(["sudo", pm, "-y", "install", "docker"])
            subprocess.check_call(["sudo", "systemctl", "enable", "docker"])
            subprocess.check_call(["sudo", "systemctl", "start", "docker"])
        elif pm == "zypper":
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
    """Attempt to install Docker on BSD using 'pkg' (best-effort)."""
    pkg_path = shutil.which("pkg")
    if not pkg_path:
        print("[ERROR] 'pkg' not found. Cannot auto-install Docker on BSD.")
        return False
    print("[INFO] Attempting to install Docker using 'pkg' on BSD (best-effort).")
    try:
        subprocess.check_call(["sudo", "pkg", "update"])
        subprocess.check_call(["sudo", "pkg", "install", "-y", "docker"])
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Auto-installation of Docker on BSD failed: {e}")
        return False

def attempt_install_docker_nix():
    """Attempt to install Docker on Nix-based systems using 'nix-env -i docker' (very best-effort)."""
    nixenv_path = shutil.which("nix-env")
    if not nixenv_path:
        print("[ERROR] 'nix-env' not found. Cannot auto-install Docker on Nix.")
        return False
    print("[INFO] Attempting to install Docker using 'nix-env -i docker' on Nix.")
    try:
        subprocess.check_call(["sudo", "nix-env", "-i", "docker"])
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Auto-installation of Docker on Nix failed: {e}")
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

    # On Linux, attempt to enable/start Docker
    if platform.system().lower().startswith("linux"):
        try:
            subprocess.check_call(["sudo", "systemctl", "enable", "docker"])
            subprocess.check_call(["sudo", "systemctl", "start", "docker"])
        except subprocess.CalledProcessError as e:
            print(f"[WARN] Could not enable/start docker service: {e}")

    # Re-exec with 'sg docker' to avoid dropping user into an interactive shell
    print("[INFO] Re-executing script under 'sg docker' to activate group membership.")
    os.environ["CCDC_DOCKER_GROUP_FIX"] = "1"  # Avoid infinite loops
    script_path = os.path.abspath(sys.argv[0])
    script_args = sys.argv[1:]
    # Build a command line to pass to sg
    # We'll also pass environment variable to skip redoing group fix
    # e.g. "export CCDC_DOCKER_GROUP_FIX=1 && python3 /path/to/script --menu"
    command_line = f'export CCDC_DOCKER_GROUP_FIX=1; exec "{sys.executable}" "{script_path}" ' + " ".join(f'"{arg}"' for arg in script_args)
    cmd = ["sg", "docker", "-c", command_line]
    os.execvp("sg", cmd)

def ensure_docker_installed():
    """
    Check if Docker is installed & if the user can run it.
    If missing, attempt auto-install. If the user isn't in docker group, fix that, then re-exec with sg.
    """
    if "CCDC_DOCKER_GROUP_FIX" in os.environ:
        # Already tried group fix once. Let's see if we can run docker now.
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

    # If not installed or not accessible, try installing
    sysname = platform.system().lower()
    if sysname.startswith("linux"):
        installed = attempt_install_docker_linux()
        if not installed:
            print("[ERROR] Could not auto-install Docker on Linux. Please install it manually.")
            sys.exit(1)
        # Now see if we can run docker
        if not can_run_docker():
            fix_docker_group()
        else:
            print("[INFO] Docker is installed and accessible on Linux now.")
    elif "bsd" in sysname:
        installed = attempt_install_docker_bsd()
        if not installed:
            print("[ERROR] Could not auto-install Docker on BSD. Please install it manually.")
            sys.exit(1)
        if not can_run_docker():
            fix_docker_group()
        else:
            print("[INFO] Docker is installed and accessible on BSD now.")
    elif "nix" in sysname:
        installed = attempt_install_docker_nix()
        if not installed:
            print("[ERROR] Could not auto-install Docker on Nix. Please install manually.")
            sys.exit(1)
        if not can_run_docker():
            fix_docker_group()
        else:
            print("[INFO] Docker is installed and accessible on Nix now.")
    elif sysname == "windows":
        print("[ERROR] Docker not found, and auto-install is not supported on Windows. Please install Docker or Docker Desktop manually.")
        sys.exit(1)
    else:
        print(f"[ERROR] Unrecognized system '{sysname}'. Docker is missing. Please install it manually.")
        sys.exit(1)

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

def check_docker_compose():
    """Check if Docker Compose is installed (warn if not)."""
    try:
        subprocess.check_call(["docker-compose", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("[INFO] Docker Compose is installed.")
    except Exception:
        print("[WARN] Docker Compose not found. Some orchestration features may be unavailable.")

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
        # assume some Linux distro
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

def run_generic_container(os_name, base_image, container_name="generic_container"):
    """Launch a generic interactive container from the base image in read-only mode, non-root."""
    user = "nonroot" if os_name == "windows" else "nobody"
    shell_cmd = "cmd.exe" if os_name == "windows" else "/bin/bash"
    try:
        print(f"[INFO] Launching interactive container '{container_name}' from image '{base_image}' as user '{user}' in read-only mode.")
        subprocess.check_call([
            "docker", "run", "-it",
            "--read-only",
            "--user", user,
            "--name", container_name,
            base_image,
            shell_cmd
        ])
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not launch container '{container_name}': {e}")

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

# -------------------------------------------------
# 5. Web Container with Integrated ModSecurity WAF
# -------------------------------------------------

def deploy_web_with_waf():
    """
    Deploy a web container (matching host OS) with integrated ModSecurity WAF.
    The web container is a minimal OS-based container that tries to run a built-in web server in read-only mode.
    The WAF container is 'owasp/modsecurity-crs:nginx'.
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
    
    # Attempt to pick a built-in server command
    user = "nonroot" if os_name == "windows" else "nobody"
    if os_name == "windows":
        server_cmd = "powershell.exe -Command \"Write-Host 'Starting minimal web server...'; while($true){echo 'HTTP/1.1 200 OK`r`n`r`nHello from Windows Container' | nc -l -p 80}\""
        container_port = "80"
    else:
        server_cmd = "/bin/sh -c 'which python3 && python3 -m http.server 80 || (which busybox && busybox httpd -f -p 80 || echo \"No server found\" && sleep infinity)'"
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

# -------------------------------------------------
# 6. Interactive Menu
# -------------------------------------------------

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

# -------------------------------------------------
# 7. Main Entry Point
# -------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="CCDC OS-to-Container & Integrity Tool: auto-installs Docker if missing, matches OS for container, integrates WAF."
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
