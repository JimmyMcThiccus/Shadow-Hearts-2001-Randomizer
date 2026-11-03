"""Command line: python -m shrando.cli <clean.iso> <out.iso> [--code SH1-...] [--seed S]"""
import argparse
import os
import random
import sys

from .randomize import Randomizer, Settings


def main(argv=None):
    ap = argparse.ArgumentParser(description="Shadow Hearts (USA) randomizer")
    ap.add_argument("iso", help="clean Shadow Hearts (USA) image")
    ap.add_argument("out", help="randomized image to write")
    ap.add_argument("--code", help="settings code from the GUI or a spoiler log")
    ap.add_argument("--seed", help="seed (default: random)")
    a = ap.parse_args(argv)
    s = Settings.from_code(a.code) if a.code else Settings()
    if a.seed:
        s.seed = a.seed
    if not s.seed:
        s.seed = "%08d" % random.randrange(10 ** 8)
    last = [None]

    def progress(f, msg):
        line = "%3d%% %s" % (f * 100, msg)
        if line != last[0]:
            print("\r%-40s" % line, end="", flush=True)
            last[0] = line

    log = Randomizer(a.iso, s, progress).run(a.out)
    print()
    spoiler = os.path.splitext(a.out)[0] + "_spoiler.txt"
    open(spoiler, "w", encoding="utf-8").write(log)
    print("wrote", a.out, "and", spoiler)
    print("code", s.to_code())


if __name__ == "__main__":
    sys.exit(main())
