
# Dockerization of Web Services Repository
---

## 0. System Requirements

- **Operating System:** Best supported on Linux (auto-install features available). Windows, BSD, and other Unix-like systems are partially supported (manual steps may be needed).
- **Python:** Version 3.7 or higher.
- **Docker & Docker Compose:** The script will check and attempt to install these if missing (Linux only).
- **Permissions:** Sudo privileges are required for auto-installation and configuration tasks.

---

## 1. Installation & Setup

1. **Clone the Repository:**
   ```bash
   git clone https://your-repo-url.git
   cd your-repo-directory
   ```
2. **Ensure Python 3.7+ is Installed:**
   ```bash
   python3 --version
   ```
3. **Run the Main Script with the Interactive Menu:**
   ```bash
   python3 dv1.py --menu
   ```
   The script will check for dependencies and auto-install Docker and Docker Compose on Linux systems. Windows users will be prompted with manual installation instructions if needed.

---

## 2. Features Overview

### 2.1 Docker & Docker Compose Auto-Installation
- **Auto-Detection:** Detects your Linux package manager (e.g., `apt`, `yum`, `zypper`) and attempts to install Docker and Docker Compose automatically.
- **Group & Permission Handling:** If Docker is installed but inaccessible, the script will try to add your user to the Docker group and re-execute the script.

### 2.2 Dependency & Environment Checks
- **Python Version:** Verifies that you’re running Python 3.7+.
- **WSL Check (Windows):** On Windows, the tool checks for WSL if Docker Desktop isn’t used.

### 2.3 OS Detection & Docker Image Mapping
- **OS Mapping:** Detects your host OS and suggests a recommended base Docker image for containerization.
- **Custom Image Selection:** Maps popular distributions (Ubuntu, Debian, CentOS, etc.) to corresponding Docker images.

### 2.4 Container Launch & Integrity Checking
- **Container Deployment:** Launch containers with options such as read-only mode and non-root enforcement.
- **Integrity Checks:** Compute a SHA256 hash of a container’s filesystem and perform continuous or minimal integrity checks. If discrepancies are detected, the container can be restored automatically from a provided snapshot.

### 2.5 Interactive Menu
- **Comprehensive Operations:** Choose from various options including:
  - Building new containers with host web files.
  - Pulling and deploying Docker containers.
  - Copying website files into existing containers.
  - Running integrity checks on one or multiple containers.
  - **Destructive Option:** Purging Docker completely (removes all Docker data and uninstalls Docker/Docker Compose).

---

## 3. Usage Instructions

### 3.1 Launching the Interactive Menu
Run the following command to launch the interactive menu:
```bash
python3 dv1.py --menu
```
Follow the on-screen prompts to select options such as:
- **Comprehensive Setup:** Containerize your service environment with host configuration files.
- **Integrity Check:** Monitor running containers for any unauthorized changes.
- **Purge Docker:** Remove all Docker data and uninstall Docker (use with caution).

### 3.2 Containerization & Integrity Operations
- **Containerize Service:** Automatically copy critical directories, generate a Dockerfile, and build a Docker image that encapsulates your current service environment.
- **Continuous Integrity Check:** Monitor a container by periodically hashing its filesystem. If an integrity violation is detected, the tool can restore the container from a snapshot file.

### 3.3 Purge Operation (Destructive)
- **Purge Docker:** This option will stop all containers, remove all Docker data (images, volumes, networks), and uninstall Docker and Docker Compose (Linux only).  
  **Warning:** This operation is irreversible. Only proceed if you are sure.

---

## 4. Customization & Configuration

- **Read-Only Mode & Non-Root Enforcement:**  
  Enhance container security by enabling read-only mode and running containers as non-root users.
- **Volume Mounts:**  
  Customize which directories to mount into your containers for persistent storage.
- **Docker Network Configuration:**  
  Specify custom Docker networks for your containers or use the default `bridge` network.
- **Environment Variables:**  
  Pass custom environment variables (e.g., database credentials, timezone settings) to your containers as needed.

---

## 5. Troubleshooting

- **Auto-Installation Issues:**  
  If Docker or Docker Compose fails to install automatically, ensure your Linux package manager is supported. On Windows, manual installation (e.g., Docker Desktop) is required.
- **Permission Errors:**  
  Run the script with appropriate privileges (using `sudo` if necessary).
- **Integrity Check Failures:**  
  Verify that the snapshot file is correctly provided and accessible for container restoration.

---

## 6. Contributing 

Contributions are welcome! If you have ideas, improvements, or bug fixes, please open an issue or submit a pull request via the repository’s GitHub page.

---

Additional resources to explore: 
https://www.cio.gov/assets/files/Containerization%20Readiness%20Guide_Final%20_v3.pdf#:~:text=many%20publicly%20available%20and%20pre,images%20that%20can%20quickly%20run

https://github.com/ucrcyber/ccdc_practice_env

https://github.com/vitalyford/vsftpd-2.3.4-vulnerable

https://github.com/vulhub/vulhub/tree/master

https://move2kube.konveyor.io/tutorials/migration-workflow/plan#:~:text=We%20start%20by%20planning%20the,Kubernetes%20Deployments%2C%20Services%2C%20Ingress%2C%20etc

https://www.fairwinds.com/blog/introducing-base-image-finder-an-open-source-tool-for-identifying-base-images#:~:text=Introducing%20Base%20Image%20Finder

https://github.com/docker-archive/communitytools-image2docker-win

