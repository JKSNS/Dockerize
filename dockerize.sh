#!/bin/bash
set -e

# Function: print_banner
print_banner() {
    echo "======================================"
    echo "$1"
    echo "======================================"
}

# Function: detect_system_info
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

# Function: install_docker
install_docker() {
    print_banner "Installing Docker"
    case "$pm" in
        apt-get)
            sudo apt-get update -y
            sudo apt-get install -y ca-certificates curl gnupg lsb-release
            sudo install -m 0755 -d /etc/apt/keyrings
            sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
            sudo chmod a+r /etc/apt/keyrings/docker.asc
            echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \$(
              . /etc/os-release && echo \"\${UBUNTU_CODENAME:-\$VERSION_CODENAME}\"
            ) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
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
            # On OpenSUSE, docker and docker-compose may be available from the official repositories.
            sudo zypper --non-interactive install docker docker-compose
            ;;
        *)
            echo "[X] ERROR: Unsupported package manager '$pm'."
            exit 1
            ;;
    esac
}

# Function: install_docker_compose
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

# Function: fix_docker_group
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

# Function: check_dependencies
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

# Main Execution
detect_system_info
check_dependencies

echo "[INFO] All dependencies installed and configured successfully."
