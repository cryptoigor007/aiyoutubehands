"""Real (non-dry-run) HTTP paths of :mod:`aiyoutubehands.youtube` via respx.

Every test here mocks HTTP with respx: no request leaves the process. The
services are built with a throwaway ``HttpClient(access_token="fake")`` and a
per-test SQLite quota ledger, so quota accounting is asserted to the unit.

For write methods the first real call is ``_verify_expected_channel()``:
``GET /channels?part=snippet&statistics&contentDetails&mine=true`` returning the
expected channel. It is mocked in every write test and costs 1 quota unit.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import respx
from httpx import Response

from aiyoutubehands.client import ClientError, HttpClient
from aiyoutubehands.models.youtube import (
    CaptionResource,
    ChannelResource,
    CommentResource,
    PlaylistResource,
    VideoResource,
    VideoSnippet,
    VideoStatus,
)
from aiyoutubehands.quota import QuotaEngine
from aiyoutubehands.youtube import YoutubeService

if TYPE_CHECKING:
    from pathlib import Path

BASE = "https://www.googleapis.com/youtube/v3"
UPLOAD_BASE = "https://www.googleapis.com/upload/youtube/v3"


def _service(tmp_path: Path) -> tuple[YoutubeService, QuotaEngine]:
    client = HttpClient(access_token="fake")
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    return YoutubeService(client, quota, expected_channel_id="UC_test"), quota


def _mock_channel(mock: respx.MockRouter, channel_id: str = "UC_test", **extra: Any) -> respx.Route:
    item: dict[str, Any] = {"id": channel_id, "snippet": {"title": "T"}}
    item.update(extra)
    return mock.get(f"{BASE}/channels").mock(return_value=Response(200, json={"items": [item]}))


def _recent(days: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat().replace("+00:00", "Z")


def _video_item(video_id: str, published: str = "2026-01-01T00:00:00Z") -> dict[str, Any]:
    return {
        "id": video_id,
        "snippet": {"title": video_id, "publishedAt": published},
        "status": {"privacyStatus": "private"},
    }


def _playlist_item(video_id: str, published: str) -> dict[str, Any]:
    return {"snippet": {"resourceId": {"videoId": video_id}, "publishedAt": published}}


# --------------------------------------------------------------------------- #
# get_my_channel
# --------------------------------------------------------------------------- #


def test_get_my_channel_success(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(f"{BASE}/channels").mock(
            return_value=Response(
                200,
                json={
                    "items": [
                        {
                            "id": "UC_test",
                            "snippet": {"title": "Мой канал", "description": "desc"},
                            "statistics": {"subscriberCount": "123"},
                        }
                    ]
                },
            )
        )
        ch = yt.get_my_channel(dry_run=False)

    assert isinstance(ch, ChannelResource)
    assert ch.id == "UC_test"
    assert ch.title == "Мой канал"
    assert ch.subscriber_count == 123
    req = route.calls[0].request
    assert req.method == "GET"
    assert str(req.url).startswith(f"{BASE}/channels")
    assert dict(req.url.params) == {
        "part": "snippet,statistics,contentDetails",
        "mine": "true",
    }
    assert quota.used_today() == 1


def test_get_my_channel_empty_is_not_found(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/channels").mock(return_value=Response(200, json={"items": []}))
        with pytest.raises(ClientError) as ei:
            yt.get_my_channel(dry_run=False)

    assert ei.value.code == "CHANNEL_NOT_FOUND"
    # Неуспешная проверка канала не должна списывать квоту.
    assert quota.used_today() == 0


def test_get_my_channel_without_expected_id_is_not_configured(tmp_path: Path) -> None:
    client = HttpClient(access_token="fake")
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    yt = YoutubeService(client, quota, expected_channel_id="")
    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(mock)
        with pytest.raises(ClientError) as ei:
            yt.get_my_channel(dry_run=False)

    assert ei.value.code == "CHANNEL_NOT_CONFIGURED"
    assert quota.used_today() == 0


def test_get_my_channel_mismatch_raises(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(mock, channel_id="UC_other")
        with pytest.raises(ClientError) as ei:
            yt.get_my_channel(dry_run=False)

    assert ei.value.code == "CHANNEL_MISMATCH"
    assert quota.used_today() == 0


# --------------------------------------------------------------------------- #
# get_video / list_videos
# --------------------------------------------------------------------------- #


def test_get_video_found(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(f"{BASE}/videos").mock(
            return_value=Response(200, json={"items": [_video_item("vid1")]})
        )
        video = yt.get_video("vid1", dry_run=False)

    assert isinstance(video, VideoResource)
    assert video.id == "vid1"
    assert video.snippet.title == "vid1"
    req = route.calls[0].request
    assert req.method == "GET"
    assert dict(req.url.params) == {
        "part": "snippet,status,contentDetails",
        "id": "vid1",
    }
    assert quota.used_today() == 1


def test_get_video_not_found(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/videos").mock(return_value=Response(200, json={"items": []}))
        with pytest.raises(ClientError) as ei:
            yt.get_video("nope", dry_run=False)

    assert ei.value.code == "NOT_FOUND"
    assert quota.used_today() == 0


def test_list_videos_batches_ids_in_one_request(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(f"{BASE}/videos").mock(
            return_value=Response(
                200,
                json={"items": [_video_item("a"), _video_item("b")]},
            )
        )
        videos = yt.list_videos(ids=["a", "b"], dry_run=False)

    assert isinstance(videos, list)
    assert [v.id for v in videos] == ["a", "b"]
    req = route.calls[0].request
    assert dict(req.url.params)["id"] == "a,b"
    # Один запрос за оба id — это 1 юнит, а не 2.
    assert len(route.calls) == 1
    assert quota.used_today() == 1


def test_list_videos_without_ids_is_bad_request(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False), pytest.raises(ClientError) as ei:
        yt.list_videos(ids=None, dry_run=False)

    assert ei.value.code == "BAD_REQUEST"
    assert quota.used_today() == 0


# --------------------------------------------------------------------------- #
# list_channel_videos
# --------------------------------------------------------------------------- #


def test_list_channel_videos_paginates_and_batches(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)

    def pl_handler(request: Any) -> Response:
        if request.url.params.get("pageToken") == "T2":
            return Response(200, json={"items": [_playlist_item("v2", _recent())]})
        return Response(
            200,
            json={"items": [_playlist_item("v1", _recent())], "nextPageToken": "T2"},
        )

    def videos_handler(request: Any) -> Response:
        ids = request.url.params["id"].split(",")
        return Response(200, json={"items": [_video_item(i) for i in ids]})

    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(
            mock,
            contentDetails={"relatedPlaylists": {"uploads": "UU_test"}},
        )
        pl_route = mock.get(f"{BASE}/playlistItems").mock(side_effect=pl_handler)
        mock.get(f"{BASE}/videos").mock(side_effect=videos_handler)
        videos = yt.list_channel_videos(max_age_days=14, max_results=200, dry_run=False)

    assert isinstance(videos, list)
    assert [v.id for v in videos] == ["v1", "v2"]
    assert len(pl_route.calls) == 2
    assert pl_route.calls[0].request.url.params.get("pageToken") is None
    assert pl_route.calls[1].request.url.params["pageToken"] == "T2"
    # 1 (channels) + 2 (playlistItems) + 1 (videos.list batch) = 4
    assert quota.used_today() == 4


def test_list_channel_videos_stops_early_on_max_age(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)

    def pl_handler(request: Any) -> Response:
        return Response(
            200,
            json={
                "items": [
                    _playlist_item("fresh", _recent(0)),
                    _playlist_item("old", _recent(90)),
                ],
                "nextPageToken": "T2",
            },
        )

    def videos_handler(request: Any) -> Response:
        ids = request.url.params["id"].split(",")
        return Response(200, json={"items": [_video_item(i) for i in ids]})

    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(mock, contentDetails={"relatedPlaylists": {"uploads": "UU_test"}})
        pl_route = mock.get(f"{BASE}/playlistItems").mock(side_effect=pl_handler)
        vid_route = mock.get(f"{BASE}/videos").mock(side_effect=videos_handler)
        videos = yt.list_channel_videos(max_age_days=30, max_results=200, dry_run=False)

    assert isinstance(videos, list)
    # Видео старше cutoff прерывает обход, следующая страница не запрашивается.
    assert [v.id for v in videos] == ["fresh"]
    assert len(pl_route.calls) == 1
    assert vid_route.calls[0].request.url.params["id"] == "fresh"
    # 1 (channels) + 1 (playlistItems) + 1 (videos.list) = 3
    assert quota.used_today() == 3


def test_list_channel_videos_empty_uploads_returns_empty(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(mock, contentDetails={"relatedPlaylists": {"uploads": "UU_test"}})
        mock.get(f"{BASE}/playlistItems").mock(return_value=Response(200, json={"items": []}))
        videos = yt.list_channel_videos(dry_run=False)

    assert videos == []
    # 1 (channels) + 1 (playlistItems, пустая страница) = 2; videos.list не зовётся.
    assert quota.used_today() == 2


def test_list_channel_videos_ignores_bad_dates_and_missing_resource(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)

    def pl_handler(request: Any) -> Response:
        return Response(
            200,
            json={
                "items": [
                    # Нет publishedAt: фильтр по возрасту пропускается целиком.
                    {"snippet": {"resourceId": {"videoId": "no-date"}}},
                    # Невалидная дата: ValueError проглатывается, id берётся.
                    {
                        "snippet": {
                            "resourceId": {"videoId": "bad-date"},
                            "publishedAt": "not-a-date",
                        }
                    },
                    # Нет resourceId — запись пропускается, а не падает.
                    {"snippet": {"publishedAt": _recent(0)}},
                    {"snippet": {"resourceId": {"videoId": "ok"}, "publishedAt": _recent(0)}},
                ]
            },
        )

    def videos_handler(request: Any) -> Response:
        ids = request.url.params["id"].split(",")
        return Response(200, json={"items": [_video_item(i) for i in ids]})

    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(mock, contentDetails={"relatedPlaylists": {"uploads": "UU_test"}})
        mock.get(f"{BASE}/playlistItems").mock(side_effect=pl_handler)
        vid_route = mock.get(f"{BASE}/videos").mock(side_effect=videos_handler)
        videos = yt.list_channel_videos(dry_run=False)

    assert [v.id for v in videos] == ["no-date", "bad-date", "ok"]
    assert vid_route.calls[0].request.url.params["id"] == "no-date,bad-date,ok"


def test_list_channel_videos_respects_max_results(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)

    def pl_handler(request: Any) -> Response:
        n = int(request.url.params["maxResults"])
        items = [_playlist_item(f"v{i}", _recent(0)) for i in range(1, n + 1)]
        return Response(200, json={"items": items, "nextPageToken": "T2"})

    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(mock, contentDetails={"relatedPlaylists": {"uploads": "UU_test"}})
        pl_route = mock.get(f"{BASE}/playlistItems").mock(side_effect=pl_handler)
        mock.get(f"{BASE}/videos").mock(
            return_value=Response(200, json={"items": [_video_item("v1")]})
        )
        videos = yt.list_channel_videos(max_results=1, dry_run=False)

    assert [v.id for v in videos] == ["v1"]
    # Уже набрали max_results — следующая страница не запрашивается.
    assert len(pl_route.calls) == 1
    assert pl_route.calls[0].request.url.params["maxResults"] == "1"


def test_list_channel_videos_without_uploads_playlist(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(mock)  # no contentDetails.relatedPlaylists.uploads
        with pytest.raises(ClientError) as ei:
            yt.list_channel_videos(dry_run=False)

    assert ei.value.code == "NOT_FOUND"
    assert quota.used_today() == 1


# --------------------------------------------------------------------------- #
# list_video_ids_in_playlists
# --------------------------------------------------------------------------- #


def test_list_video_ids_in_playlists(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)

    def playlists_handler(request: Any) -> Response:
        return Response(
            200,
            json={"items": [{"id": "PL1", "snippet": {"title": "A"}}, {"id": "PL2"}]},
        )

    def pl_items_handler(request: Any) -> Response:
        pid = request.url.params["playlistId"]
        token = request.url.params.get("pageToken")
        if pid == "PL1":
            return Response(
                200,
                json={
                    "items": [
                        {"contentDetails": {"videoId": "v1"}},
                        {"contentDetails": {"videoId": "v2"}},
                        # Записи без videoId должны молча пропускаться.
                        {"contentDetails": {}},
                        {},
                    ]
                },
            )
        if token == "P2":
            return Response(200, json={"items": [{"contentDetails": {"videoId": "v4"}}]})
        return Response(
            200,
            json={"items": [{"contentDetails": {"videoId": "v3"}}], "nextPageToken": "P2"},
        )

    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/playlists").mock(side_effect=playlists_handler)
        mock.get(f"{BASE}/playlistItems").mock(side_effect=pl_items_handler)
        ids = yt.list_video_ids_in_playlists(max_playlists=25, dry_run=False)

    assert ids == {"v1", "v2", "v3", "v4"}
    # 1 (playlists.list) + 1 (PL1) + 2 (PL2 pages) = 4
    assert quota.used_today() == 4


# --------------------------------------------------------------------------- #
# update_video / schedule / publish
# --------------------------------------------------------------------------- #


def test_update_video_success_status_only(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(mock)
        route = mock.put(f"{BASE}/videos").mock(
            return_value=Response(
                200, json={**_video_item("vid1"), "status": {"privacyStatus": "private"}}
            )
        )
        video = yt.update_video(
            "vid1",
            status=VideoStatus(privacy_status="private", publish_at="2026-10-01T00:00:00Z"),
            dry_run=False,
            yes=True,
        )

    assert isinstance(video, VideoResource)
    assert video.id == "vid1"
    req = route.calls[0].request
    assert req.method == "PUT"
    assert dict(req.url.params) == {"part": "status"}
    body = json.loads(req.content)
    assert body["id"] == "vid1"
    assert "snippet" not in body
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["publishAt"] == "2026-10-01T00:00:00Z"
    # 1 (channels verification) + 50 (videos.update)
    assert quota.used_today() == 51


def test_update_video_snippet_and_status_parts(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(mock)
        route = mock.put(f"{BASE}/videos").mock(
            return_value=Response(200, json=_video_item("vid1"))
        )
        yt.update_video(
            "vid1",
            snippet=VideoSnippet(title="New", description="D", tags=["a", "b"]),
            status=VideoStatus(privacy_status="public"),
            dry_run=False,
            yes=True,
        )

    req = route.calls[0].request
    assert dict(req.url.params) == {"part": "snippet,status"}
    body = json.loads(req.content)
    assert body["snippet"]["title"] == "New"
    assert body["snippet"]["description"] == "D"
    assert body["snippet"]["tags"] == ["a", "b"]
    assert body["snippet"]["categoryId"] == "22"
    assert body["status"]["privacyStatus"] == "public"
    assert quota.used_today() == 51


def test_update_video_without_fields_is_bad_request(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(mock)
        with pytest.raises(ClientError) as ei:
            yt.update_video("vid1", dry_run=False, yes=True)

    assert ei.value.code == "BAD_REQUEST"
    # Проверка канала успела отработать (1), videos.update не списан.
    assert quota.used_today() == 1


def test_schedule_video_sets_private_and_publish_at(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(mock)
        route = mock.put(f"{BASE}/videos").mock(
            return_value=Response(200, json=_video_item("vid1"))
        )
        yt.schedule_video("vid1", "2026-10-01T12:00:00Z", dry_run=False, yes=True)

    body = json.loads(route.calls[0].request.content)
    assert body["id"] == "vid1"
    assert body["status"] == {"privacyStatus": "private", "publishAt": "2026-10-01T12:00:00Z"}
    assert quota.used_today() == 51


def test_publish_video_sets_public_and_clears_publish_at(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(mock)
        route = mock.put(f"{BASE}/videos").mock(
            return_value=Response(200, json=_video_item("vid1"))
        )
        yt.publish_video("vid1", dry_run=False, yes=True)

    body = json.loads(route.calls[0].request.content)
    assert body["status"]["privacyStatus"] == "public"
    assert "publishAt" not in body["status"]
    assert quota.used_today() == 51


def test_delete_video(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(mock)
        route = mock.delete(f"{BASE}/videos").mock(return_value=Response(204))
        result = yt.delete_video("vid1", dry_run=False, yes=True)

    assert result == {"ok": True, "video_id": "vid1"}
    req = route.calls[0].request
    assert req.method == "DELETE"
    assert dict(req.url.params) == {"id": "vid1"}
    assert quota.used_today() == 51


# --------------------------------------------------------------------------- #
# playlists
# --------------------------------------------------------------------------- #


def test_list_playlists_follows_pagination(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)

    def handler(request: Any) -> Response:
        if request.url.params.get("pageToken") == "T2":
            return Response(200, json={"items": [{"id": "PL2", "snippet": {"title": "B"}}]})
        return Response(
            200,
            json={"items": [{"id": "PL1", "snippet": {"title": "A"}}], "nextPageToken": "T2"},
        )

    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(f"{BASE}/playlists").mock(side_effect=handler)
        playlists = yt.list_playlists(dry_run=False)

    assert isinstance(playlists, list)
    assert [p.id for p in playlists] == ["PL1", "PL2"]
    assert all(isinstance(p, PlaylistResource) for p in playlists)
    assert len(route.calls) == 2
    assert route.calls[1].request.url.params["pageToken"] == "T2"
    assert quota.used_today() == 2


def test_create_playlist(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(mock)
        route = mock.post(f"{BASE}/playlists").mock(
            return_value=Response(200, json={"id": "PL9", "snippet": {"title": "New"}})
        )
        pl = yt.create_playlist("New", description="D", privacy="unlisted", dry_run=False, yes=True)

    assert isinstance(pl, PlaylistResource)
    assert pl.id == "PL9"
    req = route.calls[0].request
    assert req.method == "POST"
    assert dict(req.url.params) == {"part": "snippet,status"}
    body = json.loads(req.content)
    assert body == {
        "snippet": {"title": "New", "description": "D"},
        "status": {"privacyStatus": "unlisted"},
    }
    assert quota.used_today() == 51


def test_delete_playlist(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(mock)
        route = mock.delete(f"{BASE}/playlists").mock(return_value=Response(204))
        result = yt.delete_playlist("PL9", dry_run=False, yes=True)

    assert result == {"ok": True, "playlist_id": "PL9"}
    assert route.calls[0].request.method == "DELETE"
    assert dict(route.calls[0].request.url.params) == {"id": "PL9"}
    assert quota.used_today() == 51


def test_add_to_playlist(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(mock)
        route = mock.post(f"{BASE}/playlistItems").mock(
            return_value=Response(200, json={"id": "PLI1"})
        )
        result = yt.add_to_playlist("PL9", "vid1", dry_run=False, yes=True)

    assert result == {"id": "PLI1"}
    req = route.calls[0].request
    assert dict(req.url.params) == {"part": "snippet"}
    body = json.loads(req.content)
    assert body["snippet"]["playlistId"] == "PL9"
    assert body["snippet"]["resourceId"] == {"kind": "youtube#video", "videoId": "vid1"}
    assert quota.used_today() == 51


# --------------------------------------------------------------------------- #
# comments
# --------------------------------------------------------------------------- #


def test_list_comment_threads(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    payload = {
        "items": [
            {
                "id": "ct1",
                "snippet": {
                    "videoId": "vid1",
                    "topLevelComment": {
                        "snippet": {
                            "authorDisplayName": "Alice",
                            "textDisplay": "hi",
                            "likeCount": 5,
                            "publishedAt": "2026-01-01T00:00:00Z",
                        }
                    },
                },
            }
        ]
    }
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(f"{BASE}/commentThreads").mock(return_value=Response(200, json=payload))
        comments = yt.list_comment_threads("vid1", max_results=20, dry_run=False)

    assert isinstance(comments, list)
    assert len(comments) == 1
    assert isinstance(comments[0], CommentResource)
    assert comments[0].id == "ct1"
    assert comments[0].author == "Alice"
    assert comments[0].like_count == 5
    assert dict(route.calls[0].request.url.params) == {
        "part": "snippet",
        "videoId": "vid1",
        "maxResults": "20",
        "textFormat": "plainText",
    }
    assert quota.used_today() == 1


def test_reply_to_comment(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(mock)
        route = mock.post(f"{BASE}/comments").mock(return_value=Response(200, json={"id": "c2"}))
        result = yt.reply_to_comment("c1", "спасибо!", dry_run=False, yes=True)

    assert result == {"id": "c2"}
    req = route.calls[0].request
    assert dict(req.url.params) == {"part": "snippet"}
    assert json.loads(req.content) == {"snippet": {"parentId": "c1", "textOriginal": "спасибо!"}}
    assert quota.used_today() == 51


def test_moderate_comment(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(mock)
        route = mock.post(f"{BASE}/comments/setModerationStatus").mock(return_value=Response(204))
        result = yt.moderate_comment("c1", "rejected", dry_run=False, yes=True)

    assert result == {"ok": True, "comment_id": "c1", "status": "rejected"}
    assert route.calls[0].request.method == "POST"
    assert dict(route.calls[0].request.url.params) == {
        "id": "c1",
        "moderationStatus": "rejected",
    }
    assert quota.used_today() == 51


# --------------------------------------------------------------------------- #
# captions
# --------------------------------------------------------------------------- #


def test_list_captions(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    payload = {
        "items": [
            {
                "id": "cap1",
                "snippet": {
                    "videoId": "vid1",
                    "language": "ru",
                    "name": "Rus",
                    "trackKind": "standard",
                },
            }
        ]
    }
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(f"{BASE}/captions").mock(return_value=Response(200, json=payload))
        captions = yt.list_captions("vid1", dry_run=False)

    assert isinstance(captions, list)
    assert isinstance(captions[0], CaptionResource)
    assert captions[0].language == "ru"
    assert captions[0].name == "Rus"
    assert dict(route.calls[0].request.url.params) == {"part": "snippet", "videoId": "vid1"}
    # captions.list стоит 50 юнитов.
    assert quota.used_today() == 50


def test_upload_caption_success(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    caption_file = tmp_path / "subs.srt"
    caption_file.write_bytes(b"1\n00:00:00,000 --> 00:00:01,000\nhello-caption\n")

    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(mock)
        route = mock.post(f"{UPLOAD_BASE}/captions").mock(
            return_value=Response(
                200,
                json={"id": "cap1", "snippet": {"videoId": "vid1", "language": "ru"}},
            )
        )
        result = yt.upload_caption(
            "vid1",
            caption_file,
            language="ru",
            name="Rus",
            access_token="fake",
            dry_run=False,
            yes=True,
        )

    assert result["id"] == "cap1"
    req = route.calls[0].request
    assert req.method == "POST"
    assert str(req.url).startswith(f"{UPLOAD_BASE}/captions")
    assert dict(req.url.params) == {"part": "snippet", "uploadType": "multipart"}
    assert req.headers["authorization"] == "Bearer fake"
    assert req.headers["content-type"].startswith("multipart/form-data")
    assert b"hello-caption" in req.content
    assert b'"videoId": "vid1"' in req.content
    # 1 (channels verification) + 400 (captions.insert)
    assert quota.used_today() == 401


def test_upload_caption_missing_file_is_not_found(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    upload_route_holder: list[Any] = []

    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(mock)
        upload_route_holder.append(
            mock.post(f"{UPLOAD_BASE}/captions").mock(return_value=Response(200, json={}))
        )
        with pytest.raises(ClientError) as ei:
            yt.upload_caption(
                "vid1",
                tmp_path / "does-not-exist.srt",
                access_token="fake",
                dry_run=False,
                yes=True,
            )

    assert ei.value.code == "NOT_FOUND"
    # На несуществующий файл запрос загрузки не уходит.
    assert upload_route_holder[0].calls == []
    assert quota.used_today() <= 1


def test_upload_caption_error_is_retryable(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    caption_file = tmp_path / "subs.srt"
    caption_file.write_bytes(b"1\n")

    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(mock)
        mock.post(f"{UPLOAD_BASE}/captions").mock(
            return_value=Response(400, text="captions.insert failed")
        )
        with pytest.raises(ClientError) as ei:
            yt.upload_caption("vid1", caption_file, access_token="fake", dry_run=False, yes=True)

    assert ei.value.code == "CAPTION_UPLOAD_FAILED"
    assert ei.value.retryable is True
    # captions.insert (400) не списан; осталась только проверка канала.
    assert quota.used_today() == 1


# --------------------------------------------------------------------------- #
# set_thumbnail
# --------------------------------------------------------------------------- #


def test_set_thumbnail_success(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    image = tmp_path / "cover.jpg"
    image.write_bytes(b"\xff\xd8\xffTHUMBNAIL")

    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(mock)
        route = mock.post(f"{UPLOAD_BASE}/thumbnails/set").mock(
            return_value=Response(200, json={"kind": "youtube#thumbnailSetResponse"})
        )
        result = yt.set_thumbnail("vid1", image, access_token="fake", dry_run=False, yes=True)

    assert result == {"kind": "youtube#thumbnailSetResponse"}
    req = route.calls[0].request
    assert req.method == "POST"
    assert dict(req.url.params) == {"videoId": "vid1"}
    assert req.content == b"\xff\xd8\xffTHUMBNAIL"
    assert req.headers["authorization"] == "Bearer fake"
    assert quota.used_today() == 51


def test_set_thumbnail_error_is_retryable(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    image = tmp_path / "cover.jpg"
    image.write_bytes(b"\xff\xd8\xff")

    with respx.mock(assert_all_called=False) as mock:
        _mock_channel(mock)
        mock.post(f"{UPLOAD_BASE}/thumbnails/set").mock(
            return_value=Response(400, text="image too small")
        )
        with pytest.raises(ClientError) as ei:
            yt.set_thumbnail("vid1", image, access_token="fake", dry_run=False, yes=True)

    assert ei.value.code == "THUMBNAIL_FAILED"
    assert ei.value.retryable is True
    assert quota.used_today() == 1


def test_set_thumbnail_empty_token_is_not_authenticated(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    image = tmp_path / "cover.jpg"
    image.write_bytes(b"\xff\xd8\xff")

    with respx.mock(assert_all_called=False), pytest.raises(ClientError) as ei:
        yt.set_thumbnail("vid1", image, access_token="", dry_run=False, yes=True)

    assert ei.value.code == "NOT_AUTHENTICATED"
    assert quota.used_today() == 0


def test_set_thumbnail_missing_file_is_not_found(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False), pytest.raises(ClientError) as ei:
        yt.set_thumbnail(
            "vid1", tmp_path / "nope.jpg", access_token="fake", dry_run=False, yes=True
        )

    assert ei.value.code == "NOT_FOUND"
    assert quota.used_today() == 0


# --------------------------------------------------------------------------- #
# search / claims
# --------------------------------------------------------------------------- #


def test_search_passes_query_and_costs_100(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    payload = {"items": [{"id": {"videoId": "v1"}}]}
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(f"{BASE}/search").mock(return_value=Response(200, json=payload))
        result = yt.search("коты", max_results=3, dry_run=False)

    assert result == payload
    req = route.calls[0].request
    assert req.method == "GET"
    assert dict(req.url.params) == {
        "part": "snippet",
        "q": "коты",
        "type": "video",
        "maxResults": "3",
    }
    assert quota.used_today() == 100


def test_claims_unsupported_has_no_network(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False):
        result = yt.claims_unsupported()

    assert result["status"] == "UNSUPPORTED"
    assert "Claims" in result["message"]
    assert quota.used_today() == 0


# --------------------------------------------------------------------------- #
# guards / error mapping
# --------------------------------------------------------------------------- #


def test_write_without_yes_is_confirm_required(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False), pytest.raises(ClientError) as ei:
        yt.create_playlist("T", dry_run=False, yes=False)

    assert ei.value.code == "CONFIRM_REQUIRED"
    assert quota.used_today() == 0


def test_channel_verification_is_cached_between_writes(tmp_path: Path) -> None:
    """Проверка канала делается один раз на экземпляр сервиса."""
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False) as mock:
        ch_route = _mock_channel(mock)
        mock.put(f"{BASE}/videos").mock(return_value=Response(200, json=_video_item("vid1")))
        yt.publish_video("vid1", dry_run=False, yes=True)
        yt.publish_video("vid1", dry_run=False, yes=True)

    # Второй write не должен повторно ходить за проверкой канала.
    assert len(ch_route.calls) == 1
    # 1 (channels) + 50 + 50 = 101
    assert quota.used_today() == 101


def test_http_403_quota_is_mapped_to_quota_exceeded(tmp_path: Path) -> None:
    yt, quota = _service(tmp_path)
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/videos").mock(
            return_value=Response(
                403,
                json={
                    "error": {
                        "errors": [{"reason": "quotaExceeded", "message": "quota"}],
                        "message": "quota",
                    }
                },
            )
        )
        with pytest.raises(ClientError) as ei:
            yt.get_video("vid1", dry_run=False)

    assert ei.value.code == "QUOTA_EXCEEDED"
    assert ei.value.status_code == 403
    assert quota.used_today() == 0


def test_upload_caption_requires_token(tmp_path: Path) -> None:
    """Пустой токен отвергается до сети — как в set_thumbnail.

    Регресс: upload_caption строил `Authorization: Bearer {access_token}` без
    проверки, в отличие от set_thumbnail, где есть require_access_token.
    """
    import respx as _respx

    from aiyoutubehands.quota import QuotaEngine
    from aiyoutubehands.youtube import YoutubeService

    srt = tmp_path / "a.srt"
    srt.write_text("1\n", encoding="utf-8")

    client = HttpClient(access_token="fake")
    yt = YoutubeService(client, QuotaEngine(db_path=tmp_path / "q.db"), "UC_test")

    with _respx.mock(assert_all_called=False), pytest.raises(ClientError) as ei:
        yt.upload_caption("v1", srt, access_token="", dry_run=False, yes=True)

    assert ei.value.code == "NOT_AUTHENTICATED"


def test_upload_caption_missing_file_does_not_touch_network(tmp_path: Path) -> None:
    """Отсутствующий файл проверяется ДО обращения к API.

    Регресс: _require_write() (а значит channels.list и 1 юнит) вызывался раньше
    проверки существования файла.
    """
    import respx as _respx

    from aiyoutubehands.quota import QuotaEngine
    from aiyoutubehands.youtube import YoutubeService

    client = HttpClient(access_token="fake")
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    yt = YoutubeService(client, quota, "UC_test")

    with _respx.mock(assert_all_called=False), pytest.raises(ClientError) as ei:
        yt.upload_caption("v1", tmp_path / "nope.srt", access_token="fake", dry_run=False, yes=True)

    assert ei.value.code == "NOT_FOUND"
    assert quota.used_today() == 0
