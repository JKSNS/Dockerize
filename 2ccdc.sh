#!/usr/bin/env bash
###############################################################################
# menu_modsec_waf.sh
#
# This script builds a derived Docker image (my-modsec-waf:latest) from the official
# OWASP ModSecurity CRS Nginx image so that /etc/nginx is writable and the environment-
# based rewriting script is disabled.
#
# It then presents a menu:
#  1) Comprehensive Deployment - deploy a base WAF container protecting a site on port 80.
#  2) Add Websites - add additional virtual hosts (server blocks) so that one WAF can protect
#     multiple websites.
#  3) Exit
#
# The container is run on a default host port of 8080 (mapping host:8080 → container:80).
#
# If you encounter any issues (such as "permission denied" or "cannot create /etc/nginx/nginx.conf"),
# check the container logs using:
#   docker logs modsecurity_waf
#
###############################################################################

set -e  # Exit immediately if any command exits non-zero.

##############################################
# Global Variables
##############################################
DOCKER_IMAGE_DERIVED="my-modsec-waf:latest"
WAF_CONTAINER_NAME="modsecurity_waf"

# Directories on the host to be bind-mounted into the container:
MODSEC_DIR="/etc/modsecurity"          # For modsecurity configuration
LOG_DIR="/var/log/modsec"              # For persistent modsecurity logs
NGINX_CONF_DIR="/etc/modsec/conf.d"      # For additional Nginx server block files

# Default WAF host port (change this by setting WAF_HOST_PORT when running)
DEFAULT_WAF_PORT="${WAF_HOST_PORT:-8080}"

# Temporary Dockerfile path for building the derived image
TEMP_DOCKERFILE="$(mktemp /tmp/DerivedDockerfile.XXXXXX)"

##############################################
# Function: Build Derived Image
##############################################
build_derived_image() {
  echo "[*] Building derived image '$DOCKER_IMAGE_DERIVED' from 'owasp/modsecurity-crs:nginx'..."

  cat > "$TEMP_DOCKERFILE" <<'EOF'
FROM owasp/modsecurity-crs:nginx

# Switch to root so we can modify file permissions and disable environment rewrites
USER root

# Option A: Disable the environment-based rewriting script that tries to rewrite nginx.conf.
RUN if [ -f /docker-entrypoint.d/20-envsubst-on-templates.sh ]; then \
      mv /docker-entrypoint.d/20-envsubst-on-templates.sh /docker-entrypoint.d/20-envsubst-on-templates.sh.disabled; \
    fi

# Option B: Ensure /etc/nginx and /etc/modsecurity.d are writable.
RUN chmod -R u+rw /etc/nginx /etc/modsecurity.d

# (Optional) You can also change the owner; in this example, we leave it and simply ensure it's writable.
# Drop privileges back to non-root; the base image’s non-root user is used.
USER nonroot

# The image’s entrypoint remains the same.
EOF

  docker build -f "$TEMP_DOCKERFILE" -t "$DOCKER_IMAGE_DERIVED" .
  rm -f "$TEMP_DOCKERFILE"
  echo "[*] Derived image '$DOCKER_IMAGE_DERIVED' built successfully."
}

##############################################
# Function: Install Docker (if needed)
##############################################
install_docker_if_needed() {
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
      yum install -y epel-release || true
      yum install -y docker-io || { echo "[-] Docker installation failed."; exit 1; }
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
                  echo "deb [arch=$(dpkg --print-architecture)] https://download.docker.com/linux/$OS $CODENAME stable" > /etc/apt/sources.list.d/docker.list
                  apt-get update -y
                  if ! apt-get install -y docker-ce docker-ce-cli containerd.io; then
                      echo "[!] Falling back to 'docker.io'..."
                      apt-get install -y docker.io || { echo "[-] Docker installation via apt failed."; exit 1; }
                  fi
              else
                  apt-get install -y docker.io || { echo "[-] Docker installation via apt failed."; exit 1; }
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
              yum install -y docker-ce docker-ce-cli containerd.io || { echo "[-] Docker installation via yum failed."; exit 1; }
              ;;
          dnf)
              dnf install -y dnf-plugins-core || true
              dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo || true
              dnf install -y docker-ce docker-ce-cli containerd.io || { echo "[-] Docker installation via dnf failed."; exit 1; }
              ;;
          zypper)
              zypper --non-interactive refresh
              zypper --non-interactive install docker || { echo "[-] Docker installation via zypper failed."; exit 1; }
              ;;
          pacman)
              pacman -Sy --noconfirm docker || { echo "[-] Docker installation via pacman failed."; exit 1; }
              ;;
          *)
              echo "[-] No recognized package manager. Cannot install Docker."
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

  local CURRENT_USER="${SUDO_USER:-$USER}"
  if ! id -nG "$CURRENT_USER" | grep -qw docker; then
      echo "[*] Adding $CURRENT_USER to docker group..."
      usermod -aG docker "$CURRENT_USER"
      echo "[*] Please re-log or open a new shell for group changes to take effect."
  fi

  echo "[*] Testing Docker with 'hello-world'..."
  set +e
  docker run --rm hello-world >/dev/null 2>&1
  local HW_RESULT=$?
  set -e
  if [[ $HW_RESULT -ne 0 ]]; then
      echo "[!] 'hello-world' test failed. Retrying..."
      sleep 2
      if ! docker run --rm hello-world >/dev/null 2>&1; then
          echo "[-] Docker appears not to be functioning properly. Exiting."
          exit 1
      fi
  fi
  echo "[*] Docker is installed and functional."
}

##############################################
# Function: Prepare ModSecurity CRS Configuration (Paranoia Level 4)
##############################################
prepare_modsec_config() {
  echo "[*] Preparing ModSecurity CRS configuration..."
  mkdir -p "$MODSEC_DIR" "$LOG_DIR" "$NGINX_CONF_DIR"
  cat > "$MODSEC_DIR/crs-setup.conf" << 'EOF'
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

##############################################
# Function: Create Default Site Configuration (Comprehensive Deployment)
##############################################
create_comprehensive_site() {
  echo ""
  read -rp "Enter the IP or domain for the website on port 80 (default: localhost): " BACKEND
  BACKEND="${BACKEND:-localhost}"
  # Create a default server block file in conf.d
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
  echo "[*] Default site configuration created for backend http://$BACKEND:80."
}

##############################################
# Function: Add Another Website Configuration
##############################################
add_website() {
  echo ""
  echo "[*] Add a new website to protect:"
  read -rp "  Enter domain name(s) (space-separated, e.g. example.com www.example.com): " DOMAINS
  read -rp "  Enter the backend IP/domain (default port 80, default: localhost): " BACKEND
  BACKEND="${BACKEND:-localhost}"
  # Generate a filename based on domains and timestamp
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
  echo "[*] Created configuration for: $DOMAINS -> http://$BACKEND:80."
  echo "[*] Restarting the container to apply new configuration..."
  docker restart "$WAF_CONTAINER_NAME" || true
}

##############################################
# Function: Launch the WAF Container
##############################################
run_waf_container() {
  local HOST_PORT="${WAF_HOST_PORT:-$DEFAULT_WAF_PORT}"
  echo "[*] Checking if host port $HOST_PORT is available..."
  if command -v ss >/dev/null 2>&1; then
    if ss -tulpn | grep -q ":$HOST_PORT "; then
      echo "[-] ERROR: Port $HOST_PORT is in use. Set a different value for WAF_HOST_PORT or free the port."
      exit 1
    fi
  elif command -v lsof >/dev/null 2>&1; then
    if lsof -Pi :$HOST_PORT -sTCP:LISTEN >/dev/null 2>&1; then
      echo "[-] ERROR: Port $HOST_PORT is in use. Set a different value for WAF_HOST_PORT or free the port."
      exit 1
    fi
  else
    echo "[!] Warning: Could not verify port usage. Proceeding anyway..."
  fi

  echo "[*] Pulling derived image: $DOCKER_IMAGE_DERIVED (if not up to date)..."
  docker pull "$DOCKER_IMAGE_DERIVED" || true

  echo "[*] Removing any existing container named '$WAF_CONTAINER_NAME'..."
  docker rm -f "$WAF_CONTAINER_NAME" 2>/dev/null || true

  echo "[*] Launching WAF container '$WAF_CONTAINER_NAME' on host port $HOST_PORT..."
  docker run -d \
    --name "$WAF_CONTAINER_NAME" \
    --restart unless-stopped \
    -p "$HOST_PORT:80" \
    -v "$MODSEC_DIR/crs-setup.conf:/etc/modsecurity.d/owasp-crs/crs-setup.conf" \
    -v "$LOG_DIR:/var/log/modsecurity" \
    -v "$NGINX_CONF_DIR:/etc/nginx/conf.d" \
    "$DOCKER_IMAGE_DERIVED"

  docker update --memory="1g" --cpus="1.0" "$WAF_CONTAINER_NAME" >/dev/null 2>&1 || true

  echo ""
  echo "===================================================================="
  echo "[+] WAF container '$WAF_CONTAINER_NAME' deployed using derived image."
  echo "[+] Host port $HOST_PORT → container port 80."
  echo "[+] Logs stored at: $LOG_DIR"
  echo "[!] If the container restarts, check its logs using: docker logs $WAF_CONTAINER_NAME"
  echo "===================================================================="
}

##############################################
# MAIN MENU
##############################################
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
        build_derived_image
        prepare_modsec_config
        create_comprehensive_site
        run_waf_container
        ;;
      2)
        if ! docker ps -q -f name="$WAF_CONTAINER_NAME" >/dev/null; then
          echo "[!] WAF container '$WAF_CONTAINER_NAME' is not running. Please use option 1 first."
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

# Ensure the script is run as root.
if [[ $EUID -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    echo "[*] Not running as root. Re-running with sudo..."
    exec sudo bash "$0" "$@"
  else
    echo "[-] ERROR: Please run this script as root."
    exit 1
  fi
fi

# Run the main menu.
main_menu
