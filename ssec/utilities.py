# Future Imports
from __future__ import annotations

# Typing Imports
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from typing import *

# Builtin Imports
import urllib.parse

# Library Imports
# []

# Project Imports
# []


def is_valid_url(url: str) -> bool:
    """Checks if an given URL is valid.
    
    Parameters
    ----------
    url : str
        The URL to validate.
    """
    try:
        r = urllib.parse.urlparse(url)
        return all([r.scheme, r.netloc])
    except:
        return False
