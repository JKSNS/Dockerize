#!/usr/bin/env python3
import os
import sys
import platform
import shutil
import subprocess

# -------------------------------------------------
# 0. Root/Administrator Check
# -------------------------------------------------
def ensure_run_as_root():
    """
    On Linux/macOS, check if EUID != 0. If so, fail and prompt to rerun with sudo.
    On Windows, there's no direct concept of EUID, so we skip.
    """
    if os.name == "posix":
        # We only check this on Unix-like systems
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            print("[ERROR] This script must be run as root (or with sudo).")
            print("Please re-run with sudo or switch to root user.")
            sys.exit(1)
    else:
        # On Windows, we won't forcibly check. 
        # If you want to require Admin on Windows, you'd need a different approach.
        pass

# -------------------------------------------------
# Utility: detect Linux package manager, install Docker
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
    """
    Attempt to install Docker Compose on Linux (best effort).
    Uses the detected package manager similar to Docker auto-install logic.
    """
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
    """Return True if we can run 'docker ps' without error, else False."""
    try:
        subprocess.check_call(["docker", "ps"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except:
        return False

def fix_docker_group():
    """
    Attempt to add the current user to the 'docker' group, enable & start Docker,
    then re-execute the script under 'sg docker' to apply the new group membership.
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
    """
    Check if Docker is installed & if the user can run it.
    If missing, attempt auto-install. If the user isn't in the docker group, fix that.
    """
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
            print("[ERROR] Could not auto-install Docker on Linux. Please install it manually.")
            sys.exit(1)
        if not can_run_docker():
            fix_docker_group()
        else:
            print("[INFO] Docker is installed and accessible on Linux now.")
    elif "bsd" in sysname:
        print("[ERROR] Docker auto-install is not implemented for BSD. Please install manually.")
        sys.exit(1)
    elif "nix" in sysname:
        print("[ERROR] Docker auto-install is not implemented for Nix. Please install manually.")
        sys.exit(1)
    elif sysname == "windows":
        print("[ERROR] Docker not found, and auto-install is not supported on Windows. Please install Docker or Docker Desktop manually.")
        sys.exit(1)
    else:
        print(f"[ERROR] Unrecognized system '{sysname}'. Docker is missing. Please install it manually.")
        sys.exit(1)

def check_docker_compose():
    """Check if Docker Compose is installed. If not, try to auto-install on Linux."""
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
                    print("[ERROR] Docker Compose still not available after attempted install.")
            else:
                print("[ERROR] Could not auto-install Docker Compose on Linux. Please install manually.")
        else:
            print("[ERROR] Docker Compose not found, and auto-install is only supported on Linux. Please install manually.")

def check_python_version(min_major=3, min_minor=7):
    """Ensure Python 3.7+ is being used."""
    if sys.version_info < (min_major, min_minor):
        print(f"[ERROR] Python {min_major}.{min_minor}+ is required. You are running {sys.version_info.major}.{sys.version_info.minor}.")
        sys.exit(1)
    else:
        print(f"[INFO] Python version check passed: {sys.version_info.major}.{sys.version_info.minor}.")

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
    ensure_run_as_root()         # <-- Ensure running as root/sudo on Unix
    check_python_version(3, 7)
    ensure_docker_installed()
    check_docker_compose()
    check_wsl_if_windows()

# -------------------------------------------------
# OS Detection & Docker Image Mapping
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
        "centos": {
            "6": "centos:6",
            "7": "centos:7",
            "8": "centos:8",
            "9": "centos:stream9",
            "": "ubuntu:latest"
        },
        "ubuntu": {
            "14": "ubuntu:14.04",
            "16": "ubuntu:16.04",
            "18": "ubuntu:18.04",
            "20": "ubuntu:20.04",
            "22": "ubuntu:22.04"
        },
        "debian": {
            "7": "debian:7",
            "8": "debian:8",
            "9": "debian:9",
            "10": "debian:10",
            "11": "debian:11",
            "12": "debian:12"
        },
        "fedora": {
            "25": "fedora:25",
            "26": "fedora:26",
            "27": "fedora:27",
            "28": "fedora:28",
            "29": "fedora:29",
            "30": "fedora:30",
            "31": "fedora:31",
            "35": "fedora:35"
        },
        "opensuse leap": {
            "15": "opensuse/leap:15"
        },
        "opensuse tumbleweed": {
            "": "opensuse/tumbleweed"
        },
        "linux": {
            "": "ubuntu:latest"
        }
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
        # Assume a Linux distro
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
# 1. Comprehensive Option
#    Build a new image that includes host website files, then run read-only.
# -------------------------------------------------

def build_and_run_readonly_container(base_image):
    """
    1) Create a container from the base image (writable).
    2) Copy in host website directories.
    3) (Optional) Install a web server if desired.
    4) Commit the container as a new image (with website files).
    5) Remove the temporary container.
    6) Run the new image in read-only mode, non-root user, start the web server.
    """

    # Common website directories to copy from host
    website_files = {
        "var_lib_mysql": "/var/lib/mysql",
        "etc_httpd": "/etc/httpd",
        "etc_apache2": "/etc/apache2",
        "var_www_html": "/var/www/html",
        "etc_php": "/etc/php",
        "etc_ssl": "/etc/ssl",
        "var_log_apache2": "/var/log/apache2",
        "var_log_httpd": "/var/log/httpd"
    }

    # 1) Create a stopped container (so we can copy files in)
    print(f"[INFO] Creating a temporary container from '{base_image}'...")
    create_cmd = ["docker", "create", base_image, "bash", "-c", "sleep infinity"]
    try:
        container_id = subprocess.check_output(create_cmd).decode().strip()
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to create container from image {base_image}: {e}")
        return None

    print(f"[INFO] Temporary container ID: {container_id}")

    # 2) Copy website files from host to container
    for label, host_path in website_files.items():
        if os.path.exists(host_path):
            print(f"[INFO] Found '{host_path}'. Copying into container '{container_id}'...")
            cp_cmd = ["docker", "cp", host_path, f"{container_id}:{host_path}"]
            try:
                subprocess.check_call(cp_cmd)
                print(f"[INFO] Successfully copied '{host_path}' to container.")
            except subprocess.CalledProcessError as e:
                print(f"[ERROR] Failed to copy '{host_path}' to container: {e}")
        else:
            print(f"[WARN] Path '{host_path}' not found on host. Skipping.")

    # 3) (Optional) Start container, install a web server if not present
    #    We'll do a simple check: if 'apt-get' is in the container, assume Debian/Ubuntu and install 'apache2'
    #    If 'yum' or 'dnf' is present, install 'httpd'. If 'zypper' is present, install 'apache2'.
    #    This is just an example. 
    print("[INFO] Installing a web server in the container (best-effort).")
    subprocess.check_call(["docker", "start", container_id])

    # Helper function to check if a command exists in container
    def container_has_cmd(cid, cmd):
        test_cmd = ["docker", "exec", cid, "sh", "-c", f"command -v {cmd}"]
        return (subprocess.run(test_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0)

    installed = False
    if container_has_cmd(container_id, "apt-get"):
        print("[INFO] Detected apt-get. Installing Apache2...")
        try:
            subprocess.check_call(["docker", "exec", container_id, "apt-get", "update"])
            subprocess.check_call(["docker", "exec", container_id, "apt-get", "install", "-y", "apache2"])
            installed = True
        except subprocess.CalledProcessError:
            pass
    elif container_has_cmd(container_id, "dnf"):
        print("[INFO] Detected dnf. Installing httpd...")
        try:
            subprocess.check_call(["docker", "exec", container_id, "dnf", "-y", "install", "httpd"])
            installed = True
        except subprocess.CalledProcessError:
            pass
    elif container_has_cmd(container_id, "yum"):
        print("[INFO] Detected yum. Installing httpd...")
        try:
            subprocess.check_call(["docker", "exec", container_id, "yum", "-y", "install", "httpd"])
            installed = True
        except subprocess.CalledProcessError:
            pass
    elif container_has_cmd(container_id, "zypper"):
        print("[INFO] Detected zypper. Installing apache2...")
        try:
            subprocess.check_call(["docker", "exec", container_id, "zypper", "refresh"])
            subprocess.check_call(["docker", "exec", container_id, "zypper", "--non-interactive", "install", "apache2"])
            installed = True
        except subprocess.CalledProcessError:
            pass

    if not installed:
        print("[WARN] Could not auto-install a web server (or it might already be installed).")

    # Stop container before committing
    subprocess.check_call(["docker", "stop", container_id])

    # 4) Commit container as new image
    new_image = "my_web_app_image"
    print(f"[INFO] Committing container '{container_id}' as image '{new_image}'...")
    try:
        subprocess.check_call(["docker", "commit", container_id, new_image])
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to commit container as new image: {e}")
        return None

    # 5) Remove the temporary container
    print(f"[INFO] Removing temporary container '{container_id}'...")
    subprocess.check_call(["docker", "rm", container_id])

    # 6) Run the new image in read-only mode, as non-root, then start the web server
    uid = os.getuid() if hasattr(os, "getuid") else 1000
    gid = os.getgid() if hasattr(os, "getgid") else 1000
    final_container_name = "web_app_container"
    print(f"[INFO] Running final container '{final_container_name}' from image '{new_image}' in read-only mode...")
    run_cmd = [
        "docker", "run", "-d",
        "--name", final_container_name,
        "--read-only",
        "--user", f"{uid}:{gid}",
        "-p", "80:80",  # Forward host port 80 to container port 80 for web access
        new_image,
        "sleep", "infinity"
    ]
    subprocess.check_call(run_cmd)

    # Attempt to start Apache or httpd in background
    print("[INFO] Attempting to start Apache/httpd in the final container...")
    # Check if /etc/apache2 or /etc/httpd is present, or simply try commands
    if container_has_cmd(final_container_name, "apache2ctl"):
        subprocess.run(["docker", "exec", "-d", final_container_name, "apache2ctl", "-DFOREGROUND"])
        print("[INFO] Started Apache2 in background.")
    elif container_has_cmd(final_container_name, "httpd"):
        subprocess.run(["docker", "exec", "-d", final_container_name, "httpd", "-DFOREGROUND"])
        print("[INFO] Started httpd in background.")
    else:
        print("[WARN] No known web server command found. Please start your web server manually.")

    print("[INFO] Done. Your container is running in read-only mode with your host web files baked in.")


# -------------------------------------------------
# 2. Menu Options
# -------------------------------------------------

def option_comprehensive():
    """
    Option 1: 
    - Check prerequisites
    - Detect host OS -> map to Docker image
    - Pull the base image
    - Build a new image (with host web files), then run it read-only
    """
    print("Running comprehensive steps...")
    check_all_dependencies()
    os_name, version = detect_os()
    print(f"[INFO] Detected OS: {os_name} Version: {version}")
    image = map_os_to_docker_image(os_name, version)
    print(f"[INFO] Mapped Docker image: {image}")

    # Pull the Docker image
    print(f"[INFO] Pulling Docker image: {image}")
    try:
        subprocess.check_call(["docker", "pull", image])
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to pull Docker image {image}: {e}")
        return

    build_and_run_readonly_container(image)

def option_pull_docker():
    """
    Option 2: Pull the related Docker container (just detects OS and pulls).
    """
    print("Pulling related Docker container...")
    os_name, version = detect_os()
    print(f"[INFO] Detected OS: {os_name} Version: {version}")
    image = map_os_to_docker_image(os_name, version)
    print(f"[INFO] Mapped Docker image: {image}")
    try:
        subprocess.check_call(["docker", "pull", image])
        print(f"[INFO] Docker image '{image}' pulled successfully.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to pull Docker image {image}: {e}")

def option_copy_website_files():
    """
    Option 3: 
    Just copies the known website-related files from the host to a specified container.
    This is for a user who already has a container running and wants to copy files in.
    NOTE: This will fail if the container is read-only. 
    """
    website_files = {
        "var_lib_mysql": "/var/lib/mysql",
        "etc_httpd": "/etc/httpd",
        "etc_apache2": "/etc/apache2",
        "var_www_html": "/var/www/html",
        "etc_php": "/etc/php",
        "etc_ssl": "/etc/ssl",
        "var_log_apache2": "/var/log/apache2",
        "var_log_httpd": "/var/log/httpd"
    }
    container_id = input("Enter the Docker container name or ID to copy files into: ").strip()
    if not container_id:
        print("[ERROR] No container provided.")
        return

    for label, path in website_files.items():
        if os.path.exists(path):
            print(f"[INFO] Found '{path}'. Copying to container '{container_id}'...")
            try:
                subprocess.check_call(["docker", "cp", path, f"{container_id}:{path}"])
                print(f"[INFO] Successfully copied '{path}' to container.")
            except subprocess.CalledProcessError as e:
                print(f"[ERROR] Failed to copy '{path}' to container: {e}")
        else:
            print(f"[WARN] Path '{path}' not found on host. Skipping.")

# -------------------------------------------------
# Main Menu
# -------------------------------------------------

def main_menu():
    while True:
        print("\nMenu:")
        print("1: Comprehensive (build new read-only container with host website files)")
        print("2: Pull related Docker container only")
        print("3: Copy website-related files into an existing container")
        print("4: Exit")
        choice = input("Enter your choice: ").strip()
        if choice == "1":
            option_comprehensive()
        elif choice == "2":
            option_pull_docker()
        elif choice == "3":
            option_copy_website_files()
        elif choice == "4":
            print("Exiting.")
            sys.exit(0)
        else:
            print("Invalid choice. Please try again.")

if __name__ == "__main__":
    main_menu()
