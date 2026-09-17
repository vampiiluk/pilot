from __future__ import annotations

from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest

from pilot.config import BenchConfig
from pilot.config.central import HostnameAlias
from pilot.config.common import CommonConfig
from pilot.core.bench import Bench
from pilot.core.bench.admin_domain import AdminDomainChange
from pilot.managers.nginx import NginxManager
from tests.pilot.integrations.test_central_client import _bench

OLD = "vm-old.zone.example"
NEW = "vm-new.zone.example"


def _admin_bench(tmp_path: Path, tls: bool = False) -> Bench:
    bench = _bench(tmp_path)
    bench.config.admin.domain = OLD
    bench.config.admin.tls = tls
    bench.config.production.enabled = True
    bench.config.production.process_manager = "systemd"
    bench.config.write(bench.path)
    return bench


def _with_alias(bench: Bench) -> None:
    common = CommonConfig.read(bench.path.parent)
    common.central.enabled = True
    common.central.hostname_aliases = [HostnameAlias(type="admin", pattern="vm-*.zone.example", target=OLD)]
    common.write(bench.path.parent)
    bench.config.central.enabled = True
    bench.config.central.hostname_aliases = [
        HostnameAlias(type="admin", pattern="vm-*.zone.example", target=OLD)
    ]


def _alias_targets(bench: Bench) -> list[str]:
    return [alias.target for alias in CommonConfig.read(bench.path.parent).central.hostname_aliases]


def test_nginx_publishes_the_new_hostname_before_a_certificate_is_asked_for(tmp_path: Path) -> None:
    bench = _admin_bench(tmp_path, tls=True)
    order = []

    with (
        patch.object(AdminDomainChange, "_republish_nginx", lambda self: order.append("nginx")),
        patch.object(
            AdminDomainChange, "_reissue_certificate", lambda self, on_progress: order.append("certbot")
        ),
        patch.object(NginxManager, "has_admin_cert", new_callable=PropertyMock, return_value=True),
    ):
        AdminDomainChange(bench, NEW).run()

    assert order[0] == "nginx"
    assert "certbot" in order


def test_nginx_is_republished_once_a_certificate_arrives(tmp_path: Path) -> None:
    """The first publish is HTTP; HTTPS appears after certificate issuance."""
    bench = _admin_bench(tmp_path, tls=True)
    publishes = []

    with (
        patch.object(AdminDomainChange, "_republish_nginx", lambda self: publishes.append(1)),
        patch.object(AdminDomainChange, "_reissue_certificate", lambda self, on_progress: True),
        patch.object(NginxManager, "has_admin_cert", new_callable=PropertyMock, return_value=True),
    ):
        AdminDomainChange(bench, NEW).run()

    assert len(publishes) == 2


def test_nginx_is_published_once_when_no_certificate_was_issued(tmp_path: Path) -> None:
    bench = _admin_bench(tmp_path)
    publishes = []

    with (
        patch.object(AdminDomainChange, "_republish_nginx", lambda self: publishes.append(1)),
        patch.object(AdminDomainChange, "_reissue_certificate", lambda self, on_progress: False),
    ):
        AdminDomainChange(bench, NEW).run()

    assert len(publishes) == 1


def test_the_new_domain_is_persisted_on_success(tmp_path: Path) -> None:
    bench = _admin_bench(tmp_path)

    with (
        patch.object(AdminDomainChange, "_republish_nginx"),
        patch.object(AdminDomainChange, "_reissue_certificate", lambda self, on_progress: False),
    ):
        AdminDomainChange(bench, NEW).run()

    assert BenchConfig.read(bench.path).admin.domain == NEW


def test_a_failure_rolls_bench_toml_back(tmp_path: Path) -> None:
    """A failed nginx publish also restores bench.toml."""
    bench = _admin_bench(tmp_path)

    with (
        patch.object(AdminDomainChange, "_republish_nginx", side_effect=RuntimeError("nginx is unhappy")),
        pytest.raises(RuntimeError),
    ):
        AdminDomainChange(bench, NEW).run()

    assert BenchConfig.read(bench.path).admin.domain == OLD
    assert bench.config.admin.domain == OLD


def test_a_failure_rolls_the_hostname_alias_back(tmp_path: Path) -> None:
    bench = _admin_bench(tmp_path)
    _with_alias(bench)

    with (
        patch.object(AdminDomainChange, "_republish_nginx", side_effect=RuntimeError("nginx is unhappy")),
        pytest.raises(RuntimeError),
    ):
        AdminDomainChange(bench, NEW).run()

    assert _alias_targets(bench) == [OLD]


def test_a_successful_change_moves_the_hostname_alias(tmp_path: Path) -> None:
    bench = _admin_bench(tmp_path)
    _with_alias(bench)

    with (
        patch.object(AdminDomainChange, "_republish_nginx"),
        patch.object(AdminDomainChange, "_reissue_certificate", lambda self, on_progress: False),
    ):
        AdminDomainChange(bench, NEW).run()

    assert _alias_targets(bench) == [NEW]


def test_a_failed_renewal_does_not_republish_an_expired_certificate(tmp_path: Path) -> None:
    """A stale certificate file does not count after renewal fails."""
    from pilot.managers.letsencrypt import LetsEncryptManager

    bench = _admin_bench(tmp_path, tls=True)
    bench.config.letsencrypt.email = "ops@example.com"
    publishes = []

    with (
        patch.object(AdminDomainChange, "_republish_nginx", lambda self: publishes.append(1)),
        patch.object(LetsEncryptManager, "obtain_admin", side_effect=RuntimeError("certbot failed")),
        patch.object(NginxManager, "has_admin_cert", new_callable=PropertyMock, return_value=True),
    ):
        AdminDomainChange(bench, NEW).run()

    assert len(publishes) == 1


def test_a_successful_renewal_republishes(tmp_path: Path) -> None:
    from pilot.managers.letsencrypt import LetsEncryptManager

    bench = _admin_bench(tmp_path, tls=True)
    bench.config.letsencrypt.email = "ops@example.com"
    publishes = []

    with (
        patch.object(AdminDomainChange, "_republish_nginx", lambda self: publishes.append(1)),
        patch.object(LetsEncryptManager, "obtain_admin"),
        patch.object(NginxManager, "has_admin_cert", new_callable=PropertyMock, return_value=True),
    ):
        AdminDomainChange(bench, NEW).run()

    assert len(publishes) == 2


def test_an_existing_certificate_is_still_offered_for_renewal(tmp_path: Path) -> None:
    """An existing certificate is still checked for renewal."""
    from pilot.managers.letsencrypt import LetsEncryptManager

    bench = _admin_bench(tmp_path, tls=True)
    bench.config.letsencrypt.email = "ops@example.com"

    with (
        patch.object(AdminDomainChange, "_republish_nginx"),
        patch.object(LetsEncryptManager, "obtain_admin") as obtain,
        patch.object(NginxManager, "has_admin_cert", new_callable=PropertyMock, return_value=True),
    ):
        AdminDomainChange(bench, NEW).run()

    obtain.assert_called_once()


def test_a_tls_move_with_no_certificate_is_refused(tmp_path: Path) -> None:
    """Standing, the admin would answer only on HTTP while admin.tls stayed
    true - session cookies keep their Secure flag, so no browser sends them
    back - and the previous hostname would already have been released."""
    from pilot.exceptions import BenchError
    from pilot.managers.letsencrypt import LetsEncryptManager

    bench = _admin_bench(tmp_path, tls=True)
    bench.config.letsencrypt.email = "ops@example.com"
    released = []

    with patch.object(AdminDomainChange, "_republish_nginx"), patch.object(
        LetsEncryptManager, "obtain_admin", side_effect=RuntimeError("dns not ready")
    ), patch.object(
        NginxManager, "has_admin_cert", new_callable=PropertyMock, return_value=False
    ), patch(
        "pilot.core.adapters.domain_provider.DomainRouteProvider.release",
        lambda self, domain: released.append(domain),
    ), pytest.raises(BenchError, match="No TLS certificate"):
        AdminDomainChange(bench, NEW).run()

    # The admin is left where it still works, and the old hostname is still ours.
    assert BenchConfig.read(bench.path).admin.domain == OLD
    assert bench.config.admin.domain == OLD
    assert OLD not in released


def test_a_move_to_plain_http_needs_no_certificate(tmp_path: Path) -> None:
    bench = _admin_bench(tmp_path, tls=True)

    with patch.object(AdminDomainChange, "_republish_nginx"), patch.object(
        AdminDomainChange, "_reissue_certificate", lambda self, on_progress: False
    ):
        AdminDomainChange(bench, NEW, tls=False).run()

    assert BenchConfig.read(bench.path).admin.domain == NEW
    assert BenchConfig.read(bench.path).admin.tls is False
