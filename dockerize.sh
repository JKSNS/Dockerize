#!/bin/bash
set -e

# -----------------------------------------------------------------------------
# Global variables for OS detection
# -----------------------------------------------------------------------------
OS_ID=""
OS_VERSION=""
OS_MAJOR=""
recommended_image=""
pm=""

# -----------------------------------------------------------------------------
# Function: print_banner
# -----------------------------------------------------------------------------
print_banner() {
    echo "======================================"
    echo "$1"
    echo "======================================"
}

# -----------------------------------------------------------------------------
# Function: detect_system_info
# -----------------------------------------------------------------------------
detect_system_info() {
    print_banner "Detecting System Info"
    echo "[*] Detecting package manager..."
    if command -v apt-get &>/dev/null; then
        echo "[*] apt/apt-get detected (Debian-based)"
        pm="apt-get"
    elif command -v dnf &>/dev/null; then
        echo "[*] dnf detected (Fedora-based)"
        pm="dnf"
    elif command -v zypper &>/dev/null; then
        echo "[*] zypper detected (OpenSUSE)"
        pm="zypper"
    elif command -v yum &>/dev/null; then
        echo "[*] yum detected (RHEL-based)"
        pm="yum"
    else
        echo "[X] ERROR: Could not detect package manager."
        exit 1
    fi
}

# -----------------------------------------------------------------------------
# Function: install_docker
# -----------------------------------------------------------------------------
install_docker() {
    print_banner "Installing Docker"
    case "$pm" in
        apt-get)
            sudo apt-get update -y
            sudo apt-get install -y ca-certificates curl gnupg lsb-release
            # Prepare the GPG keyring directory
            sudo install -m 0755 -d /etc/apt/keyrings
            sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
            sudo chmod a+r /etc/apt/keyrings/docker.asc

            # Use lsb_release to get the codename (avoids malformed line issues)
            CODENAME=$(lsb_release -cs)
            echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $CODENAME stable" \
                | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

            sudo apt-get update -y
            sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
            ;;
        dnf)
            sudo dnf -y install dnf-plugins-core
            sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
            sudo dnf -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
            ;;
        yum)
            sudo yum install -y yum-utils
            sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
            sudo yum install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
            ;;
        zypper)
            sudo zypper refresh
            # On OpenSUSE, docker and docker-compose may be available from the official repos.
            sudo zypper --non-interactive install docker docker-compose
            ;;
        *)
            echo "[X] ERROR: Unsupported package manager '$pm'."
            exit 1
            ;;
    esac
}

# -----------------------------------------------------------------------------
# Function: install_docker_compose
# -----------------------------------------------------------------------------
install_docker_compose() {
    print_banner "Installing Docker Compose"
    if command -v docker-compose &>/dev/null; then
        echo "[INFO] Docker Compose is already installed."
        return 0
    else
        echo "[WARN] Docker Compose not found. Attempting auto-install using '$pm'..."
        case "$pm" in
            apt-get)
                sudo apt-get install -y docker-compose
                ;;
            dnf)
                sudo dnf -y install docker-compose
                ;;
            yum)
                sudo yum install -y docker-compose
                ;;
            zypper)
                sudo zypper --non-interactive install docker-compose
                ;;
            *)
                echo "[ERROR] Package manager '$pm' is not supported for Docker Compose auto-install."
                exit 1
                ;;
        esac
    fi
}

# -----------------------------------------------------------------------------
# Function: fix_docker_group
# -----------------------------------------------------------------------------
fix_docker_group() {
    print_banner "Fixing Docker Group Permissions"
    # If docker commands are not accessible, add the current user to the docker group.
    if ! docker info >/dev/null 2>&1; then
        current_user=$(whoami)
        echo "[INFO] Adding user '$current_user' to the docker group."
        sudo usermod -aG docker "$current_user" || echo "[WARN] Could not add user to docker group."
        echo "[INFO] Enabling and starting Docker service..."
        sudo systemctl enable docker || echo "[WARN] Could not enable docker service."
        sudo systemctl start docker || echo "[WARN] Could not start docker service."
        # Re-exec the script with new group membership using sg, if not already attempted.
        if [ -z "$CCDC_DOCKER_GROUP_FIX" ]; then
            export CCDC_DOCKER_GROUP_FIX=1
            echo "[INFO] Re-executing script under 'sg docker' to activate group membership."
            exec sg docker -c "$0 $*"
        else
            echo "[ERROR] Docker still not accessible even after group fix. Exiting."
            exit 1
        fi
    else
        echo "[INFO] Docker is accessible."
    fi
}

# -----------------------------------------------------------------------------
# Function: check_dependencies
# -----------------------------------------------------------------------------
check_dependencies() {
    print_banner "Checking Docker and Docker Compose"

    if ! command -v docker &>/dev/null; then
        echo "[WARN] Docker command not found, attempting installation..."
        install_docker
    else
        echo "[INFO] Docker is installed."
    fi

    if ! docker info >/dev/null 2>&1; then
        echo "[WARN] Docker is installed but not accessible by the current user."
        fix_docker_group
    fi

    if ! command -v docker-compose &>/dev/null; then
        echo "[WARN] Docker Compose not found."
        install_docker_compose
    else
        echo "[INFO] Docker Compose is installed."
    fi
}

# -----------------------------------------------------------------------------
# Function: detect_os_and_recommend_image
# -----------------------------------------------------------------------------
detect_os_and_recommend_image() {
    print_banner "OS Detection & Docker Base Image Recommendation"
    if [ -f /etc/os-release ]; then
        . /etc/os-release
    else
        echo "[WARN] Cannot detect OS information from /etc/os-release."
        recommended_image="ubuntu:latest"
        OS_ID="ubuntu"
        OS_VERSION="latest"
        OS_MAJOR="latest"
        echo "[INFO] Recommended Docker base image: $recommended_image"
        return
    fi

    OS_ID=$(echo "$ID" | tr '[:upper:]' '[:lower:]')
    OS_VERSION=$(echo "$VERSION_ID" | tr -d '"')
    OS_MAJOR=$(echo "$OS_VERSION" | cut -d. -f1)

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
        opensuse* )
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

    echo "[INFO] Detected OS: $PRETTY_NAME"
    echo "[INFO] Recommended Docker base image: $recommended_image"
}

# -----------------------------------------------------------------------------
# Function: setup_docker_database
# -----------------------------------------------------------------------------
setup_docker_database() {
    print_banner "Setting Up Dockerized Database"
    # Map OS to a compatible database container image.
    if [[ "$OS_ID" == "centos" ]]; then
        case "$OS_MAJOR" in
            6) db_image="mysql:5.5" ;;   # For very old CentOS
            7) db_image="mysql:5.7" ;;   # CentOS 7: recommended MySQL 5.7
            *) db_image="mysql:8.0" ;;   # Newer CentOS versions
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

# -----------------------------------------------------------------------------
# Function: setup_docker_modsecurity
# -----------------------------------------------------------------------------
setup_docker_modsecurity() {
    print_banner "Setting Up Dockerized ModSecurity WAF"
    # Map OS to a compatible ModSecurity container image.
    if [[ "$OS_ID" == "centos" ]]; then
        case "$OS_MAJOR" in
            6) waf_image="modsecurity/modsecurity:2.8.0" ;;  # Example older version
            7) waf_image="modsecurity/modsecurity:2.9.3" ;;  # CentOS 7
            *) waf_image="modsecurity/modsecurity:latest" ;;
        esac
    elif [[ "$OS_ID" == "ubuntu" ]]; then
        if [ "$OS_MAJOR" -lt 20 ]; then
            waf_image="modsecurity/modsecurity:2.9.2"  # Example older version
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

# -----------------------------------------------------------------------------
# Function: display_menu
# -----------------------------------------------------------------------------
display_menu() {
    echo "======================================"
    echo "Dockerization Script Menu"
    echo "======================================"
    echo "1) Install Docker and Docker Compose"
    echo "2) OS Detection and Recommended Base Image"
    echo "3) Setup Dockerized Database"
    echo "4) Setup Dockerized ModSecurity WAF"
    echo "5) Full Automatic Installation (all steps)"
    echo "6) Exit"
    echo -n "Enter your choice (1-6): "
    read -r choice
    case "$choice" in
        1)
            detect_system_info
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
            detect_system_info
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

# -----------------------------------------------------------------------------
# Main Execution
# -----------------------------------------------------------------------------
if [[ "$1" == "--menu" ]]; then
    display_menu
else
    # Full automatic installation mode if no flag is provided.
    detect_system_info
    check_dependencies
    detect_os_and_recommend_image
    setup_docker_database
    setup_docker_modsecurity
fi

echo "[INFO] All tasks completed successfully."
