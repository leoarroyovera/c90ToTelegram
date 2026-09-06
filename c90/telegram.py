"""Subida a Telegram vía Telethon (cuenta de usuario, hasta 2GB por archivo)."""
import asyncio
import html
import logging
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl import types
from telethon.tl.functions.channels import CreateChannelRequest
# Los temas viven en functions.messages, no en functions.channels.
from telethon.tl.functions.messages import (CreateForumTopicRequest,
                                            GetForumTopicsRequest)
from telethon.tl.types import ForumTopic

from . import config, organize
from .fast_upload import upload_file_fast
from .progress import Progress, human

log = logging.getLogger("c90.telegram")


async def get_client():
    if not config.API_ID or not config.API_HASH:
        raise SystemExit(
            "Falta TG_API_ID / TG_API_HASH. Obtenlos en https://my.telegram.org "
            "-> API development tools, y ponlos en el archivo .env"
        )
    client = TelegramClient(str(config.ROOT / config.SESSION_NAME), config.API_ID, config.API_HASH)
    await client.start()
    return client


async def ensure_channel(client):
    """Busca el supergrupo privado C90 con temas; lo crea si no existe.

    Es un supergrupo (megagroup=True) y no un canal porque solo los
    supergrupos admiten temas, que es lo que da la estructura A-Z.
    """
    async for d in client.iter_dialogs():
        if d.is_channel and d.name == config.CHANNEL_NAME:
            ent = d.entity
            if not getattr(ent, "megagroup", False):
                log.warning(
                    "'%s' es un canal, no un supergrupo: no admite temas. "
                    "Renombralo o borralo para que se cree el supergrupo.",
                    config.CHANNEL_NAME)
            return ent
    log.info("creando supergrupo privado %s con temas", config.CHANNEL_NAME)
    res = await client(CreateChannelRequest(
        title=config.CHANNEL_NAME,
        about="Respaldo de archive.org/details/@cumbia_noventera",
        megagroup=True,
        forum=True,
    ))
    return res.chats[0]


async def ensure_topics(client, group, nombres):
    """Crea los temas que falten y devuelve {nombre: topic_id}.

    Si los temas no se pueden crear, aborta: subir sin ellos dejaria miles
    de items sueltos en la raiz, y Telegram no permite reordenarlos despues.
    """
    topics = {}
    try:
        res = await client(GetForumTopicsRequest(
            peer=group, offset_date=0, offset_id=0, offset_topic=0, limit=100))
        for t in res.topics:
            if isinstance(t, ForumTopic):
                topics[t.title] = t.id
    except Exception as e:
        raise IOError(f"no se pudieron listar los temas de {config.CHANNEL_NAME}: {e}")

    for n in nombres:
        if n in topics:
            continue
        for _ in range(config.MAX_RETRIES):
            try:
                r = await client(CreateForumTopicRequest(peer=group, title=n))
                # El id del tema es el id del mensaje de servicio que lo abre.
                mid = next((u.id for u in r.updates if hasattr(u, "id")), None)
                if not mid:
                    raise IOError("la respuesta no trae el id del tema")
                topics[n] = mid
                log.info("tema creado: %s", n)
                await asyncio.sleep(1.0)
                break
            except FloodWaitError as e:
                log.warning("FloodWait al crear tema: %ds", e.seconds)
                await asyncio.sleep(e.seconds + 5)
        else:
            raise IOError(f"no se pudo crear el tema '{n}'")

    faltan = [n for n in nombres if n not in topics]
    if faltan:
        raise IOError(f"faltan temas por crear: {faltan}")
    log.info("%d temas listos", len(topics))
    return topics


def split_file(path: Path, chunk=None):
    """Parte un archivo en volumenes .partNNN si excede el limite."""
    chunk = chunk or config.SPLIT_SIZE

    # Primero: si una corrida previa ya partio esto y murio, el original ya
    # no existe. Hay que mirar los volumenes antes de tocar path.stat().
    done = sorted(path.parent.glob(path.name + ".part*"))
    if done and not path.exists():
        log.info("%s: reusando %d volumenes de una corrida previa", path.name, len(done))
        return done

    size = path.stat().st_size
    if size <= chunk:
        return [path]

    parts, idx = [], 1
    # Escribimos en trozos de 8MB y truncamos el origen al terminar cada
    # volumen, para no necesitar el doble del tamaño en disco.
    with open(path, "r+b") as src:
        while True:
            offset = src.tell()
            p = path.with_suffix(path.suffix + f".part{idx:03d}")
            written = 0
            with open(p, "wb") as out:
                while written < chunk:
                    data = src.read(min(1 << 23, chunk - written))
                    if not data:
                        break
                    out.write(data)
                    written += len(data)
            if written == 0:
                p.unlink(missing_ok=True)
                break
            parts.append(p)
            if written < chunk:
                break
            idx += 1
    log.info("%s partido en %d volumenes", path.name, len(parts))
    path.unlink()  # el contenido ya vive en los volumenes
    return parts


async def upload_file_parallel(client, path: Path, progress_callback=None):
    """Sube un archivo con multiples conexiones TCP reales al mismo
    datacenter (ver c90.fast_upload). Devuelve un InputFileBig/InputSizedFile
    utilizable en send_file(file=...).
    """
    return await upload_file_fast(client, path, progress_callback=progress_callback)


CAPTION_MAX = 1024
AUDIO_EXT = (".flac", ".mp3", ".wav", ".m4a", ".ogg", ".ape", ".wma")


def track_names(meta):
    """Nombres de pista, en orden, sin duplicar por formato."""
    seen, out = set(), []
    for f in meta.get("files", []):
        if f.get("source") != "original":
            continue
        name = f["name"]
        if not name.lower().endswith(AUDIO_EXT):
            continue
        stem = Path(name).stem
        key = stem.lower()
        if key not in seen:
            seen.add(key)
            out.append(stem)
    return sorted(out)


def build_caption(identifier, meta):
    """Caption buscable: la busqueda de Telegram solo indexa esto.

    Por eso van los nombres de pista: sin ellos no hay forma de encontrar
    una cancion suelta dentro del canal.
    """
    m = meta.get("metadata", {})

    def g(k):
        v = m.get(k)
        return ", ".join(str(x) for x in v) if isinstance(v, list) else v

    info = organize.parse_title(g("title") or "", meta)
    artist = info["artist"] or "?"
    tracks = track_names(meta)
    total = sum(int(f.get("size", 0) or 0) for f in meta.get("files", []))

    head = [f"<b>{html.escape(info['album'] or identifier)}</b>",
            f"Artista: {html.escape(artist)}"]
    linea2 = []
    if info["year"]:
        linea2.append(info["year"])
    if g("creator"):
        linea2.append(html.escape(str(g("creator"))))
    if info["fmt"]:
        linea2.append(html.escape(info["fmt"]))
    if linea2:
        head.append(" · ".join(linea2))
    head.append(f"{len(tracks)} pistas · {human(total)}")

    tags = [organize.hashtag(artist)]
    if info["year"]:
        tags.append("#a" + info["year"])
    if info["fmt"]:
        tags.append(organize.hashtag(info["fmt"]))
    # En compilados, subject trae los artistas participantes. Puede venir
    # como lista o como un solo string con ';' o ',' de separador: sin
    # partirlo se genera un unico hashtag gigante e inservible.
    if organize.is_varios(artist):
        for s in organize.subject_list(m.get("subject"))[:6]:
            t = organize.hashtag(s)
            if t and t not in tags and len(t) > 3:
                tags.append(t)
    tail = [" ".join(t for t in tags if t),
            f"https://archive.org/details/{identifier}"]

    # Las pistas ocupan lo que sobre: primero cabecera, tags y enlace.
    fijo = "\n".join(head) + "\n\n" + "\n".join(tail)
    libre = CAPTION_MAX - len(fijo) - 2
    cuerpo = ""
    if tracks and libre > 40:
        acc, usados = [], 0
        for t in tracks:
            linea = html.escape(t[:70])
            if usados + len(linea) + 1 > libre - 15:
                acc.append(f"… (+{len(tracks) - len(acc)} más)")
                break
            acc.append(linea)
            usados += len(linea) + 1
        cuerpo = "\n".join(acc)

    partes = ["\n".join(head)]
    if cuerpo:
        partes.append(cuerpo)
    partes.append("\n".join(tail))
    return "\n\n".join(partes)[:CAPTION_MAX]


async def send_files(client, channel, files, caption=None, reply_to=None, quiet=False):
    """Sube archivos con manejo de FloodWait. Devuelve el primer mensaje.

    `quiet` omite el progreso para lotes de archivos chicos (imagenes, XML).
    """
    first = None
    for i, f in enumerate(files):
        f = Path(f)
        size = f.stat().st_size
        # Sin esto la consola queda muda durante toda la subida y el
        # proceso parece colgado.
        show = not quiet and size > 8 * 1024 * 1024
        if show:
            log.info("subiendo %s (%s)%s", f.name, human(size),
                     f" [{i + 1}/{len(files)}]" if len(files) > 1 else "")
        for attempt in range(config.MAX_RETRIES):
            try:
                prog = Progress("  subida", size) if show else None
                cb = (lambda c, t, p=prog: p.update(c, t)) if prog else None
                # Subida propia en paralelo: client.send_file() usa
                # upload_file() de Telethon, que manda las partes una por
                # una esperando el ACK de cada una. Para archivos grandes
                # eso es mucho mas lento que Telegram Desktop/Web.
                handle = await upload_file_parallel(client, f, progress_callback=cb)
                msg = await client.send_file(
                    channel, handle,
                    caption=caption if i == 0 else None,
                    parse_mode="html",
                    reply_to=reply_to,
                    force_document=True,
                    file_size=size,
                    attributes=[types.DocumentAttributeFilename(f.name)],
                )
                if prog:
                    prog.finish()
                first = first or msg
                break
            except FloodWaitError as e:
                # Telegram limita el ritmo; esperar lo que pida es lo correcto.
                log.warning("FloodWait: Telegram pide esperar %ds", e.seconds)
                await asyncio.sleep(e.seconds + 5)
        else:
            raise IOError(f"no se pudo subir {f}")
    return first


# Telegram rechaza fotos de mas de 10MB y agrupa como maximo 10 por album.
PHOTO_MAX = 10 * 1024 * 1024
ALBUM_MAX = 10


async def send_photos(client, channel, images, reply_to=None):
    """Sube caratulas como media visible (no como documento).

    Sin force_document Telegram las comprime y las muestra en linea, que es
    como se ven las fotos al arrastrarlas al chat. Van agrupadas en album
    para no inundar el canal con un mensaje por imagen.
    """
    paths = [Path(p) for p in images]
    # Una foto muy pesada la rechaza el servidor: esa va como documento.
    photos = [p for p in paths if p.stat().st_size <= PHOTO_MAX]
    heavy = [p for p in paths if p.stat().st_size > PHOTO_MAX]
    sent = None

    for i in range(0, len(photos), ALBUM_MAX):
        lote = photos[i:i + ALBUM_MAX]
        for attempt in range(config.MAX_RETRIES):
            try:
                msg = await client.send_file(
                    channel, [str(p) for p in lote],
                    reply_to=reply_to,
                    force_document=False,
                )
                sent = sent or msg
                break
            except FloodWaitError as e:
                log.warning("FloodWait: Telegram pide esperar %ds", e.seconds)
                await asyncio.sleep(e.seconds + 5)
        else:
            raise IOError(f"no se pudieron subir las caratulas {lote}")

    if heavy:
        log.info("%d caratula(s) >10MB van como documento", len(heavy))
        await send_files(client, channel, heavy, reply_to=reply_to, quiet=True)
    return sent
