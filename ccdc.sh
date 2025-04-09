#!/usr/bin/env bash
# Bash script to deploy a Dockerized ModSecurity WAF with OWASP CRS on various Linux distributions.
# It installs Docker if not present, configures Docker permissions, and runs a ModSecurity container
# with high-security settings (Paranoia Level 4, strict rules, logging enabled).

set -e  # Exit immediately if a command exits with a non-zero status (for safety).

# --- Section 1: Detect Linux distribution and version, and select package manager ---
echo "[*] Detecting Linux distribution and package manager..."

# Initialize variables for distribution and version
OS=""        # OS family (e.g., ubuntu, centos, debian, fedora, opensuse, arch, etc.)
OS_VERSION=""  # Version number or ID (if available)
PM=""        # Package manager command (apt, yum, dnf, zypper, pacman, etc.)

# Try to source /etc/os-release if available (this is the standard on modern Linux)
if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    OS="${ID:-}"
    OS_VERSION="${VERSION_ID:-}"
elif type lsb_release >/dev/null 2>&1; then
    # Fallback to lsb_release for older systems
    OS="$(lsb_release -si | tr '[:upper:]' '[:lower:]')"
    OS_VERSION="$(lsb_release -sr)"
elif [[ -f /etc/redhat-release ]]; then
    # For very old Red Hat/CentOS (like CentOS 6) which may not have os-release
    OS="redhat"
    OS_VERSION="$(grep -oE '[0-9]+' /etc/redhat-release | head -1)"
elif [[ -f /etc/debian_version ]]; then
    # Old Debian without lsb_release
    OS="debian"
    OS_VERSION="$(cat /etc/debian_version)"
fi

# Normalize OS names for known variants
case "$OS" in
    redhat*|centos|rocky|almalinux) OS="centos" ;;  # treat RedHat-compatible as "centos"
    fedora) OS="fedora" ;;
    debian) OS="debian" ;;
    ubuntu) OS="ubuntu" ;;
    opensuse*|suse|sles) OS="suse" ;;  # openSUSE or SUSE Enterprise
    arch|manjaro) OS="arch" ;;
esac

# Select package manager based on OS or available commands
if command -v apt-get >/dev/null 2>&1; then
    PM="apt"
elif command -v dnf >/dev/null 2>&1; then
    PM="dnf"
elif command -v yum >/dev/null 2>&1; then
    PM="yum"
elif command -v zypper >/dev/null 2>&1; then
    PM="zypper"
elif command -v pacman >/dev/null 2>&1; then
    PM="pacman"
fi

echo "Detected OS: $OS $OS_VERSION, using package manager: $PM"

# --- Section 2: Install Docker Engine using appropriate method for the OS ---
echo "[*] Installing Docker Engine..."

if [[ "$OS" == "centos" && ${OS_VERSION%%.*} -lt 7 ]]; then
    # Special case: CentOS/RHEL 6 (Docker CE no longer officially supports it)
    # Enable EPEL repository and install the older 'docker-io' package from there
    echo "CentOS 6 detected - installing docker-io from EPEL repository"
    yum install -y epel-release || true  # Install EPEL (ignore if already installed)
    yum install -y docker-io || {
        echo "ERROR: Failed to install Docker on CentOS 6. Exiting."
        exit 1
    }
else
    case "$PM" in
        apt)
            # Update package list and install Docker (for Debian/Ubuntu)
            # If official docker-ce packages are available for this OS, prefer them; otherwise use fallback docker.io
            apt-get update -y
            # Install prerequisites for using Docker's repository (if apt-add-repository needed)
            apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release
            
            # Add Docker's official GPG key and repository
            if [[ "$OS" == "ubuntu" || "$OS" == "debian" ]]; then
                # Determine codename for Debian/Ubuntu
                CODENAME="$( (lsb_release -sc 2>/dev/null) || echo "" )"
                # Fallback for older Debian without lsb_release: use generic names or skip if unknown
                [[ -z "$CODENAME" && "$OS" == "debian" ]] && CODENAME="stable" 
                curl -fsSL https://download.docker.com/linux/$OS/gpg | apt-key add -
                echo "deb [arch=$(dpkg --print-architecture)] https://download.docker.com/linux/$OS $CODENAME stable" > /etc/apt/sources.list.d/docker.list
                apt-get update -y
                # Try installing Docker CE (Community Edition)
                if apt-get install -y docker-ce docker-ce-cli containerd.io; then
                    DOCKER_INSTALLED=1
                fi
            fi
            # Fallback to installing 'docker.io' from the distro repository if docker-ce failed or not available
            if [[ -z "${DOCKER_INSTALLED:-}" ]]; then
                apt-get install -y docker.io || {
                    echo "ERROR: Docker installation failed via apt. Exiting."
                    exit 1
                }
            fi
            ;;
        yum)
            # For CentOS/RHEL 7+, or Amazon Linux
            yum install -y yum-utils 2>/dev/null || true   # Install yum-utils if available (for yum-config-manager)
            # Add Docker repo for CentOS/RHEL
            yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo || {
                # If yum-config-manager is not available, manually add repo file
                cat >/etc/yum.repos.d/docker-ce.repo <<'REPO'
[docker-ce-stable]
name=Docker CE Stable - $basearch
baseurl=https://download.docker.com/linux/centos/$releasever/$basearch/stable
enabled=1
gpgcheck=1
gpgkey=https://download.docker.com/linux/centos/gpg
REPO
            }
            # Install Docker CE
            yum install -y docker-ce docker-ce-cli containerd.io || {
                echo "ERROR: Docker installation via yum failed. Exiting."
                exit 1
            }
            ;;
        dnf)
            # For Fedora or CentOS 8/9 which use dnf
            dnf install -y dnf-plugins-core 2>/dev/null || true
            dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo || true
            dnf install -y docker-ce docker-ce-cli containerd.io || {
                echo "ERROR: Docker installation via dnf failed. Exiting."
                exit 1
            }
            ;;
        zypper)
            # openSUSE/SLES
            zypper --non-interactive refresh
            zypper --non-interactive install docker || {
                echo "ERROR: Docker installation via zypper failed. Exiting."
                exit 1
            }
            ;;
        pacman)
            # Arch Linux/Manjaro
            pacman -Sy --noconfirm docker || {
                echo "ERROR: Docker installation via pacman failed. Exiting."
                exit 1
            }
            ;;
        *)
            # If we reach here, no known package manager was found
            echo "ERROR: Unsupported OS or package manager ($PM). Cannot install Docker."
            exit 1
            ;;
    esac
fi

# Ensure Docker service is enabled and started
echo "[*] Enabling and starting Docker service..."
if command -v systemctl >/dev/null 2>&1; then
    systemctl enable docker.service || true
    systemctl start docker.service
else
    # SysV init fallback
    service docker start
    # Enable service at boot (SysV or Upstart)
    command -v chkconfig >/dev/null 2>&1 && chkconfig docker on || true
fi

# --- Section 3: Docker post-installation: configure permissions for current user ---
# Add the current user to the 'docker' group so Docker can be used without sudo
if id -nG "$(whoami)" | grep -qw docker; then
    echo "[*] User '$(whoami)' is already in the docker group."
else
    USER_TO_CONFIG="${SUDO_USER:-${USER}}"
    if [[ "$USER_TO_CONFIG" != "root" && -n "$USER_TO_CONFIG" ]]; then
        echo "[*] Adding user '$USER_TO_CONFIG' to docker group for non-root Docker usage."
        usermod -aG docker "$USER_TO_CONFIG"
        # Apply new group membership immediately using newgrp or su
        if [[ -n "$SUDO_USER" ]]; then
            # Re-run the remainder of the script as the original user with new docker group
            exec sudo -u "$SUDO_USER" -g docker -- bash -c "echo '[*] Reloading shell with docker group...'; $0 --post-user-setup"
        else
            # If not run via sudo (e.g., already root login), just use newgrp
            exec newgrp docker <<EOF
bash "$0" --post-user-setup
EOF
        fi
    fi
fi

# If script is re-invoked with the flag --post-user-setup, skip installation steps (already done)
if [[ "$1" == "--post-user-setup" ]]; then
    echo "[*] Docker group membership applied for user '${USER}'. Continuing..."
fi

# --- Section 4: Verify Docker installation with a test container ---
echo "[*] Verifying Docker installation by running hello-world test..."
if ! docker run --rm hello-world >/dev/null 2>&1; then
    echo "WARNING: Docker test (hello-world) failed. Retrying once..."
    sleep 3
    if ! docker run --rm hello-world; then
        echo "ERROR: Docker does not appear to be functioning correctly. Please check the installation."
        exit 1
    fi
fi
echo "[*] Docker is installed and working."

# --- Section 5: Pull a secure ModSecurity WAF Docker image (with OWASP CRS) ---
# Choose a Docker image that includes ModSecurity + OWASP Core Rule Set.
# We use the official OWASP CRS project image (with Nginx + ModSecurity v3) for broad compatibility and security.
WAF_IMAGE="owasp/modsecurity-crs:nginx"  # latest stable Nginx-based ModSecurity CRS image
echo "[*] Pulling WAF Docker image: $WAF_IMAGE ..."
docker pull "$WAF_IMAGE"

# --- Section 6: Prepare hardened ModSecurity configuration (Paranoia Level 4, strict settings) ---
echo "[*] Creating ModSecurity CRS configuration with maximum security settings..."
MODSEC_DIR="/etc/modsecurity"            # local host directory to store modsecurity config
MODSEC_CRS_CONF="$MODSEC_DIR/crs-setup.conf"
mkdir -p "$MODSEC_DIR"

# Generate a custom crs-setup.conf that sets Paranoia Level 4 and other security tweaks
cat > "$MODSEC_CRS_CONF" << 'EOF'
# Hardened OWASP CRS configuration generated by script
# Setting Paranoia Level to 4 (highest, most strict) for maximum security&#8203;:contentReference[oaicite:4]{index=4}
SecAction "id:900000, phase:1, pass, t:none, nolog, setvar:tx.paranoia_level=4"

# For CRS v3.x, above is sufficient. For CRS v4.x (newer), also set blocking and detection paranoia separately:
SecAction "id:900001, phase:1, pass, t:none, nolog, setvar:tx.blocking_paranoia_level=4, setvar:tx.detection_paranoia_level=4"

# Enforce URLENCODED body processor for all content types to prevent evasions&#8203;:contentReference[oaicite:5]{index=5}
SecAction "id:900010, phase:1, pass, t:none, nolog, setvar:tx.enforce_bodyproc_urlencoded=1"

# Enable UTF8 encoding validation to catch malicious encoding tricks
SecAction "id:900011, phase:1, pass, t:none, nolog, setvar:tx.crs_validate_utf8_encoding=1"

# Set anomaly scoring thresholds (optional tweak for strictness)
SecAction "id:900020, phase:1, pass, t:none, nolog, \
    setvar:tx.inbound_anomaly_score_threshold=5, setvar:tx.outbound_anomaly_score_threshold=4"

# Note: Paranoia Level 4 will activate all available rule sets (including optional ones) for maximum coverage.
# These settings may cause false positives and should be adjusted with caution.
EOF

# This custom crs-setup.conf will be mounted into the container to override default CRS settings.
# (We placed all required high-security directives here to auto-enable strict rules.)

# --- Section 7: Run the ModSecurity WAF container with high-security config and resource constraints ---
echo "[*] Launching the ModSecurity WAF container..."
WAF_CONTAINER_NAME="modsecurity_waf"
HOST_PORT=${WAF_HOST_PORT:-80}   # Host port for WAF to listen on (defaults to 80, can be overridden by env var)

# Ensure log directory exists on host for ModSecurity logs
LOG_DIR="/var/log/modsec"
mkdir -p "$LOG_DIR"

# Run the Docker container with appropriate options:
docker run -d \
    --name "$WAF_CONTAINER_NAME" \
    --restart unless-stopped \
    -p "$HOST_PORT:80" \
    -v "$MODSEC_CRS_CONF:/etc/modsecurity.d/owasp-crs/crs-setup.conf:ro" \
    -v "$LOG_DIR:/var/log/modsecurity:Z" \
    -e MODSEC_AUDIT_LOG=/var/log/modsecurity/audit.log \
    -e MODSEC_AUDIT_LOG_FORMAT=JSON \
    -e MODSEC_AUDIT_ENGINE=RelevantOnly \
    "$WAF_IMAGE"

# Explanation of options:
# -d: run container in background (detached)
# --restart unless-stopped: auto-restart WAF on failure or reboot, until explicitly stopped
# -p $HOST_PORT:80: bind container's port 80 (WAF listening) to a host port
# -v $MODSEC_CRS_CONF:/etc/...:ro : bind-mount our hardened CRS config file into the container (read-only) at the appropriate location (overrides default crs-setup.conf)
# -v $LOG_DIR:/var/log/modsecurity:Z : mount host log directory into container (the :Z label is for SELinux compatibility if applicable)
# -e MODSEC_AUDIT_LOG, MODSEC_AUDIT_LOG_FORMAT, MODSEC_AUDIT_ENGINE: environment variables to configure ModSecurity logging.
#    Here we log audits to file (inside container at /var/log/modsecurity/audit.log, which is on host via bind mount), in JSON format, and use 'RelevantOnly' mode to log only suspicious requests (you can set 'On' for all requests if needed).
# $WAF_IMAGE: the chosen ModSecurity+CRS image.

# Apply resource constraints for security (optional strict limits):
docker update --memory="1g" --cpus="1.0" "$WAF_CONTAINER_NAME" >/dev/null 2>&1 || true
# (Limits the container to 1 GB RAM and 1 CPU core to prevent abuse; adjust as needed.)

echo "[+] ModSecurity WAF container '$WAF_CONTAINER_NAME' deployed. Listening on port $HOST_PORT."
echo "[+] Paranoia Level 4 with full OWASP CRS rules enabled. Logs are available at $LOG_DIR."
