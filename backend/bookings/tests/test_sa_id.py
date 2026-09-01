from datetime import date

import pytest

from bookings.sa_id import SouthAfricanIdError, decode_south_african_id


def _synthetic_id(date_part, sequence, citizenship="0", marker="8"):
    first_twelve = f"{date_part}{sequence}{citizenship}{marker}"
    provisional = f"{first_twelve}0"
    digits = [int(value) for value in provisional]
    parity = len(digits) % 2
    total = 0
    for index, value in enumerate(digits):
        if index % 2 == parity:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return f"{first_twelve}{(10 - total % 10) % 10}"


def test_decode_sa_id_derives_adult_birth_date_sex_and_status_without_race():
    identity_number = _synthetic_id("000101", "4000")

    decoded = decode_south_african_id(
        identity_number,
        today=date(2026, 8, 19),
    )

    assert decoded == {
        "date_of_birth": date(2000, 1, 1),
        "sex": "female",
        "citizenship_status": "citizen",
    }
    assert "employment_equity" not in decoded


def test_decode_sa_id_resolves_previous_century_for_an_adult():
    identity_number = _synthetic_id("900101", "5000", citizenship="1")

    decoded = decode_south_african_id(
        identity_number,
        today=date(2026, 8, 19),
    )

    assert decoded["date_of_birth"] == date(1990, 1, 1)
    assert decoded["sex"] == "male"
    assert decoded["citizenship_status"] == "permanent_resident"


def test_decode_sa_id_rejects_invalid_checksum_without_echoing_the_id():
    identity_number = _synthetic_id("000101", "4000")
    replacement = "0" if identity_number[-1] != "0" else "1"

    with pytest.raises(SouthAfricanIdError, match="checksum") as error:
        decode_south_african_id(
            f"{identity_number[:-1]}{replacement}",
            today=date(2026, 8, 19),
        )

    assert identity_number not in str(error.value)


def test_decode_sa_id_rejects_an_invalid_or_non_adult_birth_date():
    invalid_date = _synthetic_id("991332", "5000")
    child_date = _synthetic_id("150101", "5000")

    with pytest.raises(SouthAfricanIdError, match="birth date"):
        decode_south_african_id(invalid_date, today=date(2026, 8, 19))
    with pytest.raises(SouthAfricanIdError, match="adult birth date"):
        decode_south_african_id(child_date, today=date(2026, 8, 19))


def test_decode_sa_id_requires_age_eighteen():
    seventeen = _synthetic_id("080820", "4000")
    eighteen = _synthetic_id("080819", "4000")

    with pytest.raises(SouthAfricanIdError, match="adult birth date"):
        decode_south_african_id(seventeen, today=date(2026, 8, 19))

    assert decode_south_african_id(
        eighteen,
        today=date(2026, 8, 19),
    )["date_of_birth"] == date(2008, 8, 19)


def test_decode_sa_id_rejects_an_invalid_administrative_digit():
    invalid_marker = _synthetic_id("000101", "4000", marker="7")

    with pytest.raises(SouthAfricanIdError, match="administrative digit"):
        decode_south_african_id(invalid_marker, today=date(2026, 8, 19))


def test_decode_sa_id_accepts_both_current_administrative_digits():
    marker_eight = _synthetic_id("000101", "4000", marker="8")
    marker_nine = _synthetic_id("000101", "4000", marker="9")

    assert decode_south_african_id(
        marker_eight,
        today=date(2026, 8, 19),
    )["date_of_birth"] == date(2000, 1, 1)
    assert decode_south_african_id(
        marker_nine,
        today=date(2026, 8, 19),
    )["date_of_birth"] == date(2000, 1, 1)
