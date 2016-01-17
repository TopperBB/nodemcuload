#!/usr/bin/env python

"""
A command-line interface to the file system operations of the NodeMCU Lua
interpreter.
"""


def lua_bytes(text):
    """Convert some bytes into an escaped lua string literal."""
    out = b""

    # Escape any characters if necessary
    for byte in text:
        # Python 2 & 3 Compatibility hack
        byte = byte if isinstance(byte, int) else ord(byte)

        if byte == ord("\\"):
            out += b"\\\\"
        elif byte == ord("'"):
            out += b"\\'"
        elif 0x20 <= byte < 0x7F:
            # Printable ASCII chars (incl. space)
            out += chr(byte).encode("ascii")
        else:
            out += "\\x{:02X}".format(byte).encode("ascii")

    return b"'" + out + b"'"


def lua_string(text):
    """Convert a Python string into a byte-encoded escaped lua string
    literal.
    """
    return lua_bytes(text.encode("utf-8"))


class NodeMCU(object):
    """Utilities which allow basic control of an ESP8266 running NodeMCU."""

    def __init__(self, serial, verbose_stream=None):
        """Connect to a device at the end of a specific serial port.

        Parameters
        ----------
        serial : :py:class:`serial.Serial`
            A serial port connection. Users should take care to select the
            correct baudrate and set a sensible timeout value.
        verbose_stream : file or None
            If not None, the data received via serial is written into the
            provided (binary) file.
        """
        self.serial = serial
        self.verbose_stream = verbose_stream

    def __enter__(self):
        """Close the serial port using a context manager."""
        return self.serial.__enter__()

    def __exit__(self, *args, **kwargs):
        """Close the serial port using a context manager."""
        return self.serial.__exit__(*args, **kwargs)

    def read(self, length):
        """Read from the port and throw an exception if this fails."""
        data = self.serial.read(length)

        if self.verbose_stream:
            self.verbose_stream.write(data)

        if len(data) != length:
            raise TimeoutError()
        return data

    def write(self, data):
        """Write the specified data throwing an exception if this fails."""
        written = self.serial.write(data)
        if written != len(data):
            raise TimeoutError()
        return written

    def read_line(self, line_ending=b"\r\n"):
        """Read from the port until the given terminator string is found.

        Parameters
        ----------
        line_ending : string
            Read from the serial port until the supplied line ending is found.

        Returns
        -------
        Return the contents of the line read back as a string. The line ending
        is stripped from the string before it is returned.
        """
        data = b""
        while not data.endswith(line_ending):
            data += self.read(1)
        return data[:-len(line_ending)]

    def flush(self):
        """Dispose of anything remaining in the input buffer."""
        while self.serial.in_waiting:
            self.read(self.serial.in_waiting)

    def send_command(self, cmd):
        """Send a single-line Lua command.

        Also absorbs the echo back and newline.
        """
        self.write(cmd + b"\r\n")
        # Absorb the print-back
        self.read_line()

    def get_version(self):
        """Get the version number of the remote device.

        Returns
        -------
        (major, minor)
        """
        self.send_command(b"=node.info()")
        info = list(map(int, self.read_line().split(b"\t")))
        return (info[0], info[1])

    def write_file(self, filename, data, block_size=64):
        """Write a file to the device's flash.

        Parameters
        ----------
        filename : str
            File to write to on the device.
        data : bytes
            The data to write into the file.
        block_size : int
            The number of bytes to write at a time.
        """
        self.send_command(b"file.close()")
        self.send_command(b"=file.open(" + lua_string(filename) + b", 'w')")
        if self.read_line() != b"true":
            raise IOError("Could not open file for writing!")
        while data:
            block = data[:block_size]
            data = data[block_size:]
            self.send_command(b"=file.write(" + lua_bytes(block) + b")")
            response = self.read_line()
            if response != b"true":
                raise IOError("Write failed! (Return value: {})".format(
                    repr(response)))
        self.send_command(b"file.close()")

    def read_file(self, filename, block_size=64):
        """Read file from the device's flash.

        Parameters
        ----------
        filename : str
            File to read from device.
        block_size : int
            The number of bytes to read at a time.

        Returns
        -------
        The contents of the file as a bytes.
        """
        self.send_command(b"file.close()")

        # Determine file size (and that it exists)
        self.send_command(b"=file.list()[" + lua_string(filename) + b"]")
        try:
            size = int(self.read_line())
        except ValueError:
            # e.g. if "nil" due to missing file
            raise IOError("File does not exist!")

        # Attempt to open the file
        self.send_command(b"=file.open(" + lua_string(filename) + b", 'r')")
        if self.read_line() != b"true":
            raise IOError("Could not open file!")

        # Read the file one block at a time
        data = b""
        while size:
            block = min(size, block_size)
            size -= block
            self.send_command(
                "uart.write(0, file.read({}))".format(block).encode("ascii"))
            data += self.read(block)

        self.send_command(b"file.close()")

        return data

    def list_files(self):
        """Get a list of files on the device's flash.

        Returns
        -------
        {filename: size, ...}
        """
        # Get number of files
        self.send_command(
            b"do"
            b"    local cnt = 0;"
            b"    for k, v in pairs(file.list()) do"
            b"        cnt = cnt + 1;"
            b"    end;"
            b"    print(cnt);"
            b"end")
        num_files = int(self.read_line())

        # Print the files and their sizes (prefixed by filename length) Note we
        # uart.write the filename in case it contains a \n which would be
        # converted into a \r\n by print.
        self.send_command(b"for f,s in pairs(file.list()) do"
                          b"    print(#f);"
                          b"    uart.write(0, f);"
                          b"    print(s);"
                          b"end")

        files = {}
        for file in range(num_files):
            filename_length = int(self.read_line())
            filename = self.read(filename_length).decode("utf-8")
            size = int(self.read_line())
            files[filename] = size

        return files

    def remove_file(self, filename):
        """Delete a file on the device's flash."""
        # Check that the file exists
        self.send_command(b"=file.list()[" + lua_string(filename) + b"]")
        try:
            int(self.read_line())
        except ValueError:
            raise IOError("File does not exist!")

        # Delete it
        self.send_command(b"file.remove(" + lua_string(filename) + b")")

    def rename_file(self, old, new):
        """Rename a file on the device's flash."""
        self.send_command(b"=file.rename(" +
                          lua_string(old) + b", " +
                          lua_string(new) + b")")
        if self.read_line() != b"true":
            raise IOError("Rename failed!")

    def format(self):
        """Format the device's flash."""
        self.send_command(b"file.format()")

    def dofile(self, filename):
        """Execute a file in flash using 'dofile'.

        Returns
        -------
        The bytes written to the uart before the shell returns (or '> ' appears
        in the output...).
        """
        # Check for file existance
        self.send_command(b"=file.list()[" + lua_string(filename) + b"]")
        try:
            int(self.read_line())
        except ValueError:
            raise IOError("File does not exist!")

        # Run the file and await return of the prompt
        self.send_command(b"dofile(" + lua_string(filename) + b")")
        return self.read_line(b"> ")

    def restart(self):
        """Request a module restart.

        Wait for the propt to return.
        """
        self.send_command(b"node.restart()")

        # Absorb the prompt returned just before restarting
        self.read_line(b"> ")

        # Wait for prompt to return
        self.read_line(b"> ")


def main(*args):
    import sys
    import serial
    import serial.tools.list_ports
    import argparse

    # Select a sensible default serial port, prioritising FTDI-style ports
    ports = map(next, map(iter, serial.tools.list_ports.comports()))
    ports = sorted(ports, key=(lambda p: ("ttyUSB" not in p, p)))
    if ports:
        default_port = ports[0]
    else:
        default_port = None

    parser = argparse.ArgumentParser(
        description="Access files on an ESP8266 running NodeMCU.")
    parser.add_argument("--port", "-p", type=str, default=default_port,
                        help="Serial port name/path (default = %(default)s).")
    parser.add_argument("--baudrate", "-b", type=int, default=9600,
                        help="Baudrate to use (default = %(default)d).")

    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--write", "-w", nargs=1, metavar="FILENAME",
                         help="Write the contents of stdin to the specified "
                              "file in flash.")
    actions.add_argument("--read", "-r", nargs=1, metavar="FILENAME",
                         help="Write the contents of the specified file in "
                              "flash and print it to stdout.")
    actions.add_argument("--list", "--ls", "-l", action="store_true",
                         help="List all files (and their sizes in bytes).")
    actions.add_argument("--delete", "--rm", nargs=1, metavar="FILENAME",
                         help="Delete the specified file.")
    actions.add_argument("--move", "--rename", "-m", nargs=2,
                         metavar=("OLDNAME", "NEWNAME"),
                         help="Rename the specified file.")
    actions.add_argument("--format", action="store_true",
                         help="Format the flash.")
    actions.add_argument("--dofile", nargs=1, metavar="FILENAME",
                         help="Format the flash.")
    actions.add_argument("--restart", "--reset", "-R", action="store_true",
                         help="Restart the device.")

    args = parser.parse_args(*args)

    if args.port is None:
        parser.error("No serial port specified.")

    n = NodeMCU(serial.Serial(args.port, args.baudrate))
    with n:
        # Check version for compatibility (and also ensure serial stream is in
        # sync)
        if not ((1, 4) <= n.get_version() < (2, 0)):
            raise ValueError("Incompatible version of NodeMCU!")

        # Handle command
        if args.write:
            # Python 2/3 hack: get stdin for bytes
            stdin = getattr(sys.stdin, "buffer", sys.stdin)
            n.write_file(args.write[0], stdin.read())
        elif args.read:
            # Python 2/3 hack: get stdout for bytes
            stdout = getattr(sys.stdout, "buffer", sys.stdout)
            stdout.write(n.read_file(args.read[0]))
        elif args.list:
            files = n.list_files()

            # Summary line
            num_files = len(files)
            total_size = sum(files.values())
            print("Total: {} file{}, {} byte{}.".format(
                num_files, "s" if num_files != 1 else "",
                total_size, "s" if total_size != 1 else ""))

            # File listing
            if files:
                max_filename_length = max(map(len, files)) + 1
                for filename, size in files.items():
                    print(filename.ljust(max_filename_length), size)
        elif args.delete:
            n.remove_file(args.delete[0])
        elif args.move:
            n.rename_file(args.move[0], args.move[1])
        elif args.format:
            n.format()
        elif args.dofile:
            stdout = getattr(sys.stdout, "buffer", sys.stdout)
            sys.stdout.write(n.dofile(args.dofile[0]))
        elif args.restart:  # pragma: no branch
            n.restart()

    return 0

if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
