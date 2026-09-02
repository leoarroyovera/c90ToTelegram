# C90 — Respaldo de archive.org a Telegram

Respalda los 5630 items de [archive.org/details/@cumbia_noventera](https://archive.org/details/@cumbia_noventera)
a un canal privado de Telegram llamado **C90**.

Por cada item sube, en un mismo hilo:
- el **ZIP comprimido** (el destino del boton `a.boxy-ttl.hover-badge` = `/compress/<id>`),
- las **imagenes** (caratulas, sin espectrogramas),
- los **metadatos**: JSON completo de `/metadata/` + los `_meta.xml`, `_files.xml`, `_meta.sqlite`.

El mensaje del ZIP lleva un pie con titulo, creador, fecha, licencia, tamaño y enlace al item.

## Configuracion

**1. Credenciales de Telegram** — entra a https://my.telegram.org → *API development tools*,
crea una app y copia `api_id` y `api_hash`:

```
cp .env.example .env      # y edita .env con tus valores
```

**2. Primera ejecucion** (login interactivo, una sola vez):

```
python run.py run --limit 1
```

Pedira tu telefono, el codigo que llega por Telegram y tu clave 2FA si la tienes.
Queda guardado en `c90_session.session`; las siguientes corridas no preguntan nada.
El canal privado **C90** se crea solo si no existe.

## Uso

```
python run.py sync              # refresca la lista (para discos nuevos)
python run.py run               # descarga y sube todo lo pendiente
python run.py run --limit 10    # procesa solo 10 items
python run.py status            # progreso
```

Es **reanudable**: el avance vive en `state.sqlite`. Si lo cortas con Ctrl+C,
al volver a lanzar `run` sigue donde iba. Los fallidos se reintentan solos
en la siguiente corrida.

Cuando subas discos nuevos a archive.org, `sync` los detecta y `run` los sube.

## Opciones (.env)

| Variable | Efecto |
|---|---|
| `C90_ORIGINALS_ONLY=1` | ZIP solo con archivos originales, omitiendo los mp3/png que archive.org genera. Reduce ~20% el volumen. |
| `C90_CLEANUP=0` | Conserva las descargas en `work/` en vez de borrarlas tras subir. |

## Notas sobre el volumen

La coleccion son **~3.5 TB**. Consideraciones:

- Con `CLEANUP=1` (por defecto) el disco nunca guarda mas de un item a la vez.
- Telethon sube hasta 2 GB por archivo; los ZIP mayores se parten en volumenes
  `.part001`, `.part002`… Para reconstruirlos:
  `cat archivo.zip.part* > archivo.zip` (Linux/Mac)
  `cmd /c copy /b archivo.zip.part001+archivo.zip.part002 archivo.zip` (Windows)
- **16 items de video superan los 2 GB**; el mayor (8.78 GB) son 5 volumenes.
- Subir 3.5 TB toma dias. Conviene dejarlo corriendo por tandas con `--limit`.
- El script respeta los `FloodWait` de Telegram esperando lo que pida el servidor.
