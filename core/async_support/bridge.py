"""Puente entre vistas async y el Service Layer (sync, porque el ORM
de Django sigue siendo sync). `sync_to_async` corre el código sync en
un threadpool sin bloquear el event loop, así la vista puede seguir
atendiendo otras peticiones mientras espera la DB.

thread_sensitive=True es obligatorio: el ORM usa conexiones ligadas al
thread, así que todo el trabajo de una misma request debe correr en el
mismo thread (evita 'DatabaseError: database is being accessed by
another thread' en SQLite y problemas de conexión en Postgres).
"""
import asyncio
import logging

from asgiref.sync import sync_to_async

logger = logging.getLogger("ticketera")

# Loop principal del servidor ASGI, capturado una vez al arrancar
# (config/asgi.py). Los Observers corren dentro del threadpool de
# sync_to_async (sin loop propio); para lanzar una tarea async real
# desde ahí hace falta agendarla contra este loop con
# run_coroutine_threadsafe, en vez de asyncio.create_task (que exige
# estar ya dentro de un loop corriendo en el thread actual).
_main_loop: asyncio.AbstractEventLoop | None = None


def register_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


def to_async(func):
    """Decorator: convierte una función/método sync en awaitable."""
    return sync_to_async(func, thread_sensitive=True)


def fire_and_forget(coro) -> None:
    """Lanza una corutina sin esperar su resultado, desde código sync
    (ej. un Observer disparado dentro del Service). Si no hay loop ASGI
    registrado (ej. management command, tests), se ejecuta sync como
    fallback para no perder la notificación."""
    if _main_loop is not None and _main_loop.is_running():
        asyncio.run_coroutine_threadsafe(coro, _main_loop)
    else:
        try:
            asyncio.run(coro)
        except RuntimeError:
            logger.warning("No se pudo agendar tarea async: sin loop disponible.")
