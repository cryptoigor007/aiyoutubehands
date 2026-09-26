"""doctor command."""

from __future__ import annotations

import json
import sys

import click

from aiyoutubehands import __version__


def register(cli: click.Group) -> None:
    @cli.command()
    @click.option("--json", "as_json", is_flag=True, help="Вывод в JSON")
    @click.pass_context
    def doctor(ctx: click.Context, as_json: bool) -> None:
        """Диагностика окружения и конфигурации."""
        log = ctx.obj["log"]
        log.info("doctor_started")
        result: dict = {
            "ok": True,
            "version": __version__,
            "checks": {},
        }
        try:
            from aiyoutubehands.config import get_config_dir, get_state_dir

            result["checks"]["config_dir"] = str(get_config_dir())
            result["checks"]["state_dir"] = str(get_state_dir())
        except Exception as exc:  # noqa: BLE001
            result["ok"] = False
            result["checks"]["config"] = str(exc)

        try:
            from aiyoutubehands.logging import get_logger as gl

            gl("doctor-test")
            result["checks"]["logging"] = "ok"
        except Exception as exc:  # noqa: BLE001
            result["ok"] = False
            result["checks"]["logging"] = str(exc)

        modules = (
            "aiyoutubehands.token",
            "aiyoutubehands.quota",
            "aiyoutubehands.client",
            "aiyoutubehands.calendar",
            "aiyoutubehands.youtube",
            "aiyoutubehands.ai",
            "aiyoutubehands.upload",
        )
        mod_status: dict[str, str] = {}
        for mod in modules:
            try:
                __import__(mod)
                mod_status[mod.split(".")[-1]] = "ok"
            except Exception as exc:  # noqa: BLE001
                mod_status[mod.split(".")[-1]] = f"error: {exc}"
                result["ok"] = False
        result["checks"]["modules"] = mod_status

        if as_json:
            click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            status = "OK" if result["ok"] else "ОШИБКА"
            click.echo(f"doctor: {status}")
            click.echo(f"версия: {result['version']}")
            for k, v in result["checks"].items():
                click.echo(f"  {k}: {v}")
        log.info("doctor_finished", ok=result["ok"])
        if not result["ok"]:
            sys.exit(1)
