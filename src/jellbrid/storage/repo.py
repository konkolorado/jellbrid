from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jellbrid.storage.active_dls import ActiveDownload


class SqliteRequestRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, download: ActiveDownload):
        async with self.session.begin():
            self.session.add(download)

    async def delete(self, download: ActiveDownload):
        async with self.session.begin():
            await self.session.delete(download)

    async def has_movie(self, imdb_id: str):
        async with self.session.begin():
            query = select(ActiveDownload).where(ActiveDownload.imdb_id == imdb_id)
            results = await self.session.execute(query)
        return results.fetchone() is not None

    async def has_season(self, imdb_id: str, season: int):
        async with self.session.begin():
            query = (
                select(ActiveDownload)
                .where(ActiveDownload.imdb_id == imdb_id)
                .where(ActiveDownload.season == season)
            )
            results = await self.session.execute(query)
        return results.fetchone() is not None

    async def has_episode(self, imdb_id: str, season: int, episode: int):
        async with self.session.begin():
            query = (
                select(ActiveDownload)
                .where(ActiveDownload.imdb_id == imdb_id)
                .where(ActiveDownload.season == season)
                .where(ActiveDownload.episode == episode)
            )
            results = await self.session.execute(query)
        return results.fetchone() is not None

    async def get_requests(self):
        async with self.session.begin():
            query = select(ActiveDownload)
            results = await self.session.scalars(query)
        return results.all()