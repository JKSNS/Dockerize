#!/usr/bin/env python3

import sys
import platform
import subprocess
import argparse
import os
import hashlib
import time
import shutil

def detect_linux_package_manager():
    for pm in ["apt", "apt-get", "dnf", "yum", "zypper"]:
        if shutil.which(pm):
            return pm
    return None

def group_exists(group_name):
    try:
        subprocess.check_call(["getent", "group", group_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False

def user_in_group(username, group_name):
    try:
        groups_output = subprocess.check_output(["groups", username], text=True)
        return group_name in groups_output.split()
    except:
        return False

def create_docker_group_if_missing():
    if not group_exists("docker"):
        try:
            subprocess.check_call(["sudo", "groupadd", "docker"])
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Could not create 'docker' group: {e}")
            return False
    return True

def add_user_to_docker_group(username):
    if user_in_group(username, "docker"):
        return True
    try:
        subprocess.check_call(["sudo", "usermod", "-aG", "docker", username])
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not add user '{username}' to 'docker' group: {e}")
        return False

def attempt_docker_service_reload():
    try:
        subprocess.check_call(["sudo", "systemctl", "daemon-reload"])
        subprocess.check_call(["sudo", "systemctl", "restart", "docker"])
        subprocess.check_call(["sudo", "systemctl", "is-active", "--quiet", "docker"])
        print("[INFO] Docker service is active after forced reload/restart.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Docker service still failing after reload/restart: {e}")

def enable_and_start_docker_service():
    if shutil.which("systemctl"):
        try:
            subprocess.check_call(["sudo", "systemctl", "enable", "docker"])
            subprocess.check_call(["sudo", "systemctl", "start", "docker"])
        except subprocess.CalledProcessError as e:
            print(f"[WARN] Could not enable/start Docker service via systemd: {e}")
            attempt_docker_service_reload()
    else:
        print("[WARN] systemctl not found. If on WSL or non-systemd distro, start Docker manually.")

def attempt_install_docker_linux():
    pm = detect_linux_package_manager()
    if not pm:
        print("[ERROR] No recognized package manager found on Linux.")
        return False
    try:
        env = os.environ.copy()
        env["DEBIAN_FRONTEND"] = "noninteractive"
        env["TZ"] = "America/Denver"
        if pm in ("apt", "apt-get"):
            subprocess.check_call(["sudo", pm, "update", "-y"], env=env)
            subprocess.check_call(["sudo", pm, "install", "-y", "docker.io"], env=env)
        elif pm in ("yum", "dnf"):
            subprocess.check_call(["sudo", pm, "-y", "install", "docker"], env=env)
        elif pm == "zypper":
            subprocess.check_call(["sudo", "zypper", "refresh"], env=env)
            subprocess.check_call(["sudo", "zypper", "--non-interactive", "install", "docker"], env=env)
        else:
            return False
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Auto-installation of Docker failed: {e}")
        return False
    if not create_docker_group_if_missing():
        return False
    try:
        current_user = os.getlogin()
    except:
        current_user = os.environ.get("USER", "unknown")
    if not add_user_to_docker_group(current_user):
        return False
    enable_and_start_docker_service()
    return True

def attempt_install_docker_compose_linux():
    pm = detect_linux_package_manager()
    if not pm:
        return False
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
            return False
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Auto-installation of Docker Compose failed: {e}")
        return False

def can_run_docker():
    try:
        subprocess.check_call(["docker", "ps"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except:
        return False

def reexec_with_docker_group():
    print("[INFO] Re-executing script under 'sg docker'.")
    os.environ["CCDC_DOCKER_GROUP_FIX"] = "1"
    script_path = os.path.abspath(sys.argv[0])
    script_args = sys.argv[1:]
    command_line = f'export CCDC_DOCKER_GROUP_FIX=1; exec "{sys.executable}" "{script_path}" ' + " ".join(f'"{arg}"' for arg in script_args)
    cmd = ["sg", "docker", "-c", command_line]
    os.execvp("sg", cmd)

def ensure_docker_installed():
    if "CCDC_DOCKER_GROUP_FIX" in os.environ:
        if can_run_docker():
            return
        else:
            sys.exit(1)
    if shutil.which("docker") and can_run_docker():
        if not group_exists("docker"):
            create_docker_group_if_missing()
        try:
            current_user = os.getlogin()
        except:
            current_user = os.environ.get("USER", "unknown")
        add_user_to_docker_group(current_user)
        enable_and_start_docker_service()
        return
    else:
        sysname = platform.system().lower()
        if sysname.startswith("linux"):
            if not attempt_install_docker_linux():
                sys.exit(1)
            if not can_run_docker():
                reexec_with_docker_group()
        elif "bsd" in sysname or "nix" in sysname:
            sys.exit(1)
        elif sysname == "windows":
            sys.exit(1)
        else:
            sys.exit(1)

def check_docker_compose():
    try:
        subprocess.check_call(["docker-compose", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        if platform.system().lower().startswith("linux"):
            installed = attempt_install_docker_compose_linux()
            if installed:
                try:
                    subprocess.check_call(["docker-compose", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except:
                    pass
        else:
            pass

def check_python_version(min_major=3, min_minor=7):
    if sys.version_info < (min_major, min_minor):
        sys.exit(1)

def check_wsl_if_windows():
    if platform.system().lower() == "windows":
        try:
            subprocess.check_call(["wsl", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except:
            pass

def check_all_dependencies():
    check_python_version(3, 7)
    ensure_docker_installed()
    check_docker_compose()
    check_wsl_if_windows()

def detect_os():
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
    elif sysname in ["freebsd", "openbsd", "netbsd"]:
        return "bsd", ""
    elif "nix" in sysname:
        return "nix", ""
    elif sysname == "windows":
        return "windows", platform.release().lower()
    else:
        return sysname, ""

def map_os_to_docker_image(os_name, version):
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
        "xp": "legacy-windows/xp:latest",
        "vista": "legacy-windows/vista:latest",
        "7": "legacy-windows/win7:latest",
        "2008": "legacy-windows/win2008:latest",
        "2012": "legacy-windows/win2012:latest",
        "10": "mcr.microsoft.com/windows/nanoserver:1809",
        "2016": "mcr.microsoft.com/windows/servercore:2016",
        "2019": "mcr.microsoft.com/windows/servercore:ltsc2019",
        "2022": "mcr.microsoft.com/windows/servercore:ltsc2022"
    }
    if os_name in ["bsd", "nix"]:
        return "alpine:latest"
    elif os_name == "windows":
        for k, img in windows_map.items():
            if k in version:
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

def pull_docker_image(image):
    try:
        subprocess.check_call(["docker", "pull", image])
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not pull image '{image}': {e}")

def compute_container_hash(container_name):
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
        return hasher.hexdigest()
    except:
        return None

def restore_container_from_snapshot(snapshot_tar, container_name):
    try:
        subprocess.check_call(["docker", "load", "-i", snapshot_tar])
        image_name = os.path.splitext(os.path.basename(snapshot_tar))[0]
        os_name, _ = detect_os()
        user = "nonroot" if os_name == "windows" else "nobody"
        subprocess.check_call(["docker", "run", "-d", "--read-only", "--user", user, "--name", container_name, image_name])
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not restore container '{container_name}': {e}")

def continuous_integrity_check(container_name, snapshot_tar, check_interval=30):
    baseline_hash = compute_container_hash(container_name)
    if not baseline_hash:
        return
    try:
        while True:
            time.sleep(check_interval)
            current_hash = compute_container_hash(container_name)
            if current_hash != baseline_hash:
                subprocess.check_call(["docker", "rm", "-f", container_name])
                restore_container_from_snapshot(snapshot_tar, container_name)
                baseline_hash = compute_container_hash(container_name)
    except KeyboardInterrupt:
        pass

def minimal_integrity_check(container_name, check_interval=30):
    baseline_hash = compute_container_hash(container_name)
    if not baseline_hash:
        return
    try:
        while True:
            time.sleep(check_interval)
            current_hash = compute_container_hash(container_name)
            if current_hash != baseline_hash:
                baseline_hash = current_hash
    except KeyboardInterrupt:
        pass

def container_exists(name):
    try:
        output = subprocess.check_output(["docker", "ps", "-a", "--format", "{{.Names}}"], text=True)
        existing_names = output.split()
        return name in existing_names
    except:
        return False

def prompt_for_container_name(default_name):
    while True:
        name = input(f"Enter container name (default '{default_name}'): ").strip() or default_name
        if not container_exists(name):
            return name
        else:
            choice = input("Options: [R]emove, [C]hoose another, or e[X]it: ").strip().lower()
            if choice == "r":
                try:
                    subprocess.check_call(["docker", "rm", "-f", name])
                    return name
                except:
                    pass
            elif choice == "c":
                continue
            else:
                sys.exit(1)

def maybe_apply_read_only_and_nonroot(cmd_list):
    read_only = input("Run container in secure mode? (y/n) [y]: ").strip().lower() != "n"
    if read_only:
        cmd_list.append("--read-only")
        if not platform.system().lower().startswith("windows"):
            cmd_list.extend(["--user", "nobody"])
    return cmd_list

def stop_local_web_service():
    services = ["apache2", "httpd"]
    for service in services:
        try:
            subprocess.check_call(["sudo", "systemctl", "is-active", "--quiet", service])
            subprocess.check_call(["sudo", "systemctl", "stop", service])
        except:
            pass

def dockerize_web_service_comprehensive():
    check_all_dependencies()
    os_name, version = detect_os()
    base_image = map_os_to_docker_image(os_name, version)
    pm = detect_linux_package_manager()
    install_cmd = ""
    cmd_statement = ""
    if pm in ("apt", "apt-get"):
        install_cmd = (
            "RUN apt-get update && "
            "DEBIAN_FRONTEND=noninteractive TZ=America/Denver "
            "apt-get install -y apache2"
        )
        cmd_statement = 'CMD ["apache2ctl", "-D", "FOREGROUND"]'
    elif pm in ("yum", "dnf"):
        install_cmd = "RUN yum -y install httpd"
        cmd_statement = 'CMD ["/usr/sbin/httpd", "-D", "FOREGROUND"]'
    elif pm == "zypper":
        install_cmd = (
            "RUN zypper refresh && "
            "zypper --non-interactive install apache2"
        )
        cmd_statement = 'CMD ["apache2ctl", "-D", "FOREGROUND"]'
    else:
        install_cmd = (
            "RUN apt-get update && "
            "DEBIAN_FRONTEND=noninteractive TZ=America/Denver "
            "apt-get install -y apache2"
        )
        cmd_statement = 'CMD ["apache2ctl", "-D", "FOREGROUND"]'
    build_context = "web_service_build_context"
    if os.path.exists(build_context):
        shutil.rmtree(build_context)
    os.makedirs(build_context)
    dirs_to_copy = {}
    if os.path.exists("/var/www/html"):
        dirs_to_copy["var_www_html"] = "/var/www/html"
    if os.path.exists("/etc/httpd"):
        dirs_to_copy["etc_httpd"] = "/etc/httpd"
    elif os.path.exists("/etc/apache2"):
        dirs_to_copy["etc_apache2"] = "/etc/apache2"
    if not dirs_to_copy:
        return
    copied = []
    for subdir, src in dirs_to_copy.items():
        dest = os.path.join(build_context, subdir)
        try:
            shutil.copytree(src, dest)
            copied.append(subdir)
        except:
            pass
    dockerfile_path = os.path.join(build_context, "Dockerfile")
    copy_lines = []
    if "var_www_html" in copied:
        copy_lines.append("COPY var_www_html/ /var/www/html/")
    if "etc_httpd" in copied:
        copy_lines.append("COPY etc_httpd/ /etc/httpd/")
    if "etc_apache2" in copied:
        copy_lines.append("COPY etc_apache2/ /etc/apache2/")
    dockerfile_content = f"""FROM {base_image}

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=America/Denver

{install_cmd}
"""
    for line in copy_lines:
        dockerfile_content += line + "\n"
    dockerfile_content += f"""
EXPOSE 80
{cmd_statement}
"""
    with open(dockerfile_path, "w") as f:
        f.write(dockerfile_content)
    image_name = input("Enter the name for the web service image (default 'docker_blueprint'): ").strip() or "docker_blueprint"
    try:
        subprocess.check_call(["docker", "build", "-t", image_name, build_context])
    except:
        return
    stop_local_web_service()
    container_name = prompt_for_container_name("web_app")
    cmd = ["docker", "run", "-d", "--name", container_name, "--read-only"]
    if not platform.system().lower().startswith("windows"):
        cmd.extend(["--user", "nobody"])
    cmd.append(image_name)
    try:
        subprocess.check_call(cmd)
    except:
        pass

def setup_docker_db():
    check_all_dependencies()
    default_db_name = "web_db"
    db_container = prompt_for_container_name(default_db_name)
    volume_opts_db = []
    while True:
        dir_input = input("Enter a directory to mount into the DB container (blank to finish): ").strip()
        if not dir_input:
            break
        volume_opts_db.extend(["-v", f"{dir_input}:{dir_input}"])
    pull_docker_image("mariadb:latest")
    db_password = input("Enter MariaDB root password (default 'root'): ").strip() or "root"
    db_name = input("Enter a DB name to create (default 'mydb'): ").strip() or "mydb"
    cmd = ["docker", "run", "-d", "--name", db_container]
    network_name = input("Enter a Docker network to attach (default 'bridge'): ").strip() or "bridge"
    if network_name != "bridge":
        try:
            subprocess.check_call(["docker", "network", "inspect", network_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except:
            subprocess.check_call(["docker", "network", "create", network_name])
        cmd.extend(["--network", network_name])
    cmd = maybe_apply_read_only_and_nonroot(cmd)
    cmd.extend(volume_opts_db)
    cmd.extend(["-e", f"MYSQL_ROOT_PASSWORD={db_password}", "-e", f"MYSQL_DATABASE={db_name}", "mariadb:latest"])
    try:
        subprocess.check_call(cmd)
    except:
        sys.exit(1)

def setup_docker_waf():
    check_all_dependencies()
    waf_image = "owasp/modsecurity-crs:nginx"
    pull_docker_image(waf_image)
    waf_container = prompt_for_container_name("modsec2-nginx")
    host_waf_port = input("Enter host port for WAF (default '8080'): ").strip() or "8080"
    network_name = input("Enter Docker network to attach (default 'bridge'): ").strip() or "bridge"
    if network_name != "bridge":
        try:
            subprocess.check_call(["docker", "network", "inspect", network_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except:
            subprocess.check_call(["docker", "network", "create", network_name])
        cmd_net = ["--network", network_name]
    else:
        cmd_net = []
    backend_container = input("Enter backend container name or IP (default 'web_app'): ").strip() or "web_app"
    tz = os.environ.get("TZ", "America/Denver")
    waf_env = [
        "PORT=8080",
        "PROXY=1",
        f"BACKEND=http://{backend_container}:80",
        "MODSEC_RULE_ENGINE=on",
        "BLOCKING_PARANOIA=4",
        f"TZ={tz}",
        "MODSEC_TMP_DIR=/tmp",
        "MODSEC_RESP_BODY_ACCESS=On",
        "MODSEC_RESP_BODY_MIMETYPE=text/plain text/html text/xml application/json",
        "COMBINED_FILE_SIZES=65535"
    ]
    cmd = ["docker", "run", "-d", *cmd_net, "--name", waf_container, "-p", f"{host_waf_port}:8080"]
    cmd = maybe_apply_read_only_and_nonroot(cmd)
    for env_var in waf_env:
        cmd.extend(["-e", env_var])
    cmd.append(waf_image)
    try:
        subprocess.check_call(cmd)
    except:
        sys.exit(1)

def toggle_web_container_mode():
    container_name = input("Enter the name of the web service container to toggle: ").strip()
    image_name = input("Enter the image name used for this container: ").strip()
    desired_mode = input("Enter desired mode ('secure' or 'development'): ").strip().lower()
    if desired_mode not in ["secure", "development"]:
        return
    try:
        subprocess.check_call(["docker", "rm", "-f", container_name])
    except:
        return
    cmd = ["docker", "run", "-d", "--name", container_name]
    if desired_mode == "secure":
        cmd.append("--read-only")
        if not platform.system().lower().startswith("windows"):
            cmd.extend(["--user", "nobody"])
    cmd.append(image_name)
    try:
        subprocess.check_call(cmd)
    except:
        pass

def run_integrity_check_menu():
    print("1. Integrity check for a single container")
    print("2. Integrity check for multiple containers")
    choice = input("Choose an option (1/2): ").strip()
    if choice == "1":
        container_name = input("Enter container name: ").strip()
        snapshot_tar = input("Enter path to snapshot (blank to skip): ").strip()
        interval_str = input("Enter check interval (default 30): ").strip()
        try:
            interval = int(interval_str) if interval_str else 30
        except:
            interval = 30
        check_all_dependencies()
        if snapshot_tar:
            continuous_integrity_check(container_name, snapshot_tar, interval)
        else:
            minimal_integrity_check(container_name, interval)
    elif choice == "2":
        try:
            output = subprocess.check_output(["docker", "ps", "--format", "{{.Names}}"], text=True)
            containers = output.split()
            if not containers:
                return
            sel = input("Enter 'all' or comma-separated indexes: ").strip().lower()
            if sel == "all":
                selected = containers
            else:
                indexes = [x.strip() for x in sel.split(",") if x.strip()]
                selected = []
                for i in indexes:
                    try:
                        idx = int(i)
                        if 1 <= idx <= len(containers):
                            selected.append(containers[idx - 1])
                    except:
                        pass
            if not selected:
                return
            interval_str = input("Enter interval (default 30): ").strip()
            try:
                interval = int(interval_str) if interval_str else 30
            except:
                interval = 30
            for name in selected:
                snapshot_tar = input(f"Enter snapshot tar for '{name}' (blank to skip): ").strip()
                if snapshot_tar:
                    continuous_integrity_check(name, snapshot_tar, interval)
                else:
                    minimal_integrity_check(name, interval)
        except:
            pass

def interactive_menu():
    while True:
        print("1. Dockerize Web Service (Comprehensive)")
        print("2. Dockerize Database")
        print("3. Dockerize WAF")
        print("4. Toggle Web Container Mode")
        print("5. Run Continuous Integrity Check")
        print("6. Exit")
        choice = input("Enter your choice (1-6): ").strip()
        if choice == "1":
            dockerize_web_service_comprehensive()
        elif choice == "2":
            setup_docker_db()
        elif choice == "3":
            setup_docker_waf()
        elif choice == "4":
            toggle_web_container_mode()
        elif choice == "5":
            run_integrity_check_menu()
        elif choice == "6":
            sys.exit(0)
        else:
            pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--menu", action="store_true")
    args = parser.parse_args()
    if args.menu:
        interactive_menu()
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
