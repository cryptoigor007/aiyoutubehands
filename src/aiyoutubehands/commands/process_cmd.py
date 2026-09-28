"""process — safe post-processing of already uploaded Shorts Maker videos."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import click

from aiyoutubehands.client import require_access_token
from aiyoutubehands.commands.security import require_passphrase

_CONFIRM_RE = re.compile(r"^подтверждаю план от (\d{2}\.\d{2}\.\d{4}) #([0-9a-f]{12})$")


def _parse_confirm(confirm: str) -> tuple[str, str]:
    """Разобрать фразу подтверждения в (дата, хэш плана).

    Фраза обязана включать хэш: без него подтверждение не отличает один план
    от другого, и оператор может подтвердить один набор, а применить другой.
    """
    m = _CONFIRM_RE.match((confirm or "").strip())
    if not m:
        raise click.ClickException(
            "Фраза должна быть: «подтверждаю план от ДД.ММ.ГГГГ #<хэш>».\n"
            "Хэш печатается вместе с планом (analyze или apply --dry-run)."
        )
    return m.group(1), m.group(2)


def _require_fingerprint_match(plan: object, expected: str) -> None:
    """Отказ, если текущий план не тот, который подтвердили."""
    from aiyoutubehands.shorts_maker.plan import ProcessPlan

    if not isinstance(plan, ProcessPlan):
        raise TypeError("plan должен быть ProcessPlan")
    if plan.fingerprint != expected:
        raise click.ClickException(
            "План изменился после подтверждения (хэш не совпал).\n"
            f"Подтверждён: {expected}\n"
            f"Сейчас:      {plan.fingerprint}\n"
            "Покажите план заново и подтвердите новый хэш."
        )


def register(cli: click.Group) -> None:
    @cli.group(invoke_without_command=True)
    @click.pass_context
    def process(ctx: click.Context) -> None:
        """Пост-обработка уже загруженных видео (Shorts Maker).

        Перед работой AI и оператор обязаны следовать docs/AGENT_PROMPT_PROCESS.md
        """
        # Баннер на каждом вызове `ayh process …`, включая голый `process`.
        # При `--help` click выходит раньше колбэка, поэтому там баннера нет.
        from aiyoutubehands.agent_rules import print_safety_banner

        print_safety_banner(echo=click.echo)
        if ctx.invoked_subcommand is None:
            click.echo(ctx.get_help())
            ctx.exit(2)

    @process.command("rules")
    def process_rules() -> None:
        """Показать путь и полный текст обязательных правил для AI/оператора."""
        from aiyoutubehands.agent_rules import load_rules_text, rules_file_path

        path = rules_file_path()
        text = load_rules_text()
        if path is None or text is None:
            raise click.ClickException(
                "docs/AGENT_PROMPT_PROCESS.md не найден. Откройте репозиторий целиком."
            )
        click.echo(text)

    @process.command("analyze")
    @click.option(
        "--path",
        "root_path",
        type=click.Path(exists=True, file_okay=False, path_type=Path),
        default=None,
        help="Корневая папка Shorts Maker",
    )
    @click.option("--days", default=14, show_default=True, help="Горизонт видео на канале")
    @click.option(
        "--dry-run/--no-dry-run",
        default=False,
        help="dry-run: не ходить в API канала (план без сопоставления). "
        "По умолчанию канал читается; записи на канал нет.",
    )
    @click.option("--json", "as_json", is_flag=True)
    @click.option("--save-plan", type=click.Path(path_type=Path), default=None)
    @click.option(
        "--playlist",
        default=None,
        help="ID плейлиста (по умолчанию не добавлять; для Shorts обычно пусто)",
    )
    @click.option(
        "--allow-ai",
        is_flag=True,
        help="Если нет description/tags — сгенерировать через ayh ai (local stub)",
    )
    def process_analyze(
        root_path: Path | None,
        days: int,
        dry_run: bool,
        as_json: bool,
        save_plan: Path | None,
        playlist: str | None,
        allow_ai: bool,
    ) -> None:
        """Сканировать папку Shorts Maker, сопоставить с каналом, показать план."""
        if root_path is None:
            entered = click.prompt("Путь к корневой папке Shorts Maker", type=str)
            root_path = Path(entered).expanduser()
            if not root_path.is_dir():
                raise click.ClickException(f"Папка не найдена: {root_path}")

        passphrase = require_passphrase(None)

        from aiyoutubehands.service_factory import build_youtube_service
        from aiyoutubehands.shorts_maker.folder_scanner import scan_root
        from aiyoutubehands.shorts_maker.ledger import ProcessedLedger
        from aiyoutubehands.shorts_maker.matcher import match_candidates
        from aiyoutubehands.shorts_maker.plan import build_plan, render_plan_table

        yt, client = build_youtube_service(passphrase=passphrase)
        try:
            click.echo(f"Сканирую {root_path} …")
            candidates = scan_root(root_path)
            click.echo(f"Найдено подпапок: {len(candidates)}")

            if dry_run:
                click.echo(
                    "dry-run: список видео канала не запрашивается — "
                    "сопоставление будет пустым. Уберите --dry-run для реального плана."
                )
                videos: list[Any] = []
            else:
                click.echo(f"Загружаю видео канала (последние {days} дн.) …")
                raw = yt.list_channel_videos(max_age_days=days, dry_run=False)
                videos = raw if isinstance(raw, list) else []
                click.echo(f"Видео на канале: {len(videos)}")

            playlist_id = _resolve_playlist(playlist, yt=yt if not dry_run else None)

            in_playlist_ids: set[str] | None = None
            if not dry_run:
                try:
                    mid = yt.list_video_ids_in_playlists(dry_run=False)
                    if isinstance(mid, set):
                        in_playlist_ids = mid
                        click.echo(f"В плейлистах: {len(in_playlist_ids)} видео")
                except Exception as exc:  # noqa: BLE001
                    click.echo(f"Не удалось загрузить membership плейлистов: {exc}")

            ledger = ProcessedLedger()
            matches = match_candidates(
                candidates,
                videos,
                max_age_days=days,
                processed_ids=ledger.all_ids(),
                in_playlist_ids=in_playlist_ids,
            )
            plan = build_plan(
                matches,
                root_path=root_path,
                quota=yt.quota,
                playlist_id=playlist_id,
                allow_ai=allow_ai,
            )

            if save_plan:
                _save_plan_json(plan, save_plan)
                click.echo(f"План сохранён: {save_plan}")

            if as_json:
                click.echo(json.dumps(_plan_to_dict(plan), ensure_ascii=False, indent=2))
            else:
                click.echo(render_plan_table(plan))
                if not playlist_id:
                    click.echo(
                        "Плейлист: не задан (по умолчанию для Shorts). "
                        "Укажите --playlist ID при необходимости."
                    )
        finally:
            client.close()

    @process.command("apply")
    @click.option(
        "--confirm",
        default=None,
        help="Точная фраза: «подтверждаю план от ДД.ММ.ГГГГ #<хэш плана>»",
    )
    @click.option(
        "--path",
        "root_path",
        type=click.Path(exists=True, file_okay=False, path_type=Path),
        required=True,
        help="Корневая папка Shorts Maker (та же, что при analyze)",
    )
    @click.option("--days", default=14, show_default=True)
    @click.option("--yes", is_flag=True)
    @click.option("--dry-run/--no-dry-run", default=True)
    @click.option("--playlist", default=None, help="ID плейлиста (опционально)")
    @click.option("--allow-ai", is_flag=True)
    @click.option(
        "--plan",
        "plan_file",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        default=None,
        help="Файл analyze --save-plan для сверки: применится только он",
    )
    def process_apply(
        confirm: str,
        root_path: Path,
        days: int,
        yes: bool,
        dry_run: bool,
        playlist: str | None,
        allow_ai: bool,
        plan_file: Path | None,
    ) -> None:
        """Применить план после точного подтверждения."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from aiyoutubehands.service_factory import build_youtube_service
        from aiyoutubehands.shorts_maker.folder_scanner import scan_root
        from aiyoutubehands.shorts_maker.ledger import ProcessedLedger
        from aiyoutubehands.shorts_maker.matcher import match_candidates
        from aiyoutubehands.shorts_maker.plan import build_plan, render_plan_table
        from aiyoutubehands.shorts_maker.processor import apply_plan

        if dry_run:
            # Предпросмотр полностью офлайн: план берём из файла, если он дан.
            if plan_file is None:
                raise click.ClickException(
                    "apply --dry-run не запрашивает видео канала, поэтому плана нет.\n"
                    "Показать план: ayh process analyze --path <PATH>\n"
                    "Либо передайте сохранённый план: "
                    "ayh process apply --path <PATH> --plan <файл> --dry-run"
                )
            saved = json.loads(plan_file.read_text(encoding="utf-8"))
            click.echo(f"План из {plan_file} (dry-run, сеть не используется)")
            click.echo(f"Хэш плана: {saved.get('fingerprint', '<нет>')}")
            click.echo(f"Фраза подтверждения: {saved.get('confirm_phrase', '<нет>')}")
            for item in saved.get("items") or []:
                click.echo(
                    f"  {item.get('video_id') or '—':<12} "
                    f"{item.get('status', ''):<24} {item.get('new_title', '')}"
                )
            return

        if not confirm:
            raise click.ClickException(
                "Нужен --confirm: «подтверждаю план от ДД.ММ.ГГГГ #<хэш плана>»"
            )
        expected_date = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y")
        phrase_date, phrase_fp = _parse_confirm(confirm)
        if phrase_date != expected_date:
            raise click.ClickException(
                f"Дата во фразе не сегодняшняя: {phrase_date}, ожидается {expected_date}"
            )

        if not yes and not dry_run:
            raise click.ClickException("Нужен --yes вместе с --no-dry-run")

        passphrase = require_passphrase(None)
        yt, client = build_youtube_service(passphrase=passphrase)
        try:
            candidates = scan_root(root_path)
            if dry_run:
                videos: list[Any] = []
            else:
                raw = yt.list_channel_videos(max_age_days=days, dry_run=False)
                videos = raw if isinstance(raw, list) else []

            playlist_id = _resolve_playlist(playlist, yt=yt if not dry_run else None)
            in_playlist_ids: set[str] | None = None
            if not dry_run:
                try:
                    mid = yt.list_video_ids_in_playlists(dry_run=False)
                    if isinstance(mid, set):
                        in_playlist_ids = mid
                except Exception as exc:  # noqa: BLE001
                    click.echo(f"membership плейлистов пропущен: {exc}")
            ledger = ProcessedLedger()
            matches = match_candidates(
                candidates,
                videos,
                max_age_days=days,
                processed_ids=ledger.all_ids(),
                in_playlist_ids=in_playlist_ids,
            )
            plan = build_plan(
                matches,
                root_path=root_path,
                quota=yt.quota,
                playlist_id=playlist_id,
                allow_ai=allow_ai,
            )

            if plan.quota_projection.get("would_exceed"):
                raise click.ClickException(
                    "Квота будет превышена. Дождитесь сброса или уменьшите план."
                )

            # Подтверждение привязано к содержимому: план, показанный оператору,
            # и план, который применяется, обязаны совпасть.
            _require_fingerprint_match(plan, phrase_fp)

            if plan_file is not None:
                saved = json.loads(plan_file.read_text(encoding="utf-8"))
                saved_fp = str(saved.get("fingerprint") or "")
                if saved_fp != plan.fingerprint:
                    raise click.ClickException(
                        f"План из {plan_file} не совпадает с текущим.\n"
                        f"В файле: {saved_fp or '<нет поля fingerprint>'}\n"
                        f"Сейчас:  {plan.fingerprint}\n"
                        "Запустите analyze заново и подтвердите актуальный план."
                    )

            actionable = plan.actionable_items()
            if not actionable:
                click.echo("Нет видео для обработки.")
                return

            # План всегда показывается перед применением.
            click.echo(render_plan_table(plan))
            click.echo(f"Хэш плана: {plan.fingerprint}")
            click.echo(f"Применяю {len(actionable)} видео (dry_run={dry_run}) …")
            token = require_access_token(client.access_token)
            report = apply_plan(
                plan,
                yt,
                access_token=token,
                dry_run=dry_run,
                yes=yes or dry_run,
                ledger=ledger,
            )
            click.echo(report.summary())
            click.echo(
                f"Квота после: used={yt.quota.used_today()} remaining={yt.quota.remaining()}"
            )
        finally:
            client.close()

    @process.command("run")
    @click.option(
        "--path",
        "root_path",
        type=click.Path(exists=True, file_okay=False, path_type=Path),
        default=None,
    )
    @click.option("--days", default=14, show_default=True)
    @click.option("--yes", is_flag=True)
    @click.option("--dry-run/--no-dry-run", default=True)
    @click.option("--allow-ai", is_flag=True)
    def process_run(
        root_path: Path | None,
        days: int,
        yes: bool,
        dry_run: bool,
        allow_ai: bool,
    ) -> None:
        """Интерактивно: analyze → плейлист? → подтверждение → apply."""
        from aiyoutubehands.service_factory import build_youtube_service
        from aiyoutubehands.shorts_maker.folder_scanner import scan_root
        from aiyoutubehands.shorts_maker.ledger import ProcessedLedger
        from aiyoutubehands.shorts_maker.matcher import match_candidates
        from aiyoutubehands.shorts_maker.plan import build_plan, render_plan_table
        from aiyoutubehands.shorts_maker.processor import apply_plan

        if root_path is None:
            entered = click.prompt("Путь к корневой папке Shorts Maker", type=str)
            root_path = Path(entered).expanduser()
            if not root_path.is_dir():
                raise click.ClickException(f"Папка не найдена: {root_path}")

        # Playlist question (TZ: ask user; default for Shorts = none)
        pl_answer = click.prompt(
            "Добавить в плейлист? (нет / указать ID или название)",
            default="нет",
            show_default=True,
        )

        passphrase = require_passphrase(None)
        yt, client = build_youtube_service(passphrase=passphrase)
        try:
            candidates = scan_root(root_path)
            click.echo(f"Подпапок: {len(candidates)}")

            if dry_run:
                click.echo("dry-run: канал не запрашивается")
                videos: list[Any] = []
            else:
                raw = yt.list_channel_videos(max_age_days=days, dry_run=False)
                videos = raw if isinstance(raw, list) else []
                click.echo(f"Видео на канале: {len(videos)}")

            playlist_id = _resolve_playlist(pl_answer, yt=yt if not dry_run else None)

            in_playlist_ids: set[str] | None = None
            if not dry_run:
                try:
                    mid = yt.list_video_ids_in_playlists(dry_run=False)
                    if isinstance(mid, set):
                        in_playlist_ids = mid
                except Exception as exc:  # noqa: BLE001
                    click.echo(f"membership плейлистов пропущен: {exc}")

            ledger = ProcessedLedger()
            matches = match_candidates(
                candidates,
                videos,
                max_age_days=days,
                processed_ids=ledger.all_ids(),
                in_playlist_ids=in_playlist_ids,
            )
            plan = build_plan(
                matches,
                root_path=root_path,
                quota=yt.quota,
                playlist_id=playlist_id,
                allow_ai=allow_ai,
            )
            click.echo(render_plan_table(plan))

            if not plan.actionable_items():
                click.echo("Нечего применять.")
                return

            phrase = click.prompt(
                f"Для применения введите точно: {plan.confirm_phrase}",
                type=str,
            )
            if phrase.strip() != plan.confirm_phrase:
                raise click.ClickException("Фраза подтверждения не совпала — отмена.")

            if not dry_run and not yes and not click.confirm("Выполнить изменения на канале?"):
                click.echo("Отмена.")
                return

            token = require_access_token(client.access_token)
            report = apply_plan(
                plan,
                yt,
                access_token=token,
                dry_run=dry_run,
                yes=True,
                ledger=ledger,
            )
            click.echo(report.summary())
        finally:
            client.close()


def _resolve_playlist(value: str | None, yt: object | None = None) -> str | None:
    """Return playlist id or None. Accepts ID or title (resolved via API if yt given)."""
    if value is None:
        return None
    v = value.strip()
    if not v or v.lower() in {"нет", "no", "none", "-", "0"}:
        return None
    # Looks like a playlist id (PL...)
    if v.startswith("PL") and len(v) >= 10 and " " not in v:
        return v
    if yt is None:
        return v  # treat as id as-is
    try:
        from aiyoutubehands.models.youtube import PlaylistResource
        from aiyoutubehands.youtube import YoutubeService

        if not isinstance(yt, YoutubeService):
            raise TypeError("yt должен быть YoutubeService")
        pls = yt.list_playlists(dry_run=False)
        if not isinstance(pls, list):
            return v
        v_low = v.lower()
        for p in pls:
            if isinstance(p, PlaylistResource) and p.title.lower() == v_low:
                return p.id
        # Partial match
        for p in pls:
            if isinstance(p, PlaylistResource) and v_low in p.title.lower():
                return p.id
        click.echo(f"Плейлист «{v}» не найден по названию — пропускаю.")
        return None
    except Exception as exc:  # noqa: BLE001
        click.echo(f"Не удалось разрешить плейлист: {exc}")
        return None


def _plan_to_dict(plan: object) -> dict[str, Any]:
    from aiyoutubehands.shorts_maker.plan import ProcessPlan

    if not isinstance(plan, ProcessPlan):
        raise TypeError("plan должен быть ProcessPlan")
    return {
        "created_at": plan.created_at.isoformat(),
        "root_path": str(plan.root_path),
        "confirm_phrase": plan.confirm_phrase,
        "fingerprint": plan.fingerprint,
        "quota": plan.quota_projection,
        "items": [
            {
                "index": i.index,
                "folder": i.folder.folder_name,
                "video_id": i.video.id if i.video else None,
                "match": i.match_method,
                "new_title": i.new_title,
                "new_description": i.new_description,
                "tags": i.new_tags,
                "thumbnail": str(i.thumbnail_path) if i.thumbnail_path else None,
                "publish_at": i.publish_at,
                "playlist_id": i.playlist_id,
                "status": i.status,
                "quota": i.estimated_quota,
            }
            for i in plan.items
        ],
    }


def _save_plan_json(plan: object, path: Path) -> None:
    path.write_text(
        json.dumps(_plan_to_dict(plan), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
