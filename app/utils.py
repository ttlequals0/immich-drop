"""
Shared utility functions for immich-drop
"""


def detect_file_type(data: bytes) -> tuple[str, str]:
    """
    Detect file type from magic bytes.
    Returns (extension, mime_type) or (None, None) if unknown.
    """
    if len(data) < 12:
        return None, None

    # JPEG: FF D8 FF
    if data[:3] == b'\xff\xd8\xff':
        return '.jpg', 'image/jpeg'

    # PNG: 89 50 4E 47 0D 0A 1A 0A
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return '.png', 'image/png'

    # GIF: GIF87a or GIF89a
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return '.gif', 'image/gif'

    # WebP: RIFF....WEBP
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return '.webp', 'image/webp'

    # HEIC/HEIF/AVIF: ftyp box with brand
    if data[4:8] == b'ftyp':
        brand = data[8:12]
        if brand in (b'heic', b'heix', b'hevc', b'hevx', b'mif1'):
            return '.heic', 'image/heic'
        if brand == b'avif':
            return '.avif', 'image/avif'
        # MP4/MOV video formats
        if brand in (b'isom', b'iso2', b'mp41', b'mp42', b'M4V ', b'M4A '):
            return '.mp4', 'video/mp4'
        if brand == b'qt  ':
            return '.mov', 'video/quicktime'

    # BMP: BM
    if data[:2] == b'BM':
        return '.bmp', 'image/bmp'

    # TIFF: II or MM
    if data[:4] in (b'II*\x00', b'MM\x00*'):
        return '.tiff', 'image/tiff'

    return None, None
