#!/usr/bin/env bash
################################################################################
# deploy_modsec_waf.sh
#
# A script to deploy a single Dockerized ModSecurity WAF (with OWASP CRS) that
# protects one or more websites running on the same machine on port 80.
#
# Steps:
# 1) Detect OS and install Docker if missing.
# 2) Prompt user for IP/domain of the machine's websites (defaults to 'localhost').
# 3) Generate a high-security CRS config (Paranoia Level 4).
# 4) Generate a simple Nginx config inside the WAF container that proxies traffic
#    from container port 80 to the specified backend (machine:80).
# 5) Map host port 8080 -> container port 80, so your WAF is accessible on 8080.
#
# If the container restarts continuously, check logs with:
#   docker logs modsecurity_waf
################################################################################

###############################################################################
# 0. Ensure the script runs as root (or via sudo)
###############################################################################
if [[ $EUID -ne 0 ]]; then
    if command -v sudo >/dev/null 2>&1; then
        echo "[*] Not running as root. Re-running with sudo..."
        exec sudo bash "$0" "$@"
    else
        echo "[-] ERROR: Please run this script as root or install sudo."
        exit 1
    fi
fi

set -e  # Exit on any error

echo "[*] Starting single-site ModSecurity WAF deployment..."

###############################################################################
# 1. Detect Linux Distribution, Version, and Package Manager
###############################################################################
OS=""
OS_VERSION=""
PM=""

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

case "$OS" in
    redhat*|centos|rocky|almalinux) OS="centos" ;;
    fedora) OS="fedora" ;;
    debian) OS="debian" ;;
    ubuntu) OS="ubuntu" ;;
    opensuse*|suse|sles) OS="suse" ;;
    arch|manjaro) OS="arch" ;;
esac

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

echo "[*] Detected OS: $OS $OS_VERSION (PM: $PM)"

###############################################################################
# 2. Install Docker if Needed
###############################################################################
echo "[*] Installing Docker (if not present)..."
if [[ "$OS" == "centos" && ${OS_VERSION%%.*} -lt 7 ]]; then
    # Legacy CentOS/RHEL 6
    yum install -y epel-release || true
    yum install -y docker-io || {
        echo "[-] Docker install failed on CentOS 6."
        exit 1
    }
else
    case "$PM" in
        apt)
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
                    echo "[!] Falling back to 'docker.io'..."
                    apt-get install -y docker.io || {
                        echo "[-] Docker install failed via apt."
                        exit 1
                    }
                fi
            else
                apt-get install -y docker.io || {
                    echo "[-] Docker install failed via apt."
                    exit 1
                }
            fi
            ;;
        yum)
            yum install -y yum-utils || true
            yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo || {
                cat >/etc/yum.repos.d/docker-ce.repo <<'EOF'
[docker-ce-stable]
name=Docker CE Stable
baseurl=https://download.docker.com/linux/centos/$releasever/$basearch/stable
enabled=1
gpgcheck=1
gpgkey=https://download.docker.com/linux/centos/gpg
EOF
            }
            yum install -y docker-ce docker-ce-cli containerd.io || {
                echo "[-] Docker install failed via yum."
                exit 1
            }
            ;;
        dnf)
            dnf install -y dnf-plugins-core || true
            dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo || true
            dnf install -y docker-ce docker-ce-cli containerd.io || {
                echo "[-] Docker install failed via dnf."
                exit 1
            }
            ;;
        zypper)
            zypper --non-interactive refresh
            zypper --non-interactive install docker || {
                echo "[-] Docker install failed via zypper."
                exit 1
            }
            ;;
        pacman)
            pacman -Sy --noconfirm docker || {
                echo "[-] Docker install failed via pacman."
                exit 1
            }
            ;;
        *)
            echo "[-] No recognized package manager found. Cannot install Docker."
            exit 1
            ;;
    esac
fi

# Enable + Start Docker
if command -v systemctl >/dev/null 2>&1; then
    systemctl enable docker.service || true
    systemctl start docker.service
else
    service docker start || true
    command -v chkconfig && chkconfig docker on || true
fi

###############################################################################
# 3. Configure Docker Permissions for Current User
###############################################################################
CURRENT_USER="${SUDO_USER:-$USER}"
if id -nG "$CURRENT_USER" | grep -qw docker; then
    echo "[*] User '$CURRENT_USER' is already in the docker group."
else
    echo "[*] Adding user '$CURRENT_USER' to docker group..."
    usermod -aG docker "$CURRENT_USER"
    echo "[*] Re-log or open a new shell for the group change to take effect."
fi

###############################################################################
# 4. Verify Docker with 'hello-world'
###############################################################################
echo "[*] Testing Docker with 'hello-world'..."
set +e
docker run --rm hello-world >/dev/null 2>&1
HELLO_RESULT=$?
set -e
if [[ $HELLO_RESULT -ne 0 ]]; then
    echo "[!] 'hello-world' test failed. Retrying..."
    sleep 2
    if ! docker run --rm hello-world >/dev/null 2>&1; then
        echo "[-] Docker not functioning properly. Exiting."
        exit 1
    fi
fi
echo "[*] Docker is installed and functional."

###############################################################################
# 5. Prompt for the machine's IP/domain hosting websites on port 80
###############################################################################
echo ""
read -rp "Enter the IP or domain name of the machine hosting your site(s) on port 80 [default: localhost]: " WEBSERVER
WEBSERVER="${WEBSERVER:-localhost}"
echo "[*] Using backend: http://$WEBSERVER:80"

###############################################################################
# 6. Pull the OWASP ModSecurity CRS (Nginx) image
###############################################################################
WAF_IMAGE="owasp/modsecurity-crs:nginx"
echo "[*] Pulling WAF image: $WAF_IMAGE..."
docker pull "$WAF_IMAGE"

###############################################################################
# 7. Create a High-Security CRS config (Paranoia Level 4)
###############################################################################
MODSEC_DIR="/etc/modsecurity"
MODSEC_CRS_CONF="$MODSEC_DIR/crs-setup.conf"

mkdir -p "$MODSEC_DIR"
cat > "$MODSEC_CRS_CONF" << 'EOF'
# OWASP CRS with Paranoia Level 4 (strictest)
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
# 8. Generate a Simple Nginx Config that Proxies to Our Machine:80
###############################################################################
NGINX_CUSTOM_CONF="/etc/modsecurity/nginx_single_site.conf"
cat > "$NGINX_CUSTOM_CONF" <<EOF
# Nginx reverse proxy config for a single site with ModSecurity enabled
load_module modules/ngx_http_modsecurity_module.so;

worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

events {
  worker_connections 1024;
}

http {
  modsecurity on;
  modsecurity_rules_file /etc/modsecurity.d/modsecurity.conf;
  # The crs-setup.conf is also included from the container's default startup.

  include /etc/nginx/mime.types;
  default_type application/octet-stream;

  sendfile on;
  keepalive_timeout 65;

  server {
    listen 80;
    server_name localhost;

    # Access logs stored in container => bind-mounted to /var/log/modsecurity
    access_log /var/log/modsecurity/access.log;

    location / {
      proxy_pass http://$WEBSERVER:80;
      proxy_http_version 1.1;
      proxy_set_header Host \$host;
      proxy_set_header X-Real-IP \$remote_addr;
      proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto \$scheme;
    }
  }
}
EOF

###############################################################################
# 9. Launch the Container on Host Port 8080 by Default
###############################################################################
HOST_PORT="${WAF_HOST_PORT:-8080}"

# Check if port is free
if command -v ss >/dev/null 2>&1; then
    if ss -tulpn | grep -q ":$HOST_PORT "; then
        echo "[-] ERROR: Port $HOST_PORT is in use. Free it or set WAF_HOST_PORT to another port."
        exit 1
    fi
elif command -v lsof >/dev/null 2>&1; then
    if lsof -Pi :$HOST_PORT -sTCP:LISTEN >/dev/null 2>&1; then
        echo "[-] ERROR: Port $HOST_PORT is in use. Free it or set WAF_HOST_PORT to another port."
        exit 1
    fi
else
    echo "[!] WARNING: Could not verify port usage. Proceeding anyway..."
fi

WAF_CONTAINER_NAME="modsecurity_waf"
LOG_DIR="/var/log/modsec"
mkdir -p "$LOG_DIR"

echo "[*] Launching container '$WAF_CONTAINER_NAME' (port $HOST_PORT->80) to proxy to $WEBSERVER:80..."
docker run -d \
    --name "$WAF_CONTAINER_NAME" \
    --restart unless-stopped \
    -p "$HOST_PORT:80" \
    -v "$MODSEC_CRS_CONF:/etc/modsecurity.d/owasp-crs/crs-setup.conf:ro" \
    -v "$NGINX_CUSTOM_CONF:/etc/nginx/nginx.conf:ro" \
    -v "$LOG_DIR:/var/log/modsecurity:Z" \
    "$WAF_IMAGE"

# Optional resource constraints
docker update --memory="1g" --cpus="1.0" "$WAF_CONTAINER_NAME" >/dev/null 2>&1 || true

echo ""
echo "===================================================================="
echo "[+] ModSecurity WAF deployed at Paranoia Level 4."
echo "[+] Listening on port $HOST_PORT (host) -> port 80 (container)."
echo "[+] All traffic is proxied to http://$WEBSERVER:80."
echo "[+] Logs are stored in $LOG_DIR on the host."
echo "[i] If the container restarts, run: docker logs modsecurity_waf"
echo "===================================================================="
