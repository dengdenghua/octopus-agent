from __future__ import annotations

import logging
import re
import socket
import ssl
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from .base import Channel, ChannelMetadata, InboundMessage, OutboundMessage

logger = logging.getLogger(__name__)

_NICK_RE = re.compile(r"^[A-Za-z\[\]\\`_^{|}][A-Za-z0-9\[\]\\`_^{|}-]{0,30}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_MAX_IRC_LINE_BYTES = 512


class IRCError(RuntimeError):
    pass


@dataclass(frozen=True)
class IRCMessage:
    command: str
    params: tuple[str, ...]
    prefix: str = ""
    tags: dict[str, str] | None = None


def parse_irc_line(line: str) -> IRCMessage:
    """Parse one IRC/IRCv3 line without accepting embedded control lines."""
    line = line.rstrip("\r\n")
    if not line or "\r" in line or "\n" in line:
        raise ValueError("invalid IRC line")

    rest = line
    tags: dict[str, str] = {}
    if rest.startswith("@"):
        raw_tags, separator, rest = rest.partition(" ")
        if not separator:
            raise ValueError("IRC tags without command")
        for item in raw_tags[1:].split(";"):
            key, has_value, value = item.partition("=")
            if key:
                tags[key] = _unescape_tag(value) if has_value else ""

    prefix = ""
    if rest.startswith(":"):
        raw_prefix, separator, rest = rest.partition(" ")
        if not separator:
            raise ValueError("IRC prefix without command")
        prefix = raw_prefix[1:]

    head, trailing_separator, trailing = rest.partition(" :")
    parts = head.split()
    if not parts:
        raise ValueError("IRC line without command")
    params = parts[1:]
    if trailing_separator:
        params.append(trailing)
    return IRCMessage(
        command=parts[0].upper(),
        params=tuple(params),
        prefix=prefix,
        tags=tags,
    )


def _unescape_tag(value: str) -> str:
    replacements = {"s": " ", ":": ";", "r": "\r", "n": "\n", "\\": "\\"}
    output: list[str] = []
    index = 0
    while index < len(value):
        if value[index] == "\\" and index + 1 < len(value):
            output.append(replacements.get(value[index + 1], value[index + 1]))
            index += 2
        else:
            output.append(value[index])
            index += 1
    return "".join(output)


def _validate_atom(value: str, label: str, *, max_length: int = 253) -> str:
    clean = value.strip()
    if not clean or len(clean) > max_length or _CONTROL_RE.search(clean) or " " in clean:
        raise ValueError(f"invalid {label}")
    return clean


def _normalize_channels(channels: str | Iterable[str]) -> tuple[str, ...]:
    raw = channels.split(",") if isinstance(channels, str) else list(channels)
    normalized: list[str] = []
    for value in raw:
        channel = value.strip()
        if not channel:
            continue
        if not channel.startswith(("#", "&")):
            channel = f"#{channel}"
        normalized.append(_validate_atom(channel, "channel", max_length=200))
    if not normalized:
        raise ValueError("at least one channel required")
    return tuple(dict.fromkeys(normalized))


class IRCChannel(Channel):
    """Long-lived IRC adapter with IRCv3 IDs and automatic reconnects."""

    channel_id = "irc"

    def __init__(
        self,
        *,
        server: str,
        nickname: str,
        channels: str | Iterable[str],
        port: int = 6697,
        password: str = "",
        username: str | None = None,
        realname: str = "Octopus Agent",
        use_tls: bool = True,
        channel_id: str = "irc",
        connect_timeout_s: float = 10.0,
        reconnect_min_s: float = 1.0,
        reconnect_max_s: float = 30.0,
        socket_factory: Callable[..., socket.socket] | None = None,
    ) -> None:
        self.server = _validate_atom(server, "server")
        if not 1 <= int(port) <= 65535:
            raise ValueError("port must be between 1 and 65535")
        self.port = int(port)
        self.nickname = _validate_atom(nickname, "nickname", max_length=31)
        if not _NICK_RE.fullmatch(self.nickname):
            raise ValueError("invalid nickname")
        self.username = _validate_atom(username or nickname, "username", max_length=31)
        self.realname = realname.strip() or "Octopus Agent"
        if _CONTROL_RE.search(self.realname):
            raise ValueError("invalid realname")
        if _CONTROL_RE.search(password):
            raise ValueError("invalid password")
        self.password = password
        self.channels = _normalize_channels(channels)
        self.use_tls = bool(use_tls)
        self.channel_id = channel_id
        self._connect_timeout_s = max(0.1, float(connect_timeout_s))
        self._reconnect_min_s = max(0.1, float(reconnect_min_s))
        self._reconnect_max_s = max(self._reconnect_min_s, float(reconnect_max_s))
        self._socket_factory = socket_factory
        self._socket: socket.socket | None = None
        self._reader: threading.Thread | None = None
        self._dispatch_pool: ThreadPoolExecutor | None = None
        self._stop_event = threading.Event()
        self._connected = threading.Event()
        self._socket_lock = threading.RLock()
        self.send_log: list[OutboundMessage] = []

    @property
    def platform_name(self) -> str:
        return "irc"

    @property
    def capabilities(self) -> tuple[str, ...]:
        return ("server-time", "message-tags")

    def start(self) -> None:
        with self._socket_lock:
            if self._reader is not None and self._reader.is_alive():
                return
            self._stop_event.clear()
            self._dispatch_pool = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix=f"{self.channel_id}-dispatch",
            )
            try:
                self._connect_locked()
            except Exception:
                self._dispatch_pool.shutdown(wait=False, cancel_futures=True)
                self._dispatch_pool = None
                raise
            self._reader = threading.Thread(
                target=self._reader_loop,
                name=f"{self.channel_id}-reader",
                daemon=True,
            )
            self._reader.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._socket_lock:
            sock = self._socket
            self._socket = None
            self._connected.clear()
        if sock is not None:
            with suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
            with suppress(OSError):
                sock.close()
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=2.0)
        self._reader = None
        pool = self._dispatch_pool
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)
        self._dispatch_pool = None

    def health_check(self) -> bool:
        reader = self._reader
        return bool(self._connected.is_set() and reader is not None and reader.is_alive())

    def send(self, msg: OutboundMessage) -> None:
        self.send_log.append(msg)
        verdict = self.safe_send(msg)
        if verdict.action == "block":
            logger.warning(
                "channel.send.blocked",
                extra={"channel": self.channel_id, "reason": verdict.reason},
            )
            return
        content = verdict.sanitized if verdict.action == "rewrite" else msg.content
        target = _validate_atom(msg.thread_id, "thread_id", max_length=200)
        for chunk in self._message_chunks(target, content):
            self._send_line(f"PRIVMSG {target} :{chunk}")

    def _open_socket(self) -> socket.socket:
        if self._socket_factory is not None:
            return self._socket_factory(
                self.server,
                self.port,
                self.use_tls,
                self._connect_timeout_s,
            )
        raw = socket.create_connection(
            (self.server, self.port),
            timeout=self._connect_timeout_s,
        )
        if self.use_tls:
            context = ssl.create_default_context()
            return context.wrap_socket(raw, server_hostname=self.server)
        return raw

    def _connect_locked(self) -> None:
        sock = self._open_socket()
        sock.settimeout(1.0)
        self._socket = sock
        try:
            for line in self._registration_lines():
                self._send_line_locked(line)
        except Exception:
            self._socket = None
            sock.close()
            raise
        self._connected.set()

    def _registration_lines(self) -> list[str]:
        lines: list[str] = []
        if self.password:
            lines.append(f"PASS {self.password}")
        lines.extend(
            [
                f"NICK {self.nickname}",
                f"USER {self.username} 0 * :{self.realname}",
            ]
        )
        if self.capabilities:
            lines.append(f"CAP REQ :{' '.join(self.capabilities)}")
            lines.append("CAP END")
        lines.extend(f"JOIN {channel}" for channel in self.channels)
        return lines

    def _reader_loop(self) -> None:
        buffer = b""
        backoff = self._reconnect_min_s
        while not self._stop_event.is_set():
            with self._socket_lock:
                sock = self._socket
            if sock is None:
                if self._stop_event.wait(backoff):
                    break
                try:
                    with self._socket_lock:
                        self._connect_locked()
                    buffer = b""
                    backoff = self._reconnect_min_s
                except (OSError, IRCError):
                    backoff = min(self._reconnect_max_s, backoff * 2)
                continue
            try:
                payload = sock.recv(4096)
                if not payload:
                    raise IRCError("IRC connection closed")
                buffer += payload
                while b"\n" in buffer:
                    raw_line, buffer = buffer.split(b"\n", 1)
                    self._handle_line(raw_line.rstrip(b"\r").decode("utf-8", errors="replace"))
            except TimeoutError:
                continue
            except (OSError, IRCError, ValueError) as exc:
                if not self._stop_event.is_set():
                    logger.warning(
                        "channel.irc.disconnected",
                        extra={"channel": self.channel_id, "error": type(exc).__name__},
                    )
                self._drop_socket(sock)

    def _drop_socket(self, expected: socket.socket) -> None:
        with self._socket_lock:
            if self._socket is expected:
                self._socket = None
                self._connected.clear()
        with suppress(OSError):
            expected.close()

    def _handle_line(self, line: str) -> None:
        parsed = parse_irc_line(line)
        if parsed.command == "PING":
            token = parsed.params[-1] if parsed.params else ""
            self._send_line(f"PONG :{token}")
            return
        if parsed.command != "PRIVMSG" or len(parsed.params) < 2:
            return
        sender = parsed.prefix.partition("!")[0]
        if not sender or sender.casefold() == self.nickname.casefold():
            return
        target, content = parsed.params[0], parsed.params[1]
        is_group = target.startswith(("#", "&"))
        thread_id = target if is_group else sender
        tags = parsed.tags or {}
        message_id = tags.get("msgid") or tags.get("id") or ""
        received_at = _parse_server_time(tags.get("time", ""))
        metadata = cast(
            ChannelMetadata,
            {
                "platform": self.platform_name,
                "message_id": message_id,
                "sender_id": sender,
                "channel_type": "group" if is_group else "direct",
                "is_group": is_group,
                "server_time": tags.get("time", ""),
            },
        )
        inbound = InboundMessage(
            channel_id=self.channel_id,
            thread_id=thread_id,
            sender_id=sender,
            content=content,
            metadata=metadata,
            received_at=received_at,
        )
        pool = self._dispatch_pool
        if pool is not None:
            pool.submit(self._dispatch_safely, inbound)

    def _dispatch_safely(self, message: InboundMessage) -> None:
        try:
            self._dispatch(message)
        except Exception:
            logger.exception("channel.irc.dispatch_failed", extra={"channel": self.channel_id})

    def _send_line(self, line: str) -> None:
        with self._socket_lock:
            self._send_line_locked(line)

    def _send_line_locked(self, line: str) -> None:
        if "\r" in line or "\n" in line or _CONTROL_RE.search(line):
            raise ValueError("IRC command contains control characters")
        encoded = (line + "\r\n").encode("utf-8")
        if len(encoded) > _MAX_IRC_LINE_BYTES:
            raise ValueError("IRC command exceeds 512-byte protocol limit")
        if (
            self._socket is None
            or not self._connected.is_set()
            and not line.startswith(("PASS ", "NICK ", "USER ", "CAP ", "JOIN "))
        ):
            raise IRCError("IRC channel is not connected")
        self._socket.sendall(encoded)

    @staticmethod
    def _message_chunks(target: str, content: str) -> list[str]:
        prefix_bytes = len(f"PRIVMSG {target} :\r\n".encode())
        limit = _MAX_IRC_LINE_BYTES - prefix_bytes
        if limit <= 0:
            raise ValueError("IRC target leaves no room for a message")
        clean = content.replace("\r", " ").replace("\n", " ").strip()
        if not clean:
            return []
        chunks: list[str] = []
        current: list[str] = []
        current_bytes = 0
        for character in clean:
            width = len(character.encode("utf-8"))
            if current and current_bytes + width > limit:
                chunks.append("".join(current))
                current = []
                current_bytes = 0
            if width > limit:
                continue
            current.append(character)
            current_bytes += width
        if current:
            chunks.append("".join(current))
        return chunks


class TwitchChannel(IRCChannel):
    channel_id = "twitch"

    def __init__(
        self,
        *,
        oauth_token: str,
        nickname: str,
        channels: str | Iterable[str],
        channel_id: str = "twitch",
        socket_factory: Callable[..., socket.socket] | None = None,
        connect_timeout_s: float = 10.0,
        reconnect_min_s: float = 1.0,
        reconnect_max_s: float = 30.0,
    ) -> None:
        token = oauth_token.strip()
        if token.lower().startswith("oauth:"):
            token = token[6:]
        if not token or _CONTROL_RE.search(token) or " " in token:
            raise ValueError("invalid oauth_token")
        super().__init__(
            server="irc.chat.twitch.tv",
            port=6697,
            nickname=nickname.lower(),
            channels=channels,
            password=f"oauth:{token}",
            use_tls=True,
            channel_id=channel_id,
            socket_factory=socket_factory,
            connect_timeout_s=connect_timeout_s,
            reconnect_min_s=reconnect_min_s,
            reconnect_max_s=reconnect_max_s,
        )
        self.channels = tuple(channel.lower() for channel in self.channels)

    @property
    def platform_name(self) -> str:
        return "twitch"

    @property
    def capabilities(self) -> tuple[str, ...]:
        return (
            "twitch.tv/tags",
            "twitch.tv/commands",
            "twitch.tv/membership",
        )


def _parse_server_time(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
