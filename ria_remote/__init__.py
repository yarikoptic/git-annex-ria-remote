from .version import __version__
from .remote import RIARemote

from ._version import get_versions
__version__ = get_versions()['version']
del get_versions
