# Future Imports
from __future__ import annotations

# Typing Imports
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from typing import *
    from ssec import Event

# Builtin Imports
import logging
import threading
import time
import sys

# Library Imports
# []

# Project Imports
from ssec import EventSource

logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)


# # # # # # # # # #
# Normal Example
event_source = EventSource('https://stream.wikimedia.org/v2/stream/recentchange')
event_source.on_open = print
event_source.on_message = print
event_source.on_error = print
event_source.open()  # Interrupt with CTRL+C

# # # # # # # # # #
# Thread Example
event_source = EventSource('https://stream.wikimedia.org/v2/stream/recentchange', timeout=5)
event_source.on_open = print
event_source.on_message = print
event_source.on_error = print
t = threading.Thread(target=event_source.open)
t.start()
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
event_source.close()
t.join()
