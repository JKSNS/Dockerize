# Dockerize

Just testing...

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

<br>
<br>
<br>


Resources to pull from: 

https://www.cio.gov/assets/files/Containerization%20Readiness%20Guide_Final%20_v3.pdf#:~:text=many%20publicly%20available%20and%20pre,images%20that%20can%20quickly%20run

https://github.com/ucrcyber/ccdc_practice_env

https://github.com/vitalyford/vsftpd-2.3.4-vulnerable

https://github.com/vulhub/vulhub/tree/master

https://move2kube.konveyor.io/tutorials/migration-workflow/plan#:~:text=We%20start%20by%20planning%20the,Kubernetes%20Deployments%2C%20Services%2C%20Ingress%2C%20etc

https://www.fairwinds.com/blog/introducing-base-image-finder-an-open-source-tool-for-identifying-base-images#:~:text=Introducing%20Base%20Image%20Finder

https://github.com/docker-archive/communitytools-image2docker-win

