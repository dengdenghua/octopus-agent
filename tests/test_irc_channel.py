from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from runtime.adapters.channels import (
    InboundMessage,
    IRCChannel,
    IRCError,
    OutboundMessage,
    TwitchChannel,
    parse_irc_line,
)
from runtime.sensing.gateway._channels_constructors import _construct_channel


class _FakeSocket:
    def __init__(self, incoming: list[bytes] | None = None) -> None:
        self.sent: list[bytes] = []
        self.closed = False
        self.incoming = list(incoming or [b":irc.example.com 001 octopus :Welcome\r\n"])

    def settimeout(self, _timeout: float) -> None:
        pass

    def sendall(self, payload: bytes) -> None:
        if self.closed:
            raise OSError("closed")
        self.sent.append(payload)

    def recv(self, _size: int) -> bytes:
        if self.incoming:
            return self.incoming.pop(0)
        raise TimeoutError

    def shutdown(self, _how: int) -> None:
        self.closed = True

    def close(self) -> None:
        self.closed = True


def _allow(message: OutboundMessage) -> SimpleNamespace:
    return SimpleNamespace(action="allow", sanitized=message.content, reason="")


def test_parse_ircv3_privmsg_with_stable_event_id_and_time() -> None:
    parsed = parse_irc_line(
        "@id=event-42;time=2026-09-05T08:30:00Z;display-name=Alice\\sA "
        ":alice!user@example PRIVMSG #octopus :hello team"
    )

    assert parsed.command == "PRIVMSG"
    assert parsed.prefix == "alice!user@example"
    assert parsed.params == ("#octopus", "hello team")
    assert parsed.tags == {
        "id": "event-42",
        "time": "2026-09-05T08:30:00Z",
        "display-name": "Alice A",
    }


def test_inbound_group_message_dispatches_without_blocking_reader() -> None:
    channel = IRCChannel(
        server="irc.example.com",
        nickname="octopus",
        channels="#agents",
    )
    received: list[InboundMessage] = []
    channel.bind_dispatcher(lambda message: received.append(message))
    channel._dispatch_pool = ThreadPoolExecutor(max_workers=1)  # noqa: SLF001

    channel._handle_line(  # noqa: SLF001
        "@msgid=m-1;time=2026-09-05T08:30:00Z :alice!u@h PRIVMSG #agents :ship it"
    )
    channel._dispatch_pool.shutdown(wait=True)  # noqa: SLF001

    assert len(received) == 1
    assert received[0].thread_id == "#agents"
    assert received[0].sender_id == "alice"
    assert received[0].metadata["message_id"] == "m-1"
    assert received[0].metadata["is_group"] is True  # type: ignore[typeddict-item]
    assert received[0].received_at is not None


def test_self_messages_are_ignored() -> None:
    channel = IRCChannel(
        server="irc.example.com",
        nickname="Octopus",
        channels="#agents",
    )
    received: list[InboundMessage] = []
    channel.bind_dispatcher(lambda message: received.append(message))
    channel._dispatch_pool = ThreadPoolExecutor(max_workers=1)  # noqa: SLF001

    channel._handle_line(":octopus!u@h PRIVMSG #agents :echo")  # noqa: SLF001
    channel._dispatch_pool.shutdown(wait=True)  # noqa: SLF001

    assert received == []


def test_registration_send_and_utf8_chunking_stay_inside_protocol_limit() -> None:
    sock = _FakeSocket()
    channel = IRCChannel(
        server="irc.example.com",
        nickname="octopus",
        channels="agents, #ops",
        password="server-pass",
        socket_factory=lambda *_args: sock,  # type: ignore[arg-type]
    )
    channel.safe_send = _allow  # type: ignore[method-assign]
    channel.start()
    try:
        channel.send(
            OutboundMessage(
                channel_id="irc",
                thread_id="#agents",
                content="章鱼" * 400,
            )
        )
        lines = [payload for payload in sock.sent if payload.startswith(b"PRIVMSG")]
        assert len(lines) > 1
        assert all(len(line) <= 512 and line.endswith(b"\r\n") for line in lines)
        registration = b"".join(sock.sent)
        assert b"PASS server-pass\r\n" in registration
        assert b"JOIN #agents\r\n" in registration
        assert b"JOIN #ops\r\n" in registration
        assert channel.health_check() is True
    finally:
        channel.stop()
    assert channel.health_check() is False


def test_control_line_injection_is_rejected() -> None:
    with pytest.raises(ValueError, match="password"):
        IRCChannel(
            server="irc.example.com",
            nickname="octopus",
            channels="#agents",
            password="secret\r\nOPER root",
        )


def test_connection_is_not_healthy_until_server_welcomes_login() -> None:
    sock = _FakeSocket([b":irc.example.com 464 octopus :Password incorrect\r\n"])
    channel = IRCChannel(
        server="irc.example.com",
        nickname="octopus",
        channels="#agents",
        connect_timeout_s=0.1,
        socket_factory=lambda *_args: sock,  # type: ignore[arg-type]
    )

    with pytest.raises(IRCError, match="registration rejected"):
        channel.start()

    assert channel.health_check() is False
    assert sock.closed is True


def test_twitch_uses_tls_oauth_and_twitch_capabilities() -> None:
    channel = TwitchChannel(
        oauth_token="oauth:secret-token",
        nickname="OctopusBot",
        channels="CreatorOne, #creatorTwo",
    )

    assert channel.server == "irc.chat.twitch.tv"
    assert channel.port == 6697
    assert channel.use_tls is True
    assert channel.password == "oauth:secret-token"
    assert channel.channels == ("#creatorone", "#creatortwo")
    assert channel.platform_name == "twitch"
    assert "twitch.tv/tags" in channel.capabilities


def test_gateway_constructors_create_both_long_lived_channels() -> None:
    irc = _construct_channel(
        "irc",
        {
            "server": "irc.example.com",
            "port": "6667",
            "nickname": "octopus",
            "channels": "#agents",
            "use_tls": "false",
        },
    )
    twitch = _construct_channel(
        "twitch",
        {
            "oauth_token": "oauth:test",
            "nickname": "octopusbot",
            "channels": "creator",
        },
    )

    assert isinstance(irc, IRCChannel)
    assert irc.use_tls is False
    assert isinstance(twitch, TwitchChannel)
