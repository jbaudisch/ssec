# Future Imports
from __future__ import annotations

# Typing Imports
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from typing import *
    from ssec import Event

# Builtin Imports
import threading
import time

# Library Imports
# []

# Project Imports
from ssec import EventSource


def on_open(event: Event) -> None:
    print(event)

def on_message(event: Event) -> None:
    print(event)

def on_error(event: Event) -> None:
    print(event)

# # # # # # # # # #
# Normal Example
event_source = EventSource('https://stream.wikimedia.org/v2/stream/recentchange')
event_source.on_open = on_error
event_source.on_message = on_message
event_source.on_error = on_error
try:
    event_source.open()  # this will block
except KeyboardInterrupt:
    pass
event_source.close()

# # # # # # # # # #
# Thread Example
event_source = EventSource('https://stream.wikimedia.org/v2/stream/recentchange', timeout=5)
event_source.on_open = on_error
event_source.on_message = on_message
event_source.on_error = on_error
t = threading.Thread(target=event_source.open)
t.start()
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
event_source.close()
t.join()
