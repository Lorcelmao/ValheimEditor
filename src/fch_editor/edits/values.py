"""Validation shared by edits: numbers must be storable exactly as the file will hold them."""
import math

from ..errors import EditError
from ..reader import F32


def stored_f32(value: float, what: str) -> float:
    """Validate a finite, non-negative number and return it as the file stores it (f32).

    Normalising up front means the pipeline's write-back check compares like
    with like: -0.0 and values that underflow become plain 0.0.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise EditError(f"{what} must be a finite number >= 0, got {value!r}")
    try:
        stored = F32.unpack(F32.pack(value))[0]
    except OverflowError:
        raise EditError(f"{what} {value:g} is too large to store") from None
    return stored + 0.0


def parse_number(text: str, what: str) -> float:
    try:
        return float(text)
    except ValueError:
        raise EditError(f"{what} must be a number, got {text!r}") from None
