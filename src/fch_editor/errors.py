"""Error types shared by the codec, editing, and file IO layers."""


class FchError(Exception):
    """Base class for every error this package raises on purpose."""


class FormatError(FchError):
    """Input bytes do not match the expected layout.

    Carries the byte offset and a dotted field path so users can tell exactly
    where a save diverges from the spec.
    """

    def __init__(self, message: str, offset: int | None = None, path: str = ""):
        self.message = message
        self.offset = offset
        self.path = path
        where = []
        if path:
            where.append(path)
        if offset is not None:
            where.append(f"offset 0x{offset:x}")
        super().__init__(f"{message} ({', '.join(where)})" if where else message)


class UnsupportedVersion(FchError):
    """A section version is outside the table the editor can safely write."""


class UnsafeWrite(FchError):
    """A write was refused because it could damage the save."""


class EditError(FchError):
    """An edit request is invalid (unknown name, out-of-range value, ...)."""
