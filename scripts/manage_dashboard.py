#!/usr/bin/env python3
# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Manage local qem-dashboard environment for integration testing."""

import os
import subprocess  # noqa: S404
import sys
import time
from pathlib import Path

try:
    import typer
except ImportError:
    sys.stdout.write(
        "Error: 'typer' module not found. Please ensure it is installed (e.g., via your virtual environment).\n"
    )
    sys.exit(1)


app = typer.Typer(help="Manage local qem-dashboard environment for integration testing")


def run_command(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:  # noqa: ANN003
    """Run a subprocess command and return the result."""
    check_result = kwargs.pop("check", True)
    return subprocess.run(cmd, check=check_result, **kwargs)  # noqa: S603


@app.command()
def start(
    podman_bin: str = typer.Option(os.environ.get("PODMAN_BIN", "podman"), help="Podman executable to use"),
    postgres_image: str = typer.Option("docker.io/library/postgres:15-alpine", help="PostgreSQL image to use"),
    dashboard_repo: str = typer.Option(
        "https://github.com/openSUSE/qem-dashboard.git", help="qem-dashboard repository URL"
    ),
    dashboard_branch: str = typer.Option("main", help="Branch to checkout for qem-dashboard"),
) -> None:
    """Start the qem-dashboard and database environment in podman."""
    typer.echo("Starting qem-dashboard in podman...")

    # Cleanup any existing containers
    run_command(
        [podman_bin, "rm", "-f", "qem-db", "qem-dashboard"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    run_command(
        [podman_bin, "network", "rm", "qem-net"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    # Create network
    run_command([podman_bin, "network", "create", "qem-net"])

    # Start DB
    run_command([
        podman_bin,
        "run",
        "-d",
        "--name",
        "qem-db",
        "--network",
        "qem-net",
        "-e",
        "POSTGRES_USER=postgres",
        "-e",
        "POSTGRES_PASSWORD=postgres",
        "-e",
        "POSTGRES_DB=postgres",
        "-p",
        "5432:5432",
        postgres_image,
    ])

    typer.echo("Waiting for postgres to be ready...")
    # Wait for DB to be responsive
    retries = 15
    while retries > 0:
        result = run_command(
            [podman_bin, "exec", "qem-db", "pg_isready", "-U", "postgres"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            typer.echo("Postgres is ready.")
            break

        typer.echo("Waiting...")
        time.sleep(2)
        retries -= 1

    if retries == 0:
        typer.secho("Error: Postgres did not start in time.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    tmp_dir = Path(".tmp")
    tmp_dir.mkdir(exist_ok=True)
    dashboard_dir = tmp_dir / "qem-dashboard"

    # Clone or update qem-dashboard
    if not dashboard_dir.is_dir():
        typer.echo("Cloning qem-dashboard repository...")
        run_command(["git", "clone", "--depth", "1", dashboard_repo, str(dashboard_dir)])
    else:
        typer.echo("Updating qem-dashboard repository...")
        run_command(["git", "pull", "origin", dashboard_branch], cwd=str(dashboard_dir))

    # Temporary fix: Containerfile is missing MCP::Server and Mojolicious::Plugin::OpenAPI
    containerfile = dashboard_dir / "Containerfile"
    if containerfile.exists():
        content = containerfile.read_text()
        if "cpanm -n MCP::Server" not in content:
            typer.echo("Applying temporary fixes to Containerfile...")
            content = content.replace(
                "perl-IO-Socket-SSL \\",
                (
                    "perl-IO-Socket-SSL \\\n"
                    "    perl-App-cpanminus \\\n"
                    "    make \\\n"
                    "    gcc \\\n"
                    "    perl-CryptX \\\n"
                    "    perl-IPC-Run \\\n"
                    "    perl-Mojolicious-Plugin-OpenAPI \\"
                ),
            )
            content = content.replace("COPY . .", "COPY . .\nRUN cpanm -n MCP::Server")

            # Remove playwright installation which downloads ~500MB of browsers we don't need for API testing
            content = content.replace(" && \\\n    npx playwright install", "")

            containerfile.write_text(content)

    # Build dashboard
    typer.echo("Building qem-dashboard container image (this may take a few minutes)...")
    run_command([podman_bin, "build", "-t", "qem-dashboard:latest", "-f", str(containerfile), str(dashboard_dir)])

    # Start Dashboard
    typer.echo("Starting qem-dashboard...")
    run_command([
        podman_bin,
        "run",
        "-d",
        "--name",
        "qem-dashboard",
        "--network",
        "qem-net",
        "-e",
        'DASHBOARD_CONF_OVERRIDE={"pg":"postgresql://postgres:postgres@qem-db:5432/postgres"}',
        "-p",
        "3000:3000",
        "qem-dashboard:latest",
        "script/dashboard",
        "daemon",
        "-l",
        "http://*:3000",
    ])

    typer.secho("Dashboard started on http://localhost:3000", fg=typer.colors.GREEN)


@app.command()
def stop(
    podman_bin: str = typer.Option(os.environ.get("PODMAN_BIN", "podman"), help="Podman executable to use"),
) -> None:
    """Stop the qem-dashboard and database containers and remove the network."""
    typer.echo("Stopping qem-dashboard and database...")

    run_command(
        [podman_bin, "rm", "-f", "qem-dashboard", "qem-db"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    run_command(
        [podman_bin, "network", "rm", "qem-net"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    typer.echo("Cleanup complete.")


if __name__ == "__main__":
    app()
