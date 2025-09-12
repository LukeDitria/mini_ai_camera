# Installing Requirements
Steps for setting up your raspberry pi!
You'll need to install a few things first...

### Update Pi if you haven't already
```commandline
sudo apt update && sudo apt full-upgrade
```

## Picamera2
#### Picamera2 will already be install on the full desktop version
#### On systems where Picamera2 is supported but not pre-installed (Such as the Lite OS), you can install it with
```commandline
sudo apt install python3-picamera2
```
#### OR to get a slightly reduced installation with fewer of the window system related elements (USE THIS for installing on a Raspberry Pi OS Lite system)
```commandline
sudo apt install python3-picamera2 --no-install-recommends
```

## Other Requirements
### IMX500 (AI Camera)
```commandline
sudo apt install imx500-all
```
### picamera2 tells us to install system wide
### Therefore we need to install opencv etc, also at the system level...
### E.G.
```commandline
sudo apt install python3-opencv
```

## OS Lite!
### If you're using the Lite OS you will also need to install:
```commandline
sudo apt install python3-picamera2 --no-install-recommends
sudo apt install git
```

## Reboot Pi after install!

```commandline
sudo reboot now
```

# Git Clone the repo!
### If using the Lite OS first
```commandline
mkdir Documents
```
### then
```commandline
cd Documents
git clone https://github.com/LukeDitria/mini_ai_camera.git
```

## Install pip requirements including system-wide packages (we need to use the system picamera2 install...)
```commandline
cd mini_ai_camera/
python -m venv venv --system-site-packages
source venv/bin/activate
pip install -r requirements.txt
deactivate
```

## Check file paths in data_logger.sh and data_logger.service are correct for you!!
### Activate script
```commandline
chmod +x data_logger.sh
```
### Test run!
```commandline
./data_logger.sh
```

## Creating a service
```commandline
sudo cp data_logger.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable data_logger.service
sudo systemctl start data_logger.service
```

# Auto Mounting a USB Drive!
### If you are using the full desktop OS then ANY USB storage device will be automatically mounted in /media
### However, if you are using the OS Lite this will not happen and you will need to configure every USB device you want to use
### so it will auto mount when plugged in...
### Follow this guide to know how!
[Mount a USB Drive to the Raspberry Pi Manually](https://pimylifeup.com/raspberry-pi-mount-usb-drive/)

