"""run-capsule: scoped fingerprints for reproducible scientific runs."""
__version__ = "0.1.0"
from .core import CapsuleError, snapshot, verify
__all__ = ["CapsuleError", "snapshot", "verify"]
