try:
    import pykickstart
except:
    import mic
    import sys
    sys.path.insert(0, mic.__path__[0])
    import pykickstart
    del(sys.path[0])

import desktop
import moblinrepo

__all__ = (
    "Moblin_Desktop",
    "Moblin_Repo",
    "Moblin_RepoData",
)
