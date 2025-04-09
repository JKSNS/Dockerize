#!/usr/bin/env bash
################################################################################
# deploy_multisite_modsec_waf.sh
#
# This script installs Docker (if needed), prompts the user for multiple websites
# to protect (domains and their backend addresses), generates a multi-site
# Nginx reverse-proxy configuration with ModSecurity CRS at Paranoia Level 4,
# and then launches a single container that can protect all these sites.
#
# The WAF container listens on host port 8080 by default, but you can override
# by setting WAF_HOST_PORT before running:
#   export WAF_HOST_PORT=8888
#   ./deploy_multisite_modsec_waf.sh
#
# If you see "Restarting" loops, run:
#   docker logs modsecurity_waf
# to see why Nginx is failing. Typical causes are syntax errors or invalid backends.
################################################################################

###############################################################################
# 0. Ensure we run as root or via sudo
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

set -e  # Abort on error
echo "[*] Starting multi-site ModSecurity WAF deployment..."

###############################################################################
# 1. Detect OS + Package Manager, Install Docker if needed
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

echo "[*] OS: $OS $OS_VERSION, Package manager: $PM"

echo "[*] Installing Docker if not present..."
if [[ "$OS" == "centos" && ${OS_VERSION%%.*} -lt 7 ]]; then
    # CentOS 6
    yum install -y epel-release || true
    yum install -y docker-io || {
        echo "[-] Docker install failed on CentOS6."
        exit 1
    }
else
    case "$PM" in
        apt)
            apt-get update -y
            apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release
            # Try Docker CE official
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
            echo "[-] Unsupported package manager. Cannot install Docker."
            exit 1
            ;;
    esac
fi

# Enable and start Docker
if command -v systemctl >/dev/null 2>&1; then
    systemctl enable docker.service || true
    systemctl start docker.service
else
    service docker start || true
    command -v chkconfig && chkconfig docker on || true
fi

###############################################################################
# 2. Configure Docker group for current user
###############################################################################
CURRENT_USER="${SUDO_USER:-$USER}"
if id -nG "$CURRENT_USER" | grep -qw docker; then
    echo "[*] $CURRENT_USER already in docker group."
else
    echo "[*] Adding $CURRENT_USER to docker group..."
    usermod -aG docker "$CURRENT_USER"
    echo "[*] Re-log or open a new shell so group membership takes effect."
fi

###############################################################################
# 3. Test Docker with 'hello-world'
###############################################################################
echo "[*] Verifying Docker by running 'hello-world'..."
set +e
docker run --rm hello-world >/dev/null 2>&1
HELLO_RESULT=$?
set -e
if [[ $HELLO_RESULT -ne 0 ]]; then
    echo "[!] 'hello-world' test failed. Retrying..."
    sleep 2
    if ! docker run --rm hello-world >/dev/null 2>&1; then
        echo "[-] Docker not functioning properly."
        exit 1
    fi
fi
echo "[*] Docker is working."

###############################################################################
# 4. Prompt for Multiple Websites to Protect
###############################################################################
echo ""
echo "=== MULTI-SITE CONFIGURATION ==="
read -rp "How many websites do you want to protect? " NUM_SITES

# If user cancels or gives invalid input
if ! [[ $NUM_SITES =~ ^[0-9]+$ ]]; then
    echo "[-] Invalid number. Exiting."
    exit 1
fi

SITES=()

# For each site, gather domain(s) + backend
for (( i=1; i<=$NUM_SITES; i++ )); do
    echo ""
    echo "Configuring site #$i..."
    read -rp "  Enter the domain name(s), e.g. 'example.com www.example.com': " DOMAINS
    read -rp "  Enter the backend URL, e.g. 'http://127.0.0.1:8000': " BACKEND

    # We store as "DOMAINS|BACKEND" in an array; we will parse later
    SITES+=("$DOMAINS|$BACKEND")
done

###############################################################################
# 5. Pull the OWASP ModSecurity CRS (Nginx) image
###############################################################################
WAF_IMAGE="owasp/modsecurity-crs:nginx"
echo "[*] Pulling ModSecurity WAF image: $WAF_IMAGE..."
docker pull "$WAF_IMAGE"

###############################################################################
# 6. Create a High-Security CRS config (Paranoia Level 4)
###############################################################################
MODSEC_DIR="/etc/modsecurity"
MODSEC_CRS_CONF="$MODSEC_DIR/crs-setup.conf"

mkdir -p "$MODSEC_DIR"
cat > "$MODSEC_CRS_CONF" << 'EOF'
# OWASP CRS - High Security
SecAction "id:900000, phase:1, pass, t:none, nolog, setvar:tx.paranoia_level=4"
SecAction "id:900001, phase:1, pass, t:none, nolog, setvar:tx.blocking_paranoia_level=4, setvar:tx.detection_paranoia_level=4"
SecAction "id:900010, phase:1, pass, t:none, nolog, setvar:tx.enforce_bodyproc_urlencoded=1"
SecAction "id:900011, phase:1, pass, t:none, nolog, setvar:tx.crs_validate_utf8_encoding=1"
SecAction "id:900020, phase:1, pass, t:none, nolog, \
  setvar:tx.inbound_anomaly_score_threshold=5, \
  setvar:tx.outbound_anomaly_score_threshold=4"
EOF

###############################################################################
# 7. Build a Multi-Site Nginx Config that includes ModSecurity
###############################################################################
# We'll create a single config file with multiple server blocks. Each block:
# - listens on port 80 inside container
# - uses modsecurity at PL4
# - proxies traffic to the user-specified backend
# NOTE: We assume each domain is a separate server_name directive.

NGINX_CUSTOM_CONF="/etc/modsecurity/nginx_multisite.conf"
cat > "$NGINX_CUSTOM_CONF" <<'END_NGINX'
# Nginx config for multiple websites behind ModSecurity CRS
# The main modsecurity.conf is included from the container's default locations,
# but we also include our custom crs-setup.conf to enforce PL4 rules.

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
  # The container's base image automatically includes /etc/modsecurity.d/owasp-crs/crs-setup.conf
  # but we override it by bind-mounting if needed. This is just an extra reference.

  include /etc/nginx/mime.types;
  default_type application/octet-stream;

  sendfile on;
  keepalive_timeout 65;

  # For each site, we'll generate a server block here:
END_NGINX

# Append a server block for each site
for SITE_DATA in "${SITES[@]}"; do
    # Parse the stored "DOMAINS|BACKEND"
    IFS='|' read -r DOMAINS BACKEND <<< "$SITE_DATA"
    # Example: server_name example.com www.example.com;
    cat >> "$NGINX_CUSTOM_CONF" <<END_SERVER

  server {
    listen 80;
    server_name $DOMAINS;

    # Access logs (optional)
    access_log /var/log/modsecurity/access.log;

    # ModSecurity is enabled globally (modsecurity on; above)
    # but if you want a site-specific rule, you could do:
    # modsecurity_rules_file /path/to/custom.conf;

    location / {
      proxy_pass $BACKEND;
      proxy_http_version 1.1;
      proxy_set_header Host \$host;
      proxy_set_header X-Real-IP \$remote_addr;
      proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto \$scheme;
    }
  }
END_SERVER
done

# Finish config
cat >> "$NGINX_CUSTOM_CONF" <<'END_NGINX'
}
END_NGINX

echo "[*] Generated multi-site Nginx config: $NGINX_CUSTOM_CONF"

###############################################################################
# 8. Launch the Container with the Custom Config
###############################################################################
HOST_PORT="${WAF_HOST_PORT:-8080}"

echo "[*] Checking if host port $HOST_PORT is free..."
if command -v ss >/dev/null 2>&1; then
    if ss -tulpn | grep -q ":$HOST_PORT "; then
        echo "[-] ERROR: Port $HOST_PORT is already in use. Free it or set WAF_HOST_PORT= another port."
        exit 1
    fi
elif command -v lsof >/dev/null 2>&1; then
    if lsof -Pi :$HOST_PORT -sTCP:LISTEN >/dev/null 2>&1; then
        echo "[-] ERROR: Port $HOST_PORT is in use. Free it or set WAF_HOST_PORT= new port."
        exit 1
    fi
else
    echo "[!] Could not verify port usage. Proceeding..."
fi

WAF_CONTAINER_NAME="modsecurity_waf"
LOG_DIR="/var/log/modsec"
mkdir -p "$LOG_DIR"

echo "[*] Launching container '$WAF_CONTAINER_NAME' on host port $HOST_PORT..."
docker run -d \
    --name "$WAF_CONTAINER_NAME" \
    --restart unless-stopped \
    -p "$HOST_PORT:80" \
    -v "$MODSEC_CRS_CONF:/etc/modsecurity.d/owasp-crs/crs-setup.conf:ro" \
    -v "$NGINX_CUSTOM_CONF:/etc/nginx/nginx.conf:ro" \
    -v "$LOG_DIR:/var/log/modsecurity:Z" \
    "$WAF_IMAGE"

# Optionally set resource limits
docker update --memory="1g" --cpus="1.0" "$WAF_CONTAINER_NAME" >/dev/null 2>&1 || true

echo ""
echo "======================================================================"
echo "[+] Multi-site ModSecurity WAF container launched."
echo "[+] Listening on port $HOST_PORT -> Container's port 80."
echo "[+] Virtual hosts generated for the following sites:"
for SITE_DATA in "${SITES[@]}"; do
    IFS='|' read -r DOMAINS BACKEND <<< "$SITE_DATA"
    echo "   - Domains: $DOMAINS -> Backend: $BACKEND"
done
echo "[+] Paranoia Level 4, advanced CRS config. Logs at $LOG_DIR on host."
echo "[i] If the container restarts repeatedly, run:"
echo "    docker logs modsecurity_waf"
echo "    to see error messages (typos, invalid upstream, SELinux issues, etc.)"
echo "======================================================================"
