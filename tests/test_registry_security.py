import pytest

from errand_crew.config import Settings, parse_client_tokens
from errand_crew.registry import Registry
from errand_crew.security import (
    BearerTokenVerifier,
    SlidingWindowLimiter,
    grounded,
    looks_blocked,
)


def test_registry_loads_and_has_categories():
    reg = Registry.load()
    assert {"evomag", "altex"} <= {s.id for s in reg.sites_for("laptops")}
    assert "pcgarage" not in {s.id for s in reg.sites_for("laptops")}  # URLs unverified


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.evomag.ro/portabile-laptopuri-notebook/", True),
        ("https://altex.ro/laptopuri/cpl/", True),
        ("http://altex.ro/laptopuri/cpl/", False),  # not https
        ("https://evil-evomag.ro/", False),  # look-alike domain
        ("https://evomag.ro.evil.com/", False),  # allowed name as a prefix
        ("https://example.com/", False),
        ("javascript:alert(1)", False),
        ("not a url", False),
    ],
)
def test_allowlist(url, expected):
    assert Registry.load().is_allowed_url(url) is expected


def test_registry_rejects_category_url_outside_allowlist():
    from errand_crew.registry import Listing, Site

    with pytest.raises(ValueError):
        Registry(
            {"laptops": "x"},
            [Site("a", "a", "a.ro", {"laptops": Listing("https://b.ro/x")})],
        )


A, B, C = "a" * 24, "b" * 24, "c" * 24


async def test_each_client_has_its_own_token():
    v = BearerTokenVerifier({"demo": A, "judges": B, "dev": C})
    for name, secret in {"demo": A, "judges": B, "dev": C}.items():
        access = await v.verify_token(secret)
        assert access is not None and access.client_id == name
    assert await v.verify_token("wrong") is None
    assert await v.verify_token("") is None
    assert await v.verify_token(A[:-1]) is None  # a prefix is not enough


async def test_revoking_one_client_keeps_the_others():
    v = BearerTokenVerifier({"demo": A, "dev": C})  # "judges" removed
    assert await v.verify_token(B) is None
    assert (await v.verify_token(A)).client_id == "demo"


def test_parse_client_tokens():
    assert parse_client_tokens(f"demo:{A}, judges:{B}") == {"demo": A, "judges": B}
    assert parse_client_tokens("") == {}
    assert parse_client_tokens("demo:ab:cd")["demo"] == "ab:cd"  # ':' allowed in a secret
    with pytest.raises(ValueError):
        parse_client_tokens("no-separator")
    with pytest.raises(ValueError):
        parse_client_tokens(f"demo:{A},demo:{B}")


@pytest.mark.parametrize(
    "tokens",
    [
        {},  # no client at all
        {"demo": "short"},  # too short
        {"demo": "a" * 23},  # one short of the minimum
        {"demo": A, "dev": A},  # same secret for two clients
        {"Demo Client": A},  # bad name
        {f"c{i}": f"{i:024d}" for i in range(11)},  # too many clients
    ],
)
def test_settings_reject_bad_tokens(tokens):
    with pytest.raises(ValueError):
        Settings(client_tokens=tokens)


def test_settings_require_tokens_in_env():
    with pytest.raises(ValueError):
        Settings.from_env({})


def test_validation_errors_never_contain_a_secret():
    secret = "SECRET-VALUE-1234"  # too short on purpose
    with pytest.raises(ValueError) as exc:
        Settings(client_tokens={"demo": secret})
    assert secret not in str(exc.value)


def test_settings_render_host_is_allowed():
    s = Settings.from_env(
        {
            "ERRAND_CREW_TOKENS": f"demo:{A}",
            "RENDER_EXTERNAL_HOSTNAME": "crew.onrender.com",
        }
    )
    assert "crew.onrender.com" in s.allowed_hosts
    assert s.client_tokens == {"demo": A}


def test_sliding_window_limiter():
    now = [0.0]
    lim = SlidingWindowLimiter(2, 10, clock=lambda: now[0])
    assert lim.check()
    lim.record()
    lim.record()
    assert not lim.check()
    now[0] = 10.5
    assert lim.check()


def test_looks_blocked():
    assert looks_blocked("anything", 403)
    assert looks_blocked("Please solve this CAPTCHA", 200)
    assert not looks_blocked("Laptop Asus 3.499 lei " * 40, 200)


@pytest.mark.parametrize(
    "name,price,text,expected",
    [
        ("Laptop ASUS Vivobook 15", 3499.99, "Laptop ASUS Vivobook 15 X1504\n3.499,99 lei", True),
        ("Laptop ASUS Vivobook 15", 3499, "Laptop ASUS Vivobook 15\n3 499 lei", True),
        ("Laptop ASUS Vivobook 15", 2999, "Laptop ASUS Vivobook 15\n3.499,99 lei", False),
        ("Laptop Fantoma 9000", 3499, "Laptop ASUS Vivobook\n3.499 lei", False),  # not on page
        ("Laptop ASUS Vivobook", 499, "Laptop ASUS Vivobook\n3.499 lei", False),  # substring of price
    ],
)
def test_grounding(name, price, text, expected):
    assert grounded(name, price, text) is expected
