"""Enumeracion y descarga desde archive.org."""
import json
import logging
import time
import zipfile
from pathlib import Path
from urllib.parse import quote

import requests

from . import config
from .progress import Progress, human

log = logging.getLogger("c90.archive")
SCRAPE = "https://archive.org/services/search/v1/scrape"
META = "https://archive.org/metadata/{}"
COMPRESS = "https://archive.org/compress/{}"
DOWNLOAD = "https://archive.org/download/{}/{}"

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "c90-backup/1.0 (personal archive)"


def list_items():
    """Devuelve todos los items del uploader, paginando con cursor."""
    out, cursor = [], None
    while True:
        params = {
            "q": f'uploader:("{config.UPLOADER}")',
            "count": 10000,
            "fields": "identifier,title,mediatype,item_size",
        }
        if cursor:
            params["cursor"] = cursor
        r = SESSION.get(SCRAPE, params=params, timeout=120)
        r.raise_for_status()
        data = r.json()
        out.extend(data.get("items", []))
        log.info("enumerados %d/%d", len(out), data.get("total", 0))
        cursor = data.get("cursor")
        if not cursor:
            return out
        time.sleep(0.5)


def get_metadata(identifier):
    r = SESSION.get(META.format(identifier), timeout=60)
    r.raise_for_status()
    return r.json()


def _stream(url, dest, timeout=None, label=None):
    """Descarga a disco con reintentos y reanudacion por Range."""
    timeout = timeout or config.DOWNLOAD_TIMEOUT
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            have = dest.stat().st_size if dest.exists() else 0
            headers = {"Range": f"bytes={have}-"} if have else {}
            with SESSION.get(url, stream=True, timeout=timeout, headers=headers) as r:
                if have and r.status_code == 416:
                    return dest  # ya completo
                if r.status_code not in (200, 206):
                    r.raise_for_status()
                mode = "ab" if r.status_code == 206 else "wb"
                total = int(r.headers.get("Content-Length") or 0) + have
                prog = Progress(label or dest.name, total) if label else None
                got = have
                with open(dest, mode) as fh:
                    for chunk in r.iter_content(1 << 20):
                        if chunk:
                            fh.write(chunk)
                            got += len(chunk)
                            if prog:
                                prog.update(got)
                if prog:
                    prog.finish()
            if dest.stat().st_size == 0:
                raise IOError("descarga vacia")
            return dest
        except Exception as e:
            log.warning("intento %d/%d fallo en %s: %s", attempt, config.MAX_RETRIES, url, e)
            if attempt == config.MAX_RETRIES:
                raise
            time.sleep(min(2 ** attempt, 30))


def download_zip(identifier, workdir):
    """Descarga el ZIP de /compress/ (el destino del boton a.boxy-ttl)."""
    dest = workdir / f"{identifier}.zip"
    # /compress/ arma el ZIP al vuelo: puede tardar antes del primer byte.
    log.info("descargando ZIP de /compress/ (se genera al vuelo, puede demorar)")
    _stream(COMPRESS.format(identifier), dest, label="  descarga ZIP")
    # /compress/ genera al vuelo: validamos que sea un ZIP integro.
    try:
        with zipfile.ZipFile(dest) as z:
            if z.testzip() is not None:
                raise zipfile.BadZipFile("CRC invalido")
    except zipfile.BadZipFile as e:
        dest.unlink(missing_ok=True)
        raise IOError(f"ZIP corrupto desde /compress/: {e}")
    return dest


def build_zip_originals(identifier, meta, workdir):
    """Fallback / modo liviano: baja solo archivos 'original' y comprime local."""
    files = [f for f in meta.get("files", []) if f.get("source") == "original"]
    staging = workdir / "orig"
    staging.mkdir(parents=True, exist_ok=True)
    total = sum(int(f.get("size", 0) or 0) for f in files)
    log.info("bajando %d archivos originales (%s)", len(files), human(total))
    for i, f in enumerate(files, 1):
        name = f["name"]
        target = staging / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and str(target.stat().st_size) == f.get("size"):
            continue
        log.info("  [%d/%d] %s", i, len(files), Path(name).name)
        _stream(DOWNLOAD.format(identifier, quote(name)), target)
    dest = workdir / f"{identifier}.zip"
    # Comprimir cientos de MB tarda: avisamos antes de quedar en silencio.
    log.info("comprimiendo %s en ZIP local...", human(total))
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(staging.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(staging))
    log.info("ZIP local listo: %s", human(dest.stat().st_size))
    return dest


def download_images(identifier, meta, workdir):
    """Descarga solo las imagenes originales del disco (caratulas).

    archive.org genera por cada pista un waveform y un espectrograma .png
    marcados como 'derivative': no son parte del material y se omiten.
    __ia_thumb.jpg tambien lo genera archive.org, aunque figure como original.
    """
    out = []
    imgs = workdir / "images"
    imgs.mkdir(parents=True, exist_ok=True)
    for f in meta.get("files", []):
        name = f["name"]
        if Path(name).suffix.lower() not in config.IMAGE_EXT:
            continue
        if f.get("source") != "original":
            continue
        if Path(name).name == "__ia_thumb.jpg":
            continue
        target = imgs / Path(name).name
        if target.exists():
            continue
        try:
            _stream(DOWNLOAD.format(identifier, quote(name)), target)
            out.append(target)
        except Exception as e:
            log.warning("imagen fallo %s: %s", name, e)
    return out


def write_metadata(identifier, meta, workdir):
    """Guarda metadatos completos: JSON + los XML del item."""
    files = []
    j = workdir / f"{identifier}_metadata.json"
    j.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    files.append(j)
    for f in meta.get("files", []):
        n = f["name"]
        if n.endswith((".xml", "_meta.sqlite")):
            t = workdir / Path(n).name
            try:
                _stream(DOWNLOAD.format(identifier, quote(n)), t)
                files.append(t)
            except Exception as e:
                log.warning("metadato fallo %s: %s", n, e)
    return files
