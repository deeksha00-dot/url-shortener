CHARACTERS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def encode_base62(number):
    if number == 0:
        return CHARACTERS[0]

    result = ""

    while number > 0:
        remainder = number % 62
        result = CHARACTERS[remainder] + result
        number = number // 62

    return result