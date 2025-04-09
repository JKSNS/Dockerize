#!/usr/bin/env bash
################################################################################
# deploy_root_modsec.sh
#
# A single script that:
#   1) Builds a derived Docker image from owasp/modsecurity-crs:nginx, ensuring
#      /etc/nginx is fully writable, and root is used (no "nonroot" user).
#   2) Disables environment-based rewriting scripts so /etc/nginx/nginx.conf
#      isn't forcibly overwritten.
#   3) Sets up a simple local conf.d and a high-security ModSecurity CRS config.
#   4) Runs the container on host port 8080 (mapping to container port 80),
#      reverse-proxying to localhost:80 inside the container.
################################################################################

set -e  # Exit on any error

# Require root or sudo
if [[ $EUID -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    echo "[*] Not running as root. Re-running with sudo..."
    exec sudo bash "$0" "$@"
  else
    echo "[-] ERROR: Please run this script as root or via sudo."
    exit 1
  fi
fi

# Image/tag for the derived container
DERIVED_IMAGE="my-modsec-waf:latest"
CONTAINER_NAME="modsecurity_waf"

# Host directories for local config/logs
BASE_DIR="$(pwd)/modsec_files"
MODSEC_DIR="$BASE_DIR/modsecurity"
CONFD_DIR="$BASE_DIR/conf.d"
LOG_DIR="$BASE_DIR/logs"

# Default host port for the WAF
WAF_HOST_PORT="${WAF_HOST_PORT:-8080}"

################################################################################
# 1. Create a Dockerfile for our derived image
################################################################################
DOCKERFILE_CONTENT="$(cat <<'EOF'
# Dockerfile for a derived image that runs as root, with /etc/nginx writable.
FROM owasp/modsecurity-crs:nginx

# Switch to root so we can fix permissions and remove rewriting scripts
USER root

# Disable the environment-based rewriting script if present
RUN if [ -f /docker-entrypoint.d/20-envsubst-on-templates.sh ]; then \
      mv /docker-entrypoint.d/20-envsubst-on-templates.sh /docker-entrypoint.d/20-envsubst-on-templates.sh.disabled; \
    fi

# Make /etc/nginx and /etc/modsecurity.d fully writable (chmod 0755 or 0777)
RUN chmod -R 0755 /etc/nginx /etc/modsecurity.d

# Stay root (no 'USER nonroot')
EOF
)"

################################################################################
# 2. Build the Derived Docker Image
################################################################################
build_derived_image() {
  echo "[*] Building derived Docker image: $DERIVED_IMAGE"
  mkdir -p "$BASE_DIR"
  echo "$DOCKERFILE_CONTENT" > "$BASE_DIR/Dockerfile"
  docker build -t "$DERIVED_IMAGE" "$BASE_DIR"
  echo "[*] Derived image '$DERIVED_IMAGE' built successfully."
}

################################################################################
# 3. Create Local Directories and Basic ModSecurity Config
################################################################################
prepare_local_config() {
  echo "[*] Preparing local directories under '$BASE_DIR'..."
  mkdir -p "$MODSEC_DIR" "$CONFD_DIR" "$LOG_DIR"

  # High-security CRS config (Paranoia Level 4)
  cat > "$MODSEC_DIR/crs-setup.conf" <<'EOF'
# OWASP CRS with Paranoia Level 4
SecAction "id:900000, phase:1, pass, t:none, nolog, setvar:tx.paranoia_level=4"
SecAction "id:900001, phase:1, pass, t:none, nolog, setvar:tx.blocking_paranoia_level=4, setvar:tx.detection_paranoia_level=4"
SecAction "id:900010, phase:1, pass, t:none, nolog, setvar:tx.enforce_bodyproc_urlencoded=1"
SecAction "id:900011, phase:1, pass, t:none, nolog, setvar:tx.crs_validate_utf8_encoding=1"
SecAction "id:900020, phase:1, pass, t:none, nolog, \
  setvar:tx.inbound_anomaly_score_threshold=5, \
  setvar:tx.outbound_anomaly_score_threshold=4"
EOF

  # A simple default server block in conf.d to proxy to localhost:80
  cat > "$CONFD_DIR/000-default.conf" <<'EOF'
server {
  listen 80;
  server_name _;

  access_log /var/log/modsecurity/access.log;

  location / {
    proxy_pass http://localhost:80;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }
}
EOF

  echo "[*] Local config ready. CRS config at '$MODSEC_DIR/crs-setup.conf'."
  echo "[*] Nginx conf.d in '$CONFD_DIR'."
}

################################################################################
# 4. Run the Container as Root, Mapping Our Directories
################################################################################
run_container() {
  echo "[*] Checking if port $WAF_HOST_PORT is available..."
  if command -v ss >/dev/null 2>&1; then
    if ss -tulpn | grep -q ":$WAF_HOST_PORT "; then
      echo "[-] ERROR: Port $WAF_HOST_PORT is already in use. Free it or set WAF_HOST_PORT=..."
      exit 1
    fi
  elif command -v lsof >/dev/null 2>&1; then
    if lsof -Pi :$WAF_HOST_PORT -sTCP:LISTEN >/dev/null 2>&1; then
      echo "[-] ERROR: Port $WAF_HOST_PORT is already in use. Free it or set WAF_HOST_PORT=..."
      exit 1
    fi
  else
    echo "[!] Warning: couldn't verify port usage, proceeding anyway..."
  fi

  echo "[*] Removing any existing container named '$CONTAINER_NAME'..."
  docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

  echo "[*] Launching container '$CONTAINER_NAME' as root on host port $WAF_HOST_PORT -> container:80..."
  docker run -d \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    -p "$WAF_HOST_PORT:80" \
    -v "$MODSEC_DIR/crs-setup.conf:/etc/modsecurity.d/owasp-crs/crs-setup.conf" \
    -v "$LOG_DIR:/var/log/modsecurity" \
    -v "$CONFD_DIR:/etc/nginx/conf.d" \
    -u 0 \
    "$DERIVED_IMAGE"

  echo ""
  echo "==========================================================================="
  echo "[+] Container '$CONTAINER_NAME' is running as root."
  echo "[+] Host port $WAF_HOST_PORT -> container port 80."
  echo "[+] A default server block proxies to 'localhost:80' from within the container."
  echo "[+] CRS config is set to Paranoia Level 4."
  echo "[+] Logs stored in: $LOG_DIR"
  echo "[!] If you see any errors or the container restarts, check logs with:"
  echo "    docker logs $CONTAINER_NAME"
  echo "==========================================================================="
}

################################################################################
# MAIN
################################################################################
echo "[*] Building derived image and deploying ModSecurity (as root) WAF..."

build_derived_image
prepare_local_config
run_container

echo "[*] Done. You can now visit http://<HOST_IP>:$WAF_HOST_PORT/"
