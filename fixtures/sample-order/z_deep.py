def deep_handler():
    try:
        return 7
    except ValueError:
        return 0


def run():
    try:
        return deep_handler()
    except ValueError:
        return 0
