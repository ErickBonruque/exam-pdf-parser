"""Download the official ENEM PDFs from INEP.

TLS note: ``download.inep.gov.br`` sends its certificate without the
intermediate CA. Browsers fetch the missing certificate on their own; Python
does not, so a plain request fails. Instead of turning verification off, this
module adds that one public intermediate (shipped in ``certs/``) to the
certifi bundle.
"""

from __future__ import annotations

import logging
import tempfile
import time
from collections.abc import Iterable
from functools import cache
from importlib import resources
from pathlib import Path

import certifi
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from exam_pdf_parser.enem import Booklet

log = logging.getLogger(__name__)

CHUNK_SIZE = 1 << 16
TIMEOUT = (30, 120)  # connect, read (seconds)
PAUSE = 1.0  # seconds between files, to be polite with the server


class DownloadError(RuntimeError):
    """The file could not be downloaded completely."""


@cache
def ca_bundle() -> str:
    """Return a CA bundle path: certifi roots plus the INEP intermediate."""
    extra = resources.files("exam_pdf_parser").joinpath("certs/rnp-icpedu-gr46-ov-tls-ca-2025.pem")
    # A new file with a random name, readable only by this user: a fixed name
    # in the shared temp folder could be created first by someone else.
    with tempfile.NamedTemporaryFile(
        "w", encoding="ascii", prefix="exam_pdf_parser_ca_", suffix=".pem", delete=False
    ) as fh:
        fh.write(Path(certifi.where()).read_text(encoding="ascii"))
        fh.write("\n")
        fh.write(extra.read_text(encoding="ascii"))
    return fh.name


def make_session(retries: int = 5) -> requests.Session:
    """Session with retry and exponential backoff on network errors and 429/5xx."""
    retry = Retry(
        total=retries,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = "exam-pdf-parser/0.1"
    return session


def download(url: str, dest: Path, session: requests.Session) -> bool:
    """Stream ``url`` to ``dest``. Return ``False`` if ``dest`` already existed.

    The data goes to ``<dest>.part`` first and is renamed only when the size
    matches ``Content-Length``, so an interrupted run never leaves a file that
    looks complete.

    Raises:
        DownloadError: On HTTP errors, a size mismatch, or a body that is not a PDF.
    """
    if dest.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        with session.get(url, stream=True, timeout=TIMEOUT, verify=ca_bundle()) as resp:
            resp.raise_for_status()
            expected = int(resp.headers.get("Content-Length", 0)) or None
            written = 0
            with part.open("wb") as fh:
                for chunk in resp.iter_content(CHUNK_SIZE):
                    fh.write(chunk)
                    written += len(chunk)
        if expected is not None and written != expected:
            raise DownloadError(f"{url}: got {written} bytes, expected {expected}")
        with part.open("rb") as fh:
            if fh.read(5) != b"%PDF-":
                raise DownloadError(f"{url}: response is not a PDF")
    except requests.RequestException as exc:
        part.unlink(missing_ok=True)
        raise DownloadError(f"{url}: {exc}") from exc
    except DownloadError:
        part.unlink(missing_ok=True)
        raise
    part.replace(dest)
    log.info("downloaded %s (%d KB)", dest.name, written >> 10)
    return True


def fetch_booklets(
    booklets: Iterable[Booklet], dest_dir: Path, session: requests.Session | None = None
) -> list[Path]:
    """Download booklet and answer key of each booklet. Existing files are kept."""
    session = session or make_session()
    paths: list[Path] = []
    for booklet in booklets:
        for kind in ("PV", "GB"):
            dest = dest_dir / booklet.file_name(kind)
            if download(booklet.url(kind), dest, session):
                time.sleep(PAUSE)
            paths.append(dest)
    return paths
