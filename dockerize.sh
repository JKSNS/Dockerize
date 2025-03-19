#!/usr/bin/env bash
set -e

###############################################################################
# GLOBAL VARIABLES FOR OS DETECTION (used by DB/WAF logic)
###############################################################################
OS_ID=""
OS_VERSION=""
OS_MAJOR=""
recommended_image=""

###############################################################################
# UTILITY: print_banner
###############################################################################
print_banner() {
    echo "======================================"
    echo "$1"
    echo "======================================"
}

###############################################################################
# 1) DETECT LINUX PACKAGE MANAGER
#    (Mirrors the Python snippet's detect_linux_package_manager)
###############################################################################
detect_linux_package_manager() {
    if command -v apt-get &>/dev/null; then
        echo "apt-get"
    elif command -v apt &>/dev/null; then
        # Some systems use 'apt' instead of apt-get
        echo "apt-get"
    elif command -v yum &>/dev/null; then
        echo "yum"
    elif command -v dnf &>/dev/null; then
        echo "dnf"
    elif command -v zypper &>/dev/null; then
        echo "zypper"
    else
        return 1
    fi
}

###############################################################################
# 2) ATTEMPT INSTALL DOCKER (Mirrors your Python snippet, but in Bash)
###############################################################################
attempt_install_docker_linux() {
    local pm
    pm="$(detect_linux_package_manager)" || {
        echo "[ERROR] No recognized package manager found on Linux. Cannot auto-install Docker."
        return 1
    }

    echo "[INFO] Attempting to install Docker using '${pm}' on Linux..."
    case "${pm}" in
        apt-get)
            sudo "${pm}" update -y
            # On Debian/Ubuntu, we install 'docker.io' to avoid advanced repo logic
            sudo "${pm}" install -y docker.io
            ;;
        yum|dnf)
            sudo "${pm}" -y install docker
            sudo systemctl enable docker
            sudo systemctl start docker
            ;;
        zypper)
            sudo zypper refresh
            # Add the official Docker repository
            sudo zypper addrepo https://download.docker.com/linux/opensuse/opensuse.repo
            sudo zypper --non-interactive install docker
            sudo systemctl enable docker
            sudo systemctl start docker
            ;;
        *)
            echo "[ERROR] Package manager '${pm}' is not fully supported for auto-installation."
            return 1
            ;;
    esac

    echo "[INFO] Docker installation attempt completed. Checking if Docker is now available..."
    if command -v docker &>/dev/null; then
        return 0
    else
        return 1
    fi
}

###############################################################################
# 3) ATTEMPT INSTALL DOCKER COMPOSE (Mirrors your Python snippet, but in Bash)
###############################################################################
attempt_install_docker_compose_linux() {
    local pm
    pm="$(detect_linux_package_manager)" || {
        echo "[ERROR] No recognized package manager found. Cannot auto-install Docker Compose."
        return 1
    }

    echo "[INFO] Attempting to install Docker Compose using '${pm}' on Linux..."
    case "${pm}" in
        apt-get|yum|dnf|zypper)
            # Remove package manager-based installation
            ;;
        *)
            echo "[ERROR] Package manager '${pm}' is not fully supported for Docker Compose auto-install."
            return 1
            ;;
    esac

    # Install Docker Compose directly from GitHub
    DOCKER_COMPOSE_VERSION="v2.21.0" # specify version
    DOCKER_COMPOSE_URL="https://github.com/docker/compose/releases/download/${DOCKER_COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)"

    echo "[INFO] Downloading Docker Compose from ${DOCKER_COMPOSE_URL}"
    sudo curl -L "${DOCKER_COMPOSE_URL}" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose

    echo "[INFO] Docker Compose installation attempt completed. Checking if it is now available..."
    if command -v docker-compose &>/dev/null; then
        return 0
    else
        return 1
    fi
}

###############################################################################
# 4) can_run_docker
#    Return 0 if 'docker ps' runs without error; else non-zero.
###############################################################################
can_run_docker() {
    if command -v docker &>/dev/null; then
        if docker ps &>/dev/null; then
            return 0
        fi
    fi
    return 1
}

###############################################################################
# 5) fix_docker_group
#    Add current user to 'docker' group, enable/start Docker, re-exec script
#    under 'sg docker'.
###############################################################################
fix_docker_group() {
    local current_user
    current_user="$(whoami 2>/dev/null || echo "$USER")"

    echo "[INFO] Adding user '${current_user}' to docker group."
    if ! sudo usermod -aG docker "${current_user}"; then
        echo "[WARN] Could not add user to docker group."
    fi

    echo "[INFO] Please log out and log back in to activate the new group membership."
    return 1 # Indicate that the script cannot proceed automatically

    #echo "[INFO] Enabling and starting Docker service..."
    #if command -v systemctl &>/dev/null; then
    #    sudo systemctl enable docker || echo "[WARN] Could not enable docker service."
    #    sudo systemctl start docker  || echo "[WARN] Could not start docker service."
    #fi
    #echo "[INFO] Re-executing script under 'sg docker' to activate group membership."
    #export CCDC_DOCKER_GROUP_FIX=1
    #local script_path
    #script_path="$(readlink -f "$0")"
    #local cmd
    #cmd=("sg" "docker" "-c" "export CCDC_DOCKER_GROUP_FIX=1; exec \"${script_path}\" $*")
    #exec "${cmd[@]}"
}

###############################################################################
# 6) ensure_docker_installed
#    Checks if Docker is installed & user can run it. If missing, tries auto-install.
#    If user isn't in docker group, fix that, then re-exec with sg.
###############################################################################
ensure_docker_installed() {
    if [[ -n "${CCDC_DOCKER_GROUP_FIX}" ]]; then
        # Already tried group fix once. Let's see if we can run docker now.
        if can_run_docker; then
            echo "[INFO] Docker is accessible now after group fix."
            return 0
        else
            echo "[ERROR] Docker still not accessible even after group fix. Exiting."
            exit 1
        fi
    fi

    if can_run_docker; then
        echo "[INFO] Docker is already installed and accessible."
        return 0
    fi

    echo "[INFO] Docker not found or not accessible. Attempting installation..."
    if attempt_install_docker_linux; then
        if can_run_docker; then
            echo "[INFO] Docker is installed and accessible on Linux now."
            return 0
        else
            fix_docker_group "$@"
        fi
    else
        echo "[ERROR] Could not auto-install Docker on Linux. Please install it manually."
        exit 1
    fi
}

###############################################################################
# 7) check_docker_compose
#    Checks if Docker Compose is installed. If not, tries auto-install.
###############################################################################
check_docker_compose() {
    if command -v docker-compose &>/dev/null; then
        echo "[INFO] Docker Compose is already installed."
        return 0
    fi

    echo "[WARN] Docker Compose not found. Attempting auto-install (Linux only)."
    if attempt_install_docker_compose_linux; then
        if command -v docker-compose &>/dev/null; then
            echo "[INFO] Docker Compose installed successfully."
        else
            echo "[ERROR] Docker Compose still not available after attempted install."
        fi
    else
        echo "[ERROR] Could not auto-install Docker Compose on Linux. Please install manually."
    fi
}

###############################################################################
# 8) check_dependencies
#    Calls ensure_docker_installed + check_docker_compose.
###############################################################################
check_dependencies() {
    print_banner "Checking Docker and Docker Compose"
    ensure_docker_installed "$@"
    check_docker_compose
}

###############################################################################
# 9) detect_os_and_recommend_image
#    Reads /etc/os-release to map OS to a recommended Docker base image.
###############################################################################
detect_os_and_recommend_image() {
    print_banner "OS Detection & Docker Base Image Recommendation"
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS_ID=$(echo "$ID" | tr '[:upper:]' '[:lower:]')
        OS_VERSION=$(echo "$VERSION_ID" | tr -d '"')
        OS_MAJOR=$(echo "$OS_VERSION" | cut -d. -f1)
    else
        echo "[WARN] Cannot detect OS information from /etc/os-release."
        OS_ID="ubuntu"
        OS_VERSION="latest"
        OS_MAJOR="latest"
        recommended_image="ubuntu:latest"
        echo "[INFO] Recommended Docker base image: $recommended_image"
        return
    fi

    case "$OS_ID" in
        ubuntu)
            case "$OS_MAJOR" in
                14) recommended_image="ubuntu:14.04" ;;
                16) recommended_image="ubuntu:16.04" ;;
                18) recommended_image="ubuntu:18.04" ;;
                20) recommended_image="ubuntu:20.04" ;;
                22) recommended_image="ubuntu:22.04" ;;
                *) recommended_image="ubuntu:latest" ;;
            esac
            ;;
        debian)
            case "$OS_MAJOR" in
                7) recommended_image="debian:7" ;;
                8) recommended_image="debian:8" ;;
                9) recommended_image="debian:9" ;;
                10) recommended_image="debian:10" ;;
                11) recommended_image="debian:11" ;;
                12) recommended_image="debian:12" ;;
                *) recommended_image="debian:latest" ;;
            esac
            ;;
        centos)
            case "$OS_MAJOR" in
                6) recommended_image="centos:6" ;;
                7) recommended_image="centos:7" ;;
                8) recommended_image="centos:8" ;;
                9) recommended_image="centos:stream9" ;;
                *) recommended_image="ubuntu:latest" ;;
            esac
            ;;
        fedora)
            case "$OS_MAJOR" in
                25) recommended_image="fedora:25" ;;
                26) recommended_image="fedora:26" ;;
                27) recommended_image="fedora:27" ;;
                28) recommended_image="fedora:28" ;;
                29) recommended_image="fedora:29" ;;
                30) recommended_image="fedora:30" ;;
                31) recommended_image="fedora:31" ;;
                35) recommended_image="fedora:35" ;;
                *) recommended_image="fedora:latest" ;;
            esac
            ;;
        opensuse*)
            if [[ "$PRETTY_NAME" == *"Tumbleweed"* ]]; then
                recommended_image="opensuse/tumbleweed"
            elif [[ "$PRETTY_NAME" == *"Leap"* ]]; then
                case "$OS_MAJOR" in
                    15) recommended_image="opensuse/leap:15" ;;
                    *) recommended_image="opensuse/leap:latest" ;;
                esac
            else
                recommended_image="opensuse:latest"
            fi
            ;;
        *)
            recommended_image="ubuntu:latest"
            ;;
    esac

    echo "[INFO] Detected OS: ${PRETTY_NAME:-Unknown}"
    echo "[INFO] Recommended Docker base image: $recommended_image"
}

###############################################################################
# 10) setup_docker_database
#     Example DB container logic, mapping OS to MySQL versions
###############################################################################
setup_docker_database() {
    print_banner "Setting Up Dockerized Database"

    local db_image
    if [[ "$OS_ID" == "centos" ]]; then
        case "$OS_MAJOR" in
            6) db_image="mysql:5.5" ;;
            7) db_image="mysql:5.7" ;;
            *) db_image="mysql:8.0" ;;
        esac
    elif [[ "$OS_ID" == "ubuntu" ]]; then
        if [ "$OS_MAJOR" -lt 20 ]; then
            db_image="mysql:5.7"
        else
            db_image="mysql:8.0"
        fi
    elif [[ "$OS_ID" == "debian" ]]; then
        if [ "$OS_MAJOR" -lt 10 ]; then
            db_image="mysql:5.7"
        else
            db_image="mysql:8.0"
        fi
    else
        db_image="mysql:8.0"
    fi

    echo "[INFO] Recommended Dockerized Database image: $db_image"
    echo "[INFO] Pulling the database image..."
    docker pull "$db_image"
    echo "[INFO] Running the Dockerized Database container..."
    docker run -d --name dockerized_db -e MYSQL_ROOT_PASSWORD=my-secret-pw -p 3306:3306 "$db_image"
    echo "[INFO] Database container 'dockerized_db' is running."
}

###############################################################################
# 11) setup_docker_modsecurity
#     Example WAF container logic, mapping OS to ModSecurity versions
###############################################################################
setup_docker_modsecurity() {
    print_banner "Setting Up Dockerized ModSecurity WAF"

    local waf_image
    if [[ "$OS_ID" == "centos" ]]; then
        case "$OS_MAJOR" in
            6) waf_image="modsecurity/modsecurity:2.8.0" ;;
            7) waf_image="modsecurity/modsecurity:2.9.3" ;;
            *) waf_image="modsecurity/modsecurity:latest" ;;
        esac
    elif [[ "$OS_ID" == "ubuntu" ]]; then
        if [ "$OS_MAJOR" -lt 20 ]; then
            waf_image="modsecurity/modsecurity:2.9.2"
        else
            waf_image="modsecurity/modsecurity:latest"
        fi
    else
        waf_image="modsecurity/modsecurity:latest"
    fi

    echo "[INFO] Recommended Dockerized ModSecurity WAF image: $waf_image"
    echo "[INFO] Pulling the ModSecurity image..."
    docker pull "$waf_image"
    echo "[INFO] Running the Dockerized ModSecurity WAF container..."
    docker run -d --name dockerized_waf -p 80:80 "$waf_image"
    echo "[INFO] ModSecurity WAF container 'dockerized_waf' is running."
}

###############################################################################
# 12) display_menu
#     Menu-based approach to choose steps or do everything
###############################################################################
display_menu() {
    echo "======================================"
    echo "Dockerization Script Menu"
    echo "======================================"
    echo "1) Check & Install Docker and Docker Compose"
    echo "2) OS Detection and Recommended Base Image"
    echo "3) Setup Dockerized Database"
    echo "4) Setup Dockerized ModSecurity WAF"
    echo "5) Full Automatic Installation (all steps)"
    echo "6) Exit"
    echo -n "Enter your choice (1-6): "
    read -r choice
    case "$choice" in
        1)
            check_dependencies
            ;;
        2)
            detect_os_and_recommend_image
            ;;
        3)
            detect_os_and_recommend_image
            setup_docker_database
            ;;
        4)
            detect_os_and_recommend_image
            setup_docker_modsecurity
            ;;
        5)
            check_dependencies
            detect_os_and_recommend_image
            setup_docker_database
            setup_docker_modsecurity
            ;;
        6)
            echo "Exiting."
            exit 0
            ;;
        *)
            echo "Invalid option. Exiting."
            exit 1
            ;;
    esac
}

###############################################################################
# MAIN EXECUTION
###############################################################################
if [[ "$1" == "--menu" ]]; then
    display_menu
else
    # Full automatic installation mode if no flag is provided
    check_dependencies
    detect_os_and_recommend_image
    setup_docker_database
    setup_docker_modsecurity
fi

echo "[INFO] All tasks completed successfully."
