"""Production client installer package for the Extella desktop distribution."""

from .bundle import BundleVerificationError, verify_bundle

__all__ = ["BundleVerificationError", "verify_bundle"]
