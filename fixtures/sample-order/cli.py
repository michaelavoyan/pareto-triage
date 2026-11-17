"""A small repo where the ranked order and a random sample disagree.

`cli.py` is the entrypoint, so its functions rank first. `hub.py` sorts before
`z_deep.py`, so with a small `--limit` the ranked order spends the whole cap on
those two files and never reaches `z_deep.deep_handler`. A seeded shuffle can.
"""

import hub
import z_deep


def main():
    return hub.run() + z_deep.run()


def alpha():
    return 1


def beta():
    return 2


def gamma():
    return 3


if __name__ == "__main__":
    main()
