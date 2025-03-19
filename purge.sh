#!/bin/bash
set -e

# Detect package manager
PM=$(detect_linux_package_manager)

# Uninstall Docker packages
uninstall_docker_packages() {
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
  return 0
}

# Remove data directories, configs, and related files
remove_docker_data() {
  sudo rm -rf /var/lib/docker
  sudo rm -rf /etc/docker
  sudo rm -f /etc/apparmor.d/docker
  sudo rm -rf /var/run/docker.sock
  sudo rm -rf /usr/local/bin/com.docker.cli
  sudo rm -rf /usr/bin/docker-compose # Remove Compose binary if it exists
  sudo find / -name '*docker*' -print0 | sudo xargs -0 rm -rf
  return 0
}

# Remove Docker group
remove_docker_group() {
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
  sudo systemctl stop docker || true
  sudo systemctl disable docker || true
  sudo rm -rf /etc/systemd/system/docker.service.d
  sudo rm -rf /etc/systemd/system/docker.socket
  sudo rm -rf /etc/systemd/system/multi-user.target.wants/docker.service
  sudo rm -rf /etc/systemd/system/multi-user.target.wants/docker.socket
  sudo rm -rf /lib/systemd/system/docker.service
  sudo rm -rf /lib/systemd/system/docker.socket
  sudo systemctl daemon-reload || true
  return 0
}

# Main execution
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
