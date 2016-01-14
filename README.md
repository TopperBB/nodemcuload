`nodemcuload`: NodeMCU file system utility
==========================================

A simple command-line interface for reading and writing files to the
[spiffs](https://github.com/pellepl/spiffs) filesystem of an ESP8266 wifi IoT
device running [NodeMCU](https://github.com/nodemcu/nodemcu-firmware).

Optional: Install using `setup.py`
----------------------------------

    $ python setup.py install

You can alternatively use the `nodemcuload.py` file standalone. Make sure you
have the [pyserial](https://pythonhosted.org/pyserial/) library installed and
substitute `python nodemcuload.py` for `nodemcuload` in the examples below.

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

Implementation Note
-------------------

This tool functions by sending commands to the Lua interpreter provided by
NodeMCU. This means that if this functionality is unavailable (e.g. due to a
rogue `init.lua`) the command will fail.
