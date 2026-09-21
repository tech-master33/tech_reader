"""Package TechReader into screenreader_portable.zip.

Run this after `python -m PyInstaller screenreader.spec --noconfirm --clean`:

    python tools/package_zip.py

It guarantees the zip is clean: no .log / .dic / leftover junk, and the
run instructions sit at the top level next to the exe.
"""
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist", "screenreader")
OUT = os.path.join(ROOT, "screenreader_portable.zip")

EXCLUDE_EXT = (".dic", ".log", ".pyc", ".pyo")
EXCLUDE_NAMES = {"missing_deps.txt", "Thumbs.db", "desktop.ini"}


def clean_zip() -> None:
    n = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for dp, _dn, fn in os.walk(DIST):
            for f in fn:
                if f.lower().endswith(EXCLUDE_EXT) or f in EXCLUDE_NAMES:
                    continue
                p = os.path.join(dp, f)
                arc = "screenreader/" + os.path.relpath(p, DIST).replace(os.sep, "/")
                z.write(p, arc)
                n += 1
        # The run instructions must be visible next to the exe, not buried
        # in _internal.
        readme = os.path.join(ROOT, "packaging", "README-RUN.txt")
        z.write(readme, "screenreader/README-RUN.txt")
        n += 1
    with zipfile.ZipFile(OUT) as z:
        assert z.testzip() is None
        leaks = [x for x in z.namelist()
                 if x.lower().endswith(EXCLUDE_EXT) or os.path.basename(x) in EXCLUDE_NAMES]
        assert not leaks, leaks
        assert "screenreader/README-RUN.txt" in z.namelist()
    print(f"wrote {OUT} ({n} files, {os.path.getsize(OUT) / 1e6:.1f} MB), verified clean")


if __name__ == "__main__":
    clean_zip()
