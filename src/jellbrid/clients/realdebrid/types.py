import enum
import typing as t

RDBundleFileFilter = t.Callable[[str], bool]
InstantAvailablityType = dict[str, dict[str, list[dict[str, dict]]]]


class CachedTorrent(t.TypedDict):
    filename: str
    filesize: int


class MagnetAddedResponse(t.TypedDict):
    uri: str
    id: str


class TorrentStatus(enum.Enum):
    WAITING_FILES_SELECTION = "waiting_files_selection"
    DOWNLOADING = "downloading"
    DOWNLOADED = "DOWNLOADED"
    ERROR = "ERROR"
    DEAD = "DEAD"
    VIRUS = "VIRUS"
