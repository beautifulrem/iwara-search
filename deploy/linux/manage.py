#!/usr/bin/env python3
"""Search Iwara Linux deployment manager.

The single source of truth for the deployment: the env file, the systemd units and the
nginx site are all rendered by the ``search_iwara_deploy`` package next to this script.
It runs interactively (``sudo ./deploy/linux/manage.py``) and non-interactively from
``install.sh`` (``manage.py install --non-interactive ...``).

Only the standard library is used so it works before the app venv exists.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from search_iwara_deploy.cli import main

if __name__ == "__main__":
    main()
