from datetime import date


class SouthAfricanIdError(ValueError):
    pass


def _age_on(birth_date, today):
    return today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )


def _has_valid_luhn_checksum(value):
    total = 0
    parity = len(value) % 2
    for index, character in enumerate(value):
        digit = int(character)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def decode_south_african_id(value, *, today=None):
    today = today or date.today()
    if not isinstance(value, str) or len(value) != 13 or not value.isdigit():
        raise SouthAfricanIdError("Enter a 13-digit South African ID number.")
    if not _has_valid_luhn_checksum(value):
        raise SouthAfricanIdError("The South African ID checksum is invalid.")

    year = int(value[:2])
    month = int(value[2:4])
    day = int(value[4:6])
    valid_dates = []
    for century in (1900, 2000):
        try:
            candidate = date(century + year, month, day)
        except ValueError:
            continue
        if candidate <= today:
            valid_dates.append(candidate)
    if not valid_dates:
        raise SouthAfricanIdError("The South African ID birth date is invalid.")

    adult_dates = [
        candidate
        for candidate in valid_dates
        if 18 <= _age_on(candidate, today) <= 100
    ]
    if len(adult_dates) != 1:
        raise SouthAfricanIdError(
            "The South African ID does not contain an unambiguous adult birth date."
        )

    citizenship_statuses = {
        "0": "citizen",
        "1": "permanent_resident",
        "2": "refugee",
    }
    citizenship_status = citizenship_statuses.get(value[10])
    if citizenship_status is None:
        raise SouthAfricanIdError("The South African ID status digit is invalid.")
    if value[11] not in {"8", "9"}:
        raise SouthAfricanIdError(
            "The South African ID administrative digit is invalid."
        )

    return {
        "date_of_birth": adult_dates[0],
        "sex": "female" if int(value[6:10]) < 5000 else "male",
        "citizenship_status": citizenship_status,
    }
