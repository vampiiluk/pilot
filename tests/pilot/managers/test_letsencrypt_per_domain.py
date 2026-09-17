from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from pilot.config import SiteConfig
from pilot.managers.letsencrypt import (
    LetsEncryptManager,
    certificate_domains,
    public_domains,
)
from tests.pilot.integrations.test_central_client import _bench


def _site(bench, name: str, **config) -> None:
    site_dir = bench.sites_path / name
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "site_config.json").write_text(json.dumps(config))


def _obtained(bench) -> list[str]:
    """The sites obtain_all actually asked certbot for."""
    names: list[str] = []
    with (
        patch.object(LetsEncryptManager, "obtain", lambda self, site: names.append(site.name)),
        patch.object(LetsEncryptManager, "obtain_admin", lambda self: names.append("ADMIN")),
    ):
        LetsEncryptManager(bench).obtain_all()
    return names


def test_certificate_domains_are_only_those_terminating_here() -> None:
    site = SiteConfig(
        name="site-a1.zone.example",
        apps=[],
        domains=[{"domain": "shop.customer.com", "tls": True}],
        ssl=False,
    )

    # Both are candidates for TLS; only the custom domain terminates here.
    assert public_domains(site) == ["site-a1.zone.example", "shop.customer.com"]
    assert certificate_domains(site) == ["shop.customer.com"]


def test_a_custom_domain_gets_a_certificate_though_the_admin_is_proxied(tmp_path: Path) -> None:
    """The documented cloud case: admin.tls off, site ssl off, one custom domain
    whose TLS ends on this host."""
    bench = _bench(tmp_path)
    bench.config.admin.tls = False
    _site(bench, "site-a1.zone.example", ssl=False, domains=[{"domain": "shop.customer.com", "tls": True}])

    assert _obtained(bench) == ["site-a1.zone.example"]


def test_a_plain_site_is_left_alone(tmp_path: Path) -> None:
    bench = _bench(tmp_path)
    bench.config.admin.tls = False
    _site(bench, "site-a1.zone.example", ssl=False)

    assert _obtained(bench) == []


def test_the_admin_certificate_still_follows_the_admin_flag(tmp_path: Path) -> None:
    bench = _bench(tmp_path)
    bench.config.admin.domain = "admin.example.com"

    bench.config.admin.tls = False
    assert "ADMIN" not in _obtained(bench)

    bench.config.admin.tls = True
    assert "ADMIN" in _obtained(bench)
