#!/bin/bash
# deploy_modsec_waf.sh
# This script installs Docker (if not present), configures it,
# and deploys a Dockerized ModSecurity Web Application Firewall (WAF)
# with a high-security configuration intended for cyber defense competitions.
#
# It supports multiple Linux distributions (CentOS, Ubuntu, Debian, Fedora, etc.),
# detects the package manager, installs Docker, sets permissions,
# verifies the installation, deploys a container with a hardened ModSecurity config,
# and logs to /var/log/modsec.
#
# Ensure you run this script with root or via sudo for package installations.

set -euo pipefail

#####################
# Utility Functions #
#####################

# Function: log_msg
# Purpose: Uniform logging to stdout and optionally to syslog.
log_msg() {
    local msg="$1"
    echo "[INFO] $msg"
    # Optionally, write to syslog:
    # logger -t deploy_modsec_waf "$msg"
}

# Retry wrapper function
retry() {
    local -r -i max_attempts="${2:-3}"
    local -i attempt_num=1
    until "$1"; do
        if (( attempt_num == max_attempts )); then
            echo "Command failed after ${attempt_num} attempts." >&2
            return 1
        fi
        log_msg "Attempt ${attempt_num} failed; retrying..."
        sleep 2
        ((attempt_num++))
    done
}

#############################
# Distribution Detection    #
#############################

# Function: detect_distro
# Purpose: Identify the Linux distribution and version
detect_distro() {
    if [ -e /etc/os-release ]; then
        . /etc/os-release
        DISTRO_ID=${ID,,}
        DISTRO_VERSION=${VERSION_ID}
    elif command -v lsb_release > /dev/null 2>&1; then
        DISTRO_ID=$(lsb_release -si | tr '[:upper:]' '[:lower:]')
        DISTRO_VERSION=$(lsb_release -sr)
    else
        echo "Unable to determine Linux distribution." >&2
        exit 1
    fi
    log_msg "Detected distribution: $DISTRO_ID $DISTRO_VERSION"
}

###############################
# Package Manager Determination
###############################

# Function: get_pkg_manager
# Purpose: Set a PACKAGE_MANAGER variable based on the distro
get_pkg_manager() {
    if command -v apt-get >/dev/null; then
        PACKAGE_MANAGER="apt-get"
    elif command -v dnf >/dev/null; then
        PACKAGE_MANAGER="dnf"
    elif command -v yum >/dev/null; then
        PACKAGE_MANAGER="yum"
    elif command -v zypper >/dev/null; then
        PACKAGE_MANAGER="zypper"
    elif command -v pacman >/dev/null; then
        PACKAGE_MANAGER="pacman"
    else
        echo "No known package manager found." >&2
        exit 1
    fi
    log_msg "Using package manager: $PACKAGE_MANAGER"
}

###############################
# Docker Installation         #
###############################

install_docker() {
    if command -v docker >/dev/null 2>&1; then
        log_msg "Docker is already installed."
        return 0
    fi

    log_msg "Installing Docker..."
    case "$PACKAGE_MANAGER" in
        apt-get)
            # Update package list and install prerequisites
            apt-get update
            apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release
            # Add Docker’s official GPG key and repository
            curl -fsSL https://download.docker.com/linux/$(. /etc/os-release; echo "$ID")/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
            echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/$(. /etc/os-release; echo "$ID") $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list
            apt-get update
            apt-get install -y docker-ce docker-ce-cli containerd.io
            ;;
        dnf|yum)
            # Install required packages and add Docker repo if needed
            $PACKAGE_MANAGER install -y yum-utils device-mapper-persistent-data lvm2
            yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
            $PACKAGE_MANAGER install -y docker-ce docker-ce-cli containerd.io
            ;;
        zypper)
            zypper install -y docker
            ;;
        pacman)
            pacman -Sy --noconfirm docker
            ;;
        *)
            echo "Unsupported package manager: $PACKAGE_MANAGER" >&2
            exit 1
            ;;
    esac

    systemctl enable docker
    systemctl start docker
    log_msg "Docker installed and started."
}

#####################################
# Docker Permissions Configuration  #
#####################################

configure_docker_permissions() {
    # Add the current user to the docker group (if not already a member)
    if ! groups "$USER" | grep -q '\bdocker\b'; then
        log_msg "Adding user '$USER' to the docker group."
        usermod -aG docker "$USER"
        # Attempt to reload the group membership in the current session.
        # Note: newgrp docker will spawn a new shell; in many cases, re-login is recommended.
        newgrp docker <<'EOF'
log_msg "Docker group refreshed. Please re-run the script if docker is not recognized."
EOF
    else
        log_msg "User already in docker group."
    fi
}

#####################################
# Docker Verification              #
#####################################

verify_docker() {
    log_msg "Verifying Docker installation with hello-world container..."
    if ! retry "docker run --rm hello-world"; then
        echo "Docker verification failed. Exiting." >&2
        exit 1
    fi
    log_msg "Docker verification succeeded."
}

#####################################
# Prepare ModSecurity Configuration #
#####################################

prepare_modsec_config() {
    # Create configuration directory for ModSecurity logs and config if not existing.
    CONFIG_DIR="/etc/modsec"
    LOG_DIR="/var/log/modsec"
    mkdir -p "$CONFIG_DIR" "$LOG_DIR"

    CONFIG_FILE="$CONFIG_DIR/modsecurity.conf"

    # Create or modify a hardened ModSecurity configuration file
    # You can expand these rules; here we include minimal directives
    log_msg "Creating hardened ModSecurity configuration at $CONFIG_FILE"
    cat > "$CONFIG_FILE" <<'EOF'
# Basic ModSecurity Configuration - Hardened for Cyber Defense
SecRuleEngine On
SecRequestBodyAccess On
SecResponseBodyAccess On
SecResponseBodyMimeType text/plain text/html text/xml
SecAuditEngine RelevantOnly
SecAuditLogRelevantStatus "^(?:5|4(?!04))"
SecAuditLogParts ABIJDEFHZ
SecAuditLogType Concurrent
SecAuditLog /var/log/modsec/audit.log

# Maximum paranoia configuration (Paranoia Level 4)
# Enable all optional rules, anomaly scoring, strict rule checks, and evasion protection.
IncludeOptional /usr/local/modsecurity-crs/base_rules/*.conf
# Example settings, adjust according to your environment:
SecDefaultAction "phase:1,log,auditlog,deny,status:403"
SecDefaultAction "phase:2,log,auditlog,deny,status:403"
SecParanoiaLevel 4
EOF
}

#####################################
# Deploy ModSecurity WAF Container  #
#####################################

deploy_waf_container() {
    # Pull a Dockerized ModSecurity image.
    # Replace "modsecurity/modsecurity:legacy" with your chosen image/tag that supports older OS or dependencies.
    IMAGE_NAME="modsecurity/modsecurity:legacy"

    log_msg "Pulling ModSecurity Docker image ($IMAGE_NAME)..."
    docker pull "$IMAGE_NAME"

    # Run container configuration:
    # - Bind host port 8080 to container port 80 (adjust as necessary)
    # - Mount the hardened configuration file and log directory.
    # - Apply resource constraints (example: 256 MB memory, 0.5 CPU)
    # - Set to restart unless manually stopped.
    CONTAINER_NAME="modsec-waf"
    log_msg "Starting $CONTAINER_NAME container..."
    docker run -d \
      --name "$CONTAINER_NAME" \
      -p 8080:80 \
      -v "$LOG_DIR":/var/log/modsec \
      -v "/etc/modsec/modsecurity.conf":/etc/modsecurity/modsecurity.conf:ro \
      --restart unless-stopped \
      --memory "256m" \
      --cpus "0.5" \
      "$IMAGE_NAME"
}

#####################
# Main Script Flow  #
#####################

log_msg "Starting deployment of Dockerized ModSecurity WAF..."
detect_distro
get_pkg_manager
install_docker
configure_docker_permissions
verify_docker
prepare_modsec_config
deploy_waf_container
log_msg "Deployment complete. The ModSecurity WAF container is running and logging to /var/log/modsec."
