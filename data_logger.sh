cd /home/pi/Documents/mini_ai_camera
echo powersave | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
source venv/bin/activate
python detector_data_logger.py --config_file config.json