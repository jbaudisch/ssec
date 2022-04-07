"""
This package provides a modern client for server-sent events (sse).

The code is based on the standard specification[1] and was adapted for python.
Althought there are serveral other implementations like [2] and [3], the goal
of this package is to have a modern (2022), thread-safe, well documented and
feature-rich client.

[1]: https://html.spec.whatwg.org/multipage/server-sent-events.html
[2]: https://github.com/btubbs/sseclient
[3]: https://github.com/mpetazzoni/sseclient

NotImplemented:
    - Event stream requests can be redirected using HTTP 301 and 307 redirects as with normal HTTP requests
    - A client can be told to stop reconnecting using the HTTP 204 No Content response code.
    - withCredentials
"""
# Future Imports
from __future__ import annotations

# Typing Imports
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from typing import *

# Builtin Imports
import cgi
import codecs
import collections
import dataclasses
import enum
import logging
import threading

# Library Imports
import requests
import urllib3

# Project Imports
from ssec.utilities import is_valid_url

_logger = logging.getLogger(__name__)
logging.getLogger('urllib3').setLevel(logging.ERROR)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


@dataclasses.dataclass(frozen=True)
class Event:
    type: str = ''
    data: str = ''


class EventSource:

    class State(enum.Enum):
        """Enum representing the state of the EventSource connection."""
        CONNECTING = enum.auto()
        OPEN = enum.auto()
        CLOSED = enum.auto()

    MIME_TYPE = 'text/event-stream'
    DELIMITER = ':'

    def __init__(self, url: str, reconnection_time: int = 3000, backoff_delay: int = 3000, chunk_size: int = 1,
                 session: Optional[requests.Session] = None, **request_kwargs: Dict[str, Any]) -> None:
        """
        Parameters
        ----------
        url : str
            The url of the event source.
        reconnection_time : int
            The time after which a reconnection being attempted on a connection lost, in milliseconds.
        backoff_delay : int
            An exponential backoff delay to avoid overloading a potentially already
            overloaded server (powered by reconnect-attempts), in milliseconds.
        chunk_size : int
            Size of the chunks read by the underlying response object.
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
        self._chunk_size = chunk_size
        self._last_event_id = ''
        self._request = session or requests
        self._state = self.State.CONNECTING
        self._request_kwargs = request_kwargs
    
        # Ensure mandatory headers are set correctly.
        if 'headers' not in self._request_kwargs:
            self._request_kwargs['headers'] = {}

        self._request_kwargs['headers']['Accept'] = self.MIME_TYPE
        self._request_kwargs['headers']['Cache-Control'] = 'no-store'

        self._listeners: Dict[str, List[Callable[[Event], None]]] = collections.defaultdict(list)
        self._response: Optional[requests.Response] = None
        
        # Event streams are always decoded as UTF-8. There is no way to specify another character encoding.
        # Process a queue with an instance of UTF-8’s decoder [...] "replacement".
        self._decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')

        self._rlock = threading.RLock()
        self._slock = threading.RLock()
        self._interrupt = threading.Event()

    def __str__(self) -> str:
        return f'{self.__class__.__name__}(url={self._url}, state={self.state})'

    @property
    def url(self) -> str:
        return self._url

    @property
    def state(self) -> State:
        with self._slock:
            return self._state

    def __announce(self) -> None:
        if self.state is not self.State.CONNECTING:
            return

        with self._slock:
            self._state = self.State.OPEN

        self.__dispatch('open')

    def __connect(self) -> None:
        if self.state is not self.State.CONNECTING:
            return

        try:
            with self._rlock:
                self._response = self._request.get(self._url, stream=True, **self._request_kwargs)
                self._response.raise_for_status()
        except requests.RequestException as e:
            _logger.error(e)
            self.__fail()
            return

        mime_type, _ = cgi.parse_header(self._response.headers['Content-Type'])
        if mime_type != self.MIME_TYPE:
            msg = f'Source responded with an invalid content type "{mime_type}", should have been "{self.MIME_TYPE}"!'
            _logger.error(msg)
            self.__fail()
            return

        if self._response.status_code != 200:
            msg = f'Source responded with an invalid status code "{self._response.status_code}", should have been "200"!'
            _logger.error(msg)
            self.__fail()
            return

        self.__announce()

    def __dispatch(self, type: str, data: str = '') -> None:
        if not type:
            type = 'message'

        # Remove last character of data if it is a U+000A LINE FEED (LF) character.
        data = data.rstrip('\n')

        event = Event(type, data)
        _logger.debug(f'{self} - Dispatching event: {event}')

        match event.type:
            case 'open':
                self.on_open(event)
            case 'message':
                self.on_message(event)
            case 'error':
                self.on_error(event)

        for callback in self._listeners[event.type]:
            callback(event)

    def __fail(self) -> None:
        if self.state is self.State.CLOSED:
            return

        _logger.error(f'{self} - Connection failed due to a previous error!')
        self.close()
        self.__dispatch('error')

    def __iter_content(self) -> Generator[str]:
        def generate() -> Generator[str]:
            while self.state is self.State.OPEN:
                try:
                    with self._rlock:
                        chunk = self._response.raw.read(self._chunk_size)
                except urllib3.exceptions.HTTPError as e:
                    _logger.debug(f'{self} - Failed reading content from response!')
                    _logger.debug(f'{self} - Reason: "{e}"!')
                    self.__reconnect()
                    continue
                except KeyboardInterrupt:
                    _logger.error(f'{self} - KeyboardInterrupt through user!')
                    self.__fail()
                    return

                if not chunk:
                    break
                yield chunk

        yield from generate()

    def __iter_lines(self) -> Generator[str]:
        # While testing a previous version of this library, which included
        # an approach using the response.iter_lines()/content() method from the
        # request module, it turned out that it was missing some content of some
        # sse messages. It seems like the chunked header is responsible for that.
        # To bypass this behaviour, we'll use the raw response here.
        buffer = ''
        for chunk in self.__iter_content():
            buffer += self._decoder.decode(chunk)
            lines = buffer.splitlines(keepends=True)
            buffer = ''
            for line in lines:
                if line.endswith(('\r\n', '\n', '\r')):
                    # Using '\r\n' as the parameter to rstrip means that it will strip out any trailing combination of '\r' or '\n'.
                    yield line.rstrip('\r\n')
                else:
                    buffer += line

    def __listen(self) -> None:
        if self.state is not self._state.OPEN:
            return

        event_type = ''
        event_data = ''
        for line in self.__iter_lines():
            # If the line is empty (a blank line) -> Dispatch the event.
            if not line:
                self.__dispatch(event_type, event_data)
                event_type, event_data = '', ''
                continue

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
                    # If the field name is "data" -> Append the field value to the data buffer,
                    # then append a single U+000A LINE FEED (LF) character to the data buffer.
                    event_data += f'{value}\n'
                case 'id':
                    # If the field name is "id" -> If the field value does not contain U+0000 NULL,
                    # then set the last event ID buffer to the field value. Otherwise, ignore the field.
                    # The specification is not clear here. In an example it says: "If the "id" field
                    # has no value, this will reset the last event ID to the empty string"
                    self._last_event_id = value
                case 'retry':
                    # If the field name is "retry" -> If the field value consists of only ASCII digits,
                    # then interpret the field value as an integer in base ten, and set the event stream's
                    # reconnection time to that integer. Otherwise, ignore the field.
                    if value.isdigit():
                        self._reconnection_time = int(value)
                case _:
                    # Otherwise -> The field is ignored.
                    continue

    def __reconnect(self) -> None:
        if self.state is self.State.CLOSED:
            return

        self.__dispatch('error')
        with self._slock:
            self._state = self.State.CONNECTING

        if self._last_event_id:
            self._request_kwargs['headers']['Last-Event-ID'] = self._last_event_id

        attempt = 0
        while self.state is self.State.CONNECTING:
            if _logger.isEnabledFor(logging.DEBUG):
                if attempt > 0:
                    _logger.debug(f'{self} - Reconnecting in {(self._reconnection_time/1000) + ((self._backoff_delay/1000)**attempt)} seconds.')
                else:
                    _logger.debug(f'{self} - Reconnecting in {(self._reconnection_time/1000)} seconds.')

            try:
                # Wait a delay equal to the reconnection time of the event source.
                self._interrupt.wait(self._reconnection_time/1000)

                # If the previous attempt failed, then use exponential backoff delay
                # to avoid overloading a potentially already overloaded server.
                if attempt > 0:
                    self._interrupt.wait((self._backoff_delay/1000)**attempt)
            except KeyboardInterrupt:
                _logger.error(f'{self} - KeyboardInterrupt through user!')
                self.__fail()
                return

            self.__connect()
            attempt += 1

        _logger.debug(f'{self} - Reconnected!')

    def add_event_listener(self, event_type: str, callback: Callable[[Event], None]) -> None:
        """Sets up a listener that will be called whenever an event with the specified type is received.
        
        Parameters
        ----------
        event_type : str
            The type of events this listener should react to.
        callback : Callable[[Event], None]
            The listener itself.
        """
        self._listeners[event_type].append(callback)
        _logger.debug(f'{self} - Added a new event listener for event_type = "{event_type}": {callback}')

    def close(self) -> None:
        """Closes the event source stream."""
        if self.state is self.State.CLOSED:
            return

        with self._slock:
            self._state = self.State.CLOSED

        self._interrupt.set()

        if not self._response:
            return

        with self._rlock:
            self._response.close()

        _logger.debug(f'{self} - Closed!')

    def open(self) -> None:
        """Opens the event source stream."""
        self.__connect()
        self.__listen()

    # # # # # # # # # #
    # Event Methods
    def on_error(self, event: Event) -> None:
        """Fires on connection failure.
        
        Overwrite this method to capture those events.
        Equivalent to addEventListener('error', lambda event: None).

        Parameters
        ----------
        event : Event
            The error event of the EventSource.
        """
        pass

    def on_message(self, event: Event) -> None:
        """Fires if an event is received.
        
        Overwrite this method to capture those events.
        Equivalent to addEventListener('message', lambda event: None).

        Parameters
        ----------
        event : Event
            The message event of the EventSource.
        """
        pass

    def on_open(self, event: Event) -> None:
        """Fires on connection establishment.
        
        Overwrite this method to capture those events.
        Equivalent to addEventListener('open', lambda event: None).

        Parameters
        ----------
        event : Event
            The open event of the EventSource.
        """
        pass
