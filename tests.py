"""
nodemcuload test suite.

Usage:

    $ pip install -r requirements-test.txt
    $ py.test tests.py
"""

import pytest

from mock import Mock

from nodemcuload import lua_bytes, lua_string, NodeMCU, main


@pytest.mark.parametrize("case,string",
                         [(b"", b"''"),
                          # Printable characters (incl space)
                          (b"hello", b"'hello'"),
                          (b"hi there", b"'hi there'"),
                          (b"Testing!", b"'Testing!'"),
                          (b"mail@jhnet.co.uk", b"'mail@jhnet.co.uk'"),
                          (b" !}~", b"' !}~'"),
                          # Escape-needing characters
                          (b"\\", b"'\\\\'"),
                          (b"'", b"'\\''"),
                          # Unprintable ASCII characters
                          (b"\x1F", b"'\\x1F'"),
                          (b"\x7F", b"'\\x7F'"),
                          # Arbitrary bytes
                          (b"\xDE\xAD\xBE\xEF\xFF",
                           b"'\\xDE\\xAD\\xBE\\xEF\\xFF'")])
def test_lua_bytes(case, string):
    """Tests for the lua_string string-literal generator."""
    assert lua_bytes(case) == string


@pytest.mark.parametrize("case,string",
                         [("", b"''"),
                          # Printable characters (incl space)
                          ("hello", b"'hello'"),
                          ("hi there", b"'hi there'"),
                          ("Testing!", b"'Testing!'"),
                          ("mail@jhnet.co.uk", b"'mail@jhnet.co.uk'"),
                          (" !}~", b"' !}~'"),
                          # Escape-needing characters
                          ("\\", b"'\\\\'"),
                          ("'", b"'\\''"),
                          # Unprintable ASCII characters
                          ("\x1F", b"'\\x1F'"),
                          ("\x7F", b"'\\x7F'"),
                          # Unicode
                          (u"\u2603", b"'\\xE2\\x98\\x83'")])
def test_lua_string(case, string):
    """Tests for the lua_string string-literal generator."""
    assert lua_string(case) == string


class MockSerial(object):
    """A pretend serial device."""

    def __init__(self, expected_sequence=[]):
        """A pretend serial device with protocol checking.

        Parameters
        ----------
        expected_sequence : list
            A list in which odd members indicate expected byte strings sent to
            the device and even members indicate byte strings to return. If a
            return value is b"", no data will be sent back. The expected
            sequence is checked.
        """
        self.expected_sequence = expected_sequence

        self.context_manager_state = []

    def __enter__(self):
        self.context_manager_state.append("enter")

    def __exit__(self, *args, **kwargs):
        self.context_manager_state.append(("exit", args, kwargs))

    @property
    def in_waiting(self):  # pragma: no cover
        if self.expected_sequence:
            return len(self.expected_sequence[0])
        else:
            return 0

    def read(self, length):
        assert self.expected_sequence, "No more expected reads."
        assert self.expected_sequence[0], "Was not expected further reads."
        assert length <= len(self.expected_sequence[0]), \
            "Tried to read more data than is available."

        data = self.expected_sequence[0][:length]
        self.expected_sequence[0] = self.expected_sequence[0][length:]
        return data

    def write(self, data):
        assert len(data) > 0, "At least *some* data should be written."
        assert len(self.expected_sequence) >= 2, "Unexpected write!"
        assert not self.expected_sequence[0], "Some input remains unread!"
        assert self.expected_sequence[1].startswith(data), \
            "Write data did not match expectation (Got {} not {}).".format(
                repr(data),
                repr(self.expected_sequence[1][:len(data) + 1]))

        # Remove data recieved from buffer
        self.expected_sequence[1] = self.expected_sequence[1][len(data):]

        # If no data is left to write, remove the expectation from the list
        if not self.expected_sequence[1]:  # pragma: no branch
            self.expected_sequence = self.expected_sequence[2:]

        return len(data)

    @property
    def finished(self):
        return (not self.expected_sequence or
                (len(self.expected_sequence) == 1 and
                 self.expected_sequence[0] == b""))


class TestNodeMCU(object):

    def test_context_manager_wrapper(self):
        """Make sure the context manager passes through to the serial port."""
        s = MockSerial()
        n = NodeMCU(s)

        assert s.context_manager_state == []
        with n:
            assert s.context_manager_state == ["enter"]
        assert s.context_manager_state == [
            "enter", ("exit", (None, None, None), {})]

    def test_read(self):
        """Read wrapper should work as expected..."""
        s = Mock(read=Mock(return_value=b"passes"))
        n = NodeMCU(s)
        assert n.read(6) == b"passes"

    def test_read_verbose(self):
        """When verbose channel provided, reads are echoed."""
        s = Mock(read=Mock(return_value=b"passes"))
        verb = Mock()
        n = NodeMCU(s, verb)
        assert n.read(6) == b"passes"
        verb.write.assert_called_once_with(b"passes")

    def test_read_timeout(self):
        """Make sure read fails when wrong response length received."""
        s = Mock(read=Mock(return_value=b"fails"))
        n = NodeMCU(s)
        with pytest.raises(IOError):
            n.read(6)

    def test_write(self):
        """Write wrapper should work as expected..."""
        s = Mock(write=Mock(return_value=6))
        n = NodeMCU(s)
        assert n.write(b"passes") == 6

    def test_write_timeout(self):
        """Make sure write fails when wrong response length received."""
        s = Mock(write=Mock(return_value=1))
        n = NodeMCU(s)
        with pytest.raises(IOError):
            n.write(b"fails")

    @pytest.mark.parametrize("junk",
                             [b"",
                              b"a",
                              b"foo bar baz"])
    def test_flush(self, junk):
        """Flush should read all available data."""
        s = MockSerial([junk])
        n = NodeMCU(s)

        n.flush()
        assert s.expected_sequence[0] == b""

    def test_read_line(self):
        """Line up to the line-ending should be absorbed."""
        s = MockSerial([b"ba-ba-black sheep bar baz"])
        n = NodeMCU(s)

        line = n.read_line(b"bar")

        # Ending should be stripped off
        assert line == b"ba-ba-black sheep "

        # Remainder should say in the buffer
        assert s.expected_sequence[0] == b" baz"

    @pytest.mark.parametrize("prompt", [b"", b"> "])
    @pytest.mark.parametrize("response", [b"", b"response!\r\n", b"response!"])
    def test_send_command(self, prompt, response):
        """Make sure commands are sent and the echo-back absorbed."""
        s = MockSerial([b"",           # Nothing to read in buffer
                        b"foo()\r\n",  # Command should be sent
                        (prompt +
                         b"foo()\r\n" +
                         response)])   # Echo-back and response
        n = NodeMCU(s)

        n.send_command(b"foo()")

        # Should have sent the command as expected
        assert len(s.expected_sequence) == 1

        # Should have read in the echo-back but left the response
        assert s.expected_sequence[0] == response

    def test_get_version(self):
        """Make sure versions are correctly decoded."""
        s = MockSerial([b"",                       # Nothing to read in buffer
                        b"=node.info()\r\n",       # Command should be sent
                        b"=node.info()\r\n"        # Echo-back and response
                        b"1\t4\t1234\t4321\r\n"])  # Node info
        n = NodeMCU(s)

        major, minor = n.get_version()

        assert major == 1
        assert minor == 4

        assert s.finished

    def test_write_file_unopenable(self):
        """Files which can't be opened for write cause an error."""
        s = MockSerial([b"",
                        # Close existing file
                        b"file.close()\r\n",
                        b"file.close()\r\n",
                        # Open file
                        b"=file.open('test.txt', 'w')\r\n",
                        b"=file.open('test.txt', 'w')\r\nnil\r\n"])
        n = NodeMCU(s)

        with pytest.raises(IOError):
            n.write_file("test.txt", b"1234")

        assert s.finished

    def test_write_file_unwriteable(self):
        """Files which can't be be written to cause an error."""
        s = MockSerial([b"",
                        # Close existing file
                        b"file.close()\r\n",
                        b"file.close()\r\n",
                        # Open file
                        b"=file.open('test.txt', 'w')\r\n",
                        b"=file.open('test.txt', 'w')\r\ntrue\r\n",
                        # Write fails
                        b"=file.write('1234')\r\n",
                        b"=file.write('1234')\r\nnil\r\n"])
        n = NodeMCU(s)

        with pytest.raises(IOError):
            n.write_file("test.txt", b"1234")

        assert s.finished

    def test_write_file(self):
        """Writing should succeed in blocks of some predetermined size."""
        s = MockSerial([b"",
                        # Close existing file
                        b"file.close()\r\n",
                        b"file.close()\r\n",
                        # Open file
                        b"=file.open('test.txt', 'w')\r\n",
                        b"=file.open('test.txt', 'w')\r\ntrue\r\n",
                        # Write part 1
                        b"=file.write('12')\r\n",
                        b"=file.write('12')\r\ntrue\r\n",
                        # Write part 2
                        b"=file.write('3')\r\n",
                        b"=file.write('3')\r\ntrue\r\n",
                        # Close file
                        b"file.close()\r\n",
                        b"file.close()\r\n"])
        n = NodeMCU(s)

        # Write two bytes at a time
        n.write_file("test.txt", b"123", 2)

        assert s.finished

    def test_read_file_not_exists(self):
        """Files which can't be opened for read cause an error."""
        s = MockSerial([b"",
                        # Close existing file
                        b"file.close()\r\n",
                        b"file.close()\r\n",
                        # Check for existance of the file
                        b"=file.list()['test.txt']\r\n",
                        b"=file.list()['test.txt']\r\nnil\r\n"])
        n = NodeMCU(s)

        with pytest.raises(IOError):
            n.read_file("test.txt")

        assert s.finished

    def test_read_file_not_openable(self):
        """Files which can't be opened for read cause an error."""
        s = MockSerial([b"",
                        # Close existing file
                        b"file.close()\r\n",
                        b"file.close()\r\n",
                        # Check for existance of the file
                        b"=file.list()['test.txt']\r\n",
                        b"=file.list()['test.txt']\r\n123\r\n",
                        # Open the file for read
                        b"=file.open('test.txt', 'r')\r\n",
                        b"=file.open('test.txt', 'r')\r\nnil\r\n"])
        n = NodeMCU(s)

        with pytest.raises(IOError):
            n.read_file("test.txt")

        assert s.finished

    def test_read_file(self):
        """Reading should proceed block-by-block."""
        s = MockSerial([b"",
                        # Close existing file
                        b"file.close()\r\n",
                        b"file.close()\r\n",
                        # Check for existance of the file
                        b"=file.list()['test.txt']\r\n",
                        b"=file.list()['test.txt']\r\n3\r\n",
                        # Open the file for read
                        b"=file.open('test.txt', 'r')\r\n",
                        b"=file.open('test.txt', 'r')\r\ntrue\r\n",
                        # Read a block
                        b"uart.write(0, file.read(2))\r\n",
                        b"uart.write(0, file.read(2))\r\n\x01\x02",
                        # Read last block
                        b"uart.write(0, file.read(1))\r\n",
                        b"uart.write(0, file.read(1))\r\n\x03",
                        # Close the file
                        b"file.close()\r\n",
                        b"file.close()\r\n"])
        n = NodeMCU(s)

        assert n.read_file("test.txt", 2) == b"\x01\x02\x03"

        assert s.finished

    """Lua snippet used to count the number of files in flash."""
    COUNT_FILES_SNIPPET = (b"do"
                           b"    local cnt = 0;"
                           b"    for k, v in pairs(file.list()) do"
                           b"        cnt = cnt + 1;"
                           b"    end;"
                           b"    print(cnt);"
                           b"end")

    """Lua snippet used to list all file names and sizes."""
    LIST_FILES_SNIPPET = (b"for f,s in pairs(file.list()) do"
                          b"    print(#f);"
                          b"    uart.write(0, f);"
                          b"    print(s);"
                          b"end")

    def test_list_files_with_no_files(self):
        """Special case: list files when none present"""

        s = MockSerial([b"",
                        # Get file count
                        self.COUNT_FILES_SNIPPET + b"\r\n",
                        self.COUNT_FILES_SNIPPET + b"\r\n0\r\n",
                        # Enumerate file info
                        self.LIST_FILES_SNIPPET + b"\r\n",
                        self.LIST_FILES_SNIPPET + b"\r\n"])
        n = NodeMCU(s)

        assert n.list_files() == {}

        assert s.finished

    def test_list_files(self):
        """Should send a suitable file-listing command."""

        s = MockSerial([b"",
                        # Get file count
                        self.COUNT_FILES_SNIPPET + b"\r\n",
                        self.COUNT_FILES_SNIPPET + b"\r\n2\r\n",
                        # Enumerate file info
                        self.LIST_FILES_SNIPPET + b"\r\n",
                        self.LIST_FILES_SNIPPET + b"\r\n" +
                        b"7\r\nfoo.txt123\r\n"
                        b"5\r\n\t.tab0\r\n"])
        n = NodeMCU(s)

        assert n.list_files() == {
            "foo.txt": 123,
            "\t.tab": 0,
        }

        assert s.finished

    def test_remove_file_no_file(self):
        """Make sure a file which doesn't exist doesn't get removed."""

        s = MockSerial([b"",
                        # Check file existance
                        b"=file.list()['test.txt']\r\n",
                        b"=file.list()['test.txt']\r\nnil\r\n"])
        n = NodeMCU(s)

        with pytest.raises(IOError):
            n.remove_file("test.txt")

        assert s.finished

    def test_remove_file(self):
        """Remove file should work."""

        s = MockSerial([b"",
                        # Check file existance
                        b"=file.list()['test.txt']\r\n",
                        b"=file.list()['test.txt']\r\n123\r\n",
                        # Remove file
                        b"file.remove('test.txt')\r\n",
                        b"file.remove('test.txt')\r\n"])
        n = NodeMCU(s)

        n.remove_file("test.txt")

        assert s.finished

    def test_rename_file_fails(self):
        """Remove file can fail."""

        s = MockSerial([b"",
                        # Rename
                        b"=file.rename('old.txt', 'new.txt')\r\n",
                        b"=file.rename('old.txt', 'new.txt')\r\nnil\r\n"])
        n = NodeMCU(s)

        with pytest.raises(IOError):
            n.rename_file("old.txt", "new.txt")

        assert s.finished

    def test_rename_file(self):
        """Remove file should work."""

        s = MockSerial([b"",
                        # Rename
                        b"=file.rename('old.txt', 'new.txt')\r\n",
                        b"=file.rename('old.txt', 'new.txt')\r\ntrue\r\n"])
        n = NodeMCU(s)

        n.rename_file("old.txt", "new.txt")

        assert s.finished

    def test_format(self):
        """Format should just work..."""

        s = MockSerial([b"",
                        b"file.format()\r\n",
                        b"file.format()\r\n"])
        n = NodeMCU(s)

        n.format()

        assert s.finished

    def test_dofile_no_file(self):
        """If no file, dofile should fail."""

        s = MockSerial([b"",
                        # Check existance
                        b"=file.list()['test.lua']\r\n",
                        b"=file.list()['test.lua']\r\nnil\r\n"])
        n = NodeMCU(s)

        with pytest.raises(IOError):
            n.dofile("test.lua")

        assert s.finished

    def test_dofile(self):
        """Dofile should return command's output."""

        s = MockSerial([b"",
                        # Check existance
                        b"=file.list()['test.lua']\r\n",
                        b"=file.list()['test.lua']\r\n123\r\n",
                        # Execute and await prompt
                        b"dofile('test.lua')\r\n",
                        b"dofile('test.lua')\r\nhello!\r\n> "])
        n = NodeMCU(s)

        assert n.dofile("test.lua") == b"hello!\r\n"

        assert s.finished

    def test_restart(self):
        """Should be able to restart, absorbing any garbage."""

        s = MockSerial([b"",
                        # Send restart command, get echoback, a prompt and
                        # some garbage
                        b"node.restart()\r\n",
                        (b"node.restart()\r\n"
                         b"> "
                         b"\xDE\xAD\xBE\xEF\xFF"  # Garbage
                         b"\r\n\r\n"
                         b"NodeMCU [some version]\r\n"  # Banner
                         b"        some info: here\r\n"
                         b" build built on: 1990-12-11 19:56\r\n"
                         b" powered by Lua 5.1.4 on SDK 1.4.0\r\n"
                         b"> ")])
        n = NodeMCU(s)

        n.restart()

        assert s.finished


class TestCLI(object):
    """Test the command-line interface."""

    @pytest.fixture
    def serial(self, monkeypatch):
        """When used, the serial port will be mocked out."""
        import serial

        def exit(self, type, value, tb):
            if isinstance(value, Exception):
                raise
        mock = Mock(__enter__=Mock(), __exit__=exit)
        mock.return_value = mock
        monkeypatch.setattr(serial, "Serial", mock)
        return mock

    @pytest.fixture
    def mock_version_response(self, monkeypatch):
        """When used, the NodeMCU will successfuly run a .get_version()."""
        monkeypatch.setattr(NodeMCU, "get_version", Mock(return_value=(1, 4)))

    @pytest.fixture
    def mock_format_response(self, monkeypatch, mock_version_response):
        """When used, the NodeMCU will successfuly run a .format()."""
        monkeypatch.setattr(NodeMCU, "format", Mock())

    @pytest.fixture
    def serial_ports(self, monkeypatch):
        """When used, the serial library will find two serial ports."""
        ports = [
            ("/dev/ttyS0", "n/a", "n/a"),
            ("/dev/ttyUSB5", "n/a", "n/a"),
        ]

        import serial.tools.list_ports
        comports = Mock(return_value=ports)
        monkeypatch.setattr(serial.tools.list_ports, "comports", comports)

        return ports

    @pytest.fixture
    def no_serial_ports(self, monkeypatch):
        """When used, the serial library will not find any valid com ports."""
        import serial.tools.list_ports
        comports = Mock(return_value=[])
        monkeypatch.setattr(serial.tools.list_ports, "comports", comports)

        return []

    @pytest.mark.parametrize("args",
                             ["",  # No arguments
                              # Multiple actions at once
                              "--restart --format",
                              # Missing argument
                              "--write",
                              "--read",
                              "--delete",
                              "--move",
                              "--move old.txt",
                              "--dofile",
                              # Too many arguments
                              "--write foo bar",
                              "--read foo bar",
                              "--list foo",
                              "--delete foo bar",
                              "--move foo bar baz",
                              "--format foo",
                              "--dofile foo bar",
                              "--restart foo",
                              # Baudrate not an integer...
                              "--baudrate abc"])
    def test_bad_arguments(self, args, serial_ports, serial):
        """Make sure various obvious bad arguments make the parser crash."""
        with pytest.raises(SystemExit):
            main(args.split())

    def test_no_ports_available(self, no_serial_ports, serial):
        """If no ports are available and none are specified, everything should
        fail."""
        with pytest.raises(SystemExit):
            main("--list".split())

    def test_manual_port(self, no_serial_ports, serial, mock_format_response):
        """If no ports are available specifying a port will fix things."""
        main("--port /dev/null --format".split())
        serial.assert_called_once_with("/dev/null", 9600, timeout=2.0)

    def test_manual_port_overrides(self, serial_ports, serial,
                                   mock_format_response):
        """Specifying a port should override the default one."""
        main("--port /dev/null --format".split())
        serial.assert_called_once_with("/dev/null", 9600, timeout=2.0)

    def test_sensible_port(self, serial_ports, serial, mock_format_response):
        """If several ports are available, select /dev/ttyUSB* by preference.
        """
        main("--format".split())
        serial.assert_called_once_with("/dev/ttyUSB5", 9600, timeout=2.0)

    def test_manual_baudrate(self, serial_ports, serial, mock_format_response):
        """Baudrate should be overrideable."""
        main("--baudrate 115200 --format".split())
        serial.assert_called_once_with("/dev/ttyUSB5", 115200, timeout=2.0)

    @pytest.mark.parametrize("version", [(0, 0), (1, 3), (2, 0), (2, 5)])
    def test_bad_version(self, serial_ports, serial, monkeypatch, version):
        """Incompatible versions should fail."""
        monkeypatch.setattr(NodeMCU, "get_version", Mock(return_value=version))
        with pytest.raises(ValueError):
            main("--format".split())

    def test_write(self, serial_ports, serial, monkeypatch,
                   mock_version_response):
        """Writes should be passed through."""
        import sys

        # Mock stdin
        stdin = Mock(read=Mock(return_value=b"foo"))
        stdin.return_value = stdin
        stdin.buffer = stdin
        monkeypatch.setattr(sys, "stdin", stdin)

        write_file = Mock()
        monkeypatch.setattr(NodeMCU, "write_file", write_file)
        assert main("--write foo.txt".split()) == 0
        write_file.assert_called_once_with("foo.txt", b"foo")

    def test_read(self, serial_ports, serial, monkeypatch,
                  mock_version_response, capfd):
        """Reads should be passed through."""
        read_file = Mock(return_value=b"foo")
        monkeypatch.setattr(NodeMCU, "read_file", read_file)
        assert main("--read foo.txt".split()) == 0
        read_file.assert_called_once_with("foo.txt")

        out, err = capfd.readouterr()
        assert out == "foo"  # XXX: capfd always gives a string...

    def test_list(self, serial_ports, serial, monkeypatch,
                  mock_version_response, capsys):
        """File listings should be formatted nicely."""
        files = {
            "a.txt": 123,
            "bb.txt": 321,
        }
        monkeypatch.setattr(NodeMCU, "list_files", Mock(return_value=files))
        assert main("--list".split()) == 0

        # NB: Aligned columns
        out, err = capsys.readouterr()
        assert out in (
            "Total: 2 files, 444 bytes.\na.txt   123\nbb.txt  321\n",
            "Total: 2 files, 444 bytes.\nbb.txt  321\na.txt   123\n",
        )

    def test_list_singletons(self, serial_ports, serial, monkeypatch,
                             mock_version_response, capsys):
        """Grammar should be correct..."""
        files = {
            "a.txt": 1,
        }
        monkeypatch.setattr(NodeMCU, "list_files", Mock(return_value=files))
        assert main("--list".split()) == 0

        # NB: Aligned columns
        out, err = capsys.readouterr()
        assert out == "Total: 1 file, 1 byte.\na.txt  1\n"

    def test_list_empty(self, serial_ports, serial, monkeypatch,
                        mock_version_response, capsys):
        """Special case shouldn't break."""
        monkeypatch.setattr(NodeMCU, "list_files", Mock(return_value={}))
        assert main("--list".split()) == 0

        # NB: Aligned columns
        out, err = capsys.readouterr()
        assert out == "Total: 0 files, 0 bytes.\n"

    def test_delete(self, serial_ports, serial, monkeypatch,
                    mock_version_response):
        """Should pass the call through."""
        remove_file = Mock()
        monkeypatch.setattr(NodeMCU, "remove_file", remove_file)
        assert main("--delete foo.txt".split()) == 0
        remove_file.assert_called_once_with("foo.txt")

    def test_move(self, serial_ports, serial, monkeypatch,
                  mock_version_response):
        """Should pass the call through."""
        rename_file = Mock()
        monkeypatch.setattr(NodeMCU, "rename_file", rename_file)
        assert main("--rename foo.txt bar.txt".split()) == 0
        rename_file.assert_called_once_with("foo.txt", "bar.txt")

    def test_format(self, serial_ports, serial, monkeypatch,
                    mock_version_response):
        """Should pass the call through."""
        format = Mock()
        monkeypatch.setattr(NodeMCU, "format", format)
        assert main("--format".split()) == 0
        format.assert_called_once_with()

    def test_dofile(self, serial_ports, serial, monkeypatch,
                    mock_version_response, capfd):
        """Dofile should run and the output printed."""
        dofile = Mock(return_value=b"hello, there!\r\n")
        monkeypatch.setattr(NodeMCU, "dofile", dofile)
        assert main("--dofile foo.lua".split()) == 0
        dofile.assert_called_once_with("foo.lua")

        out, err = capfd.readouterr()
        assert out == "hello, there!\r\n"  # XXX: capfd always gives a string

    def test_restart(self, serial_ports, serial, monkeypatch,
                     mock_version_response):
        """Should pass the call through."""
        restart = Mock()
        monkeypatch.setattr(NodeMCU, "restart", restart)
        assert main("--restart".split()) == 0
        restart.assert_called_once_with()
