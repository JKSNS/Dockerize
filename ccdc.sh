#!/usr/bin/env bash
################################################################################
# Bash script to deploy a Dockerized ModSecurity WAF with the OWASP Core Rule Set
# for multiple Linux distributions in incident response / competition scenarios.
#
# Fixes / Changes from original version:
# 1. Enforces running as root (or via sudo), preventing permission errors
#    during apt-get / yum / dnf / pacman / zypper operations.
# 2. Minor cleanup of conditionals and fallback logic to improve reliability.
################################################################################

# --- Ensure script is run as root (or via sudo) ---
if [[ $EUID -ne 0 ]]; then
    if command -v sudo >/dev/null 2>&1; then
        echo "[*] Script not running as root. Re-running with sudo..."
        exec sudo bash "$0" "$@"
    else
        echo "[-] Please run this script as root or install 'sudo' to continue."
        exit 1
    fi
fi

# Abort on any error
set -e

echo "[*] Starting Dockerized ModSecurity WAF deployment script..."

###############################################################################
# Section 1: Detect Linux distribution and version, and select the package manager
###############################################################################

OS=""          # OS family (ubuntu, centos, debian, fedora, suse, arch, etc.)
OS_VERSION=""  # Version number
PM=""          # Package manager command (apt, yum, dnf, zypper, pacman, ...)

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

# Special case: CentOS/RHEL 6 (deprecated, uses docker-io from EPEL)
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

            # Attempt Docker CE official repo first
            if [[ "$OS" == "ubuntu" || "$OS" == "debian" ]]; then
                CODENAME="$( (lsb_release -sc 2>/dev/null) || echo "" )"
                # For very old Debian that doesn't have lsb_release, fallback:
                [[ -z "$CODENAME" && "$OS" == "debian" ]] && CODENAME="stable"
                
                curl -fsSL https://download.docker.com/linux/$OS/gpg | apt-key add -
                echo "deb [arch=$(dpkg --print-architecture)] https://download.docker.com/linux/$OS $CODENAME stable" \
                  > /etc/apt/sources.list.d/docker.list
                
                apt-get update -y
                if ! apt-get install -y docker-ce docker-ce-cli containerd.io; then
                    echo "[!] Docker CE not available. Falling back to 'docker.io' package..."
                    apt-get install -y docker.io || {
                        echo "[-] ERROR: Docker installation failed via apt."
                        exit 1
                    }
                fi
            else
                # If not Ubuntu/Debian, fallback to 'docker.io'
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
                # If yum-config-manager not installed, add repo file manually
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
            echo "[-] ERROR: No supported package manager found. Cannot install Docker."
            exit 1
            ;;
    esac
fi

echo "[*] Enabling and starting Docker service..."

# systemctl-based systems
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

# Typically the real user is in $SUDO_USER if script was run via sudo
CURRENT_USER="${SUDO_USER:-$USER}"

if id -nG "$CURRENT_USER" | grep -qw docker; then
    echo "[*] User '$CURRENT_USER' is already in the docker group."
else
    # Add the user to docker group to allow docker usage without sudo
    echo "[*] Adding user '$CURRENT_USER' to 'docker' group..."
    usermod -aG docker "$CURRENT_USER"
    # Force the group membership to apply to the user’s current session
    # The simplest approach is to inform the user they must re-log or re-run
    echo "[*] Docker group membership updated. A re-login or new shell session is required."
fi

###############################################################################
# Section 4: Verify Docker installation
###############################################################################

echo "[*] Testing Docker with 'hello-world' container..."
set +e
docker run --rm hello-world >/dev/null 2>&1
TEST_RESULT=$?
set -e

if [[ $TEST_RESULT -ne 0 ]]; then
    echo "[!] First 'hello-world' test failed. Retrying once..."
    sleep 2
    if ! docker run --rm hello-world >/dev/null 2>&1; then
        echo "[-] ERROR: Docker does not appear functional. Check installation logs."
        exit 1
    fi
fi
echo "[*] Docker is installed and functional."

###############################################################################
# Section 5: Pull a secure ModSecurity WAF Docker image (with OWASP CRS)
###############################################################################

WAF_IMAGE="owasp/modsecurity-crs:nginx"
echo "[*] Pulling ModSecurity WAF image: $WAF_IMAGE"
docker pull "$WAF_IMAGE"

###############################################################################
# Section 6: Configure the WAF for maximum security (Paranoia Level 4, etc.)
###############################################################################

MODSEC_DIR="/etc/modsecurity"
MODSEC_CRS_CONF="$MODSEC_DIR/crs-setup.conf"

echo "[*] Creating hardened ModSecurity CRS config..."
mkdir -p "$MODSEC_DIR"

cat > "$MODSEC_CRS_CONF" << 'EOF'
# OWASP CRS maximum security setup
# Paranoia Level 4 (strictest)
SecAction "id:900000, phase:1, pass, t:none, nolog, setvar:tx.paranoia_level=4"

# Also set blocking and detection to PL4 (for newer CRS versions)
SecAction "id:900001, phase:1, pass, t:none, nolog, \
  setvar:tx.blocking_paranoia_level=4, setvar:tx.detection_paranoia_level=4"

# Enforce URLENCODED body processor
SecAction "id:900010, phase:1, pass, t:none, nolog, setvar:tx.enforce_bodyproc_urlencoded=1"

# Validate UTF-8 encoding
SecAction "id:900011, phase:1, pass, t:none, nolog, setvar:tx.crs_validate_utf8_encoding=1"

# Adjust inbound/outbound anomaly thresholds
SecAction "id:900020, phase:1, pass, t:none, nolog, \
  setvar:tx.inbound_anomaly_score_threshold=5, \
  setvar:tx.outbound_anomaly_score_threshold=4"
EOF

###############################################################################
# Section 7: Run the WAF container with strict resource constraints
###############################################################################

WAF_CONTAINER_NAME="modsecurity_waf"
HOST_PORT=${WAF_HOST_PORT:-80}  # Host port to bind; default to 80 if not set

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

# (Optional) Apply CPU/RAM limits to protect host from container resource abuse
docker update --memory="1g" --cpus="1.0" "$WAF_CONTAINER_NAME" >/dev/null 2>&1 || true

echo ""
echo "[+] ModSecurity WAF container '$WAF_CONTAINER_NAME' deployed successfully."
echo "[+] Listening on port $HOST_PORT with Paranoia Level 4, full OWASP CRS."
echo "[+] Logs stored on host at $LOG_DIR."
echo "[i] If you just added a non-root user to the docker group, please re-log or start a new shell to use Docker without sudo."
