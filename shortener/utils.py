import secrets

# Base62 alphabet: digits + uppercase + lowercase
CHARACTERS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

# 62^7 is about 3.5 trillion possible codes
CODE_LENGTH = 7


def generate_short_code(length=CODE_LENGTH):
    """Return a random Base62 string using a cryptographically secure RNG.

    Random codes (unlike codes derived from the database ID) cannot be
    guessed or enumerated by counting upwards.
    """
    return "".join(
        secrets.choice(CHARACTERS)
        for _ in range(length)
    )
