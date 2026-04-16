# Mini Raspberry Pi AI Wildlife monitor!
Video here:
https://youtu.be/qhY_3XCSYsM

## Installing Requirements!
Steps for setting up your raspberry pi!
You'll need to install a few things first...

## Requirements
PV PI Manager is designed to operate on Raspberry Pi compatible devices.  
The following setup was verified on a Raspberry Pi 5 and Pi Zero 2W with Raspberry Pi OS Trixie.<br>
It requires Python>=3.13

### Update Pi if you haven't already
```commandline
sudo apt update && sudo apt full-upgrade -y
```

### Picamera2
#### Picamera2 will already be install on the full desktop version. On systems where Picamera2 is supported but not pre-installed you can install it with:
```commandline
sudo apt install python3-picamera2 -y
```
#### Use this slightly reduced installation for installing on a Raspberry Pi __OS Lite system!__
```commandline
sudo apt install python3-picamera2 --no-install-recommends -y
```

### Other Requirements
#### IMX500 (AI Camera)
```commandline
sudo apt install imx500-all -y
```
#### picamera2 tells us to install system wide
#### Therefore we need to install opencv etc, also at the system level...
```commandline
sudo apt install python3-opencv -y
```

### OS Lite!
#### If you're using the Lite OS you will also need to install:
```commandline
sudo apt install git -y
```

### Python `uv`

Python packager manager [uv](https://docs.astral.sh/uv) is the preferred method for operating the mini_ai_camera.
```shell
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Reboot Pi after install!
```commandline
sudo reboot now
```


# mini_ai_camera Installation

Clone the repo:
```shell
git clone https://github.com/LukeDitria/mini_ai_camera.git
```

# Install requirements including system-wide packages (we need to use the system picamera2 install...)
```commandline
cd mini_ai_camera
uv venv --system-site-packages
uv sync
```

## Quick-start

```shell
uv run ai_cam  # show usage help
```

## Install AI Camera Service
Repo comes with an `install` command to setup the systemd service

```shell
uv run ai_cam install
```

# Updating the config.json
When you install the service a default config.json file will be created in the mini_ai_camera directory. Subsequent restarts of the service will load configuration parameters from this config.json.

You can change the behaviour of the services by editing and saving this file and restarting the AI detector services.
```shell
uv run ai_cam restart
```

## Configuration
All settings live in `config.json`

| Key | Default | Description |
|---|---|---|
| `output_dir` | `output` | Local fallback output directory |
| `device_name` | `site1` | Name embedded in output filenames |
| `model` | `yolov8n.rpk` | Path to the compiled yolo model file |
| `labels` | `coco_labels.txt` | Path to class labels |
| `valid_classes` | *(none)* | Optional path to a subset of classes to detect |
| `confidence` | `0.5` | Detection confidence threshold (0–1) |
| `iou_threshold` | `0.5` | NMS IoU threshold (0–1) |
| `ips` | `5` | Max inferences per second |
| `lps` | *(none)* | Max log writes per second (defaults to every inference) |
| `video_size` | `"1920,1080"` | Camera resolution as `"width,height"` |
| `buffer_secs` | `3` | Circular video buffer length in seconds |
| `detection_run` | `5` | Consecutive detections before recording starts |
| `save_video` | `false` | Save H.264 video clips |
| `save_images` | `false` | Save JPEG frames on detection |
| `save_data` | `false` | Save per-detection JSON files |
| `draw_bbox` | `false` | Draw bounding boxes on saved images |
| `auto_select_media` | `false` | Auto-detect USB drive under `/media` for output |


# More about systemd

(i) `systemd` is the standard system and service manager for modern Linux distributions. Once installed, you can check the `status`, `start`, `stop`, or `restart` the Ai Cam services using the `systemctl` command:
```shell
sudo systemctl status ai_data_logger.service
```

For example, to stop and disable the service so it will no longer run on boot:
```shell
sudo systemctl stop ai_data_logger.service
sudo systemctl disable ai_data_logger.service
```

While the status of services can be viewed with `systemctl` as shown above, the log output can be followed using `journalctl`.

To follow the **live** log output from the service:
```shell
journalctl -u ai_data_logger.service -f
```

(i) `journalctl` is a Linux command-line tool for viewing and managing logs from `systemd`. Logs can be filtered by process and time. [Learn more](https://www.digitalocean.com/community/tutorials/how-to-use-journalctl-to-view-and-manipulate-systemd-logs).

# Auto Mounting a USB Drive!
### If you are using the full desktop OS then ANY USB storage device will be automatically mounted in /media
### However, if you are using the OS Lite this will not happen and you will need to configure *every* USB device you want to use so it will auto mount when plugged in...
## 📂 Auto-Mounting a USB Drive by UUID

If you want your Raspberry Pi (or Linux system) to automatically mount a USB drive at boot, you can use its **UUID** in `/etc/fstab`. This ensures the correct drive is mounted every time, even if the device path (`/dev/sda1`, `/dev/sdb1`, etc.) changes.

### 1. Find the UUID of Your USB Drive
First, plug in your USB drive and find its partition (e.g /dev/sda1):
```commandline
lsblk -o NAME,SIZE,MODEL,MOUNTPOINT
```
then find it's UUID (replace /dev/sda1 with your USB device partition)
```commandline
sudo blkid /dev/sda1
```

 You'll see something like:
```bash
/dev/sda1: UUID="17F8-3814" BLOCK_SIZE="512" TYPE="vfat"
```
Note down the UUID and TYPE

### Create a mount point
```commandline
sudo mkdir -p /media/pi/myusb
sudo chown -R pi:pi /media/pi/myusb/
```

### Edit /etc/fstab to include your device
```commandline
sudo nano /etc/fstab
```

Add this line at the end using YOUR UUID and TYPE!!

```commandline
UUID=17F8-3814  /media/pi/myusb  vfat  defaults,uid=1000,gid=1000,umask=000  0  0
```
You may need to run 
```commandline
systemctl daemon-reload
```

### Testing that it works
```commandline
sudo mount -a
df -h
```
You should see a line like
```commandline
/dev/sda1       115G  140M  115G   1% /media/pi/myusb
```

### Reboot!
Reboot your Pi and then run 
```commandline
df -h
```
To see if it has mounted automatically!
