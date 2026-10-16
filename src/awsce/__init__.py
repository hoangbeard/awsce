"""awsce: check, summarize and analyze your AWS costs from the command line."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("awsce")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.0.0"

__all__ = ["__version__"]
