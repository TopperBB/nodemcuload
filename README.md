`nodemcuload`: NodeMCU file system utility
==========================================

[![PyPi version](https://img.shields.io/pypi/v/nodemcuload.svg?style=flat)](https://pypi.python.org/pypi/nodemcuload)
[![Build status](https://travis-ci.org/mossblaser/nodemcuload.svg?branch=master)](https://travis-ci.org/mossblaser/nodemcuload)

A simple command-line interface and Python (2 and 3) library for reading and
writing files to the [spiffs](https://github.com/pellepl/spiffs) filesystem of
an ESP8266 wifi IoT device running
[NodeMCU](https://github.com/nodemcu/nodemcu-firmware).

Optional: Install using `setup.py`
----------------------------------

    $ python setup.py install

You can alternatively use the `nodemcuload.py` file standalone. Make sure you
have the [pyserial](https://pythonhosted.org/pyserial/) library installed and
substitute `python nodemcuload.py` in place of `nodemcuload` in the examples
below.

Examples
--------

Write `myscript.lua` to `main.lua` in flash:

    $ nodemcuload --write main.lua < myscript.lua

Read `main.lua` back from flash and print it to `myscript.lua`:

    $ nodemcuload --read main.lua > myscript.lua

List all files on the device:

    $ nodemcuload --list
    Total 1 file, 2117 bytes
    main.lua  2117

Delete `main.lua` from flash:

    $ nodemcuload --delete main.lua

Reformat the flash (erasing all files):

    $ nodemcuload --format

Move/rename `foo.lua` to `bar.lua` in flash:

    $ nodemcuload --move foo.lua bar.lua

Start executing `main.lua` on the device using the Lua
[`dofile`](http://www.lua.org/pil/8.html) command:

    $ nodemcuload --dofile main.lua

Instruct the device to reset itself and wait until the prompt returns:

    $ nodemcuload --restart

To use a specific device and baudrate:

    $ nodemcuload --port=/dev/ttyUSB0 --baudrate=115200 ...

Use as a Python library:

    $ python
    >>> from serial import Serial
    >>> from nodemcuload import NodeMCU
    >>> n = NodeMCU(Serial("/dev/ttyUSB0", 9600, timeout=1.0))
    >>> print(n.get_version())
    (1, 4)

Implementation Note
-------------------

This tool functions by sending commands to the Lua interpreter provided by
NodeMCU. This means that if this functionality is unavailable (e.g. due to a
rogue `init.lua`) the command will fail.

Running Tests
-------------

To run all tests automatically against various versions of Python run:

    $ pip install tox
    $ tox

Alternatively you can run the [pytest](https://pytest.org/) based test suite by
hand like so:

    $ pip install -r requirements-test.txt
    $ py.test tests.py --cov nodemcuload.py --cov tests.py --cov-fail-under=100 --cov-report=term-missing

Code formatting should also be checked by flake8:

    $ pip install flake8
    $ flake8 tests.py nodemcuload.py
