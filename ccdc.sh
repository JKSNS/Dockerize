#!/usr/bin/env bash
################################################################################
# Bash script to deploy a Dockerized ModSecurity WAF (OWASP CRS) for multiple
# Linux distributions, with maximum security settings. This version fixes:
#
# 1. Permission errors during Docker install by enforcing root/sudo usage.
# 2. "bind: address already in use" errors by checking if the host port is taken.
################################################################################

# --- Ensure script is run as root (or via sudo) ---
if [[ $EUID -ne 0 ]]; then
    if command -v sudo >/dev/null 2>&1; then
        echo "[*] Script not running as root. Re-running with sudo..."
        exec sudo bash "$0" "$@"
    else
        echo "[-] ERROR: Please run this script as root or install 'sudo' to continue."
        exit 1
    fi
fi

set -e  # Abort on any error

echo "[*] Starting Dockerized ModSecurity WAF deployment script..."

###############################################################################
# Section 1: Detect Linux distribution and version, and select the package manager
###############################################################################

OS=""          # OS family (ubuntu, centos, debian, fedora, suse, arch, etc.)
OS_VERSION=""  # Version number
PM=""          # Package manager (apt, yum, dnf, zypper, pacman, ...)

echo "[*] Detecting Linux distribution..."

if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    OS="${ID:-}"
    OS_VERSION="${VERSION_ID:-}"
elif type lsb_release >/dev/null 2>&1; then
    OS="$(lsb_release -si | tr '[:upper:]' '[:lower:]')"
    OS_VERSION="$(lsb_release -sr)"
elif [[ -f /etc/redhat-release ]]; then
    OS="centos"
    OS_VERSION="$(grep -oE '[0-9]+' /etc/redhat-release | head -1)"
elif [[ -f /etc/debian_version ]]; then
    OS="debian"
    OS_VERSION="$(cat /etc/debian_version)"
fi

# Normalize for known variants
case "$OS" in
    redhat*|centos|rocky|almalinux) OS="centos" ;;
    fedora) OS="fedora" ;;
    debian) OS="debian" ;;
    ubuntu) OS="ubuntu" ;;
    opensuse*|suse|sles) OS="suse" ;;
    arch|manjaro) OS="arch" ;;
esac

# Pick package manager
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

echo "[*] Detected OS: $OS $OS_VERSION. Chosen package manager: $PM"

###############################################################################
# Section 2: Install Docker using the appropriate method
###############################################################################

echo "[*] Installing Docker Engine..."

# Special case: CentOS/RHEL 6 uses older docker-io from EPEL
if [[ "$OS" == "centos" && ${OS_VERSION%%.*} -lt 7 ]]; then
    echo "[*] CentOS/RHEL 6 detected - installing docker-io from EPEL..."
    yum install -y epel-release || true
    yum install -y docker-io || {
        echo "[-] ERROR: Failed to install Docker on CentOS 6."
        exit 1
    }
else
    case "$PM" in
        apt)
            echo "[*] Using apt-get (Debian/Ubuntu) to install Docker..."
            apt-get update -y
            apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release

            # Attempt official Docker CE repo first
            if [[ "$OS" == "ubuntu" || "$OS" == "debian" ]]; then
                CODENAME="$( (lsb_release -sc 2>/dev/null) || echo "" )"
                [[ -z "$CODENAME" && "$OS" == "debian" ]] && CODENAME="stable"
                curl -fsSL https://download.docker.com/linux/$OS/gpg | apt-key add -
                echo "deb [arch=$(dpkg --print-architecture)] https://download.docker.com/linux/$OS $CODENAME stable" \
                    > /etc/apt/sources.list.d/docker.list
                apt-get update -y
                if ! apt-get install -y docker-ce docker-ce-cli containerd.io; then
                    echo "[!] Docker CE not available. Falling back to 'docker.io'..."
                    apt-get install -y docker.io || {
                        echo "[-] ERROR: Docker installation failed via apt."
                        exit 1
                    }
                fi
            else
                # Fallback for other apt-based OSes
                apt-get install -y docker.io || {
                    echo "[-] ERROR: Docker installation failed via apt."
                    exit 1
                }
            fi
            ;;
        yum)
            echo "[*] Using yum (CentOS/RHEL) to install Docker..."
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
            echo "[*] Using dnf (Fedora/CentOS 8/9) to install Docker..."
            dnf install -y dnf-plugins-core || true
            dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo || true
            dnf install -y docker-ce docker-ce-cli containerd.io || {
                echo "[-] ERROR: Docker installation via dnf failed."
                exit 1
            }
            ;;
        zypper)
            echo "[*] Using zypper (openSUSE/SLES) to install Docker..."
            zypper --non-interactive refresh
            zypper --non-interactive install docker || {
                echo "[-] ERROR: Docker installation via zypper failed."
                exit 1
            }
            ;;
        pacman)
            echo "[*] Using pacman (Arch/Manjaro) to install Docker..."
            pacman -Sy --noconfirm docker || {
                echo "[-] ERROR: Docker installation via pacman failed."
                exit 1
            }
            ;;
        *)
            echo "[-] ERROR: No known package manager. Cannot install Docker."
            exit 1
            ;;
    esac
fi

echo "[*] Enabling and starting Docker service..."

# systemctl-based
if command -v systemctl >/dev/null 2>&1; then
    systemctl enable docker.service || true
    systemctl start docker.service
else
    # SysV init fallback
    service docker start || true
    command -v chkconfig >/dev/null 2>&1 && chkconfig docker on || true
fi

###############################################################################
# Section 3: Configure Docker permissions for the current user
###############################################################################

CURRENT_USER="${SUDO_USER:-$USER}"
if id -nG "$CURRENT_USER" | grep -qw docker; then
    echo "[*] User '$CURRENT_USER' is already in the docker group."
else
    echo "[*] Adding user '$CURRENT_USER' to 'docker' group..."
    usermod -aG docker "$CURRENT_USER"
    echo "[*] User group updated. A re-login or new shell is needed for it to take effect."
fi

###############################################################################
# Section 4: Verify Docker installation
###############################################################################

echo "[*] Testing Docker with 'hello-world'..."
set +e
docker run --rm hello-world >/dev/null 2>&1
TEST_RESULT=$?
set -e

if [[ $TEST_RESULT -ne 0 ]]; then
    echo "[!] 'hello-world' test failed once. Retrying..."
    sleep 2
    if ! docker run --rm hello-world >/dev/null 2>&1; then
        echo "[-] ERROR: Docker not functioning correctly. Check logs."
        exit 1
    fi
fi
echo "[*] Docker is installed and functional."

###############################################################################
# Section 5: Pull a secure ModSecurity WAF Docker image (with OWASP CRS)
###############################################################################

WAF_IMAGE="owasp/modsecurity-crs:nginx"
echo "[*] Pulling WAF image: $WAF_IMAGE..."
docker pull "$WAF_IMAGE"

###############################################################################
# Section 6: Configure the WAF (max security: Paranoia Level 4, etc.)
###############################################################################

MODSEC_DIR="/etc/modsecurity"
MODSEC_CRS_CONF="$MODSEC_DIR/crs-setup.conf"

echo "[*] Creating hardened ModSecurity CRS config..."
mkdir -p "$MODSEC_DIR"

cat > "$MODSEC_CRS_CONF" << 'EOF'
# OWASP CRS maximum security setup
SecAction "id:900000, phase:1, pass, t:none, nolog, setvar:tx.paranoia_level=4"
SecAction "id:900001, phase:1, pass, t:none, nolog, \
  setvar:tx.blocking_paranoia_level=4, setvar:tx.detection_paranoia_level=4"
SecAction "id:900010, phase:1, pass, t:none, nolog, \
  setvar:tx.enforce_bodyproc_urlencoded=1"
SecAction "id:900011, phase:1, pass, t:none, nolog, \
  setvar:tx.crs_validate_utf8_encoding=1"
SecAction "id:900020, phase:1, pass, t:none, nolog, \
  setvar:tx.inbound_anomaly_score_threshold=5, \
  setvar:tx.outbound_anomaly_score_threshold=4"
EOF

###############################################################################
# Section 7: Check if the host port is in use, then run the WAF container
###############################################################################

# The user can override the default host port (80) by setting WAF_HOST_PORT=8080, etc.
HOST_PORT="${WAF_HOST_PORT:-80}"

# Quick check if port is already bound
if command -v ss >/dev/null 2>&1; then
    # prefer ss if available
    if ss -tulpn | grep -q ":$HOST_PORT "; then
        echo "[-] ERROR: TCP port $HOST_PORT appears to be in use. Free it or set WAF_HOST_PORT to another port, then re-run."
        exit 1
    fi
elif command -v lsof >/dev/null 2>&1; then
    # fallback to lsof
    if lsof -Pi :$HOST_PORT -sTCP:LISTEN >/dev/null 2>&1; then
        echo "[-] ERROR: TCP port $HOST_PORT is already in use. Free it or set WAF_HOST_PORT to a different port, then re-run."
        exit 1
    fi
else
    echo "[!] WARNING: Could not check port usage (no 'ss' or 'lsof'). Proceeding..."
fi

WAF_CONTAINER_NAME="modsecurity_waf"

# Create local log dir for persistent WAF logs
LOG_DIR="/var/log/modsec"
mkdir -p "$LOG_DIR"

echo "[*] Launching ModSecurity WAF container '$WAF_CONTAINER_NAME'..."
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

# (Optional) Apply CPU/RAM constraints
docker update --memory="1g" --cpus="1.0" "$WAF_CONTAINER_NAME" >/dev/null 2>&1 || true

echo ""
echo "[+] ModSecurity WAF container '$WAF_CONTAINER_NAME' deployed."
echo "[+] Listening on port $HOST_PORT with Paranoia Level 4, full OWASP CRS."
echo "[+] Logs mounted to $LOG_DIR on the host."
echo "[i] If you just added a non-root user to the 'docker' group, please re-log or open a new shell."
