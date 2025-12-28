"""Mirror website into a static site directory using wget.

The script prefers the bundled wget on Windows (tools/mingw64/bin/wget.exe),
and uses the system wget on Linux/macOS, falling back to the bundled version
when system wget is unavailable. Output defaults to ./site and can be cleaned
before each run.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen


DEFAULT_URL = "https://typecho.org/"
DEFAULT_OUTPUT_DIR = "site"
REJECT_REGEX = r"/(admin|login|register|action|feed)/"


def project_root() -> Path:
    """Return the directory containing this script."""
    return Path(__file__).resolve().parent


def resolve_output_dir(root: Path, output_dir: str) -> Path:
    """Resolve and validate the output directory inside the project root."""
    target = (root / output_dir).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("Output directory must stay under the project root") from exc
    return target


def temp_output_dir(output_dir: Path) -> Path:
    """Derive a temporary output directory alongside the final output."""
    return output_dir.with_name(f"{output_dir.name}_tmp")


def bundled_wget_path(root: Path) -> Path:
    """Path to the repository-bundled wget executable."""
    return root / "tools" / "mingw64" / "bin" / "wget.exe"


def find_wget(root: Path) -> Path:
    """Pick the appropriate wget executable."""
    system_name = platform.system().lower()
    bundled = bundled_wget_path(root)
    system_wget = shutil.which("wget")

    if system_name == "windows":
        if bundled.exists():
            return bundled
        if system_wget:
            return Path(system_wget)
        raise FileNotFoundError(
            "wget not found. Expected bundled wget at tools/mingw64/bin/wget.exe "
            "or a system wget in PATH."
        )

    if system_wget:
        return Path(system_wget)
    if bundled.exists():
        return bundled
    raise FileNotFoundError(
        "wget not found. Install wget or place it at tools/mingw64/bin/wget.exe."
    )


def cleanup_directory(path: Path) -> None:
    """Remove a directory tree if it exists."""
    if path.exists():
        shutil.rmtree(path)


def prepare_temp_directory(temp_dir: Path, seed_from: Path | None) -> None:
    """Create a fresh temporary directory, optionally seeded from an existing tree."""
    cleanup_directory(temp_dir)
    temp_dir.parent.mkdir(parents=True, exist_ok=True)
    if seed_from and seed_from.exists():
        shutil.copytree(seed_from, temp_dir)
    else:
        temp_dir.mkdir(parents=True, exist_ok=True)


def replace_directory(src: Path, dst: Path) -> None:
    """Replace dst with src, keeping the previous dst until replacement succeeds."""
    backup = dst.with_name(f"{dst.name}_backup")
    if backup.exists():
        shutil.rmtree(backup)

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst_existed = dst.exists()
    if dst_existed:
        dst.rename(backup)

    try:
        src.rename(dst)
    except OSError:
        if dst_existed and backup.exists():
            backup.rename(dst)
        raise

    if backup.exists():
        shutil.rmtree(backup)


def build_wget_command(
    wget_path: Path, output_dir: Path, url: str, spider: bool
) -> List[str]:
    """Construct the wget command for the mirror job."""
    command: List[str] = [
        str(wget_path),
        "--mirror",
        "--convert-links",
        "--adjust-extension",
        "--page-requisites",
        "--no-parent",
        "--restrict-file-names=windows",
        f"--reject-regex={REJECT_REGEX}",
        "-P",
        str(output_dir),
        "-nH",
    ]
    if spider:
        command.append("--spider")
    command.append(url)
    return command


def stream_process_output(command: Iterable[str]) -> int:
    """Run a process and stream stdout/stderr to the console."""
    with subprocess.Popen(
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    ) as proc:
        if proc.stdout:
            for line in proc.stdout:
                print(line, end="")
        return_code = proc.wait()
    return return_code


def rewrite_links_to_local(output_dir: Path, base_url: str) -> None:
    """Post-process downloaded files to point base-domain assets to local copies."""
    parsed = urlsplit(base_url)
    host = parsed.netloc
    if not host:
        return
    prefixes = {f"{scheme}://{host}" for scheme in ("http", "https")}
    prefixes.add(f"//{host}")
    pattern = re.compile(
        r"(?P<prefix>" + "|".join(re.escape(p) for p in prefixes) + r")(?P<path>/[^\s\"'>)]+)"
    )
    for file_path in output_dir.rglob("*"):
        if file_path.suffix.lower() not in {".html", ".htm", ".css", ".js"}:
            continue
        try:
            original = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        changed = False

        def _replace(match: re.Match[str]) -> str:
            nonlocal changed
            url_path = match.group("path")
            local_target = (output_dir / url_path.lstrip("/")).resolve()
            if local_target.exists():
                relative = Path(
                    os.path.relpath(local_target, start=file_path.parent.resolve())
                )
                changed = True
                return str(relative).replace("\\", "/")
            return match.group(0)

        rewritten = pattern.sub(_replace, original)
        if changed:
            try:
                file_path.write_text(rewritten, encoding="utf-8")
            except OSError:
                pass


def _hash_filename(url: str, default_ext: str = ".bin") -> str:
    parsed = urlsplit(url)
    ext = Path(parsed.path).suffix or default_ext
    digest = hashlib.sha1(url.encode("utf-8", "ignore")).hexdigest()
    return f"{digest}{ext}"


def download_external_images(output_dir: Path, base_url: str) -> None:
    """Download external img/src assets and rewrite HTML to local relative paths."""
    base_host = urlsplit(base_url).netloc
    external_dir = output_dir / "external_assets"
    external_dir.mkdir(parents=True, exist_ok=True)

    img_pattern = re.compile(
        r'(<img[^>]+src=["\'])(?P<src>https?:\/\/[^"\']+)(["\'])',
        flags=re.IGNORECASE,
    )
    replacements: dict[str, Path] = {}
    html_files = [
        p for p in output_dir.rglob("*") if p.suffix.lower() in {".html", ".htm"}
    ]

    for file_path in html_files:
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        changed = False

        def _handle_match(match: re.Match[str]) -> str:
            nonlocal changed
            src_url = match.group("src")
            host = urlsplit(src_url).netloc
            if not host or host == base_host:
                return match.group(0)

            if src_url not in replacements:
                filename = _hash_filename(src_url, default_ext=".img")
                dest_path = external_dir / filename
                if not dest_path.exists():
                    try:
                        with urlopen(src_url, timeout=20) as resp, open(
                            dest_path, "wb"
                        ) as out_f:
                            shutil.copyfileobj(resp, out_f)
                    except (URLError, OSError):
                        return match.group(0)
                replacements[src_url] = dest_path

            dest_path = replacements[src_url]
            relative = Path(
                os.path.relpath(dest_path.resolve(), start=file_path.parent.resolve())
            )
            changed = True
            new_src = str(relative).replace("\\", "/")
            return f"{match.group(1)}{new_src}{match.group(3)}"

        rewritten = img_pattern.sub(_handle_match, content)
        if changed:
            try:
                file_path.write_text(rewritten, encoding="utf-8")
            except OSError:
                pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mirror website into a local static site directory."
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="Root URL to mirror (default: %(default)s)",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Directory (relative to project root) to store the mirrored site (default: %(default)s)",
    )
    clean_group = parser.add_mutually_exclusive_group()
    clean_group.add_argument(
        "--clean",
        dest="clean",
        action="store_true",
        help="Start from a fresh temporary directory instead of seeding from the existing output (default).",
    )
    clean_group.add_argument(
        "--no-clean",
        dest="clean",
        action="store_false",
        help="Seed the temporary download directory from the existing output before mirroring.",
    )
    parser.set_defaults(clean=True)
    parser.add_argument(
        "--spider",
        action="store_true",
        help="Only run wget spider mode to test links without downloading files.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = project_root()
    try:
        output_dir = resolve_output_dir(root, args.output_dir)
        temp_dir = temp_output_dir(output_dir)
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        temp_dir.parent.mkdir(parents=True, exist_ok=True)
        wget_path = find_wget(root)
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"Using wget at: {wget_path}")
    print(f"Output directory: {output_dir}")
    print(f"Temporary directory: {temp_dir}")

    # Spider-only mode remains available for manual checks.
    if args.spider:
        cleanup_directory(temp_dir)
        spider_command = build_wget_command(wget_path, temp_dir, args.url, spider=True)
        print("Running spider command:")
        print(" ".join(spider_command))
        spider_code = stream_process_output(spider_command)
        cleanup_directory(temp_dir)
        if spider_code != 0:
            print(f"Spider check failed with code {spider_code}", file=sys.stderr)
        return spider_code

    # Pre-flight: spider the site before attempting a mirror.
    cleanup_directory(temp_dir)
    spider_command = build_wget_command(wget_path, temp_dir, args.url, spider=True)
    print("Running spider check before mirroring:")
    print(" ".join(spider_command))
    spider_code = stream_process_output(spider_command)
    if spider_code != 0:
        print(
            "Skipping mirroring because spider check failed; keeping existing output.",
            file=sys.stderr,
        )
        cleanup_directory(temp_dir)
        return spider_code

    try:
        seed_source = output_dir if not args.clean else None
        prepare_temp_directory(temp_dir, seed_from=seed_source)
    except OSError as exc:
        print(f"Failed to prepare temporary directory: {exc}", file=sys.stderr)
        cleanup_directory(temp_dir)
        return 1

    mirror_command = build_wget_command(wget_path, temp_dir, args.url, spider=False)
    print("Running mirror command:")
    print(" ".join(mirror_command))

    return_code = stream_process_output(mirror_command)
    if return_code != 0:
        print(f"wget exited with code {return_code}", file=sys.stderr)
        cleanup_directory(temp_dir)
        return return_code

    # Post-process links to ensure assets point to local copies for offline deploy.
    rewrite_links_to_local(temp_dir, args.url)
    download_external_images(temp_dir, args.url)

    try:
        replace_directory(temp_dir, output_dir)
    except OSError as exc:
        print(f"Failed to replace output directory: {exc}", file=sys.stderr)
        cleanup_directory(temp_dir)
        return 1

    return return_code


if __name__ == "__main__":
    sys.exit(main())
