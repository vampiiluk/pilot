from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import TYPE_CHECKING

from pilot.exceptions import BenchError
from pilot.utils import host_owner, matches_wildcard, normalize_host

if TYPE_CHECKING:
    from pilot.core.bench import Bench


class ProductionAdminDomain:
    def __init__(self, bench: "Bench", existing_domain: str) -> None:
        self.bench = bench
        self.existing_domain = existing_domain
        self.registered_domain: str | None = None

    def check(self) -> None:
        """Reject domains that are missing, already claimed, or outside the wildcard set."""
        from pilot.core.adapters.domain_provider import DomainRouteProvider

        domain = self.bench.config.admin.domain
        if not domain:
            return  # config validation raises the required-in-prod error with bench context
        owner = host_owner(self.bench.path, domain)
        if owner:
            raise BenchError(f"Admin domain '{domain}' is already used by bench '{owner}'.")
        # Check this bench separately because host_owner only sees siblings.
        if claimed_by := self.bench.site_claiming(domain):
            raise BenchError(
                f"Admin domain '{domain}' conflicts with this bench's own site '{claimed_by}'. "
                f"An admin domain must not match a site domain."
            )
        if normalize_host(domain) == normalize_host(self.existing_domain):
            return
        patterns = DomainRouteProvider.wildcard_domains()
        if patterns and not matches_wildcard(domain, patterns):
            raise BenchError(
                f"Admin domain must match one of this bench's wildcard domains: {', '.join(patterns)}."
            )

    def register(self) -> None:
        """Provision a new/changed admin domain with the route provider."""
        from pilot.core.adapters.domain_provider import DomainRouteProvider

        self.registered_domain = None
        domain = self.bench.config.admin.domain
        if not domain or normalize_host(domain) == normalize_host(self.existing_domain):
            return
        DomainRouteProvider(self.bench).register(domain, domain)
        self.registered_domain = domain

    def rollback(self) -> None:
        """Release the just-registered admin route after a failed setup."""
        if not self.registered_domain:
            return
        from pilot.core.adapters.domain_provider import DomainRouteProvider

        DomainRouteProvider(self.bench).release(self.registered_domain)

    def release_previous(self) -> None:
        """Free the superseded admin hostname once the switch is committed."""
        if not self.registered_domain or not self.existing_domain:
            return
        from pilot.core.adapters.domain_provider import DomainRouteProvider

        DomainRouteProvider(self.bench).release(self.existing_domain)


class AdminDomainChange:
    """Move the admin route, config, nginx host, and TLS together."""

    def __init__(self, bench: "Bench", domain: str, tls: bool | None = None) -> None:
        self.bench = bench
        self.domain = domain.strip().lower()
        self.tls = tls
        self.previous = bench.config.admin.domain
        self._route = ProductionAdminDomain(bench, self.previous)

    def run(self, on_progress: Callable[[str], None] = lambda message: None) -> None:
        admin = self.bench.config.admin
        restore = (admin.domain, admin.tls)
        self._validate()

        admin.domain = self.domain
        if self.tls is not None:
            admin.tls = self.tls
        self._route.check()
        self._route.register()

        on_progress(f"Moving the admin to '{self.domain}'...")
        try:
            self._persist()
            self._retarget_hostname_aliases()
            # Publish the vhost before HTTP-01 certificate validation.
            self._republish_nginx()
            if self._reissue_certificate(on_progress):
                self._republish_nginx()
            self._require_tls_if_requested()
        except BaseException:
            self._roll_back(restore, on_progress)
            raise

        self._route.release_previous()
        on_progress(f"\nAdmin is now at {self._served_scheme()}://{self.domain}")

    def _served_scheme(self) -> str:
        """Return the scheme nginx can currently serve."""
        from pilot.managers.nginx import NginxManager

        serves_https = self.bench.config.admin.tls and NginxManager(self.bench).has_admin_cert
        return "https" if serves_https else "http"

    def _validate(self) -> None:
        from pilot.internal.validators import validate_hostname

        if not self.domain:
            raise BenchError("An admin domain is required.")
        if error := validate_hostname(self.domain, "admin domain"):
            raise BenchError(error)
        if normalize_host(self.domain) == normalize_host(self.previous) and self.tls is None:
            raise BenchError(f"The admin domain is already '{self.domain}'.")

    def _persist(self) -> None:
        from pilot.config import BenchConfig

        admin = self.bench.config.admin
        with BenchConfig.open(self.bench.path, mode="raw") as data:
            data.setdefault("admin", {}).update({"domain": admin.domain, "tls": admin.tls})

    def _retarget_hostname_aliases(self) -> None:
        self.bench.hostname_aliases.retarget("admin", self.previous, self.domain)

    def _reissue_certificate(self, on_progress: Callable[[str], None]) -> bool:
        """Try to obtain the new certificate; pending DNS leaves HTTP active."""
        from pilot.managers.letsencrypt import LetsEncryptManager, letsencrypt_active
        from pilot.managers.nginx import NginxManager

        if not self.bench.config.admin.tls or not letsencrypt_active(self.bench):
            return False
        on_progress(f"Obtaining a certificate for {self.domain}...")
        try:
            # obtain_admin also renews an expired certificate.
            LetsEncryptManager(self.bench).obtain_admin()
        except Exception as exc:
            on_progress(
                f"Could not obtain a certificate for {self.domain} yet ({exc}). "
                f"Serving the admin over HTTP - retry once its DNS resolves."
            )
            return False
        return NginxManager(self.bench).has_admin_cert

    def _require_tls_if_requested(self) -> None:
        """Refuse to finish a TLS move that has no certificate to serve.

        Left to stand, the admin would answer only on HTTP while `admin.tls`
        stayed true - so session cookies keep their Secure flag and no browser
        sends them back - and the previous hostname would already have been
        released. Failing here rolls the move back instead, leaving the admin
        where it still works.
        """
        from pilot.managers.nginx import NginxManager

        if not self.bench.config.admin.tls or NginxManager(self.bench).has_admin_cert:
            return
        raise BenchError(
            f"No TLS certificate for '{self.domain}', so the admin would serve HTTP while "
            f"configured for HTTPS. The admin is unchanged; retry once its DNS resolves, or "
            f"pass tls=false to move it to plain HTTP."
        )

    def _roll_back(self, restore: tuple[str, bool], on_progress: Callable[[str], None]) -> None:
        """Undo committed config and routes after a failed switch."""
        admin = self.bench.config.admin
        admin.domain, admin.tls = restore
        with contextlib.suppress(Exception):
            self._persist()
        with contextlib.suppress(Exception):
            self.bench.hostname_aliases.retarget("admin", self.domain, self.previous)
        # Rollback must not hide the original failure or skip nginx recovery.
        with contextlib.suppress(Exception):
            self._route.rollback()
        with contextlib.suppress(Exception):
            self._republish_nginx()
        on_progress(f"Rolled the admin back to '{self.previous}'.")

    def _republish_nginx(self) -> None:
        from pilot.managers.nginx import NginxManager

        if not self.bench.config.production.enabled:
            return
        nginx = NginxManager(self.bench)
        nginx.generate_config(ssl_ready=True)
        nginx.reload()
