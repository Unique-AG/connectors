"""Database certificate verification through the service engine, against a TLS-only fake server."""

import asyncio
import contextlib
import ipaddress
import ssl
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import final

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from sqlalchemy.exc import DBAPIError

from backstop_mcp.config import DatabaseConfig
from backstop_mcp.db import create_engine

LOOPBACK = "127.0.0.1"


@final
class FakePostgres:
    """Answers PostgreSQL's SSLRequest, completes TLS, then hangs up before authentication."""

    def __init__(self, server_ctx: ssl.SSLContext) -> None:
        self._server_ctx = server_ctx
        self.connections = 0
        self.handshakes = 0

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        with contextlib.suppress(ssl.SSLError, ConnectionError, asyncio.IncompleteReadError):
            await reader.readexactly(8)
            writer.write(b"S")
            await writer.drain()
            await writer.start_tls(self._server_ctx)
            self.handshakes += 1
        writer.close()


@final
class Pki:
    """A throwaway CA, written to disk the way the chart mounts CloudNativePG's."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._key = ec.generate_private_key(ec.SECP256R1())
        ca_cert = self._sign(
            x509.CertificateBuilder()
            .subject_name(_name("test-pg-cluster-ca"))
            .public_key(self._key.public_key())
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(_ca_key_usage(), critical=True)
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(self._key.public_key()), critical=False
            )
        )
        self.ca_path = directory / "ca.crt"
        self.ca_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))

    def server_context(self, san: x509.GeneralName) -> ssl.SSLContext:
        key = ec.generate_private_key(ec.SECP256R1())
        cert = self._sign(
            x509.CertificateBuilder()
            .subject_name(_name("test-pg-cluster-rw"))
            .public_key(key.public_key())
            .add_extension(x509.SubjectAlternativeName([san]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(self._key.public_key()),
                critical=False,
            )
        )
        cert_path = self._directory / "tls.crt"
        key_path = self._directory / "tls.key"
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert_path, key_path)
        return ctx

    def _sign(self, builder: x509.CertificateBuilder) -> x509.Certificate:
        now = datetime.now(UTC)
        return (
            builder.issuer_name(_name("test-pg-cluster-ca"))
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=1))
            .sign(self._key, hashes.SHA256())
        )


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _ca_key_usage() -> x509.KeyUsage:
    return x509.KeyUsage(
        digital_signature=False,
        content_commitment=False,
        key_encipherment=False,
        data_encipherment=False,
        key_agreement=False,
        key_cert_sign=True,
        crl_sign=True,
        encipher_only=False,
        decipher_only=False,
    )


@contextlib.asynccontextmanager
async def _serve(server_ctx: ssl.SSLContext) -> AsyncGenerator[tuple[FakePostgres, int]]:
    fake = FakePostgres(server_ctx)
    server = await asyncio.start_server(fake.handle, LOOPBACK, 0)
    async with server:
        yield fake, server.sockets[0].getsockname()[1]


@pytest.fixture
def pki(tmp_path: Path) -> Pki:
    return Pki(tmp_path)


def _database_config(port: int, sslmode: str, ssl_root_cert: Path | None) -> DatabaseConfig:
    return DatabaseConfig.model_validate(
        {
            "url": f"postgresql://u:p@{LOOPBACK}:{port}/backstop",
            "PG_DATABASE_SSL_MODE": sslmode,
            "ssl_root_cert": ssl_root_cert,
        }
    )


async def _connect(config: DatabaseConfig) -> None:
    engine = create_engine(config)
    try:
        async with engine.connect():
            pass
    finally:
        await engine.dispose()


LOOPBACK_SAN = x509.IPAddress(ipaddress.ip_address(LOOPBACK))
OTHER_HOST_SAN = x509.DNSName("other-pg-cluster-rw.example.svc.cluster.local")


class TestDatabaseTls:
    async def test_trusts_a_server_signed_by_the_mounted_ca(self, pki: Pki) -> None:
        async with _serve(pki.server_context(LOOPBACK_SAN)) as (server, port):
            # The fake server hangs up after TLS, so the connection itself still fails.
            with pytest.raises(DBAPIError, match="closed in the middle of operation"):
                await _connect(_database_config(port, "verify", pki.ca_path))

        assert server.handshakes == 1

    async def test_rejects_a_ca_the_system_store_does_not_trust(self, pki: Pki) -> None:
        async with _serve(pki.server_context(LOOPBACK_SAN)) as (server, port):
            with pytest.raises(ssl.SSLCertVerificationError, match="unable to get local issuer"):
                await _connect(_database_config(port, "verify", None))

        assert (server.connections, server.handshakes) == (1, 0)

    async def test_falls_back_to_the_system_store_when_the_ca_file_is_absent(
        self, pki: Pki, tmp_path: Path
    ) -> None:
        async with _serve(pki.server_context(LOOPBACK_SAN)) as (server, port):
            with pytest.raises(ssl.SSLCertVerificationError, match="unable to get local issuer"):
                await _connect(_database_config(port, "verify", tmp_path / "absent" / "ca.crt"))

        assert (server.connections, server.handshakes) == (1, 0)

    async def test_rejects_a_hostname_mismatch(self, pki: Pki) -> None:
        async with _serve(pki.server_context(OTHER_HOST_SAN)) as (server, port):
            with pytest.raises(ssl.SSLCertVerificationError, match="IP address mismatch"):
                await _connect(_database_config(port, "verify-full", pki.ca_path))

        assert (server.connections, server.handshakes) == (1, 0)

    async def test_verify_ca_accepts_a_hostname_mismatch(self, pki: Pki) -> None:
        async with _serve(pki.server_context(OTHER_HOST_SAN)) as (server, port):
            with pytest.raises(DBAPIError, match="closed in the middle of operation"):
                await _connect(_database_config(port, "verify-ca", pki.ca_path))

        assert server.handshakes == 1
