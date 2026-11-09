"""CLI: python -m run_capsule."""
import argparse
import json
from pathlib import Path
import sys
from .core import CapsuleError, snapshot, verify


def load_json(path):
    def invalid(value):
        raise CapsuleError("Nonfinite JSON number: " + value)
    with open(path, encoding="utf-8") as stream:
        return json.load(stream, parse_constant=invalid)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Explicit, deterministic experiment input manifests")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("snapshot", help="Hash selected inputs without copying data")
    create.add_argument("inputs", nargs="+", help="POSIX paths relative to --root")
    create.add_argument("--root", default=".")
    create.add_argument("--output", required=True, help="New manifest path, relative to current working directory")
    create.add_argument("--config", help="JSON object metadata, explicitly selected")
    create.add_argument("--include-hidden", action="store_true")
    check = sub.add_parser("verify", help="Compare saved manifest against a root")
    check.add_argument("manifest")
    check.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    try:
        if args.command == "snapshot":
            output = Path(args.output)
            if output.exists() or output.is_symlink():
                raise CapsuleError("Output already exists; choose a new path")
            config = load_json(args.config) if args.config else {}
            result = snapshot(args.root, args.inputs, config, args.include_hidden, output)
            # Exclusive creation prevents silent replacement of preexisting data.
            with output.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
                stream.write("\n")
            print(result["label"])
            if result["skipped_symlinks"]:
                print("Skipped symlinks: " + ", ".join(result["skipped_symlinks"]), file=sys.stderr)
            return 0
        result = verify(args.root, load_json(args.manifest))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0 if result["ok"] else 1
    except (OSError, ValueError, RecursionError) as exc:
        print("run-capsule: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
