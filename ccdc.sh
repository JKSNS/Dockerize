#!/usr/bin/env bash
################################################################################
# deploy_modsec_waf.sh
#
# This script deploys a Dockerized ModSecurity Web Application Firewall (WAF)
# using the OWASP ModSecurity CRS Nginx image, with a highly secure configuration.
# The configuration enforces Paranoia Level 4, strict anomaly thresholds, URL
# encoding enforcement, and UTF-8 validation.
#
# The WAF container is configured to run on host port 8080 (by default) so that it
# can protect a website running on port 80. It acts as a reverse proxy by forwarding
# requests to an upstream backend. The default backend is set to:
#   http://172.17.0.1:80
# (This IP is typical of Docker’s default bridge on Linux.)
#
# You can override the default WAF host port by setting WAF_HOST_PORT and the
# backend URL via BACKEND before running the script:
#
#   export WAF_HOST_PORT=8888
#   export BACKEND="http://your.backend.server:80"
#   ./deploy_modsec_waf.sh
#
# The script automatically detects your Linux distribution, installs Docker if needed,
# and configures all required settings.
################################################################################

# --- Ensure the script runs as root ---
if [[ $EUID -ne 0 ]]; then
    if command -v sudo >/dev/null 2>&1; then
        echo "[*] Not running as root. Re-running with sudo..."
        exec sudo bash "$0" "$@"
    else
        echo "[-] ERROR: Please run this script as root (or install sudo)."
        exit 1
    fi
fi

set -e  # Exit immediately on error

echo "[*] Starting Dockerized ModSecurity WAF deployment script..."

###############################################################################
# Section 1: Detect Linux Distribution, Version, and Package Manager
###############################################################################

OS=""
OS_VERSION=""
PM=""

echo "[*] Detecting Linux distribution..."
if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    OS="${ID:-}"
    OS_VERSION="${VERSION_ID:-}"
elif command -v lsb_release >/dev/null 2>&1; then
    OS="$(lsb_release -si | tr '[:upper:]' '[:lower:]')"
    OS_VERSION="$(lsb_release -sr)"
elif [[ -f /etc/redhat-release ]]; then
    OS="centos"
    OS_VERSION="$(grep -oE '[0-9]+' /etc/redhat-release | head -1)"
elif [[ -f /etc/debian_version ]]; then
    OS="debian"
    OS_VERSION="$(cat /etc/debian_version)"
fi

# Normalize OS names for known variants
case "$OS" in
    redhat*|centos|rocky|almalinux) OS="centos" ;;
    fedora) OS="fedora" ;;
    debian) OS="debian" ;;
    ubuntu) OS="ubuntu" ;;
    opensuse*|suse|sles) OS="suse" ;;
    arch|manjaro) OS="arch" ;;
esac

# Determine the package manager
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

echo "[*] Detected OS: $OS $OS_VERSION. Using package manager: $PM"

###############################################################################
# Section 2: Install Docker
###############################################################################

echo "[*] Installing Docker Engine..."
# Special case: Legacy CentOS/RHEL 6 (using docker-io from EPEL)
if [[ "$OS" == "centos" && ${OS_VERSION%%.*} -lt 7 ]]; then
    echo "[*] Legacy CentOS/RHEL 6 detected. Installing docker-io from EPEL..."
    yum install -y epel-release || true
    yum install -y docker-io || {
        echo "[-] ERROR: Docker installation failed on CentOS 6."
        exit 1
    }
else
    case "$PM" in
        apt)
            echo "[*] Using apt-get to install Docker on Debian/Ubuntu..."
            apt-get update -y
            apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release
            if [[ "$OS" == "ubuntu" || "$OS" == "debian" ]]; then
                CODENAME="$( (lsb_release -sc 2>/dev/null) || echo "" )"
                [[ -z "$CODENAME" && "$OS" == "debian" ]] && CODENAME="stable"
                curl -fsSL https://download.docker.com/linux/$OS/gpg | apt-key add -
                echo "deb [arch=$(dpkg --print-architecture)] https://download.docker.com/linux/$OS $CODENAME stable" \
                    > /etc/apt/sources.list.d/docker.list
                apt-get update -y
                if ! apt-get install -y docker-ce docker-ce-cli containerd.io; then
                    echo "[!] Docker CE installation failed. Falling back to 'docker.io'..."
                    apt-get install -y docker.io || {
                        echo "[-] ERROR: Docker installation via apt failed."
                        exit 1
                    }
                fi
            else
                apt-get install -y docker.io || {
                    echo "[-] ERROR: Docker installation via apt failed."
                    exit 1
                }
            fi
            ;;
        yum)
            echo "[*] Using yum to install Docker on CentOS/RHEL..."
            yum install -y yum-utils || true
            yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo || {
                cat >/etc/yum.repos.d/docker-ce.repo <<'EOF'
[docker-ce-stable]
name=Docker CE Stable - $basearch
baseurl=https://download.docker.com/linux/centos/$releasever/$basearch/stable
enabled=1
gpgcheck=1
gpgkey=https://download.docker.com/linux/centos/gpg
EOF
            }
            yum install -y docker-ce docker-ce-cli containerd.io || {
                echo "[-] ERROR: Docker installation via yum failed."
                exit 1
            }
            ;;
        dnf)
            echo "[*] Using dnf to install Docker on Fedora/CentOS 8/9..."
            dnf install -y dnf-plugins-core || true
            dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo || true
            dnf install -y docker-ce docker-ce-cli containerd.io || {
                echo "[-] ERROR: Docker installation via dnf failed."
                exit 1
            }
            ;;
        zypper)
            echo "[*] Using zypper to install Docker on openSUSE/SLES..."
            zypper --non-interactive refresh
            zypper --non-interactive install docker || {
                echo "[-] ERROR: Docker installation via zypper failed."
                exit 1
            }
            ;;
        pacman)
            echo "[*] Using pacman to install Docker on Arch/Manjaro..."
            pacman -Sy --noconfirm docker || {
                echo "[-] ERROR: Docker installation via pacman failed."
                exit 1
            }
            ;;
        *)
            echo "[-] ERROR: No supported package manager found. Cannot install Docker."
            exit 1
            ;;
    esac
fi

echo "[*] Enabling and starting Docker service..."
if command -v systemctl >/dev/null 2>&1; then
    systemctl enable docker.service || true
    systemctl start docker.service
else
    service docker start || true
    command -v chkconfig >/dev/null 2>&1 && chkconfig docker on || true
fi

###############################################################################
# Section 3: Configure Docker Permissions for the Invoking User
###############################################################################

CURRENT_USER="${SUDO_USER:-$USER}"
if id -nG "$CURRENT_USER" | grep -qw docker; then
    echo "[*] User '$CURRENT_USER' is already in the docker group."
else
    echo "[*] Adding user '$CURRENT_USER' to the 'docker' group..."
    usermod -aG docker "$CURRENT_USER"
    echo "[*] Group membership updated. Please re-log or open a new shell for changes to take effect."
fi

###############################################################################
# Section 4: Verify Docker Functionality
###############################################################################

echo "[*] Verifying Docker functionality with 'hello-world'..."
set +e
docker run --rm hello-world >/dev/null 2>&1
TEST_RESULT=$?
set -e
if [[ $TEST_RESULT -ne 0 ]]; then
    echo "[!] 'hello-world' test failed. Retrying..."
    sleep 2
    if ! docker run --rm hello-world >/dev/null 2>&1; then
        echo "[-] ERROR: Docker does not appear to be functioning correctly."
        exit 1
    fi
fi
echo "[*] Docker is installed and functional."

###############################################################################
# Section 5: Pull the Secure ModSecurity WAF Docker Image (OWASP CRS, Nginx)
###############################################################################

WAF_IMAGE="owasp/modsecurity-crs:nginx"
echo "[*] Pulling ModSecurity WAF image: $WAF_IMAGE..."
docker pull "$WAF_IMAGE"

###############################################################################
# Section 6: Create a Hardened ModSecurity CRS Configuration
###############################################################################

MODSEC_DIR="/etc/modsecurity"
MODSEC_CRS_CONF="$MODSEC_DIR/crs-setup.conf"

echo "[*] Generating hardened ModSecurity CRS configuration..."
mkdir -p "$MODSEC_DIR"

cat > "$MODSEC_CRS_CONF" << 'EOF'
# OWASP ModSecurity CRS Hardened Configuration
# Set Paranoia Level to 4 (maximum strictness)
SecAction "id:900000, phase:1, pass, t:none, nolog, setvar:tx.paranoia_level=4"
# For newer CRS versions, also enforce detection and blocking paranoia at level 4
SecAction "id:900001, phase:1, pass, t:none, nolog, setvar:tx.blocking_paranoia_level=4, setvar:tx.detection_paranoia_level=4"
# Enforce URLENCODED body processing to help prevent evasion techniques
SecAction "id:900010, phase:1, pass, t:none, nolog, setvar:tx.enforce_bodyproc_urlencoded=1"
# Validate UTF-8 encoding to catch malicious encoding tactics
SecAction "id:900011, phase:1, pass, t:none, nolog, setvar:tx.crs_validate_utf8_encoding=1"
# Set strict anomaly thresholds for inbound and outbound traffic
SecAction "id:900020, phase:1, pass, t:none, nolog, setvar:tx.inbound_anomaly_score_threshold=5, setvar:tx.outbound_anomaly_score_threshold=4"
EOF

###############################################################################
# Section 7: Check Host Port and Launch the WAF Container
###############################################################################

# Set the host port for the WAF container; defaults to 8080 since the website uses port 80
HOST_PORT="${WAF_HOST_PORT:-8080}"

# Check if the host port is available (using ss or lsof)
if command -v ss >/dev/null 2>&1; then
    if ss -tulpn | grep -q ":$HOST_PORT "; then
        echo "[-] ERROR: TCP port $HOST_PORT is already in use. Free it or set WAF_HOST_PORT to a different port."
        exit 1
    fi
elif command -v lsof >/dev/null 2>&1; then
    if lsof -Pi :$HOST_PORT -sTCP:LISTEN >/dev/null 2>&1; then
        echo "[-] ERROR: TCP port $HOST_PORT is already in use. Free it or set WAF_HOST_PORT to another port."
        exit 1
    fi
else
    echo "[!] WARNING: Unable to verify port usage (no 'ss' or 'lsof' found). Proceeding..."
fi

WAF_CONTAINER_NAME="modsecurity_waf"
LOG_DIR="/var/log/modsec"
mkdir -p "$LOG_DIR"

echo "[*] Launching the ModSecurity WAF container '$WAF_CONTAINER_NAME'..."

# Run the container. Note the following:
# - It binds container port 80 to host port ${HOST_PORT}.
# - It mounts the hardened CRS configuration as read-only.
# - It mounts a host directory for persistent audit logs.
# - It passes the audit log-related environment variables.
# - It sets the BACKEND variable (for reverse proxying) to a default of http://172.17.0.1:80.
docker run -d \
    --name "$WAF_CONTAINER_NAME" \
    --restart unless-stopped \
    -p "$HOST_PORT:80" \
    -v "$MODSEC_CRS_CONF:/etc/modsecurity.d/owasp-crs/crs-setup.conf:ro" \
    -v "$LOG_DIR:/var/log/modsecurity:Z" \
    -e MODSEC_AUDIT_LOG=/var/log/modsecurity/audit.log \
    -e MODSEC_AUDIT_LOG_FORMAT=JSON \
    -e MODSEC_AUDIT_ENGINE=RelevantOnly \
    -e BACKEND="${BACKEND:-http://172.17.0.1:80}" \
    "$WAF_IMAGE"

# Optionally, apply CPU and memory restrictions to prevent resource abuse
docker update --memory="1g" --cpus="1.0" "$WAF_CONTAINER_NAME" >/dev/null 2>&1 || true

echo ""
echo "[+] Deployment successful."
echo "[+] ModSecurity WAF container '$WAF_CONTAINER_NAME' is running on host port $HOST_PORT."
echo "[+] The container is configured with a hardened CRS (Paranoia Level 4 and strict thresholds)."
echo "[+] Audit logs are stored on the host at $LOG_DIR."
echo "[i] If you added a non-root user to the docker group, please re-log or open a new shell for changes to take effect."
