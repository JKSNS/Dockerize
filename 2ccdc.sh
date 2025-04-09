#!/usr/bin/env bash
###############################################################################
# menu_modsec_waf.sh
#
# A single-menu Bash script that:
#   1) Installs Docker if needed (detecting your Linux distro).
#   2) Creates a ModSecurity WAF container with OWASP CRS at Paranoia Level 4.
#   3) Allows adding multiple websites (domains/backends) behind a single WAF,
#      by placing separate Nginx config files in /etc/nginx/conf.d within
#      the container (via a bind-mounted directory).
#
# Menu Options:
#   1) Comprehensive Deployment (installs Docker, deploys base WAF with one site)
#   2) Add Websites (adds more server blocks for additional websites)
#   3) Exit
#
# Fixes the common "read-only file system" error by NOT overriding /etc/nginx/nginx.conf.
# Instead, we store site configs in conf.d. This avoids the container's
# environment-based rewriting of the main file, which can fail if read-only.
###############################################################################

set -e  # Exit on any error

############################################################
# Global Variables
############################################################
DOCKER_IMAGE="owasp/modsecurity-crs:nginx"
WAF_CONTAINER_NAME="modsecurity_waf"

# The host directory for storing modsecurity config, logs, and Nginx conf.d
MODSEC_DIR="/etc/modsecurity"
LOG_DIR="/var/log/modsec"
NGINX_CONF_DIR="/etc/modsecurity/conf.d"  # We'll mount this to /etc/nginx/conf.d inside container

# The default host port to expose the WAF on. Change or override with WAF_HOST_PORT env.
DEFAULT_WAF_PORT="${WAF_HOST_PORT:-8080}"

############################################################
# 1) Install Docker if needed
############################################################
install_docker_if_needed() {
  # Detect OS and package manager
  local OS="" OS_VERSION="" PM=""
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

  echo "[*] Checking Docker installation on $OS $OS_VERSION (PM: $PM)..."

  if [[ "$OS" == "centos" && ${OS_VERSION%%.*} -lt 7 ]]; then
    # CentOS 6 fallback
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
          local CODENAME
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
        echo "[-] No recognized package manager. Can't install Docker."
        exit 1
        ;;
    esac
  fi

  if command -v systemctl >/dev/null 2>&1; then
    systemctl enable docker.service || true
    systemctl start docker.service
  else
    service docker start || true
    command -v chkconfig && chkconfig docker on || true
  fi

  # Add user to docker group
  local CURRENT_USER="${SUDO_USER:-$USER}"
  if ! id -nG "$CURRENT_USER" | grep -qw docker; then
    echo "[*] Adding $CURRENT_USER to docker group..."
    usermod -aG docker "$CURRENT_USER"
    echo "[*] Re-log or open a new shell to finalize group membership."
  fi

  # Quick Docker test
  echo "[*] Testing Docker with 'hello-world'..."
  set +e
  docker run --rm hello-world >/dev/null 2>&1
  local HW_RESULT=$?
  set -e
  if [[ $HW_RESULT -ne 0 ]]; then
    echo "[!] 'hello-world' test failed once. Retrying..."
    sleep 2
    if ! docker run --rm hello-world >/dev/null 2>&1; then
      echo "[-] Docker not functioning properly."
      exit 1
    fi
  fi
  echo "[*] Docker is ready."
}

############################################################
# 2) Prepare ModSecurity + OWASP CRS at Paranoia 4
############################################################
prepare_modsec_config() {
  echo "[*] Preparing ModSecurity CRS config at Paranoia Level 4..."
  mkdir -p "$MODSEC_DIR" "$LOG_DIR" "$NGINX_CONF_DIR"

  # Create the CRS setup file
  local CRS_SETUP="$MODSEC_DIR/crs-setup.conf"
  cat > "$CRS_SETUP" << 'EOF'
# OWASP CRS with Paranoia Level 4
SecAction "id:900000, phase:1, pass, t:none, nolog, setvar:tx.paranoia_level=4"
SecAction "id:900001, phase:1, pass, t:none, nolog, setvar:tx.blocking_paranoia_level=4, setvar:tx.detection_paranoia_level=4"
SecAction "id:900010, phase:1, pass, t:none, nolog, setvar:tx.enforce_bodyproc_urlencoded=1"
SecAction "id:900011, phase:1, pass, t:none, nolog, setvar:tx.crs_validate_utf8_encoding=1"
SecAction "id:900020, phase:1, pass, t:none, nolog, \
 setvar:tx.inbound_anomaly_score_threshold=5, \
 setvar:tx.outbound_anomaly_score_threshold=4"
EOF
}

############################################################
# 3) Launch or Update the WAF Container
#    This will read config files from $NGINX_CONF_DIR -> /etc/nginx/conf.d
#    and the modsec CRS config from $MODSEC_DIR -> /etc/modsecurity.d/owasp-crs/crs-setup.conf
############################################################
run_waf_container() {
  echo "[*] Stopping any existing container named '$WAF_CONTAINER_NAME'..."
  docker rm -f "$WAF_CONTAINER_NAME" 2>/dev/null || true

  local HOST_PORT="${WAF_HOST_PORT:-$DEFAULT_WAF_PORT}"

  # Check if the port is free
  if command -v ss >/dev/null 2>&1; then
    if ss -tulpn | grep -q ":$HOST_PORT "; then
      echo "[-] ERROR: Host port $HOST_PORT is in use. Change WAF_HOST_PORT or free the port."
      exit 1
    fi
  elif command -v lsof >/dev/null 2>&1; then
    if lsof -Pi :$HOST_PORT -sTCP:LISTEN >/dev/null 2>&1; then
      echo "[-] ERROR: Host port $HOST_PORT is in use. Change WAF_HOST_PORT or free the port."
      exit 1
    fi
  else
    echo "[!] Could not verify port usage. Proceeding..."
  fi

  echo "[*] Pulling container image: $DOCKER_IMAGE ..."
  docker pull "$DOCKER_IMAGE"

  echo "[*] Launching container '$WAF_CONTAINER_NAME' on port $HOST_PORT..."
  docker run -d \
    --name "$WAF_CONTAINER_NAME" \
    --restart unless-stopped \
    -p "$HOST_PORT:80" \
    -v "$MODSEC_DIR/crs-setup.conf:/etc/modsecurity.d/owasp-crs/crs-setup.conf" \
    -v "$LOG_DIR:/var/log/modsecurity" \
    -v "$NGINX_CONF_DIR:/etc/nginx/conf.d" \
    "$DOCKER_IMAGE"

  # Optional resource constraints
  docker update --memory="1g" --cpus="1.0" "$WAF_CONTAINER_NAME" >/dev/null 2>&1 || true

  echo ""
  echo "================================================================"
  echo "[+] WAF container '$WAF_CONTAINER_NAME' deployed."
  echo "[+] Host port $HOST_PORT -> container 80."
  echo "[+] Log directory: $LOG_DIR"
  echo "[!] If it restarts, check logs:"
  echo "    docker logs $WAF_CONTAINER_NAME"
  echo "================================================================"
}

############################################################
# 4) Create a Single Nginx Server Block for "Comprehensive"
#    (prompts user for domain or IP, proxies to port 80)
############################################################
create_comprehensive_site() {
  echo ""
  echo "[*] Enter the domain/IP of the local website on port 80 (default: localhost)"
  read -rp "Backend host: " BACKEND
  BACKEND="${BACKEND:-localhost}"

  # Create a single default site config in conf.d
  cat > "$NGINX_CONF_DIR/000-default.conf" <<EOF
server {
  listen 80;
  server_name _;

  access_log /var/log/modsecurity/access.log;

  location / {
    proxy_pass http://$BACKEND:80;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
  }
}
EOF
  echo "[*] Created default site conf for backend '$BACKEND:80'."
}

############################################################
# 5) Function to Add Another Website
#    (creates a new .conf in conf.d, proxies domain to IP)
############################################################
add_website() {
  echo ""
  echo "[*] This option lets you add a new domain/IP to protect."
  echo "[*] Example: domain: mysite.local, backend: 127.0.0.1:8080"
  read -rp "Domain name(s) (space-separated, e.g. example.com www.example.com): " DOMAINS
  read -rp "Backend IP/host (default port 80)? For example 192.168.1.10: " BACKEND
  BACKEND="${BACKEND:-localhost}"

  # Generate a name for the .conf file based on domain or timestamp
  local CONF_NAME
  CONF_NAME=$(echo "$DOMAINS" | tr ' ' '_' | tr '.' '_' | tr ':' '_')
  [[ -z "$CONF_NAME" ]] && CONF_NAME="site_$(date +%s)"

  cat > "$NGINX_CONF_DIR/${CONF_NAME}.conf" <<EOF
server {
  listen 80;
  server_name $DOMAINS;

  access_log /var/log/modsecurity/access.log;

  location / {
    proxy_pass http://$BACKEND:80;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
  }
}
EOF

  echo "[*] Created '$CONF_NAME.conf' with server_name: $DOMAINS -> $BACKEND:80"
  echo "[*] Restarting the container to load new config..."
  docker restart "$WAF_CONTAINER_NAME" || true
}

############################################################
# MAIN MENU
############################################################
main_menu() {
  while true; do
    echo ""
    echo "========== ModSecurity WAF Menu =========="
    echo "1) Comprehensive Deployment"
    echo "2) Add Websites"
    echo "3) Exit"
    read -rp "Choose an option: " CHOICE

    case "$CHOICE" in
      1)
        install_docker_if_needed
        prepare_modsec_config
        create_comprehensive_site
        run_waf_container
        ;;
      2)
        if ! docker ps -q -f name="$WAF_CONTAINER_NAME" >/dev/null; then
          echo "[!] WAF container '$WAF_CONTAINER_NAME' not running. Use option 1 first or ensure it's deployed."
        else
          add_website
        fi
        ;;
      3)
        echo "[*] Exiting script."
        exit 0
        ;;
      *)
        echo "[-] Invalid choice, please try again."
        ;;
    esac
  done
}

# Run the menu
main_menu
