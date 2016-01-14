#!/usr/bin/env python

"""
A command-line interface to the file system operations of the NodeMCU Lua
interpreter.
"""

import serial


class NodeMCU(object):
    """Utilities which allow basic control of an ESP8266 running NodeMCU."""

    def __init__(self, serial):
        """Connect to a device at the end of a specific serial port."""
        self.serial = serial

    def __enter__(self):
        """Close the serial port using a context manager."""
        return self.serial.__enter__()

    def __exit__(self, *args, **kwargs):
        """Close the serial port using a context manager."""
        return self.serial.__exit__(*args, **kwargs)

    def flush(self):
        """Dispose of anything remaining in the input buffer."""
        while self.serial.in_waiting:
            self.serial.read(self.serial.in_waiting)

    def send_command(self, cmd):
        """Send a single-line Lua command.

        Also absorbs the echo back and newline.
        """
        cmd = (cmd + "\r\n").encode("utf-8")
        self.serial.write(cmd)
        # Absorb the print-back
        self.read_line()

    def read_line(self, line_ending="\r\n"):
        """Read a single line of response.

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
        line_ending = line_ending.encode("utf-8")
        while data[-2:] != line_ending:
            data += self.serial.read(1)
        return data[:-2].decode("utf-8")

    def get_version(self):
        """Get the version number of the remote device.

        Returns
        -------
        (major, minor)
        """
        self.send_command("=node.info()")
        info = list(map(int, self.read_line().split("\t")))
        return (info[0], info[1])

    def write_file(self, filename, data, block_size=64):
        """Write a file to the device's flash.

        Parameters
        ----------
        filename : str
            File to write to on the device.
        data : str
            The data to write into the file.
        block_size : int
            The number of bytes to write at a time.
        """
        self.send_command("file.close()")
        self.send_command("=file.open({}, 'w')".format(repr(filename)))
        if self.read_line() == "nil":
            raise IOError("Could not open file for writing!")
        while data:
            block = data[:block_size]
            data = data[block_size:]
            self.send_command("=file.write({})".format(repr(block)))
            response = self.read_line()
            if response != "true":
                raise IOError("Write failed! (Return value: {})".format(
                    repr(response)))
        self.send_command("file.close()")

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
        The contents of the file as a string.
        """
        self.send_command("file.close()")

        # Determine file size
        self.send_command("=file.list()[{}]".format(repr(filename)))
        size = self.read_line()
        if size == "nil":
            raise IOError("File does not exist!")
        size = int(size)

        self.send_command("=file.open({}, 'r')".format(repr(filename)))
        if self.read_line() != "true":
            raise IOError("Could not open file!")

        # Read the file one block at a time
        data = b""
        while size:
            block = max(size, block_size)
            size -= block
            self.send_command("uart.write(0, file.read({}))".format(block))
            data += self.serial.read(block)

        return data.decode("utf-8")

    def list_files(self):
        """Get a list of files on the device's flash.

        Returns
        -------
        {filename: size, ...}
        """
        # Get number of files
        self.send_command(
            "do local cnt = 0;"
            "for k, v in pairs(file.list()) do"
            "    cnt = cnt + 1 end;"
            "    print(cnt);"
            "end")
        num_files = int(self.read_line())

        # Print the files and their sizes (prefixed by filename length)
        self.send_command("for f,s in pairs(file.list()) do"
                          "    print(#f, f, s);"
                          "end")

        files = {}
        for file in range(num_files):
            line = self.read_line()
            filename_length, _, line = line.partition("\t")
            filename_length = int(filename_length)

            filename = line[:filename_length]
            size = int(line[filename_length + 1:])
            files[filename] = size

        return files

    def remove_file(self, filename):
        """Delete a file on the device's flash."""
        self.send_command("=file.list()[{}]".format(repr(filename)))
        if self.read_line() == "nil":
            raise IOError("File does not exist!")
        self.send_command("file.remove({})".format(repr(filename)))

    def rename_file(self, old, new):
        """Rename a file on the device's flash."""
        self.send_command("=file.rename({}, {})".format(
            repr(old), repr(new)))
        if self.read_line() != "true":
            raise IOError("Rename failed!")

    def format(self):
        """Format the device's flash."""
        self.send_command("file.format()")

    def dofile(self, filename):
        """Execute a file in flash using 'dofile'.

        Returns
        -------
        The lines printed before the shell returns (or '> ' appears in the
        output).
        """
        self.send_command("=file.list()[{}]".format(repr(filename)))
        if self.read_line() == "nil":
            raise IOError("File does not exist!")
        self.send_command("dofile({})".format(repr(filename)))
        return self.read_line({"> "})

    def restart(self):
        """Request a module restart.

        Wait for the propt to return.
        """
        self.send_command("node.restart()")

        # Absorb the prompt returned just before restarting
        self.read_line("> ")

        # Wait for prompt to return
        try:
            self.read_line("> ")
        except UnicodeDecodeError:
            # Some garbage will come back from the device...
            pass


def main():
    import sys
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

    args = parser.parse_args()

    if args.port is None:
        parser.error("No serial port specified.")

    n = NodeMCU(serial.Serial(args.port, args.baudrate))
    with n:
        # Check version for compatibility (and also ensure serial stream is in
        # sync)
        if not ((1, 4) <= n.get_version() < (2, 0)):
            raise Exception("Incompatible version of NodeMCU!")

        # Handle command
        if args.write:
            n.write_file(args.write[0], sys.stdin.read())
        elif args.read:
            sys.stdout.write(n.read_file(args.read[0]))
        elif args.list:
            files = n.list_files()

            # Summary line
            num_files = len(files)
            total_size = sum(files.values())
            print("Total {} file{}, {} byte{}".format(
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
            n.remove_file(args.move[0], args.move[1])
        elif args.format:
            n.format()
        elif args.dofile:
            sys.stdout.write(n.dofile(args.dofile[0]))
        elif args.restart:
            n.restart()
        elif args.terminal:
            n.terminal()
    
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
