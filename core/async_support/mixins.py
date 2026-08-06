"""Mixin para vistas async: registra el event loop actual en el bridge
antes de procesar la petición. Los Observers (que corren dentro del
threadpool del Service vía sync_to_async) necesitan esta referencia
para poder agendar tareas async con `fire_and_forget`."""
import asyncio

from core.async_support.bridge import register_main_loop


class LoopRegisteringMixin:
    async def dispatch(self, request, *args, **kwargs):
        register_main_loop(asyncio.get_running_loop())
        return await super().dispatch(request, *args, **kwargs)
