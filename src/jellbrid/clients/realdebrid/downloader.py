import functools
import typing as t

import structlog

from jellbrid.clients.realdebrid.bundle import RDBundle, TorrentBundle
from jellbrid.clients.realdebrid.client import RealDebridClient
from jellbrid.clients.realdebrid.filters import (
    episode_filter,
    filter_extension,
    filter_samples,
    movie_name_filter,
)
from jellbrid.clients.realdebrid.types import RDBundleFileFilter
from jellbrid.clients.torrentio import Stream
from jellbrid.clients.torrentio.filters import (
    name_contains_full_season,
    name_contains_release_year,
)
from jellbrid.requests import EpisodeRequest, MovieRequest, SeasonRequest

logger = structlog.get_logger(__name__)


class RealDebridDownloader:
    def __init__(
        self,
        rdbc: RealDebridClient,
        *,
        request: SeasonRequest | EpisodeRequest | MovieRequest,
        streams: list[Stream],
        filters: list[RDBundleFileFilter] | None = None,
    ):
        self.rdbc = rdbc
        self.streams = streams
        self.request = request

        self.filters = filters or []
        self.filters.extend((filter_samples, filter_extension))

    def _filter_full_season_named_streams(self, streams: list[Stream]) -> list[Stream]:
        results = []
        for stream in streams:
            if name_contains_full_season(stream, t.cast(SeasonRequest, self.request)):
                results.append(stream)
        return results

    def _filter_streams_with_release_year(self, streams: list[Stream]) -> list[Stream]:
        results = []
        for stream in streams:
            if name_contains_release_year(stream, t.cast(MovieRequest, self.request)):
                results.append(stream)
        return results

    async def _find_bundle_with_file_count(
        self, stream: Stream, count: int, *, filter: RDBundleFileFilter | None = None
    ):
        ffs = self.filters + [filter] if filter else self.filters
        cache = await self.rdbc.get_rd_bundle_with_file_count(
            stream["infoHash"], count, file_filters=ffs
        )
        return cache

    async def _find_bundle_with_file(self, stream: Stream):
        if not isinstance(self.request, EpisodeRequest):
            raise Exception("Attempt to use episode filter on an unsupported Request")
        e_filter = functools.partial(
            episode_filter,
            season_id=self.request.season_id,
            episode_id=self.request.episode_id,
        )
        ffs = self.filters + [e_filter]
        cache = await self.rdbc.get_rd_bundle_with_file_match(
            stream["infoHash"], file_filters=ffs
        )
        return cache

    async def _find_bundle_with_file_ratio(self, stream: Stream, ratio: float):
        if not isinstance(self.request, SeasonRequest):
            raise Exception("Attempt to use ratio filter on an unsupported Request")

        count = int(len(self.request.episodes) * ratio)
        bundle = await self.rdbc.get_rd_bundle_with_file_count_gte(
            stream["infoHash"], count, file_filters=self.filters
        )
        return bundle

    async def download_movie(self) -> str | None:
        streams = self.streams
        # try to get better results on movies with ambiguous titles
        if len(self.request.title) < 6:
            streams = self._filter_streams_with_release_year(streams)

        movie_filter = functools.partial(movie_name_filter, name=self.request.title)

        for stream in streams:
            hash = stream["infoHash"]
            with structlog.contextvars.bound_contextvars(
                hash=hash, rdbc_cache_size=self.rdbc.cache.currsize
            ):
                bundle = await self._find_bundle_with_file_count(
                    stream, 1, filter=movie_filter
                )
                if bundle is None:
                    continue
                downloaded = await self._download(stream, bundle)
                if downloaded is not None:
                    return downloaded
        return None

    async def download_show(self) -> str | None:
        # this is probably unecessary for cached streams, but necessary for
        # uncached
        streams = self.streams
        candidates = self._filter_full_season_named_streams(streams)

        # try to find a bundle with at least 80% of the files we want
        for stream in candidates:
            hash = stream["infoHash"]
            with structlog.contextvars.bound_contextvars(
                hash=hash, rdbc_cache_size=self.rdbc.cache.currsize
            ):
                bundle = await self._find_bundle_with_file_ratio(stream, 0.8)
                if bundle is None:
                    continue
                downloaded = await self._download(stream, bundle)
                if downloaded is not None:
                    return downloaded

        # try to find a bundle with any amount of files
        for stream in candidates:
            with structlog.contextvars.bound_contextvars(hash=stream["infoHash"]):
                bundle = await self._find_bundle_with_file_ratio(stream, 0)
                if bundle is None:
                    continue
                downloaded = await self._download(stream, bundle)
                if downloaded is not None:
                    return downloaded
        return None

    async def download_episode(self) -> str | None:
        if isinstance(self.request, (MovieRequest, SeasonRequest)):
            raise Exception("Can't download episode for given request type")

        e_filter = functools.partial(
            episode_filter,
            season_id=self.request.season_id,
            episode_id=self.request.episode_id,
        )
        # look for a single file that's instantly available
        for stream in self.streams:
            hash = stream["infoHash"]
            with structlog.contextvars.bound_contextvars(
                hash=hash, rdbc_cache_size=self.rdbc.cache.currsize
            ):
                bundle = await self._find_bundle_with_file_count(
                    stream, 1, filter=e_filter
                )
                if bundle is None:
                    continue

                downloaded = await self._download(stream, bundle)
                if downloaded is not None:
                    return downloaded
        return None

    async def download_episode_from_bundle(self) -> str | None:
        for stream in self.streams:
            hash = stream["infoHash"]
            with structlog.contextvars.bound_contextvars(hash=hash):
                bundle = await self._find_bundle_with_file(stream)
                if bundle is None:
                    continue

                downloaded = await self._download(stream, bundle)
                if downloaded is not None:
                    return downloaded
        return None

    async def _download(
        self, stream: Stream, bundle: RDBundle | TorrentBundle
    ) -> str | None:
        if self.rdbc.cfg.dev_mode:
            logger.info(
                "Skipped downloading file",
                bundle=bundle.bundle if bundle else bundle,
            )
            return ""

        torrent = await self.rdbc.add_magnet(stream["infoHash"])
        torrent_id = torrent.get("id")
        if torrent_id is None:
            logger.warning("Unable to add magnet", **torrent)
            return None

        result = await self.rdbc.select_files(torrent["id"], bundle.file_ids)
        if "error" in result:
            logger.warning("Unable to start torrent", **result)
            result = await self.rdbc.delete_magnet(torrent_id)
            return None

        logger.info("Downloaded torrent")
        return torrent["id"]
