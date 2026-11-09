"""Deterministic, explicitly scoped experiment fingerprints. Python standard library only."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat

SCHEMA = "run-capsule/v1"
# Original vocabulary: 32 lab/nature words, five independent 5-bit chunks.
WORDS = ("acorn", "beacon", "cedar", "delta", "ember", "fern", "glade", "harbor",
         "iris", "jade", "kelp", "lumen", "mesa", "nectar", "opal", "prism",
         "quartz", "reed", "spruce", "tide", "umber", "vale", "willow", "xenon",
         "yarrow", "zenith", "atlas", "brook", "cobalt", "dune", "echo", "flint")


class CapsuleError(ValueError):
    """Invalid inputs, unsupported filesystem entries, or invalid manifest."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest_of(payload):
    return hashlib.sha256(canonical(payload)).hexdigest()


def run_label(digest):
    """25-bit mnemonic plus 32-bit hexadecimal prefix; never an identity proof."""
    return "-".join(WORDS[(int(digest[8:16], 16) >> (5 * i)) & 31] for i in range(5)) + "-" + digest[:8]


def relative_path(value, allow_dot=False):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise CapsuleError("Paths must be nonempty relative POSIX paths")
    p = PurePosixPath(value)
    if p.is_absolute() or ".." in p.parts or (p == PurePosixPath(".") and not allow_dot) or ":" in value:
        raise CapsuleError("Unsafe relative path: " + value)
    if p.as_posix() != value:
        raise CapsuleError("Noncanonical path: " + value)
    return p


def checked_path(root, rel):
    p = root
    for part in relative_path(rel, allow_dot=True).parts:
        p = p / part
        if p.is_symlink():
            raise CapsuleError("Symlink is not allowed in selected path: " + rel)
    return p


def hash_file(path):
    # O_NOFOLLOW prevents final-component substitution where supported.
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise CapsuleError("Not a regular file: " + str(path))
        h = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise CapsuleError("File changed while hashing: " + str(path))
        return {"sha256": h.hexdigest(), "size": after.st_size}


def scan(root, selections, include_hidden, excluded):
    found, links = {}, []
    def visit(path):
        rel = path.relative_to(root).as_posix()
        if rel in excluded:
            return
        if not include_hidden and any(part.startswith(".") for part in PurePosixPath(rel).parts):
            return
        if path.is_symlink():
            links.append(rel)
            return
        try:
            mode = path.stat(follow_symlinks=False).st_mode
        except FileNotFoundError:
            return
        if stat.S_ISDIR(mode):
            for child in sorted(path.iterdir(), key=lambda p: p.name):
                visit(child)
        elif stat.S_ISREG(mode):
            found[rel] = {"path": rel, **hash_file(path)}
        else:
            raise CapsuleError("Unsupported filesystem entry: " + rel)
    for item in selections:
        path = checked_path(root, item["path"])
        # A directory replaced with a file must not escape the saved scope.
        if path.exists() and (path.is_dir() != (item["kind"] == "directory")):
            raise CapsuleError("Selected input changed type: " + item["path"])
        visit(path)
    return [found[key] for key in sorted(found)], sorted(set(links))


def snapshot(root, inputs, config=None, include_hidden=False, output=None):
    root = Path(root).resolve(strict=True)
    if not root.is_dir() or not inputs:
        raise CapsuleError("An existing root directory and explicit inputs are required")
    selections = []
    for rel in sorted(set(inputs)):
        p = checked_path(root, rel)
        if not p.exists():
            raise CapsuleError("Input does not exist: " + rel)
        if not include_hidden and any(s.startswith(".") for s in PurePosixPath(rel).parts):
            raise CapsuleError("Hidden input requires --include-hidden: " + rel)
        selections.append({"path": rel, "kind": "directory" if p.is_dir() else "file"})
    exclusions = []
    if output is not None:
        # Absolute lexical target: never follow an output symlink.
        output = Path(os.path.abspath(output))
        if output.is_symlink():
            raise CapsuleError("Refusing symlink output")
        try:
            out_rel = output.relative_to(root).as_posix()
            checked_path(root, out_rel)
            exclusions.append(out_rel)
        except ValueError as exc:
            if isinstance(exc, CapsuleError):
                raise
    metadata = {} if config is None else config
    if not isinstance(metadata, dict):
        raise CapsuleError("Config must be a JSON object")
    files, links = scan(root, selections, include_hidden, exclusions)
    payload = {"schema": SCHEMA, "inputs": selections, "policy": {"include_hidden": include_hidden, "exclude": exclusions, "symlinks": "skip"}, "config": metadata, "files": files}
    digest = digest_of(payload)
    return {**payload, "digest": digest, "label": run_label(digest), "skipped_symlinks": links}


def validate(manifest):
    try:
        if manifest["schema"] != SCHEMA or not isinstance(manifest["config"], dict):
            raise CapsuleError("Unsupported schema or invalid config")
        policy = manifest["policy"]
        if type(policy["include_hidden"]) is not bool or policy["symlinks"] != "skip":
            raise CapsuleError("Invalid policy")
        for p in policy["exclude"]:
            relative_path(p)
        if not manifest["inputs"]:
            raise CapsuleError("Empty selection")
        for entry in manifest["inputs"]:
            relative_path(entry["path"], allow_dot=True)
            if entry["kind"] not in ("file", "directory"):
                raise CapsuleError("Invalid selection kind")
        seen = set()
        for f in manifest["files"]:
            relative_path(f["path"])
            if f["path"] in seen or type(f["size"]) is not int or f["size"] < 0 or not isinstance(f["sha256"], str) or len(f["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in f["sha256"]):
                raise CapsuleError("Invalid file entry")
            seen.add(f["path"])
        payload = {k: manifest[k] for k in ("schema", "inputs", "policy", "config", "files")}
        digest = digest_of(payload)
        if manifest["digest"] != digest or manifest["label"] != run_label(digest):
            raise CapsuleError("Manifest digest or label does not match its contents")
    except (KeyError, TypeError, ValueError) as exc:
        raise CapsuleError("Invalid manifest: " + str(exc)) from exc


def verify(root, manifest):
    validate(manifest)
    root = Path(root).resolve(strict=True)
    files, links = scan(root, manifest["inputs"], manifest["policy"]["include_hidden"], manifest["policy"]["exclude"])
    old, new = ({f["path"]: f for f in entries} for entries in (manifest["files"], files))
    result = {"modified": sorted(k for k in old.keys() & new.keys() if old[k] != new[k]),
              "missing": sorted(old.keys() - new.keys()), "new": sorted(new.keys() - old.keys()), "skipped_symlinks": links}
    result["ok"] = not any(result[key] for key in ("modified", "missing", "new"))
    return result
