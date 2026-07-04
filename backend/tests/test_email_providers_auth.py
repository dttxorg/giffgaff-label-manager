from email_providers.auth import (
    hydrate_provider,
    extract_jwt_for_persist,
)
from email_providers.cloudmail import CloudMailProvider
from email_providers.moemail import MoEmailProvider


def _make_db_row(jwt="old-jwt", jwt_at=None):
    """Real dict-like object so __getitem__ returns actual values, not MagicMocks."""
    class FakeRow:
        def __init__(self, d):
            self._d = d
        def __getitem__(self, k):
            return self._d.get(k)
    return FakeRow({"last_jwt_token": jwt, "last_jwt_at": jwt_at})


def test_hydrate_provider_sets_jwt_for_cloudmail():
    p = CloudMailProvider(url="x", email="e", password="p", domain="d")
    row = _make_db_row(jwt="cached-jwt", jwt_at="2026-01-01T00:00:00+00:00")
    hydrate_provider(p, row)
    assert p._jwt == "cached-jwt"
    assert p._jwt_at == "2026-01-01T00:00:00+00:00"


def test_hydrate_provider_noop_for_non_cloudmail():
    p = MoEmailProvider(url="x", api_key="k")
    row = _make_db_row(jwt="cached-jwt")
    hydrate_provider(p, row)  # should not raise, does nothing


def test_hydrate_provider_handles_null_jwt():
    p = CloudMailProvider(url="x", email="e", password="p", domain="d")
    row = _make_db_row(jwt=None, jwt_at=None)
    hydrate_provider(p, row)
    assert p._jwt is None


def test_extract_jwt_for_persist_returns_tuple_for_cloudmail():
    p = CloudMailProvider(
        url="x", email="e", password="p", domain="d",
        jwt_token="t", jwt_acquired_at="2026-01-01T00:00:00+00:00",
    )
    result = extract_jwt_for_persist(p)
    assert result == ("t", "2026-01-01T00:00:00+00:00")


def test_extract_jwt_for_persist_returns_none_for_moemail():
    p = MoEmailProvider(url="x", api_key="k")
    assert extract_jwt_for_persist(p) == (None, None)


def test_extract_jwt_for_persist_returns_none_when_jwt_unset():
    p = CloudMailProvider(url="x", email="e", password="p", domain="d")
    assert extract_jwt_for_persist(p) == (None, None)
