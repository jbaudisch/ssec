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
import collections
import dataclasses
import enum
import logging
import time

# Library Imports
import requests
import urllib3

# Project Imports
from ssec.utilities import is_valid_url

_logger = logging.getLogger(__name__)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

@dataclasses.dataclass(frozen=True)
class Event:
    type: str
    data: str


class EventSource:

    class State(enum.Enum):
        """Represents the state of the connection."""
        CONNECTING = enum.auto()
        OPEN = enum.auto()
        CLOSED = enum.auto()

    MIME_TYPE = 'text/event-stream'
    DELIMITER = ':'

    def __init__(self, url: str, reconnection_time: int = 1000, backoff_delay: int = 5000, session: Optional[requests.Session] = None, **requests_kwargs: Dict[str, Any]):
        """
        Parameters
        ----------
        url : str
            The url of the event source.
        reconnection_time : int
            The time after which a reconnection being attempted on a connection lost, in milliseconds.
        backoff_delay : int
            An exponential backoff delay to avoid overloading a potentially already overloaded server (powered by reconnect-attempts), in milliseconds.
        session : Optional[requests.Session]
            Optionally, an already existing session object.
        requests_kwargs : Dict[str, Any]    
            Additional arguments for the underlying request like headers, verify etc.
            The stream argument is always set to True and will be ignored if set by user.

        Notes
        -----
        In case the event stream is discontinuous, the algorithm will block until a new
        event arrives. There is no way to interact with the object in the blocking state.
        Program shutdowns and other checks are not possible at that time. To prevent this,
        setting a timeout value to the requests_kwargs is the right choice.
        """
        if not is_valid_url(url):
            raise SyntaxError(f'The URL string "{url}" did not match the expected pattern.')

        self._url = url
        self._reconnection_time = reconnection_time
        self._backoff_delay = backoff_delay
        self._requests_kwargs = requests_kwargs

        # Ensure mandatory headers are set correctly
        if 'headers' not in self._requests_kwargs:
            self._requests_kwargs['headers'] = {}

        self._requests_kwargs['headers']['Accept'] = self.MIME_TYPE
        self._requests_kwargs['headers']['Cache-Control'] = 'no-store'

        self._requester = session or requests
        self._response = None

        self._state = self.State.CONNECTING
        self._last_event_id = ''

        self._listeners: Dict[str, List[Callable[[Event], None]]] = collections.defaultdict(list)

    @property
    def url(self) -> str:
        return self._url

    @property
    def state(self) -> State:
        return self._state

    def __announce(self) -> None:
        """Announces the connection."""
        if self._state is not self.State.CLOSED:
            self._state = self.State.OPEN
            self.__dispatch('open')

    def __connect(self) -> bool:
        """Tries to connect to the event stream.
        
        Returns
        -------
        True, if successfully connected, False, otherwise.
        """
        try:
            self._response = self._requester.get(self._url, stream=True, **self._requests_kwargs)
            self._response.raise_for_status()
        except requests.ConnectionError as e:
            self.__fail(str(e))
            return False
        except requests.Timeout:
            return False
        except requests.HTTPError as e:
            self.__fail(str(e))
            return False
        except requests.TooManyRedirects as e:
            self.__fail(str(e))
            return False

        if (self._response.status_code != 200) or (self.MIME_TYPE not in self._response.headers['Content-Type']):
            self.__fail(f'Invalid response: status_code={self._response.status_code}, mime-type={self._response.headers["Content-Type"]}')
            return False

        return True

    def __dispatch(self, type: str, data: str = '') -> None:
        """Dispatches an event.
        
        Parameters
        ----------
        type : str
            The event type.
        data : str
            The event data.
        """
        if self._state is self.State.CLOSED:
            return

        if not type:
            type = 'message'

        # Remove last character of data if it is a U+000A LINE FEED (LF) character.
        data = data.rstrip('\n')

        event = Event(type, data)
        match event.type:
            case 'open':
                self.on_open(event)
            case 'message':
                self.on_message(event)
            case 'error':
                self.on_error(event)

        for callback in self._listeners[event.type]:
            callback(event)

    def __fail(self, reason: str) -> None:
        """Fail the connection.
        
        Parameters
        ----------
        reason : str
            Explanation of the failure.
        """
        if self._state is not self.State.CLOSED:
            self.__dispatch('error', reason)
            self._state = self.State.CLOSED

    def __listen(self) -> None:
        """Listens for incoming events."""
        while self._state is self.State.OPEN:
            event_type = ''
            event_data = ''
            try:
                for line in self._response.iter_lines():
                    # If the line is empty (a blank line) -> Dispatch the event.
                    if not line:
                        self.__dispatch(event_type, event_data)
                        event_type, event_data = '', ''
                        continue

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
                            event_type = value
                        case 'data':
                            # If the field name is "data" -> Append the field value to the data buffer, then append a single U+000A LINE FEED (LF) character to the data buffer.
                            event_data += f'{value}\n'
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
            except requests.exceptions.RequestException:
                self.__reestablish()
            except AttributeError:
                return

    def __reestablish(self) -> None:
        """Reestablishes the connection."""
        if self._state is self.State.CLOSED:
            return
        
        self._state = self.State.CONNECTING
        self.__dispatch('error', 'reestablish')

        if self._last_event_id:
            self._requests_kwargs['headers']['Last-Event-ID'] = self._last_event_id

        attempt = 0
        while True:
            if self._state is not self.State.CONNECTING:
                break

            # Wait a delay equal to the reconnection time of the event source.
            time.sleep(self._reconnection_time/1000)

            # If the previous attempt failed, then use exponential backoff delay
            # to avoid overloading a potentially already overloaded server.
            if attempt > 0:
                time.sleep((self._backoff_delay/1000)**attempt)

            if self.__connect():
                self.__announce()
                break

            attempt += 1

    def add_event_listener(self, event_type: str, callback: Callable[[Event], None]):
        """Sets up a listener that will be called whenever an event with the specified type is received.
        
        Parameters
        ----------
        event_type : str
            The type of events this listener should react to.
        callback : Callable[[Event], None]
            The listener itself.
        """
        self._listeners[event_type].append(callback)

    def open(self) -> None:
        """Opens the event source stream."""
        if not self.__connect():
            self.__reestablish()

        self.__announce()
        self.__listen()

    def close(self) -> None:
        """Closes the event source stream."""
        self._state = self.State.CLOSED
        if self._response:
            self._response.close()

    # # # # # # # # # #
    # Event Methods
    def on_open(self, event: Event) -> None:
        """Fired when a connection to an event source has opened.
        
        Overwrite this function to capture those events.
        Equivalent to addEventListener('open', lambda event: None).

        Parameters
        ----------
        event : Event
            The open event of the EventSource.
        """
        pass

    def on_message(self, event: Event) -> None:
        """Fired when data is received from an event source.
        
        Overwrite this function to capture those events.
        Equivalent to addEventListener('message', lambda event: None).

        Parameters
        ----------
        event : Event
            The message event of the EventSource.
        """
        pass

    def on_error(self, event: Event) -> None:
        """Fired when a connection to an event source failed to open.
        
        Overwrite this function to capture those events.
        Equivalent to addEventListener('error', lambda event: None).

        Parameters
        ----------
        event : Event
            The error event of the EventSource.
        """
        pass
