# Mini Raspberry Pi AI Wildlife monitor!
Video here:
https://youtu.be/qhY_3XCSYsM

# 1. Installing Requirements!
Steps for setting up your raspberry pi!
You'll need to install a few things first...

## Base System Requirements 
The following setup was verified on a Raspberry Pi 5 and Pi Zero 2W with Raspberry Pi OS **Trixie**.<br>
It requires **system wide** Python>=3.13<br>
It's best if you start with a fresh OS...

### Update Pi if you haven't already
```commandline
sudo apt update && sudo apt full-upgrade -y
```

## Picamera2
Picamera2 will already be install on the **full desktop version**. On systems where Picamera2 is supported but not pre-installed you can install it with:
```commandline
sudo apt install python3-picamera2 -y
```
 Use this slightly reduced installation for installing on a Raspberry Pi **OS Lite system!**
```commandline
sudo apt install python3-picamera2 --no-install-recommends -y
```

## IMX500 (AI Camera)
```commandline
sudo apt install imx500-all -y
```

## OpenCV
picamera2 tells us to install **system wide**. Therefore we need to install opencv etc, also at the system level...
```commandline
sudo apt install python3-opencv -y
```

numpy comes with these system packages too. Don't install numpy, opencv or picamera2 into the project's environment with pip or uv: the system versions are the ones that work with the camera.

## OS Lite!
If you're using the Lite OS you will also need to install:
```commandline
sudo apt install git -y
```

## Python `uv`

Python packager manager [uv](https://docs.astral.sh/uv) is the preferred method for operating the mini_ai_camera.
```shell
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Reboot Pi after install!
```commandline
sudo reboot now
```


# 2. mini_ai_camera Installation

Clone the repo:
```shell
git clone https://github.com/LukeDitria/mini_ai_camera.git
```

## Install requirements including system-wide packages (we need to use the system picamera2 install...)
```commandline
cd mini_ai_camera
uv venv --system-site-packages
uv sync
```

## Quick-start

```shell
uv run ai_cam
```

## Install AI Camera Service
Repo comes with an `install` command to setup the systemd service

```shell
uv run ai_cam install
```

## Updating
To update to the latest version, pull the changes, sync the environment and restart the service:
```shell
git pull
uv sync
uv run ai_cam restart
```

# 3. Updating the config.json
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
| `model` | `models/yolov8n.rpk` | Path to the compiled yolo model file |
| `labels` | `models/coco_labels.txt` | Path to class labels |
| `valid_classes` | *(none)* | Optional path to a subset of classes to detect |
| `confidence` | `0.5` | Detection confidence threshold (0–1) |
| `iou_threshold` | `0.5` | NMS IoU threshold (0–1) |
| `ips` | `5` | Max inferences per second |
| `video_size` | `"1920,1080"` | Camera resolution as `"width,height"` |
| `buffer_secs` | `3` | Circular video buffer length in seconds |
| `ema_alpha` | `0.2` | How quickly each class's smoothed confidence follows new detections (0–1) |
| `event_activate` | `0.8` | Smoothed confidence at which an event starts |
| `event_deactivate` | `0.5` | Smoothed confidence below which an event ends |
| `save_video` | `false` | Save H.264 video clips |
| `save_images` | `false` | Save JPEG frames on detection |
| `save_data` | `true` | Save per-detection JSON files |
| `draw_bbox` | `false` | Draw bounding boxes on saved images |
| `auto_select_media` | `false` | Auto-detect USB drive under `/media` for output |
| `zoom_to_roi` | `false` | Re-check uncertain detections with the camera zoomed in on them (see below) |
| `zoom_below` | `0.5` | Detections below this confidence are re-checked zoomed in |
| `zoom_timeout_secs` | `1` | How long to wait for the zoomed view before keeping the original detection |
| `save_zoom_images` | `false` | Save the zoomed image of each re-checked detection |
| `ntfy_topic` | *(none)* | The ntfy topic to send detections to (see below) |
| `ntfy_cooldown_secs` | `60` | The shortest time between notifications for the same species |

## Zooming in on uncertain detections
The AI camera can run its model on just part of the sensor. With `zoom_to_roi` on, a detection under `zoom_below` is checked again with the model zoomed in on it, which gives a small or distant animal many more pixels:
- if the zoomed view finds something, that replaces the uncertain detection;
- if it finds nothing, the detection is dropped;
- if the camera doesn't answer within `zoom_timeout_secs`, the original detection is kept.

Each check takes a few hundred milliseconds, while the camera switches over and back. With `save_zoom_images` on, the zoomed part of the frame is saved too, as `<device>_zoom_<class>_<time>.jpg`.


## Phone notifications! (ntfy)
Want a ping on your phone when a bird turns up? The camera can send you a notification, with a picture, using [ntfy](https://ntfy.sh).
1. Install the ntfy app on your phone and subscribe to a topic, e.g. `my-camera-alerts-7f3k`.
2. Put that same topic in `config.json`: `"ntfy_topic": "my-camera-alerts-7f3k"`, then restart the service.
3. Send yourself a test (it uses the newest saved image):
```shell
uv run ai_cam notify-test --config config.json
```

You'll get one notification per species when it first shows up, even if another species is already there, with your `device_name` in the title. A species won't notify again until it has left and come back, and never more often than `ntfy_cooldown_secs`.

**Heads up:** anyone who knows a topic name on ntfy.sh can subscribe to it, so pick something hard to guess!

# 4. More about systemd

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

# 5. Auto Mounting a USB Drive! (Optional)
If **auto_select_media** is set to **true** (it is false by default) the data_logger will try to find a storage device in /media to save image/video/data to. <br>
<br>
If you are using the full desktop OS then ANY USB storage device will be automatically mounted in /media.
**However**, if you are using the **OS Lite** this will not happen and you will need to configure *every* USB device you want to use so it will auto mount when plugged in...
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
