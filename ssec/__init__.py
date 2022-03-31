"""
This package provides a modern client for server-sent events (sse).

The code is based on the standard specification[1] and was adapted for python.
Althought there are serveral other implementations like [2] and [3], the goal
of this package is to have a modern (2022), well documented and feature-rich
client.

[1]: https://html.spec.whatwg.org/multipage/server-sent-events.html
[2]: https://github.com/btubbs/sseclient
[3]: https://github.com/mpetazzoni/sseclient
"""

# Future Imports
from __future__ import annotations

# Typing Imports
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from typing import *

# Builtin Imports
import dataclasses
import enum
import logging
import queue
import re
import time

# Library Imports
import requests

# Project Imports
# []

_logger = logging.getLogger(__name__)


@dataclasses.dataclass
class Event:
    type: str = 'message'
    data: str = ''

    def clear(self) -> None:
        self.type = 'message'
        self.data = ''


class EventSource:

    class State(enum.Enum):
        """Represents the state of the connection."""
        CONNECTING = enum.auto()
        OPEN = enum.auto()
        CLOSED = enum.auto()

    DELIMITER = ':'

    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None, reconnection_time: int = 3000, backoff_delay: int = 5, timeout: int = 10, verify: bool | str = True) -> None:
        """
        Parameters
        ----------
        url
            TODO.
        headers
            TODO.
        reconnection_time
            The reconnection time, in milliseconds.
        backoff_delay
            An exponential backoff delay to avoid overloading a potentially already overloaded server (powered by reconnect-attempts), in seconds.
        timeout
            TODO.
        verify
            TODO.
        """
        self._url = url  # TODO: Check for Syntax => raise SyntaxError
        self._headers = headers if headers is not None else {}
        self._reconnection_time = reconnection_time
        self._backoff_delay = max(backoff_delay, 2)
        self._verify = verify

        # When the object is created its state must be set to CONNECTING.
        self._state = self.State.CONNECTING

        # When the object is created its last event id must be an empty string.
        self._last_event_id = ''

        self._event_queue: queue.SimpleQueue[Event] = queue.SimpleQueue()

        self._headers.update(
            {
                'Accept': 'text/event-stream',
                'Cache-Control': 'no-store'
            }
        )

        self._response = None
        if not self.__connect():
            self.__reestablish()

        self.__announce()
        self.__listen()
        print('DONE')

    def __announce(self) -> None:
        """Announces the connection."""
        if self._state is not self.State.CLOSED:
            self._state = self.State.OPEN
            self.__dispatch(Event('open'))

    def __connect(self) -> bool:
        """Tries to connect to the event stream.
        
        Returns
        -------
        True, if successfully connected, False, otherwise.
        """
        self._response = requests.get(self._url, headers=self._headers, stream=True, verify=self._verify)

        try:
            self._response.raise_for_status()
        except requests.HTTPError:  # TODO: Split Up
            return False

        if self._response.status_code != 200 or self._response.headers['Content-Type'] != 'text/event-stream':
            self.__fail()
            return False

        return True

    def __dispatch(self, event: Event) -> None:
        """Dispatches an event."""
        if self._state is self.State.CLOSED:
            return

        # If the data buffer's last character is a U+000A LINE FEED (LF) character, then remove the last character from the data buffer.
        event.data = event.data.rstrip('\n')
        # self._event_queue.put(event)
        print(event)

    def __listen(self) -> None:
        event = Event()
        for line in self._response.iter_lines():
            # If the line is empty (a blank line) -> Dispatch the event.
            if not line:
                self.__dispatch(dataclasses.replace(event))  # replace copies the event
                event.clear()

            line = (line.decode('utf8')).strip()
            # If the line starts with a U+003A COLON character (:) -> Ignore the line.
            if line.startswith(self.DELIMITER):
                continue

            name, _, value = line.partition(self.DELIMITER)

            # Space after the colon is ignored if present.
            if value.startswith(' '):
                value = value[1:]

            match name:
                case 'event':
                    # If the field name is "event" -> Set the event type buffer to field value.
                    event.type = value
                case 'data':
                    # If the field name is "data" -> Append the field value to the data buffer, then append a single U+000A LINE FEED (LF) character to the data buffer.
                    event.data += f'{value}\n'
                case 'id':
                    # If the field name is "id" -> If the field value does not contain U+0000 NULL, then set the last event ID buffer to the field value. Otherwise, ignore the field.
                    # The specification is not clear here. In an example it says: "If the "id" field has no value, this will reset the last event ID to the empty string"
                    self._last_event_id = value
                case 'retry':
                    # If the field name is "retry" -> If the field value consists of only ASCII digits, then interpret the field value as an integer in base ten, and set the event stream's reconnection time to that integer. Otherwise, ignore the field.
                    if value.isdigit():
                        self._reconnection_time = int(value)
                case _:
                    # Otherwise -> The field is ignored.
                    continue

    def __reestablish(self) -> None:
        """Reestablishes the connection."""
        # If the state attribute is set to CLOSED, abort the task.
        if self._state is self.State.CLOSED:
            return
        
        self._state = self.State.CONNECTING
        self.__dispatch(Event('error'))

        if self._last_event_id:
            self._headers.update({'Last-Event-ID': self._last_event_id})

        attempt = 0
        while True:
            if self._state is not self.State.CONNECTING:
                break

            # Wait a delay equal to the reconnection time of the event source.
            time.sleep(self._reconnection_time/1000)

            # If the previous attempt failed, then use exponential backoff delay
            # to avoid overloading a potentially already overloaded server.
            if attempt > 0:
                time.sleep(self.backoff_delay**attempt)

            if self.__connect():
                break

            attempt += 1

    def __fail(self) -> None:
        """Fail the connection."""
        if self._state is not self.State.CLOSED:
            self._state = self.State.CLOSED
            self.__dispatch(Event('error'))

    def close(self) -> None:
        """Aborts any instances of the fetch algorithm started for this EventSource object, and sets its state to CLOSED."""
        self._state = self.State.CLOSED
