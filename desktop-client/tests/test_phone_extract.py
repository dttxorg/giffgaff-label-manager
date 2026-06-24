import re

from giffgaff_client.automation import PHONE_NUMBER_PATTERN


def test_pattern_matches_spaced_format():
    m = PHONE_NUMBER_PATTERN.search("Your giffgaff number is 07732 212776")
    assert m is not None
    assert re.sub(r"\D", "", m.group(0)) == "07732212776"


def test_pattern_matches_unspaced_format():
    m = PHONE_NUMBER_PATTERN.search("07732212776")
    assert m is not None


def test_pattern_matches_dashed_format():
    m = PHONE_NUMBER_PATTERN.search("Call 07732-212776 today")
    assert m is not None


def test_pattern_does_not_match_landline():
    m = PHONE_NUMBER_PATTERN.search("020 7946 0958")
    assert m is None


def test_pattern_does_not_match_random_eleven_digits():
    m = PHONE_NUMBER_PATTERN.search("Order ID 12345678901")
    assert m is None