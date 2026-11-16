"""
Tamper-evident source fingerprints for the Student Cluster Competition.

Each record is a JSON description of the source tree (and run context), compressed and
sealed to the organizer's X25519 public key, so teams can write records but not read them.
Only the standard library and `cryptography` are used, so the organizer's judge script can
import this module directly.
"""

import base64
import datetime
import difflib
import fnmatch
import getpass
import gzip
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import zlib
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

FORMAT = "MFCFP1"
LOG_NAME = "mfc_fingerprint.log"
BUILD_LOG_NAME = ".mfc_fingerprint_build"
# Set by the test suite: its runs write no run records or seals. A competition run without
# them has no sealed fingerprint log, so it cannot be submitted.
SKIP_ENV = "MFC_SCC_SKIP_FINGERPRINT"


def skipped() -> bool:
    return os.environ.get(SKIP_ENV) == "1"


SCC_DIR = "toolchain/mfc/scc"
BASELINE_PATH = f"{SCC_DIR}/baseline.json.gz"
PUBKEY_PATH = f"{SCC_DIR}/organizer.pub"
PUBLIC_RULES_PATH = f"{SCC_DIR}/allowed_changes.txt"

# Walked in full (ignored files included) because they feed the build. Elsewhere only tracked
# files and CMake files count (see list_tree).
WALK_DIRS = ("src", "toolchain", "cmake")
CMAKE_FILES = ("CMakeLists.txt", "*.cmake", "*.cmake.in")
SKIP_DIRS = {".git", "build", "__pycache__", ".venv", "node_modules", ".ffmt_cache", ".pytest_cache", ".ruff_cache", ".mypy_cache"}  # never build inputs

# Written by the toolchain or editors; recorded, but never a precheck violation.
GENERATED = (
    "src/*/include/case.fpp",
    "src/*/autogen/*",
    "toolchain/mfc/_version.py",
    "toolchain/mfc-case-schema.json",
    "toolchain/completions/mfc.bash",
    "toolchain/completions/_mfc",
    "toolchain/mfc/test/test_coverage_cache.json",
    "*.swp",
    "*.swo",
    "*.pyc",
    "*.DS_Store",
    "*/.nfs*",
)

CONTENT_CAP_FILE = 2 << 20  # changed files larger than this are recorded by hash only
CONTENT_CAP_TOTAL = 64 << 20

_SECRET_ENV = re.compile(r"TOKEN|SECRET|PASSW|CREDENTIAL|_KEY$|^KEY|AUTH", re.IGNORECASE)


# Rules and tree manifests


def matches(path: str, patterns: Iterable[str]) -> bool:
    """fnmatch globs; `*` also crosses `/`, so `*.cmake` matches at any depth."""
    return any(fnmatch.fnmatchcase(path, p) for p in patterns)


def read_rules(path: str) -> List[str]:
    with open(path) as f:
        return [s for s in (line.split("#", 1)[0].strip() for line in f) if s]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: str) -> bytes:
    if os.path.islink(path):
        return b"symlink:" + os.readlink(path).encode()
    with open(path, "rb") as f:
        return f.read()


def _git(root: str, *args: str) -> Optional[str]:
    try:
        out = subprocess.run(["git", "-C", root, *args], capture_output=True, check=True, timeout=60)
        return out.stdout.decode(errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None


def _walk(root: str, top: str = "") -> Iterator[str]:
    """Relative paths of every file under root/top, outside SKIP_DIRS."""
    for dirpath, dirnames, filenames in os.walk(os.path.join(root, top)):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        rel = os.path.relpath(dirpath, root)
        yield from (os.path.normpath(os.path.join(rel, f)).replace(os.sep, "/") for f in filenames)


def list_tree(root: str, extra: Iterable[str] = ()) -> List[str]:
    """
    Every file that can affect a build: tracked files, all of WALK_DIRS, CMake files anywhere
    (the only way the build reaches outside WALK_DIRS), and `extra` (the baseline). Untracked
    files elsewhere (case directories, logs, deliverables) are not build inputs. No ignore
    rules apply, and the git index is used only for listing, never for change detection, so
    neither .gitignore/.git/info/exclude nor `assume-unchanged`/`skip-worktree` can hide edits.
    """
    paths = set(extra)
    listed = _git(root, "ls-files", "-z", "-c")
    if listed:
        paths.update(p for p in listed.split("\0") if p)
    for top in WALK_DIRS:
        paths.update(_walk(root, top))
    paths.update(p for p in _walk(root) if matches(os.path.basename(p), CMAKE_FILES))
    return sorted(p for p in paths if p != BASELINE_PATH and os.path.basename(p) != LOG_NAME and not set(p.split("/")) & SKIP_DIRS)


def manifest(root: str, extra: Iterable[str] = ()) -> Dict[str, str]:
    """path -> sha256 of every existing file in list_tree()."""
    out = {}
    for p in list_tree(root, extra):
        full = os.path.join(root, p)
        if os.path.isfile(full) or os.path.islink(full):
            out[p] = sha256_bytes(_read(full))
    return out


def digest(files: Dict[str, str]) -> str:
    return sha256_bytes("".join(f"{p}\0{h}\n" for p, h in sorted(files.items())).encode())


def diff(baseline: Dict[str, str], current: Dict[str, str]) -> List[Tuple[str, str]]:
    """[(status, path)] with status A(dded), M(odified) or D(eleted)."""
    out = [("D", p) for p in baseline if p not in current]
    out += [("A" if p not in baseline else "M", p) for p, h in current.items() if baseline.get(p) != h]
    return sorted(out, key=lambda c: c[1])


def apply_changes(baseline: Dict[str, str], changes: List[dict]) -> Dict[str, str]:
    files = dict(baseline)
    for c in changes:
        if c["status"] == "D":
            files.pop(c["path"], None)
        else:
            files[c["path"]] = c["sha"]
    return files


def baseline_content(root: str, path: str, sha: str) -> Optional[bytes]:
    """The baseline version of `path`: the most recent git revision whose sha256 is `sha`."""
    for rev in (_git(root, "log", "--all", "-n", "50", "--format=%H", "--", path) or "").split():
        try:
            data = subprocess.run(["git", "-C", root, "show", f"{rev}:{path}"], capture_output=True, check=True, timeout=60).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        if sha256_bytes(data) == sha:
            return data
    return None


def diff_stat(old: bytes, new: bytes) -> Optional[Tuple[int, int]]:
    """(lines added, lines removed), or None for binary files."""
    try:
        a, b = old.decode().splitlines(), new.decode().splitlines()
    except UnicodeDecodeError:
        return None
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    return sum(j2 - j1 for tag, _, _, j1, j2 in ops if tag != "equal"), sum(i2 - i1 for tag, i1, i2, _, _ in ops if tag != "equal")


def load_baseline(path: str) -> Dict[str, str]:
    with gzip.open(path, "rt") as f:
        return json.load(f)["files"]


def write_baseline(root: str, out_path: str) -> Dict[str, str]:
    files = manifest(root)
    with gzip.GzipFile(out_path, "wb", mtime=0) as f:
        f.write(json.dumps({"format": FORMAT, "files": files}, sort_keys=True).encode())
    return files


# Records


def tree_state(root: str, public_rules: List[str]) -> dict:
    """Source-tree section of a record, plus the paths that break the public rules."""
    base_file = os.path.join(root, BASELINE_PATH)
    baseline = load_baseline(base_file) if os.path.isfile(base_file) else {}
    files = manifest(root, baseline)

    changes, budget = [], CONTENT_CAP_TOTAL
    for status, path in diff(baseline, files):
        entry = {"status": status, "path": path, "sha": files.get(path)}
        if status != "D":
            data = _read(os.path.join(root, path))
            entry["size"] = len(data)
            if len(data) <= min(CONTENT_CAP_FILE, budget) and not matches(path, GENERATED):
                entry["content"] = base64.b64encode(data).decode()
                budget -= len(data)
        changes.append(entry)

    return {
        "baseline_sha": sha256_bytes(_read(base_file)) if baseline else None,
        "digest": digest(files),
        "nfiles": len(files),
        "changes": changes,
        "violations": [c["path"] for c in changes if not matches(c["path"], public_rules) and not matches(c["path"], GENERATED)],
        "git": {
            "head": (_git(root, "rev-parse", "HEAD") or "").strip() or None,
            "branch": (_git(root, "rev-parse", "--abbrev-ref", "HEAD") or "").strip() or None,
            "status": _git(root, "status", "--porcelain", "--untracked-files=all"),
        },
    }


def context() -> dict:
    return {
        "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "host": platform.node(),
        "user": getpass.getuser(),
        "cwd": os.getcwd(),
        "argv": sys.argv,
        "python": sys.version,
        "env": {k: ("<redacted>" if _SECRET_ENV.search(k) else v) for k, v in os.environ.items()},
    }


# Sealing: ephemeral X25519 + HKDF-SHA256 + ChaCha20-Poly1305, header bound as AAD


def key_id(pub_raw: bytes) -> str:
    return sha256_bytes(pub_raw)[:16]


def load_pubkey(root: str) -> bytes:
    with open(os.path.join(root, PUBKEY_PATH)) as f:
        return base64.b64decode(f.read().strip())


def _derive(shared: bytes, epk: bytes, pub_raw: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(hashes.SHA256(), 32, salt=epk + pub_raw, info=FORMAT.encode()).derive(shared)


def seal(pub_raw: bytes, data: bytes, aad: bytes) -> bytes:
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    eph = X25519PrivateKey.generate()
    epk = eph.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    key = _derive(eph.exchange(X25519PublicKey.from_public_bytes(pub_raw)), epk, pub_raw)
    nonce = os.urandom(12)
    return epk + nonce + ChaCha20Poly1305(key).encrypt(nonce, data, aad)


def unseal(priv_raw: bytes, blob: bytes, aad: bytes) -> bytes:
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    priv = X25519PrivateKey.from_private_bytes(priv_raw)
    pub_raw = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    epk, nonce, ct = blob[:32], blob[32:44], blob[44:]
    key = _derive(priv.exchange(X25519PublicKey.from_public_bytes(epk)), epk, pub_raw)
    return ChaCha20Poly1305(key).decrypt(nonce, ct, aad)


# Log lines: "MFCFP1 <keyid> <stage> <target> <exe_sha> <tree digest> <base64 ciphertext>"


def encode_line(pub_raw: bytes, stage: str, target: str, exe_sha: str, record: dict) -> str:
    header = f"{FORMAT} {key_id(pub_raw)} {stage} {target} {exe_sha} {record.get('tree', {}).get('digest', '-')}"
    blob = seal(pub_raw, zlib.compress(json.dumps(record).encode(), 9), header.encode())
    return f"{header} {base64.b64encode(blob).decode()}\n"


def split_line(line: str) -> Tuple[str, List[str], bytes]:
    """(header, [keyid, stage, target, exe_sha, digest], ciphertext)"""
    header, _, b64 = line.strip().rpartition(" ")
    fields = header.split(" ")
    if len(fields) != 6 or fields[0] != FORMAT:
        raise ValueError(f"not a {FORMAT} line")
    return header, fields[1:], base64.b64decode(b64)


def decode_line(priv_raw: bytes, line: str) -> Tuple[List[str], dict]:
    header, fields, blob = split_line(line)
    return fields, json.loads(zlib.decompress(unseal(priv_raw, blob, header.encode())))


def file_sha(path: str) -> str:
    """sha256 of a file's contents, streamed so restart files of any size fit; "-" if absent."""
    return file_shas(path)[0] if os.path.isfile(path) else "-"


def file_shas(path: str, prefixes: Iterable[int] = ()) -> Tuple[str, Dict[str, str]]:
    """sha256 of the whole file and of each leading `prefixes` bytes, in one streamed pass."""
    whole = hashlib.sha256()
    parts = {n: hashlib.sha256() for n in prefixes}
    pos = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            whole.update(chunk)
            for n, h in parts.items():
                if pos < n:
                    h.update(chunk[: n - pos])
            pos += len(chunk)
    return whole.hexdigest(), {str(n): h.hexdigest() for n, h in parts.items()}


# Run outputs: restart files per time step, in every I/O layout (shared file, file per process, serial)
_OUTPUT_STEP = re.compile(r"^(?:restart_data/lustre_(\d+)(?:\.dat|/[^/]+)|p_all/p\d+/(\d+)/[^/]+)$")
TIMING_FILES = ("time_data.dat", "io_time_data.dat")
# Restart files hold 5-7 variables back to back with density first, so the leading 1/5, 1/6 or
# 1/7 of each is its density block. Sealing those prefixes lets a density-only copy be verified.
_VARS_PER_FILE = (5, 6, 7)


def step_outputs(case_dir: str) -> Dict[int, List[str]]:
    """Time step -> restart output files (relative to case_dir) written for it."""
    steps: Dict[int, List[str]] = {}
    for top in ("restart_data", "p_all"):
        for rel in _walk(case_dir, top):
            m = _OUTPUT_STEP.match(rel)
            if m:
                steps.setdefault(int(m.group(1) or m.group(2)), []).append(rel)
    return {n: sorted(files) for n, files in steps.items()}


def hash_outputs(case_dir: str, rels: Iterable[str], prefixes: bool = False) -> Dict[str, dict]:
    """rel -> sha, size and mtime of each output file, plus the density-block prefix hashes."""
    out = {}
    for rel in rels:
        path = os.path.join(case_dir, rel)
        st = os.stat(path)
        lengths = [st.st_size // k for k in _VARS_PER_FILE if st.st_size % k == 0] if prefixes and rel.startswith("restart_data/") else []
        sha, prefix_sha = file_shas(path, lengths)
        out[rel] = {"sha": sha, "size": st.st_size, "mtime": st.st_mtime, "prefix_sha": prefix_sha}
    return out


def restart_step(params: dict) -> int:
    """The saved step a run restarts from (t_step_start, or n_start with CFL-based dt); 0 if none."""
    return max(int(float(params.get(k, 0) or 0)) for k in ("t_step_start", "n_start"))


def seal_record(case_dir: str, since: float) -> dict:
    """Hashes of the final time step's outputs and the timing files a simulation started at `since` wrote."""
    steps = step_outputs(case_dir)
    final = max(steps) if steps else None
    outputs = hash_outputs(case_dir, steps.get(final, []), prefixes=True)
    stale = [rel for rel, o in outputs.items() if o["mtime"] < since - 1]  # left over from an earlier run
    timing, timing_mtime = {}, {}
    for name in TIMING_FILES:
        path = os.path.join(case_dir, name)
        if os.path.isfile(path) and os.stat(path).st_mtime >= since - 1:
            with open(path) as f:
                timing[name] = f.read()
            timing_mtime[name] = os.stat(path).st_mtime
    return {"final_step": final, "outputs": outputs, "stale_outputs": stale, "timing": timing, "timing_mtime": timing_mtime}
