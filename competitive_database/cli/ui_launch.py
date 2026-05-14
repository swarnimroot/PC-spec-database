"""``ui`` CLI subcommand — launch the local browser UI.

Shells out to ``python -m streamlit run`` against
``competitive_database/ui/app.py``. Binds the server to ``127.0.0.1`` so
nothing leaves the machine; Streamlit's default behaviour auto-opens a
browser tab on first launch. The resolved DB path is forwarded to the
Streamlit child process via ``COMPETITIVE_DB_PATH``.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "ui",
        help="Launch the local browser UI (Streamlit).",
    )
    p.add_argument(
        "--db",
        default="competitive.db",
        help="Path to the SQLite DB file.",
    )
    p.add_argument(
        "--port",
        type=int,
        default=8501,
        help="Port for the Streamlit server (default 8501).",
    )
    p.add_argument(
        "--base-path",
        default=None,
        help=(
            "Subpath under a reverse proxy (e.g. ``competitive-database`` "
            "for ``https://host/competitive-database``). When set, also "
            "applies the reverse-proxy companion flags (headless, CORS + "
            "XSRF off). Leave unset for local-only use."
        ),
    )
    p.set_defaults(func=main)


def main(args: argparse.Namespace) -> None:
    app_path = Path(__file__).resolve().parent.parent / "ui" / "app.py"
    env = os.environ.copy()
    env["COMPETITIVE_DB_PATH"] = str(Path(args.db).resolve())
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.address=127.0.0.1",
        f"--server.port={args.port}",
    ]
    if args.base_path:
        base = args.base_path.strip("/")
        cmd.extend(
            [
                f"--server.baseUrlPath={base}",
                "--server.headless=true",
                "--server.enableCORS=false",
                "--server.enableXsrfProtection=false",
            ]
        )
    try:
        subprocess.run(cmd, env=env, check=True)
    except FileNotFoundError as exc:
        raise SystemExit(
            "ui: streamlit is not installed. Run `pip install streamlit` "
            "(or `pip install -e .[ui]` from the repo root) and try again."
        ) from exc
    except KeyboardInterrupt:
        pass
