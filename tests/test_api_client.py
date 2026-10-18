import pytest

from api_client import ThirdPartyApi


@pytest.fixture
def api(tmp_path):
    return ThirdPartyApi({"base_url": "https://example.invalid", "key": "SECRET-KEY",
                          "secret": "SECRET-VALUE", "qps": 1000}, work_dir=str(tmp_path))


def test_offer_from_url():
    assert ThirdPartyApi._offer_from_url("https://detail.1688.com/offer/123456.html") == "123456"
    assert ThirdPartyApi._offer_from_url("https://x/offerId=987") == "987"
    assert ThirdPartyApi._offer_from_url("") == ""


def test_strip_avif():
    assert ThirdPartyApi._strip_avif("https://x/a.jpg.avif") == "https://x/a.jpg"
    assert ThirdPartyApi._strip_avif("https://x/a.avif?x=1") == "https://x/a"
    assert ThirdPartyApi._strip_avif("https://x/a.jpg") == "https://x/a.jpg"


@pytest.mark.parametrize("item,expected", [
    ({"sales": "1,234"}, 1234),
    ({"biz30day": "月销 88 件"}, 88),
    ({"sold": None, "sales_count": "7"}, 7),
    ({}, 0),
])
def test_sales_num(item, expected):
    assert ThirdPartyApi._sales_num(item) == expected


def test_parse_candidates(api):
    data = {"items": {"item": [{
        "num_iid": 123,
        "title": "test",
        "pic_url": "https://a/1.jpg, https://a/2.jpg",
        "detail_url": "https://detail.1688.com/offer/123.html",
        "price": "9.9",
        "sales": "10",
    }]}}
    out = api._parse_candidates(data)
    assert out[0]["offer_id"] == "123"
    assert out[0]["image_urls"] == ["https://a/1.jpg", "https://a/2.jpg"]
    assert out[0]["main_image"] == "https://a/1.jpg"
    assert out[0]["sales_num"] == 10


def test_dedup_keep_order():
    assert ThirdPartyApi._dedup_keep_order(["a", "a", "b", "a"]) == ["a", "b"]


def test_check_redacts_secret_in_error(api):
    with pytest.raises(RuntimeError) as exc:
        api._check({"success": 0, "error_code": "4001",
                    "error": "bad", "reason": "key=SECRET-KEY secret=SECRET-VALUE"})
    msg = str(exc.value)
    assert "SECRET-KEY" not in msg
    assert "SECRET-VALUE" not in msg
    assert "key=***" in msg


def test_check_accepts_ok_payload(api):
    assert api._check({"success": 1, "error_code": "0000", "error": ""})["success"] == 1
