import logging
import os
import pwd
import shutil
import subprocess
import sys
from pathlib import Path

from ai_cam.utils import is_linux

_SERVICES = ["ai_data_logger.service"]

_logger = logging.getLogger(__name__)


def _get_project_dir() -> Path | None:
    """Return the project root if running from a cloned repo, else None."""
    candidate = Path(__file__).resolve().parent.parent.parent
    if (candidate / "pyproject.toml").exists():
        return candidate
    return None


def _get_username() -> str:
    """Return the real (non-root) username."""
    return os.environ.get("SUDO_USER") or os.getlogin()


def _find_bin(name: str) -> Path | None:
    """Find a binary, checking both PATH and the invoking user's home."""
    found = shutil.which(name)
    if found:
        return Path(found)
    # Under sudo, the user's ~/.local/bin may not be on root's PATH
    username = _get_username()
    home = Path(pwd.getpwnam(username).pw_dir)
    candidate = home / ".local/bin" / name
    if candidate.exists():
        return candidate
    return None


def _get_uv() -> Path:
    """Find the uv binary."""
    uv = _find_bin("uv")
    if uv:
        return uv
    _logger.error("Could not find uv binary on PATH")
    sys.exit(1)


def _render_service(name: str, user: str, exec_start: str) -> str:
    """Generate a systemd unit file."""
    if name == "ai_data_logger.service":
        return (
            "[Unit]\n"
            "Description=AI data logger service\n"
            "After=network-online.target\n"
            "Wants=network-online.target\n"
            "\n"
            "[Service]\n"
            "Type=simple\n"
            f"User={user}\n"
            f"Group={user}\n"
            f"ExecStart={exec_start}\n"
            "Restart=always\n"
            "RestartSec=10\n"
            "WatchdogSec=30\n"
            "NotifyAccess=all\n"
            "Type=notify\n"

            "\n"
            "[Install]\n"
            "WantedBy=default.target\n"
        )

    raise ValueError(f"unknown service: {name}")

def _check_run_requirements():
    if not is_linux():
        raise OSError("System is not linux")
    if os.geteuid() != 0:
        _logger.warning("sudo required")
        os.execvp("sudo", ["sudo", sys.executable] + sys.argv)

def install_systemd(config_path: Path | None = None) -> None:
    _check_run_requirements()

    user = _get_username()
    project_dir = _get_project_dir()

    # Create default path if no config path provided
    if config_path is None:
        config_path = project_dir / "config.json"
        _logger.info("Saving default config file at %s", config_path)

    config_flag = f" --config {config_path}" if config_path else ""

    uv = _get_uv()
    _logger.info("Detected cloned repo at %s — using uv run", project_dir)

    def make_exec_start(subcmd: str) -> str:
        return f"{uv} run --project {project_dir} ai_cam {subcmd}{config_flag}"

    _logger.info("Installing systemd services for user '%s'", user)
    target_dir = Path("/etc/systemd/system")
    target_dir.mkdir(parents=True, exist_ok=True)

    # In your systemd.py loop:
    for name in _SERVICES:
        if name == "ai_data_logger.service":
            exec_start = make_exec_start("ai-detector")
        else:
            continue    

        (target_dir / name).write_text(_render_service(name, user, exec_start))

    # Start systemd services
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    for name in _SERVICES:
        subprocess.run(["systemctl", "enable", name], check=True)
        subprocess.run(["systemctl", "restart", name], check=True)
        _logger.info("%s installed & started", name)
    _logger.info("Installation complete!")


def uninstall_systemd() -> None:
    _check_run_requirements()
    target_dir = Path("/etc/systemd/system")
    for name in _SERVICES:
        subprocess.run(["systemctl", "disable", name], check=True)
        dst = target_dir / name
        os.remove(dst)
        _logger.info("%s uninstalled", name)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    _logger.info("Uninstall complete!")


def restart_systemd() -> None:
    _check_run_requirements()
    target_dir = Path("/etc/systemd/system")
    for name in _SERVICES:
        subprocess.run(["systemctl", "restart", name], check=True)
    _logger.info("Restart complete!")