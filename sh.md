### Running the Script

- To simply pull the base image based on your host OS, run the script without arguments.
- To run a service container, for example an FTP container, use:  
  ```bash
  python3 dockerize_helper.py --service ftp
  ```
- To run a service container with a custom configuration file mounted, use:  
  ```bash
  python3 dockerize_helper.py --service ftp --config /path/to/vsftpd.conf --container-config /etc/vsftpd.conf
  ```

This example can be extended with additional logic (such as scanning for multiple configuration files, automating more complex containerization workflows, or integrating with tools like Move2Kube) as needed for a comprehensive CCDC environment.
