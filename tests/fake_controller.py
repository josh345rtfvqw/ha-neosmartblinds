"""A fake Neo Smart Controller that speaks HTTP and TCP on localhost."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field

from aiohttp import web


@dataclass
class Received:
    """One request the controller received."""

    protocol: str
    command: str
    hub_id: str | None = None
    hash: str | None = None


@dataclass
class FakeController:
    """Records what it receives. Queue HTTP statuses in `statuses`."""

    hub_id: str = "A" * 24
    received: list[Received] = field(default_factory=list)
    statuses: deque[int] = field(default_factory=deque)
    tcp_silent: bool = False
    http_port: int = 0
    tcp_port: int = 0
    connections: int = 0
    _runner: web.AppRunner | None = None
    _tcp_server: asyncio.base_events.Server | None = None

    @property
    def commands(self) -> list[str]:
        """Return just the commands received, in order."""
        return [item.command for item in self.received]

    def clear(self) -> None:
        """Forget what was received."""
        self.received.clear()

    async def start(self) -> None:
        """Start both servers, on free ports the first time and the same ports after."""
        app = web.Application()
        app.router.add_get("/neo/v1/transmit", self._handle_http)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", self.http_port)
        await site.start()
        self.http_port = site._server.sockets[0].getsockname()[1]  # noqa: SLF001

        self._tcp_server = await asyncio.start_server(
            self._handle_tcp, "127.0.0.1", self.tcp_port
        )
        self.tcp_port = self._tcp_server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        """Stop both servers."""
        if self._runner is not None:
            await self._runner.cleanup()
        if self._tcp_server is not None:
            self._tcp_server.close()
            await self._tcp_server.wait_closed()

    async def _handle_http(self, request: web.Request) -> web.Response:
        self.connections += 1
        command = request.query.get("command", "")
        hub_id = request.query.get("id")
        hash_ = request.query.get("hash")
        self.received.append(Received("http", command.lower(), hub_id, hash_))
        if self.statuses:
            return web.Response(status=self.statuses.popleft())
        if hub_id != self.hub_id:
            return web.Response(status=401)
        return web.Response(status=200)

    async def _handle_tcp(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.connections += 1
        try:
            line = await asyncio.wait_for(reader.readline(), 2)
        except TimeoutError:
            line = b""
        if line:
            self.received.append(Received("tcp", line.decode().strip().lower()))
            if not self.tcp_silent:
                writer.write(line)
                await writer.drain()
        writer.close()
