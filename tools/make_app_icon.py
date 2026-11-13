#!/usr/bin/env python3
"""Draw the installers' icon files in packaging/ from parro_gui.icons.app_icon_image.

Needs Qt (`pip install -r requirements-gui.txt`) and no display.
    python3 tools/make_app_icon.py           # write the files
    python3 tools/make_app_icon.py --check   # fail when a file differs from what would be drawn

Briefcase looks for `packaging/icon` plus an extension: icon-<size>.png on Linux, icon.ico on
Windows, icon.icns on macOS. The .ico and .icns files hold PNG images, which every Windows since
Vista and every macOS since 10.7 read; they are packed here with the standard library. Run it on
one computer and commit the files: Qt on another system may draw the edges a pixel differently.
"""

import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
FOLDER = ROOT / "packaging"
LINUX_SIZES = (16, 32, 64, 128, 256, 512)
WINDOWS_SIZES = (16, 32, 48, 64, 128, 256)
# The PNG types of the .icns format, by the size of their pixels.
MACOS_TYPES = (
    (b"icp4", 16),
    (b"icp5", 32),
    (b"icp6", 64),
    (b"ic07", 128),
    (b"ic08", 256),
    (b"ic09", 512),
    (b"ic10", 1024),
    (b"ic11", 32),
    (b"ic12", 64),
    (b"ic13", 256),
    (b"ic14", 512),
)


def pack_ico(pngs: dict[int, bytes]) -> bytes:
    """An .ico file: a header, one directory entry per image, then the PNG images."""
    sizes = sorted(pngs)
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = len(header) + 16 * len(sizes)
    entries, images = b"", b""
    for size in sizes:
        data = pngs[size]
        side = 0 if size >= 256 else size  # 0 stands for 256
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset)
        images += data
        offset += len(data)
    return header + entries + images


def pack_icns(pngs: dict[int, bytes]) -> bytes:
    """An .icns file: `icns` and the length, then each image as type, length and PNG."""
    chunks = b"".join(
        kind + struct.pack(">I", 8 + len(pngs[size])) + pngs[size] for kind, size in MACOS_TYPES
    )
    return b"icns" + struct.pack(">I", 8 + len(chunks)) + chunks


def drawn_files() -> dict[str, bytes]:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtWidgets import QApplication

    from parro_gui.icons import app_icon_image

    _application = QApplication.instance() or QApplication([])

    def png(pixels: int) -> bytes:
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        app_icon_image(pixels).save(buffer, "PNG")
        return bytes(buffer.data().data())

    pngs = {size: png(size) for size in {*LINUX_SIZES, *WINDOWS_SIZES, 1024}}
    files = {f"icon-{size}.png": pngs[size] for size in LINUX_SIZES}
    files["icon.ico"] = pack_ico({size: pngs[size] for size in WINDOWS_SIZES})
    files["icon.icns"] = pack_icns(pngs)
    return files


def main(argv: list[str]) -> int:
    files = drawn_files()
    if argv == ["--check"]:
        differ = [
            n
            for n, data in files.items()
            if not (FOLDER / n).is_file() or (FOLDER / n).read_bytes() != data
        ]
        for name in differ:
            print(f"packaging/{name} differs; run python3 tools/make_app_icon.py", file=sys.stderr)
        return 1 if differ else 0
    FOLDER.mkdir(exist_ok=True)
    for name, data in files.items():
        (FOLDER / name).write_bytes(data)
        print(f"packaging/{name}: {len(data)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
