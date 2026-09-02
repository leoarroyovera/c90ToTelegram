"""Reporte de progreso legible para descargas y subidas largas."""
import logging
import time

log = logging.getLogger("c90.progress")


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
        n /= 1024


class Progress:
    """Emite una linea cada `interval` segundos, con velocidad y ETA.

    Pensado para operaciones de minutos: sin esto la consola queda muda y
    el proceso parece colgado.
    """

    def __init__(self, label, total=0, interval=15.0):
        self.label = label
        self.total = int(total or 0)
        self.interval = interval
        self.done = 0
        self.start = time.monotonic()
        self.last = self.start
        self.last_done = 0

    def update(self, done, total=None):
        """`done` es el acumulado, no el incremento."""
        self.done = int(done)
        if total:
            self.total = int(total)
        now = time.monotonic()
        if now - self.last < self.interval:
            return
        span = now - self.last
        rate = (self.done - self.last_done) / span if span > 0 else 0
        self.last, self.last_done = now, self.done

        parts = [f"{self.label}: {human(self.done)}"]
        if self.total:
            parts.append(f"/ {human(self.total)} ({self.done * 100 / self.total:.0f}%)")
        parts.append(f"a {human(rate)}/s")
        if self.total and rate > 0:
            eta = (self.total - self.done) / rate
            parts.append(f"ETA {int(eta // 60)}m{int(eta % 60):02d}s")
        log.info(" ".join(parts))

    def finish(self):
        span = max(time.monotonic() - self.start, 1e-6)
        log.info("%s: completo %s en %.0fs (%s/s)",
                 self.label, human(self.done), span, human(self.done / span))
