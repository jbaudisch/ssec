> [!CAUTION]
> This repository has been replaced!
> New repository: https://github.com/sharly-project/ssec

# SSEC - Client for Server-Sent Events (SSE)
Yet another client library for server-sent events (sse).

## General
This package provides a modern client for server-sent events (sse).

The code is based on the standard specification[[1](https://html.spec.whatwg.org/multipage/server-sent-events.html)] and was adapted for python.
Althought there are serveral other implementations like [[2](https://github.com/btubbs/sseclient)] and [[3](https://github.com/mpetazzoni/sseclient)],
the goal of this package is to have a modern (2022 + Python3.10), thread-safe, well documented and feature-rich
client. Also, these two packages have some corner-cases where they do not work properly.

## Maintainance
This repository is under active maintainance. If you have any ideas, issues or contributions, let me know. Pull requests are welcome.

## Installation
This package should be installable via pip:

```py
pip install ssec
```

It might be the case that this package is currently not available on pip.
If so, you can download this repositoy and run

```
cd INSTALL_PATH/ssec
pip install .
```

## Usage
You can find simple examples in the ``example.py``.
