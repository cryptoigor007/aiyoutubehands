"""Optional macOS menu-bar tray (rumps). Degrades gracefully if unavailable."""

from __future__ import annotations

import shutil
import subprocess
import sys

import click


def register(cli: click.Group) -> None:
    @cli.command("tray")
    @click.option(
        "--path",
        "root_path",
        default=None,
        help="Путь Shorts Maker по умолчанию для быстрых действий",
    )
    def tray_cmd(root_path: str | None) -> None:
        """Иконка в строке меню macOS (свернуть / быстрые команды).

        Требует: pip install rumps  (только macOS).
        Правый клик по иконке: Analyze (dry-run), Doctor, Quit.
        """
        if sys.platform != "darwin":
            click.echo(
                "ayh tray рассчитан на macOS (menu bar).\n"
                "На этой ОС используйте CLI: ayh process analyze/apply/run",
                err=True,
            )
            raise SystemExit(2)

        try:
            import rumps  # type: ignore[import-untyped]
        except ImportError:
            click.echo(
                "Пакет rumps не установлен.\n"
                "  pip install rumps\n"
                "или: pip install 'aiyoutubehands[tray]'",
                err=True,
            )
            raise SystemExit(2) from None

        app = _build_app(rumps, root_path)
        app.run()


def _build_app(rumps: object, root_path: str | None) -> object:
    """Build rumps.App with menu actions."""

    class AyhTray(rumps.App):  # type: ignore[name-defined]
        def __init__(self) -> None:
            super().__init__(
                "ayh",
                title="ayh",
                quit_button=None,  # custom Quit
            )
            self.root_path = root_path
            self.menu = [
                rumps.MenuItem("Process: analyze (dry-run)", callback=self.on_analyze),
                rumps.MenuItem("Doctor", callback=self.on_doctor),
                rumps.separator,
                rumps.MenuItem("Открыть Terminal с ayh", callback=self.on_terminal),
                rumps.separator,
                rumps.MenuItem("Quit ayh tray", callback=self.on_quit),
            ]

        def _run_ayh(self, args: list[str]) -> None:
            # Prefer installed entrypoint, fall back to python -m
            cmd: list[str]
            if shutil.which("ayh"):
                cmd = ["ayh", *args]
            else:
                cmd = [sys.executable, "-m", "aiyoutubehands.main", *args]
            try:
                subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                rumps.notification(  # type: ignore[attr-defined]
                    "ayh",
                    "Запущено",
                    " ".join(args)[:80],
                )
            except OSError as exc:
                rumps.notification("ayh", "Ошибка запуска", str(exc)[:120])  # type: ignore[attr-defined]

        def on_analyze(self, _sender: object) -> None:
            args = ["process", "analyze", "--dry-run"]
            if self.root_path:
                args.extend(["--path", self.root_path])
            # dry-run analyze still needs path; if missing, open terminal hint
            if not self.root_path:
                rumps.notification(  # type: ignore[attr-defined]
                    "ayh",
                    "Нужен --path",
                    "Перезапустите: ayh tray --path /path/to/ShortsMaker",
                )
                return
            self._run_ayh(args)

        def on_doctor(self, _sender: object) -> None:
            self._run_ayh(["doctor"])

        def on_terminal(self, _sender: object) -> None:
            # Open Terminal.app in project-friendly way
            script = (
                'tell application "Terminal" to do script "ayh process --help"'
            )
            subprocess.Popen(["osascript", "-e", script])

        def on_quit(self, _sender: object) -> None:
            rumps.quit_application()  # type: ignore[attr-defined]

    return AyhTray()
