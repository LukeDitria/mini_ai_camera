# Installing Requirements
Steps for setting up your raspberry pi!
You'll need to install a few things first...

### Update Pi if you haven't already
```commandline
sudo apt update && sudo apt full-upgrade
```

#### On systems where Picamera2 is supported but not pre-installed (Such as the Lite OS), you can install it with
```commandline
sudo apt install python3-picamera2
```
#### OR to get a slightly reduced installation with fewer of the window system related elements (USE THIS for installing on a Raspberry Pi OS Lite system)
```commandline
sudo apt install python3-picamera2 --no-install-recommends
```
### IMX500 (AI Camera)

```commandline
sudo apt install imx500-all
```
### Reboot Pi after install!

```commandline
sudo reboot now
```
### picamera2 tells us to install system wide
### Therefore we need to install opencv etc, also at the system level...
### E.G.
```commandline
sudo apt install python3-opencv
```

### If you're using the Lite OS you will also need to install:


### Install pip requirements including system-wide packages (we need to use the system picamera2 install...)
```commandline
python -m venv venv --system-site-packages
source venv/bin/activate
pip install -r requirements.txt
```

## Check file paths in data_logger.sh and data_logger.service are correct for you!!
### Activate script
```commandline
chmod +x data_logger.sh
```

### Creating a service
```commandline
sudo cp data_logger.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable data_logger.service
sudo systemctl start data_logger.service
```
