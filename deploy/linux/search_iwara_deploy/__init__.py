"""Search Iwara Linux deployment manager (standard library only).

Modules, from the bottom up:

* ``shell``   – the only place that spawns processes (``systemctl``, ``nginx``, ``useradd``…)
* ``config``  – ``DeployConfig``, the env file format, legacy migration and validation
* ``render``  – systemd units, the hardening fragment and the nginx site
* ``system``  – applying a configuration to the host (accounts, venv, units, nginx, health)
* ``prompts`` – interactive questions
* ``cli``     – argparse sub-commands and the interactive menu
"""

__all__ = ["cli", "config", "prompts", "render", "shell", "system"]
