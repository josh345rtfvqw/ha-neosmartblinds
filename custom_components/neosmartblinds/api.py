"""Talking to a Neo Smart Controller over HTTP or TCP."""

from __future__ import annotations

import asyncio
import logging
import time

import aiohttp
from yarl import URL

from .const import COMMAND_TIMEOUT, PROTOCOL_HTTP

_LOGGER = logging.getLogger(__name__)

TRANSMIT_PATH = "/neo/v1/transmit"


class NeoError(Exception):
    """Base error for controller problems."""


class NeoConnectionError(NeoError):
    """The controller could not be reached or did not answer."""


class NeoAuthError(NeoError):
    """The controller did not recognise the controller ID (HTTP 401)."""


class NeoCommandError(NeoError):
    """The controller answered but refused the command."""

    def __init__(self, status: int, reason: str) -> None:
        """Store the HTTP status."""
        super().__init__(reason)
        self.status = status
        self.reason = reason


_STATUS_REASONS = {
    400: "the controller says the command is invalid (400)",
    401: "the controller ID was not found (401)",
    404: "the controller did not recognise the request path (404)",
    409: "the controller had already seen the hash (409)",
}


def status_reason(status: int) -> str:
    """Return a readable reason for an HTTP status."""
    return _STATUS_REASONS.get(status, f"the controller returned HTTP status {status}")


class HashSource:
    """Seven-digit hashes that are never the same twice in a row."""

    def __init__(self) -> None:
        """Start with no previous hash."""
        self._last: int | None = None

    def next(self) -> str:
        """Return the next hash: the last 7 digits of the time in ms."""
        value = int(time.time() * 1000) % 10_000_000
        if self._last is not None and value <= self._last < value + 1000:
            # Same or slightly older millisecond: step past the last one sent.
            value = (self._last + 1) % 10_000_000
        self._last = value
        return f"{value:07d}"


async def async_check_connection(host: str, port: int, timeout: float = COMMAND_TIMEOUT) -> None:
    """Open and close a TCP connection to the controller. Sends nothing."""
    try:
        async with asyncio.timeout(timeout):
            _reader, writer = await asyncio.open_connection(host, port)
    except (OSError, TimeoutError) as err:
        raise NeoConnectionError(str(err) or "connection timed out") from err
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass


class NeoClient:
    """Sends single commands to one controller. Callers must serialise calls."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        protocol: str,
        hub_id: str,
    ) -> None:
        """Store the connection details."""
        self._session = session
        self.host = host
        self.port = port
        self.protocol = protocol
        self.hub_id = hub_id
        self._hashes = HashSource()

    async def async_check(self) -> None:
        """Check a TCP connection can be opened."""
        await async_check_connection(self.host, self.port)

    async def async_send(self, command: str) -> None:
        """Send one command. Raises a NeoError subclass on failure."""
        if self.protocol == PROTOCOL_HTTP:
            await self._send_http(command)
        else:
            await self._send_tcp(command)

    def _url(self, command: str) -> URL:
        # Built by hand so characters like "!" reach the controller unescaped,
        # as in Neo's examples. Every part is already limited to safe characters.
        return URL(
            f"http://{self.host}:{self.port}{TRANSMIT_PATH}"
            f"?command={command}&id={self.hub_id}&hash={self._hashes.next()}",
            encoded=True,
        )

    async def _send_http(self, command: str) -> None:
        status = await self._http_once(command)
        if status == 409:
            _LOGGER.debug("Hash already used for %s, retrying with a new one", command)
            status = await self._http_once(command)
        if status == 200:
            return
        if status == 401:
            raise NeoAuthError(status_reason(status))
        raise NeoCommandError(status, status_reason(status))

    async def _http_once(self, command: str) -> int:
        url = self._url(command)
        try:
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=COMMAND_TIMEOUT)
            ) as response:
                await response.read()
                return response.status
        except (aiohttp.ClientError, TimeoutError, OSError) as err:
            raise NeoConnectionError(str(err) or type(err).__name__) from err

    async def _send_tcp(self, command: str) -> None:
        try:
            async with asyncio.timeout(COMMAND_TIMEOUT):
                reader, writer = await asyncio.open_connection(self.host, self.port)
                try:
                    writer.write(f"{command}\r\n".encode("ascii"))
                    await writer.drain()
                    # The controller echoes what it received, then closes.
                    echo = await reader.readline()
                finally:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except OSError:
                        pass
        except (OSError, TimeoutError) as err:
            raise NeoConnectionError(str(err) or "connection timed out") from err
        if not echo:
            raise NeoConnectionError("the controller closed the connection without replying")
        _LOGGER.debug("TCP echo for %s: %r", command, echo)
