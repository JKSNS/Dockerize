#!/usr/bin/env python3
"""
dockerize_website_only.py

Automatically:
1) Checks/installs Docker & Docker Compose (best effort).
2) Copies critical web directories into a Docker build context,
   ignoring permission errors so the script won't fail if some files are restricted.
3) Creates a Docker image that runs Apache (httpd) in read-only mode as non-root.
4) Connects to the host's existing database (no separate DB container).
"""

import sys
import platform
import subprocess
import argparse
import os
import shutil
import stat

# ------------------------------
# 1. Docker & Compose Installation
# ------------------------------

def detect_linux_package_manager():
    for pm in ["apt", "apt-get", "dnf", "yum", "zypper"]:
        if shutil.which(pm):
            return pm
    return None

def attempt_install_docker_linux():
    pm = detect_linux_package_manager()
    if not pm:
        print("[ERROR] No recognized package manager found on Linux. Cannot auto-install Docker.")
        return False
    print(f"[INFO] Attempting to install Docker using '{pm}' on Linux...")
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"
    env["TZ"] = "America/Denver"
    try:
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
            print(f"[ERROR] Package manager '{pm}' not fully supported for auto-installation.")
            return False
        print("[INFO] Docker installation attempt completed.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Auto-installation of Docker failed: {e}")
        return False

def fix_docker_group():
    try:
        current_user = os.getlogin()
    except:
        current_user = os.environ.get("USER", "unknown")
    print(f"[INFO] Adding user '{current_user}' to docker group.")
    try:
        subprocess.check_call(["sudo", "usermod", "-aG", "docker", current_user])
    except subprocess.CalledProcessError as e:
        print(f"[WARN] Could not add user to docker group: {e}")
    # Attempt to enable Docker
    if platform.system().lower().startswith("linux"):
        try:
            subprocess.check_call(["sudo", "systemctl", "enable", "docker"])
            subprocess.check_call(["sudo", "systemctl", "start", "docker"])
        except subprocess.CalledProcessError as e:
            print(f"[WARN] Could not enable/start docker service: {e}")
    print("[INFO] Re-executing script under 'sg docker' to activate group membership.")
    os.environ["DOCKER_GROUP_FIX"] = "1"
    script_path = os.path.abspath(sys.argv[0])
    script_args = sys.argv[1:]
    cmd = ["sg", "docker", "-c", f'export DOCKER_GROUP_FIX=1; exec "{sys.executable}" "{script_path}" ' + " ".join(f'"{arg}"' for arg in script_args)]
    os.execvp("sg", cmd)

def can_run_docker():
    try:
        subprocess.check_call(["docker", "ps"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except:
        return False

def ensure_docker_installed():
    if "DOCKER_GROUP_FIX" in os.environ:
        if can_run_docker():
            print("[INFO] Docker is accessible now.")
            return
        else:
            print("[ERROR] Docker still not accessible after group fix.")
            sys.exit(1)
    docker_path = shutil.which("docker")
    if docker_path and can_run_docker():
        print("[INFO] Docker is installed and accessible.")
        return
    sysname = platform.system().lower()
    if sysname.startswith("linux"):
        installed = attempt_install_docker_linux()
        if not installed:
            print("[ERROR] Could not auto-install Docker. Please install manually.")
            sys.exit(1)
        if not can_run_docker():
            fix_docker_group()
        else:
            print("[INFO] Docker is installed and accessible on Linux now.")
    else:
        print(f"[ERROR] Docker not found or not accessible on '{sysname}'. Please install manually.")
        sys.exit(1)

def attempt_install_docker_compose_linux():
    pm = detect_linux_package_manager()
    if not pm:
        print("[ERROR] No recognized package manager found. Cannot auto-install Docker Compose.")
        return False
    print(f"[INFO] Attempting to install Docker Compose using '{pm}' on Linux...")
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"
    env["TZ"] = "America/Denver"
    try:
        if pm in ("apt", "apt-get"):
            subprocess.check_call(["sudo", pm, "update", "-y"], env=env)
            subprocess.check_call(["sudo", pm, "install", "-y", "docker-compose"], env=env)
        elif pm in ("yum", "dnf"):
            subprocess.check_call(["sudo", pm, "-y", "install", "docker-compose"], env=env)
        elif pm == "zypper":
            subprocess.check_call(["sudo", "zypper", "refresh"], env=env)
            subprocess.check_call(["sudo", "zypper", "--non-interactive", "install", "docker-compose"], env=env)
        else:
            print(f"[ERROR] Package manager '{pm}' not fully supported for Docker Compose auto-install.")
            return False
        print("[INFO] Docker Compose installation completed.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Auto-installation of Docker Compose failed: {e}")
        return False

def check_docker_compose():
    try:
        subprocess.check_call(["docker-compose", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("[INFO] Docker Compose is installed.")
    except:
        print("[WARN] Docker Compose not found. Attempting auto-install on Linux.")
        sysname = platform.system().lower()
        if sysname.startswith("linux"):
            installed = attempt_install_docker_compose_linux()
            if installed:
                try:
                    subprocess.check_call(["docker-compose", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print("[INFO] Docker Compose installed successfully.")
                except:
                    print("[ERROR] Docker Compose still not available after install attempt.")
            else:
                print("[ERROR] Could not auto-install Docker Compose. Please install manually.")
        else:
            print("[ERROR] Docker Compose not found, and auto-install not supported on this platform.")

# ------------------------------
# 2. Permission-Ignoring Copy
# ------------------------------

def copy_dir_recursive(src, dst):
    """
    Recursively copy src->dst, skipping files if we get PermissionError.
    This ensures we won't fail on restricted directories (e.g., /var/lib/mysql).
    """
    if not os.path.isdir(dst):
        os.makedirs(dst, exist_ok=True)
    for root, dirs, files in os.walk(src):
        rel_path = os.path.relpath(root, src)
        target_dir = os.path.join(dst, rel_path)
        if not os.path.exists(target_dir):
            try:
                os.makedirs(target_dir, exist_ok=True)
            except PermissionError:
                print(f"[WARN] Permission denied creating dir '{target_dir}'. Skipping.")
                continue
        for f in files:
            source_file = os.path.join(root, f)
            target_file = os.path.join(target_dir, f)
            try:
                shutil.copy2(source_file, target_file)
            except PermissionError:
                print(f"[WARN] Permission denied reading '{source_file}'. Skipping.")
            except OSError as e:
                print(f"[WARN] Could not copy '{source_file}': {e}")

# ------------------------------
# 3. Containerize Website Only
# ------------------------------

def containerize_website_only():
    """
    Copies typical Apache/PHP directories, builds a Docker image that runs read-only + non-root,
    and connects to the existing host DB (no DB container). 
    """
    ensure_docker_installed()
    check_docker_compose()

    # Directories we want to copy:
    directories_to_copy = {
        "var_lib_mysql": "/var/lib/mysql",
        "etc_httpd": "/etc/httpd",
        "etc_apache2": "/etc/apache2",
        "var_www_html": "/var/www/html",
        "etc_php": "/etc/php",
        "etc_ssl": "/etc/ssl",
        "var_log_apache2": "/var/log/apache2",
        "var_log_httpd": "/var/log/httpd"
    }

    build_context = "website_build_context"
    if os.path.exists(build_context):
        print(f"[INFO] Removing old build context '{build_context}'.")
        shutil.rmtree(build_context)
    os.makedirs(build_context)

    # We'll track which subdirs we actually copy
    copied_subdirs = []
    for subdir, src in directories_to_copy.items():
        if os.path.exists(src):
            dst_subdir = os.path.join(build_context, subdir)
            print(f"[INFO] Copying '{src}' => '{dst_subdir}' (ignoring permission errors).")
            copy_dir_recursive(src, dst_subdir)
            copied_subdirs.append(subdir)
        else:
            print(f"[WARN] Directory '{src}' does not exist. Skipping.")

    # Generate COPY lines only for subdirs we actually copied
    copy_lines = []
    for subdir in copied_subdirs:
        if subdir == "var_lib_mysql":
            copy_lines.append("COPY var_lib_mysql/ /var/lib/mysql/")
        elif subdir == "etc_httpd":
            copy_lines.append("COPY etc_httpd/ /etc/httpd/")
        elif subdir == "etc_apache2":
            copy_lines.append("COPY etc_apache2/ /etc/apache2/")
        elif subdir == "var_www_html":
            copy_lines.append("COPY var_www_html/ /var/www/html/")
        elif subdir == "etc_php":
            copy_lines.append("COPY etc_php/ /etc/php/")
        elif subdir == "etc_ssl":
            copy_lines.append("COPY etc_ssl/ /etc/ssl/")
        elif subdir == "var_log_apache2":
            copy_lines.append("COPY var_log_apache2/ /var/log/apache2/")
        elif subdir == "var_log_httpd":
            copy_lines.append("COPY var_log_httpd/ /var/log/httpd/")

    # DB environment variables: connect to host's DB
    db_host = input("Enter the host DB address (default 'localhost'): ").strip() or "localhost"
    db_user = input("Enter DB user (default 'root'): ").strip() or "root"
    db_password = input("Enter DB password (default 'root'): ").strip() or "root"
    db_name = input("Enter DB name (default 'mydb'): ").strip() or "mydb"

    # We'll embed them as environment variables, in case the site checks them
    # (Though you'd typically pass them at runtime. Adjust as needed.)
    env_lines = f"""
ENV DB_HOST={db_host}
ENV DB_USER={db_user}
ENV DB_PASS={db_password}
ENV DB_NAME={db_name}
"""

    # Create a Dockerfile
    dockerfile_path = os.path.join(build_context, "Dockerfile")
    with open(dockerfile_path, "w") as f:
        f.write(f"""FROM ubuntu:20.04

# Noninteractive
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=America/Denver

RUN apt-get update && \\
    apt-get install -y apache2 \\
                      libapache2-mod-php \\
                      php \\
                      php-mysql \\
                      ca-certificates && \\
    apt-get clean && \\
    rm -rf /var/lib/apt/lists/*

# Copy any directories we found
""")
        for line in copy_lines:
            f.write(line + "\n")

        f.write(env_lines)

        # Expose typical web port
        f.write("""
EXPOSE 80

# If using Debian/Ubuntu's apache2:
CMD ["apache2ctl", "-D", "FOREGROUND"]
""")

    print("[INFO] Dockerfile created. Building image...")

    image_name = input("Enter the Docker image name (default 'website_readonly'): ").strip() or "website_readonly"
    try:
        subprocess.check_call(["docker", "build", "-t", image_name, build_context])
        print(f"[INFO] Docker image '{image_name}' built successfully.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Docker build failed: {e}")
        sys.exit(1)

    # Automatically run the container in read-only + non-root
    container_name = input("Enter container name (default 'website_container'): ").strip() or "website_container"
    print("[INFO] Launching container in read-only + non-root mode.")
    cmd = [
        "docker", "run", "-d",
        "--read-only",
        "--user", "nobody",
        "--name", container_name,
        "-p", "8080:80",  # Map host port 8080 => container port 80
        image_name
    ]
    try:
        subprocess.check_call(cmd)
        print(f"[INFO] Container '{container_name}' is now running in read-only mode.")
        print(f"[INFO] Access your site on http://localhost:8080 (adjust the port as needed).")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not run container '{container_name}': {e}")

# ------------------------------
# 4. Main
# ------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Auto Dockerize a website in read-only mode, ignoring permission errors, using host DB."
    )
    parser.add_argument("--run", action="store_true", help="Run the containerization process immediately")
    args = parser.parse_args()
    if args.run:
        containerize_website_only()
    else:
        print("Usage: Run the script with '--run' to containerize the website automatically.")
        print("Example: python3 dockerize_website_only.py --run")

if __name__ == "__main__":
    main()
