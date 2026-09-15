"""The custom-API fetch policy must refuse the SSRF surface (finding B2).

``base_url`` is operator/GUI-writable config fetched from inside the
container; without a policy it reaches cloud metadata, loopback and RFC1918
services. These tests anchor the policy to literals (no network I/O: DNS is
stubbed where resolution matters) and pin the default-closed posture.
"""

from __future__ import annotations

import ipaddress

import pytest

from backend.plugins.custom_api_plugin import (
    URLPolicyViolation,
    assert_url_fetchable,
    CustomAPIPlugin,
)


class TestSchemePolicy:
    def test_https_is_allowed(self, monkeypatch):
        monkeypatch.setattr(
            "backend.plugins.custom_api_plugin.socket.getaddrinfo",
            lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))],
        )
        assert_url_fetchable("https://api.example.com/v1")  # no raise

    def test_http_is_refused_by_default(self):
        with pytest.raises(URLPolicyViolation, match="http is refused"):
            assert_url_fetchable("http://api.example.com/v1")

    def test_http_can_be_opted_in_for_on_prem(self, monkeypatch):
        monkeypatch.setenv("BEACON_CUSTOM_API_ALLOW_HTTP", "1")
        monkeypatch.setattr(
            "backend.plugins.custom_api_plugin.socket.getaddrinfo",
            lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 80))],
        )
        assert_url_fetchable("http://onprem.example.com/v1")  # no raise

    def test_non_http_schemes_are_refused(self):
        with pytest.raises(URLPolicyViolation, match="unsupported URL scheme"):
            assert_url_fetchable("gopher://example.com/1")


class TestRefusedRanges:
    @pytest.mark.parametrize(
        "url",
        [
            "https://169.254.169.254/latest/meta-data/",  # cloud metadata
            "https://127.0.0.1:8080/admin",
            "https://10.1.2.3/metrics",
            "https://192.168.1.1/",
            "https://172.16.0.9/",
            "https://[::1]/",
            "https://0.0.0.0/x",
        ],
    )
    def test_literal_ips_in_refused_ranges(self, url):
        with pytest.raises(URLPolicyViolation):
            assert_url_fetchable(url)

    @pytest.mark.parametrize("host", ["localhost", "db.local", "cache.internal", "x.localhost"])
    def test_non_public_namespaces(self, host):
        with pytest.raises(URLPolicyViolation):
            assert_url_fetchable(f"https://{host}/v1")

    def test_hostname_resolving_into_private_range_is_refused(self, monkeypatch):
        monkeypatch.setattr(
            "backend.plugins.custom_api_plugin.socket.getaddrinfo",
            lambda *a, **k: [(2, 1, 6, "", ("10.0.0.5", 443))],
        )
        with pytest.raises(URLPolicyViolation, match="refused range"):
            assert_url_fetchable("https://metadata.internal-svc.example/v1")

    def test_unresolvable_host_is_refused(self, monkeypatch):
        import socket as _socket

        def _fail(*args, **kwargs):
            raise _socket.gaierror("name or service not known")

        monkeypatch.setattr("backend.plugins.custom_api_plugin.socket.getaddrinfo", _fail)
        with pytest.raises(URLPolicyViolation, match="does not resolve"):
            assert_url_fetchable("https://no-such-host.example/v1")


class TestAllowlist:
    def test_allowlist_restricts_hosts(self, monkeypatch):
        monkeypatch.setenv("BEACON_CUSTOM_API_HOST_ALLOWLIST", "data.vendor.com")
        monkeypatch.setattr(
            "backend.plugins.custom_api_plugin.socket.getaddrinfo",
            lambda *a, **k: [(2, 1, 6, "", ("93.184.216.35", 443))],
        )
        with pytest.raises(URLPolicyViolation, match="ALLOWLIST"):
            assert_url_fetchable("https://other.vendor.com/v1")
        assert_url_fetchable("https://data.vendor.com/v1")  # no raise


class TestConfigValidation:
    def test_validate_config_enforces_the_policy(self):
        plugin = CustomAPIPlugin.__new__(CustomAPIPlugin)
        plugin.config = {"base_url": "http://169.254.169.254"}
        with pytest.raises(URLPolicyViolation):
            plugin.validate_config()

    def test_test_connection_reports_refusal_as_failure(self, monkeypatch):
        plugin = CustomAPIPlugin.__new__(CustomAPIPlugin)
        plugin.config = {"base_url": "http://169.254.169.254", "test_endpoint": "/"}
        result = plugin.test_connection()
        assert result["success"] is False
        assert "policy refusal" in result["message"]
