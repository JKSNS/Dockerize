#!/bin/bash
set -e

###############################################################################
# UTILITY: print_banner
###############################################################################
print_banner() {
    echo "======================================"
    echo "$1"
    echo "======================================"
}

# Detect package manager
detect_linux_package_manager() {
    if command -v apt-get &>/dev/null; then
        echo "apt-get"
    elif command -v apt &>/dev/null; then
        echo "apt-get"
    elif command -v yum &>/dev/null; then
        echo "yum"
    elif command -v dnf &>/dev/null; then
        echo "dnf"
    elif command -v zypper &>/dev/null; then
        echo "zypper"
    else
        return 1
    fi
}

PM=$(detect_linux_package_manager)

# Uninstall Docker packages
uninstall_docker_packages() {
  echo "[INFO] Uninstalling Docker packages..."
  if [ -n "$PM" ]; then
    case "$PM" in
      apt-get)
        sudo apt-get purge -y docker-ce docker-ce-cli containerd.io docker-compose-plugin docker.io
        ;;
      yum)
        sudo yum remove -y docker-ce docker-ce-cli containerd.io docker-compose-plugin docker
        ;;
      dnf)
        sudo dnf remove -y docker-ce docker-ce-cli containerd.io docker-compose-plugin docker
        ;;
      zypper)
        sudo zypper remove -y docker-ce docker-ce-cli containerd.io docker-compose-plugin docker
        ;;
      *)
        echo "[WARN] Unsupported package manager: $PM. Please uninstall Docker packages manually."
        return 1
        ;;
    esac
  else
    echo "[WARN] No package manager detected. Please uninstall Docker packages manually."
    return 1
  fi
  echo "[INFO] Docker packages uninstalled."
  return 0
}

# Remove data directories, configs, and related files
remove_docker_data() {
  echo "[INFO] Removing Docker data and configuration files..."
  sudo rm -rf /var/lib/docker
  sudo rm -rf /etc/docker
  sudo rm -f /etc/apparmor.d/docker
  sudo rm -rf /var/run/docker.sock
  sudo rm -rf /usr/local/bin/com.docker.cli
  sudo rm -rf /usr/bin/docker-compose
  sudo rm -rf /usr/local/bin/docker-compose
  sudo find / -name '*docker*' -print0 | sudo xargs -0 rm -rf
  echo "[INFO] Docker data and configuration files removed."
  return 0
}

# Remove Docker group
remove_docker_group() {
  echo "[INFO] Removing Docker group..."
  if getent group docker >/dev/null; then
    sudo groupdel docker
    echo "[INFO] Docker group removed."
  else
    echo "[INFO] Docker group does not exist."
  fi
  return 0
}

# Remove Docker service files
remove_docker_services() {
  echo "[INFO] Removing Docker service files..."
  sudo systemctl stop docker.socket || true
  sudo systemctl stop docker || true
  sudo systemctl disable docker.socket || true
  sudo systemctl disable docker || true
  sudo rm -rf /etc/systemd/system/docker.service.d
  sudo rm -rf /etc/systemd/system/docker.socket
  sudo rm -rf /etc/systemd/system/multi-user.target.wants/docker.service
  sudo rm -rf /etc/systemd/system/multi-user.target.wants/docker.socket
  sudo rm -rf /lib/systemd/system/docker.service
  sudo rm -rf /lib/systemd/system/docker.socket
  sudo systemctl daemon-reload || true
  sudo systemctl reset-failed || true
  echo "[INFO] Docker service files removed."
  return 0
}

print_banner "Removing Docker"

# Attempt to uninstall Docker packages
uninstall_docker_packages

# Remove Docker data, configs, and related files
remove_docker_data

# Remove Docker group
remove_docker_group

# Remove Docker service files
remove_docker_services

echo "[INFO] Docker and related components have been purged (as best as possible)."
