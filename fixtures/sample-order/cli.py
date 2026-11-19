"""A small repo where the ranked order and a random sample disagree.

`cli.py` is the entrypoint, so its functions rank first. `hub.py` sorts before
`z_deep.py`, so with a small `--limit` the ranked order spends the whole cap on
those two files and never reaches `z_deep.deep_handler`. A seeded shuffle can.

Every function carries a failure surface and five non-blank lines, so the
judgeability filter keeps them all and the sample-order comparison is about
the ordering, not the filter.
"""

import hub
import z_deep


def main():
    try:
        return hub.run() + z_deep.run()
    except ValueError:
        return 0


def alpha():
    try:
        return 1
    except ValueError:
        return 0


def beta():
    try:
        return 2
    except ValueError:
        return 0


def gamma():
    try:
        return 3
    except ValueError:
        return 0


if __name__ == "__main__":
    main()
