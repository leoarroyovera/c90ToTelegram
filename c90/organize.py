"""Parseo de titulos y reglas de organizacion del supergrupo."""
import re
import unicodedata

# 'Artista - Album (Año) [Formato]' -> cubre ~95% de los items.
TITLE_RE = re.compile(r"^(?P<artist>.*?)\s+-\s+(?P<album>.*?)\s*\((?P<year>\d{4})\)\s*(?:\[(?P<fmt>[^\]]+)\])?\s*$")

VARIOS = "Varios Intérpretes"
TOPIC_VARIOS = "Varios Intérpretes"
TOPIC_VIDEOS = "Videos"
TOPIC_OTROS = "Otros"


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def parse_title(title, meta=None):
    """Extrae artista/album/año/formato. Cae a `subject` y `date` si hace falta."""
    title = (title or "").strip()
    m = TITLE_RE.match(title)
    info = {"artist": "", "album": title, "year": "", "fmt": ""}
    if m:
        info.update(artist=m.group("artist").strip(),
                    album=m.group("album").strip(),
                    year=m.group("year"),
                    fmt=(m.group("fmt") or "").strip())
    elif " - " in title:
        a, _, b = title.partition(" - ")
        info.update(artist=a.strip(), album=b.strip())

    md = (meta or {}).get("metadata", {}) if meta else {}
    if not info["artist"]:
        # subject[0] es el artista real; `creator` es el sello discografico.
        subj = md.get("subject")
        if isinstance(subj, list) and subj:
            info["artist"] = str(subj[0]).strip()
        elif isinstance(subj, str) and subj:
            info["artist"] = subj.split(";")[0].strip()
    if not info["year"]:
        for k in ("year", "date"):
            v = md.get(k)
            if v:
                mm = re.search(r"\d{4}", str(v))
                if mm:
                    info["year"] = mm.group(0)
                    break
    return info


# Etiquetas de catalogacion que archive.org agrega a subject y que no
# son artistas: no deben convertirse en hashtags.
NO_ARTISTA = {"wav/flac", "flac", "wave", "wav", "mp3", "vbr mp3", "24bit flac",
              "cumbia", "musica", "music", "audio", "cd", "album"}


def subject_list(subj):
    """Normaliza `subject` a lista de artistas.

    Viene como lista o como un solo string separado por ';' o ','.
    """
    if not subj:
        return []
    partes = subj if isinstance(subj, list) else re.split(r"[;,]", str(subj))
    out = []
    for p in partes:
        p = str(p).strip()
        if p and p.lower() not in NO_ARTISTA:
            out.append(p)
    return out


def is_varios(artist):
    a = strip_accents((artist or "").lower())
    return a.startswith("varios") or "interpretes" in a


# Sin esto, 'La'/'Los'/'Las' amontonan 1324 items (24%) bajo la letra L,
# y 'Grupo' otros 681 bajo la G. Se ignoran para clasificar y ordenar,
# igual que en las tiendas de discos.
ARTICULOS = ("la ", "las ", "los ", "el ", "grupo ", "conjunto ",
             "orquesta ", "banda ", "sonora ", "the ")


def sort_name(artist):
    """Nombre para clasificar: sin acentos, sin articulo inicial."""
    a = strip_accents(artist or "").strip().lstrip("¿¡\"'([").upper()
    for art in ARTICULOS:
        if a.startswith(art.upper()) and len(a) > len(art):
            return a[len(art):].strip()
    return a


def topic_for(info, mediatype="audio"):
    """Devuelve el nombre del tema del supergrupo donde va este item."""
    if mediatype in ("movies", "video"):
        return TOPIC_VIDEOS
    artist = info.get("artist") or ""
    if is_varios(artist):
        return TOPIC_VARIOS
    a = sort_name(artist)
    if not a:
        return TOPIC_OTROS
    c = a[0]
    if c.isdigit():
        return "0-9"
    if "A" <= c <= "Z":
        return c
    return TOPIC_OTROS


# Windows prohibe < > : " / \ | ? * en nombres de archivo, y Telegram
# muestra el nombre tal cual: hay que sanearlo sin volverlo ilegible.
ILEGALES = r'[<>:"/\\|?*\x00-\x1f]'
NOMBRE_MAX = 120


def safe_filename(title, fallback="item", ext=".zip"):
    """Convierte el title de archive.org en un nombre de archivo valido.

    Mantiene acentos y mayusculas (Telegram los muestra bien); solo cambia
    lo que romperia el sistema de archivos.
    """
    name = (title or "").strip()
    # '[Metadata]' es ruido de catalogacion. Solo se quita esa etiqueta:
    # las demas ([Flac], [WAVE], [CD1], [Vinilo]...) describen el disco.
    name = re.sub(r"\s*\[\s*metadata\s*\]", "", name, flags=re.I)
    # ':' suele separar subtitulos ("2 Albumes en 1 CD: X - Y"): queda mejor
    # como guion que borrado.
    name = name.replace(":", " -")
    name = re.sub(ILEGALES, "", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = fallback
    if len(name) > NOMBRE_MAX:
        name = name[:NOMBRE_MAX].rstrip(" .-")
    return name + ext


def topic_order(topic):
    """Orden de los temas: 0-9, A-Z, y al final Varios / Videos / Otros."""
    if topic == "0-9":
        return (0, "")
    if len(topic) == 1 and "A" <= topic <= "Z":
        return (1, topic)
    return ({TOPIC_VARIOS: 2, TOPIC_VIDEOS: 3, TOPIC_OTROS: 4}.get(topic, 5), topic)


def sort_key(info, identifier=""):
    """Orden dentro del tema: artista, luego año, luego album.

    Usa el mismo nombre sin articulo que topic_for, para que el orden
    coincida con la letra bajo la que quedo clasificado.
    """
    return (sort_name(info.get("artist", "")),
            info.get("year") or "9999",
            strip_accents(info.get("album", "")).upper(),
            identifier)


def hashtag(s):
    """#SonoraDinamita a partir de 'La Sonora Dinamita'."""
    s = strip_accents(s or "")
    parts = re.findall(r"[A-Za-z0-9]+", s)
    if not parts:
        return ""
    tag = "".join(p.capitalize() if not p.isupper() else p for p in parts)
    if tag and tag[0].isdigit():
        tag = "n" + tag
    return "#" + tag[:60]
