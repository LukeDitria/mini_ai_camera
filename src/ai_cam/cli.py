import asyncio
import logging
from datetime import datetime
from pathlib import Path

import click

from ai_cam.config import CamConfig
from ai_cam.detector_data_logger import DetectorLogger

from ai_cam.logging_ import init_logging
from ai_cam.notifier import NtfyNotifier
from ai_cam.utils import find_first_usb_drive
from ai_cam.systemd import install_systemd, uninstall_systemd, restart_systemd

logger = logging.getLogger("ai_cam")


@click.group()
@click.option("--verbose", is_flag=True, help="Enable debug logging.")
def cli(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    init_logging(logger=logger, level=level)

@cli.command()
@click.option("--config", type=click.Path(file_okay=True, dir_okay=False))
def ai_detector(config: str | None = None):
    _config = CamConfig.from_file(path=config)
    ai_detector = DetectorLogger(_config)

    ai_detector.run()

@cli.command(short_help="Send a test notification to the ntfy topic")
@click.option("--config", type=click.Path(file_okay=True, dir_okay=False))
def notify_test(config: str | None = None):
    _config = CamConfig.from_file(path=config)
    if not _config.ntfy_topic:
        raise click.ClickException("Set ntfy_topic in the config first")

    # The newest saved image, from where the detector saves them
    output = _config.output_dir
    usb = find_first_usb_drive() if _config.auto_select_media else None
    if usb:
        output = str(Path(usb) / "output")
    images = sorted(Path(output, "images").glob("*.jpg"), key=lambda path: path.stat().st_mtime)
    image = images[-1] if images else None

    device = _config.device_name
    notifier = NtfyNotifier(_config.ntfy_topic)
    try:
        status = notifier.send(
            title=f"{device}: test",
            message="A test notification from the AI camera" + (f", with {image.name}" if image else ""),
            jpeg=image.read_bytes() if image else None,
            filename=image.name if image else None,
            tags=(device,),
        )
    finally:
        notifier.close()
    logger.info("Sent to %s: HTTP %s", notifier.url, status)


@cli.command(short_help="Install AI Detector as systemd services")
@click.option("--config", type=click.Path(exists=True, file_okay=True, dir_okay=False))
def install(config: str | None = None):
    config_path = Path(config).resolve() if config else None
    install_systemd(config_path=config_path)


@cli.command(short_help="Uninstall  AI Detector as systemd services")
def uninstall():
    uninstall_systemd()

@cli.command(short_help="Restart AI Detector systemd services")
def restart():
    restart_systemd()

if __name__ == "__main__":
    cli()