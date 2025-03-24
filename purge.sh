#!/bin/bash
# Docker Removal Script - Comprehensive cleanup of Docker components
# Run with sudo: sudo bash docker_removal.sh

# Exit on any error
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

# Check if script is run with sudo
if [ "$(id -u)" -ne 0 ]; then
    echo "[ERROR] This script must be run with sudo privileges."
    echo "Please run: sudo bash $0"
    exit 1
fi

PM=$(detect_linux_package_manager)

###############################################################################
# FUNCTION: uninstall_docker_packages
###############################################################################
uninstall_docker_packages() {
  echo "[INFO] Uninstalling Docker packages..."
  if [ -n "$PM" ]; then
    case "$PM" in
      apt-get)
        apt-get purge -y docker-ce docker-ce-cli containerd.io docker-compose-plugin docker.io docker-engine docker-ce-rootless-extras docker-scan-plugin || true
        apt-get autoremove -y
        ;;
      yum)
        yum remove -y docker-ce docker-ce-cli containerd.io docker-compose-plugin docker docker-engine docker-common || true
        ;;
      dnf)
        dnf remove -y docker-ce docker-ce-cli containerd.io docker-compose-plugin docker docker-engine || true
        ;;
      zypper)
        zypper remove -y docker-ce docker-ce-cli containerd.io docker-compose-plugin docker || true
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

###############################################################################
# FUNCTION: remove_docker_data
###############################################################################
remove_docker_data() {
  echo "[INFO] Removing Docker data and configuration files..."
  
  # Remove only known Docker directories and files
  rm -rf /var/lib/docker || true
  rm -rf /etc/docker || true
  rm -f /etc/apparmor.d/docker || true
  rm -f /var/run/docker.sock || true
  rm -f /usr/local/bin/com.docker.cli || true
  rm -f /usr/bin/docker-compose || true
  rm -f /usr/local/bin/docker-compose || true
  
  # Remove Docker Desktop related files (if present on Linux)
  rm -rf ~/.docker || true
  
  # Add additional explicit paths if necessary, but avoid generic recursive searches
  echo "[INFO] Docker data and configuration files removed."
  return 0
}

###############################################################################
# FUNCTION: remove_docker_group
###############################################################################
remove_docker_group() {
  echo "[INFO] Removing Docker group..."
  if getent group docker >/dev/null; then
    groupdel docker || true
    echo "[INFO] Docker group removed."
  else
    echo "[INFO] Docker group does not exist."
  fi
  return 0
}

###############################################################################
# FUNCTION: remove_docker_services
###############################################################################
remove_docker_services() {
  echo "[INFO] Removing Docker service files..."
  systemctl stop docker.socket 2>/dev/null || true
  systemctl stop docker 2>/dev/null || true
  systemctl disable docker.socket 2>/dev/null || true
  systemctl disable docker 2>/dev/null || true
  
  # Remove specific service files
  rm -rf /etc/systemd/system/docker.service.d 2>/dev/null || true
  rm -f /etc/systemd/system/docker.socket 2>/dev/null || true
  rm -f /etc/systemd/system/multi-user.target.wants/docker.service 2>/dev/null || true
  rm -f /etc/systemd/system/multi-user.target.wants/docker.socket 2>/dev/null || true
  rm -f /lib/systemd/system/docker.service 2>/dev/null || true
  rm -f /lib/systemd/system/docker.socket 2>/dev/null || true
  
  # Reload systemd to apply changes
  systemctl daemon-reload 2>/dev/null || true
  systemctl reset-failed 2>/dev/null || true
  
  echo "[INFO] Docker service files removed."
  return 0
}

###############################################################################
# FUNCTION: clean_package_cache
###############################################################################
clean_package_cache() {
  echo "[INFO] Cleaning package manager cache..."
  if [ -n "$PM" ]; then
    case "$PM" in
      apt-get)
        apt-get clean
        ;;
      yum)
        yum clean all
        ;;
      dnf)
        dnf clean all
        ;;
      zypper)
        zypper clean
        ;;
    esac
  fi
  echo "[INFO] Package manager cache cleaned."
  return 0
}

###############################################################################
# MAIN EXECUTION
###############################################################################
print_banner "Starting Docker Removal Process"

# Attempt to uninstall Docker packages
uninstall_docker_packages

# Remove Docker data, configs, and related files
remove_docker_data

# Remove Docker group
remove_docker_group

# Remove Docker service files
remove_docker_services

# Clean package cache
clean_package_cache

print_banner "Docker Removal Complete"
echo "[INFO] Docker and related components have been purged from the system."
echo "[INFO] You may need to reboot your system for all changes to take effect."
