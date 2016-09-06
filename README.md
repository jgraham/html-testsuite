# WebDriver client for Python

This package provides Python bindings
that conform to the [W3C WebDriver standard](https://w3c.github.io/webdriver/webdriver-spec.html),
which specifies a remote control protocol for web browsers.

These bindings are written with determining
implementation compliance to the specification in mind,
so that different remote end drivers
can determine whether they meet the recognised standard.
The client is used for the WebDriver specification tests
in the [Web Platform Tests](https://github.com/w3c/web-platform-tests).

## Installation

To install the package individually
in your virtualenv or system-wide:

    % python setup.py install

Or if you want to contribute patches:

    % python setup.py develop

If you are writing WebDriver specification tests for
[WPT](https://github.com/w3c/web-platform-tests),
there is no need to install the client manually
as it is picked up as a submodule to
[wpt-tools](https://github.com/w3c/wpt-tools)
that is checked out in `./tools`.

## Usage

You can use the built-in
[context manager](https://docs.python.org/2/reference/compound_stmts.html#the-with-statement)
to manage the lifetime of the session.
The session is started implicitly
at the first call to a command if it has not already been started,
and will implicitly be ended when exiting the context:

```py
import webdriver

with webdriver.Session("127.0.0.1", 4444) as session:
    session.url = "https://mozilla.org"
    print "The current URL is %s" % session.url
```

The following is functionally equivalent to the above,
but giving you manual control of the session:

```py
import webdriver

session = webdriver.Session("127.0.0.1", 4444)
session.start()

session.url = "https://mozilla.org"
print "The current URL is %s" % session.url

session.end()
```

## Dependencies

This client has the benefit of only using standard library dependencies.
No external PyPI dependencies are needed.
