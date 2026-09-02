"""Respaldo de archive.org/@cumbia_noventera al canal privado C90 de Telegram."""
import argparse
import asyncio
import logging
import shutil
import sys

from . import archive, config, organize, state, telegram

log = logging.getLogger("c90")


def setup_logging(verbose=False):
    # La consola de Windows usa cp1252 y rompe acentos; forzamos UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)],
    )
    logging.getLogger("telethon").setLevel(logging.WARNING)


def cmd_sync():
    """Refresca la lista de items (soporta discos nuevos subidos despues)."""
    state.init()
    items = archive.list_items()
    added = state.add_items(items)
    print(f"Total en archive.org: {len(items)} | nuevos registrados: {added}")
    for st, d in sorted(state.stats().items()):
        print(f"  {st:10s} {d['n']:6d}")


async def process_item(client, channel, identifier, title, topic_id=None):
    """Descarga un item completo y lo sube a su tema del supergrupo."""
    work = config.WORK_DIR / identifier
    work.mkdir(parents=True, exist_ok=True)
    try:
        meta = archive.get_metadata(identifier)
        if not meta.get("files"):
            raise IOError("item sin archivos (¿oscurecido o eliminado?)")

        caption = telegram.build_caption(identifier, meta)

        # 1) ZIP comprimido: /compress/ (boton a.boxy-ttl), con fallback local.
        if config.ORIGINALS_ONLY:
            zpath = archive.build_zip_originals(identifier, meta, work)
        else:
            try:
                zpath = archive.download_zip(identifier, work)
            except Exception as e:
                log.warning("%s: /compress/ fallo (%s); comprimiendo originales", identifier, e)
                zpath = archive.build_zip_originals(identifier, meta, work)

        nbytes = zpath.stat().st_size
        # El ZIP se arma con el identifier (asi se reusa entre corridas);
        # se renombra al title recien ahora, que es el nombre que vera
        # Telegram. Si dos discos comparten title, el identifier desempata.
        titulo = (meta.get("metadata", {}) or {}).get("title") or identifier
        nombre = organize.safe_filename(titulo, fallback=identifier)
        destino = zpath.with_name(nombre)
        if destino != zpath:
            if destino.exists():
                destino.unlink()
            zpath = zpath.rename(destino)

        parts = telegram.split_file(zpath)

        # El ZIP encabeza el hilo dentro de su tema; las caratulas responden.
        root = await telegram.send_files(client, channel, parts, caption=caption,
                                         reply_to=topic_id)

        # Los metadatos (JSON + XML) ya viajan dentro del ZIP: no se suben
        # sueltos. Solo van las caratulas originales, como media visible.
        images = archive.download_images(identifier, meta, work)
        if images:
            log.info("subiendo %d caratulas como media", len(images))
            await telegram.send_photos(client, channel, images, reply_to=root)

        state.mark(identifier, "done", parts=len(parts), nbytes=nbytes)
        log.info("OK %s (%.1f MB, %d partes)", identifier, nbytes / 1e6, len(parts))
        return True
    except Exception as e:
        log.error("FALLO %s: %s", identifier, e)
        state.mark(identifier, "failed", error=str(e)[:500])
        return False
    finally:
        if config.CLEANUP:
            shutil.rmtree(work, ignore_errors=True)


def plan(rows):
    """Ordena los items por tema y, dentro de cada uno, artista/año/album.

    El orden de subida es el orden definitivo: Telegram no permite
    reordenar mensajes despues.
    """
    out = []
    for r in rows:
        info = organize.parse_title(r.get("title") or "")
        out.append({**r, "info": info,
                    "topic": organize.topic_for(info, r.get("mediatype") or "audio")})
    out.sort(key=lambda r: (organize.topic_order(r["topic"]),
                            organize.sort_key(r["info"], r["identifier"])))
    return out


async def cmd_run(limit=None):
    state.init()
    todo = plan(state.pending(limit))
    if not todo:
        print("Nada pendiente. Ejecuta 'sync' para buscar items nuevos.")
        return
    print(f"Pendientes: {len(todo)}")
    client = await telegram.get_client()
    try:
        group = await telegram.ensure_channel(client)
        # Se crean los 30 temas de una vez y en orden, aunque el lote actual
        # use pocos: asi el supergrupo queda ordenado desde el principio y
        # no aparecen temas nuevos intercalados en cada tanda.
        nombres = sorted({r["topic"] for r in plan(state.pending())},
                         key=organize.topic_order)
        topics = await telegram.ensure_topics(client, group, nombres)
        ok = fail = 0
        for i, it in enumerate(todo, 1):
            log.info("[%d/%d] %s -> tema %s", i, len(todo), it["identifier"], it["topic"])
            if await process_item(client, group, it["identifier"], it["title"],
                                  topic_id=topics.get(it["topic"])):
                ok += 1
            else:
                fail += 1
        print(f"\nCompletados: {ok} | fallidos: {fail}")
    finally:
        await client.disconnect()


def cmd_status():
    state.init()
    st = state.stats()
    total = sum(d["n"] for d in st.values())
    print(f"Total registrado: {total}")
    for k, d in sorted(st.items()):
        print(f"  {k:10s} {d['n']:6d}  {d['bytes'] / 1e9:8.2f} GB")


def main():
    p = argparse.ArgumentParser(description="Respaldo archive.org -> Telegram C90")
    p.add_argument("cmd", choices=["sync", "run", "status"],
                   help="sync: listar items | run: descargar y subir | status: progreso")
    p.add_argument("--limit", type=int, help="procesar solo N items (util para probar)")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    setup_logging(a.verbose)
    config.WORK_DIR.mkdir(parents=True, exist_ok=True)

    if a.cmd == "sync":
        cmd_sync()
    elif a.cmd == "status":
        cmd_status()
    else:
        asyncio.run(cmd_run(a.limit))


if __name__ == "__main__":
    main()
