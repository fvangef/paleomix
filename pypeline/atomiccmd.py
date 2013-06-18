#!/usr/bin/python
#
# Copyright (c) 2012 Mikkel Schubert <MSchubert@snm.ku.dk>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
import os
import sys
import signal
import types
import weakref
import subprocess
import collections

import pypeline.atomicpp as atomicpp
import pypeline.common.fileutils as fileutils
from pypeline.common.utilities import safe_coerce_to_tuple

_PIPES = ('IN_STDIN', 'OUT_STDOUT', 'OUT_STDERR')
_PREFIXES = ('IN_', 'TEMP_IN_', 'OUT_', 'TEMP_OUT_', 'EXEC_', 'AUX_', 'CHECK_')


# TODL:
# - Only IN_, OUT_ (w/wo TEMP_), and EXEC_ should be used during call construction
# - Refactor internals, should be possible to simplify a lot


class CmdError(RuntimeError):
    def __init__(self, msg):
        RuntimeError.__init__(self, msg)



class AtomicCmd:
    """Executes a command, only moving resulting files to the destination
    directory if the command was succesful. This helps prevent the
    accidential use of partial files in downstream analysis, and eases
    restarting of a pipeline following errors (no cleanup).

    Inividual files/paths in the command are specified using keywords (see
    the documentation for the constructor), allowing the command to be
    transparently modified to execute in a temporary directory.

    When an AtomicCmd is run(), a signal handler is installed for SIGTERM,
    which ensures that any running processes are terminated. In the absence
    of this, AtomicCmds run in terminated subprocesses can result in still
    running children after the termination of the parents."""
    PIPE = subprocess.PIPE

    def __init__(self, command, set_cwd = False, **kwargs):
        """Takes a command and a set of files.

        The command is expected to be an iterable starting with the name of an
        executable, with each item representing one string on the command line.
        Thus, the command "find /etc -name 'profile*'" might be represented as
        the list ["find", "/etc", "-name", "profile*"].

        If 'set_cwd' is True, the current working directory is set to the
        temporary directory before the command is executed. Input paths are
        automatically turned into absolute paths in this case.

        Each keyword represents a type of file, as determined by the prefix:
           IN_    -- Path to input file transformed/analysed the executable.
           OUT_   -- Path to output file generated by the executable. During
                     execution of the AtomicCmd, these paths are modified to
                     point to the temporary directory.
           EXEC_  -- Name of / path to executable. The first item in the
                     command is always one of the executables, even if not
                     specified in this manner.
           AUX_   -- Auxillery files required by the executable(s), which are
                     themselves not executable. Examples include scripts,
                     config files, data-bases, and the like.
           CHECK_ -- A callable, which upon calling carries out version checking,
                     raising an exception in the case of requirements not being
                     met. This may be used to help ensure that prerequisites are
                     met before running the command. The function is not called
                     by AtomicCmd itself.

        Note that files that are not directly invoked may be included above,
        in order to allow the specification of requirements. This could include
        required data files, or executables indirectly executed by a script.

        If the above is prefixed with "TEMP_", the files are read from / written
        to the temporary folder in which the command is executed. Note that all
        TEMP_OUT_ files are deleted when commit is called (if they exist), and
        only filenames (not dirname component) are allowed for TEMP_ values.

        In addition, the follow special names may be used with the above:
           STDIN_  -- Takes a filename, or an AtomicCmd, in which case the stdout
                      of that command is piped to the stdin of this instance.
           STDOUT_ -- Takes a filename, or the special value PIPE to allow
                      another AtomicCmd instance to use the output directly.
           STDERR_ -- Takes a filename.

        Each pipe can only be used once, with or without the TEMP_ prefix."""
        self._proc    = None
        self._temp    = None
        self._command = map(str, safe_coerce_to_tuple(command))
        self._handles = {}
        self._set_cwd = set_cwd
        if not self._command or not self._command[0]:
            raise ValueError("Empty command in AtomicCmd constructor")

        self._files     = self._process_arguments(id(self), self._command, kwargs)
        self._file_sets = self._build_files_map(self._command, self._files)

        # Dry-run, to catch errors early
        self._generate_call("")


    def run(self, temp):
        """Runs the given command, saving files in the specified temp folder. To
        move files to their final destination, call commit(). Note that in contexts
        where the *Cmds classes are used, this function may block."""
        if self._handles:
            raise CmdError("Calling 'run' on already running command.")
        self._temp  = temp

        # kwords for pipes are always built relative to the current directory,
        # since these are opened before (possibly) CD'ing to the temp directory.
        kwords = self._generate_filenames(self._files, root = temp)
        stdin  = self._open_pipe(kwords, "IN_STDIN" , "rb")
        stdout = self._open_pipe(kwords, "OUT_STDOUT", "wb")
        stderr = self._open_pipe(kwords, "OUT_STDERR", "wb")

        cwd  = temp if self._set_cwd else None
        temp = ""   if self._set_cwd else os.path.abspath(temp)
        call = self._generate_call(temp)
        self._proc = subprocess.Popen(call,
                                      stdin  = stdin,
                                      stdout = stdout,
                                      stderr = stderr,
                                      cwd    = cwd,
                                      preexec_fn = os.setsid,
                                      close_fds = True)

        # Allow subprocesses to be killed in case of a SIGTERM
        _add_to_killlist(self._proc)


    def ready(self):
        """Returns true if the command has been run to completion,
        regardless of wether or not an error occured."""
        return (self._proc and self._proc.poll() is not None)


    def join(self):
        """Similar to Popen.wait(), but returns the value wrapped in a list,
        and ensures that any opened handles are closed. Must be called before
        calling commit."""
        try:
            return_codes = [self._proc.wait()] if self._proc else [None]
        finally:
            # Close any implictly opened pipes
            for (mode, handle) in self._handles.values():
                if "w" in mode:
                    handle.flush()
                handle.close()
            self._handles = {}

        return return_codes


    def wait(self):
        """Equivalent to Subproces.wait. This function should only
        be used in contexts where a AtomicCmd needs to be combined
        with Subprocesses, as it does not exist for AtomicSets."""
        return self.join()[0]


    def terminate(self):
        """Sends SIGTERM to process if it is still running.
        Has no effect if the command has already finished."""
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc = None
            except OSError:
                pass # Already dead / finished process


    # Properties, returning filenames from self._file_sets
    def _property_file_sets(key): # pylint: disable=E0213
        def _get_property_files(self):
            return self._file_sets[key] # pylint: disable=W0212
        return property(_get_property_files)

    executables  = _property_file_sets("executable")
    requirements = _property_file_sets("requirements")
    input_files     = _property_file_sets("input")
    output_files    = _property_file_sets("output")
    auxiliary_files = _property_file_sets("auxiliary")
    expected_temp_files = _property_file_sets("output_fname")
    optional_temp_files = _property_file_sets("temporary_fname")


    def commit(self, temp):
        if not self.ready():
            raise CmdError("Attempting to commit command before it has completed")
        elif self._handles:
            raise CmdError("Called 'commit' before calling 'join'")
        elif not os.path.samefile(self._temp, temp):
            raise CmdError("Mismatch between previous and current temp folders: %r != %s" \
                           % (self._temp, temp))

        missing_files = self.expected_temp_files - set(os.listdir(temp))
        if missing_files:
            raise CmdError("Expected files not created: %s" % (", ".join(missing_files)))

        temp = os.path.abspath(temp)
        for (key, filename) in self._generate_filenames(self._files, temp).iteritems():
            if isinstance(filename, types.StringTypes):
                if key.startswith("OUT_"):
                    fileutils.move_file(filename, self._files[key])
                elif key.startswith("TEMP_OUT_"):
                    fileutils.try_remove(filename)

        self._proc = None
        self._temp = None


    @property
    def stdout(self):
        """Returns the 'stdout' value for the currently running process.
        If no such process has been started, or the process has finished,
        then the return value is None."""
        stdout = self._files.get("OUT_STDOUT", self._files.get("TEMP_OUT_STDOUT"))
        if self._proc and (stdout == AtomicCmd.PIPE):
            return self._proc.stdout


    def __str__(self):
        return atomicpp.pformat(self)


    def _generate_call(self, temp):
        kwords = self._generate_filenames(self._files, root = temp)

        try:
            return [(field % kwords) for field in self._command]
        except (TypeError, ValueError), error:
            raise CmdError("Error building Atomic Command:\n  Call = %s\n  Error = %s: %s" \
                           % (self._command, error.__class__.__name__, error))
        except KeyError, error:
            raise CmdError("Error building Atomic Command:\n  Call = %s\n  Value not specified for path = %s" \
                           % (self._command, error))


    @classmethod
    def _process_arguments(cls, proc_id, command, kwargs):
        cls._validate_pipes(kwargs)

        files = {}
        for (key, value) in kwargs.iteritems():
            if cls._validate_argument(key, value):
                files[key] = value

        executable = os.path.basename(command[0])
        for pipe in ("STDOUT", "STDERR"):
            if not (kwargs.get("OUT_" + pipe) or kwargs.get("TEMP_OUT_" + pipe)):
                filename = "pipe_%s_%i.%s" % (executable, proc_id, pipe.lower())
                files["TEMP_OUT_" + pipe] = filename

        output_files = collections.defaultdict(list)
        for (key, filename) in kwargs.iteritems():
            if key.startswith("TEMP_OUT_") or key.startswith("OUT_"):
                if isinstance(filename, types.StringTypes):
                    output_files[os.path.basename(filename)].append(key)

        for (filename, keys) in output_files.iteritems():
            if len(keys) > 1:
                raise ValueError("Same output filename (%s) is specified for multiple keys: %s" \
                                   % (filename, ", ".join(keys)))

        return files


    @classmethod
    def _validate_pipes(cls, kwargs):
        """Checks that no single pipe is specified multiple times, e.i. being specified
        both for a temporary and a final (outside the temp dir) file. For example,
        either IN_STDIN or TEMP_IN_STDIN must be specified, but not both."""
        if any((kwargs.get(pipe) and kwargs.get("TEMP_" + pipe)) for pipe in _PIPES):
            raise CmdError, "Pipes must be specified at most once (w/wo TEMP_)."


    @classmethod
    def _validate_argument(cls, key, value):
        if (key.rstrip("_") + "_") in _PREFIXES:
            raise ValueError("Argument key lacks name: %r" % key)
        elif not any(key.startswith(prefix) for prefix in _PREFIXES):
            raise ValueError("Command contains invalid argument (wrong prefix): '%s' -> '%s'" \
                           % (cls.__name__, key))
        elif value is None:
            # Values are allowed to be None, but such entries are skipped
            # This simplifies the use of keyword parameters with no default values.
            return False

        if key in ("OUT_STDOUT", "TEMP_OUT_STDOUT"):
            if not (isinstance(value, types.StringTypes) or (value == cls.PIPE)):
                raise TypeError("STDOUT must be a string or AtomicCmd.PIPE, not %r" % (value,))
        elif key in ("IN_STDIN", "TEMP_IN_STDIN"):
            if not isinstance(value, types.StringTypes + (AtomicCmd,)):
                raise TypeError("STDIN must be string or AtomicCmd, not %r" % (value,))
        elif key.startswith("CHECK_"):
            if not isinstance(value, collections.Callable):
                raise TypeError("CHECK must be callable, not %r" % (value,))
        elif not isinstance(value, types.StringTypes):
            raise TypeError("%s must be string, not %r" % (key, value))

        # Applies to TEMP_IN_* and TEMP_OUT_*
        if key.startswith("TEMP_") and isinstance(value, types.StringTypes) and os.path.dirname(value):
            raise ValueError("%s cannot contain directory component: %r" % (key, value))

        return True


    def _open_pipe(self, kwords, pipe, mode):
        filename = kwords.get(pipe, kwords.get("TEMP_" + pipe))
        if filename in (None, self.PIPE):
            return filename
        elif isinstance(filename, AtomicCmd):
            return filename.stdout

        handle = open(filename, mode)
        self._handles[pipe] = (mode, handle)

        return handle


    @classmethod
    def _generate_filenames(cls, files, root):
        filenames = {"TEMP_DIR" : root}
        for (key, filename) in files.iteritems():
            if isinstance(filename, types.StringTypes):
                if key.startswith("TEMP_") or key.startswith("OUT_"):
                    filename = os.path.join(root, os.path.basename(filename))
                elif not root and (key.startswith("IN_") or key.startswith("AUX_")):
                    filename = os.path.abspath(filename)
            filenames[key] = filename

        return filenames


    @classmethod
    def _build_files_map(cls, command, files):
        key_map   = {"IN"     : "input",
                     "OUT"    : "output",
                     "TEMP"   : "temporary_fname",
                     "EXEC"   : "executable",
                     "AUX"    : "auxiliary",
                     "CHECK"  : "requirements"}
        file_sets = dict((key, set()) for key in key_map.itervalues())

        file_sets["executable"].add(command[0])
        for (key, filename) in files.iteritems():
            if isinstance(filename, types.StringTypes) or key.startswith("CHECK_"):
                if key.startswith("TEMP_OUT_"):
                    file_sets["temporary_fname"].add(filename)
                elif not key.startswith("TEMP_"):
                    key = key_map[key.split("_", 1)[0]]
                    file_sets[key].add(filename)

        file_sets["temporary_fname"] = map(os.path.basename, file_sets["temporary_fname"])
        file_sets["output_fname"]    = map(os.path.basename, file_sets["output"])

        return dict(zip(file_sets.keys(), map(frozenset, file_sets.values())))



## The following ensures proper cleanup of child processes, for example in the case
## where multiprocessing.Pool.terminate() is called.
_PROCS = set()

def _cleanup_children(signum, _frame):
    for proc_ref in list(_PROCS):
        proc = proc_ref()
        if proc:
            os.killpg(proc.pid, signal.SIGTERM)
    sys.exit(-signum)

def _add_to_killlist(proc):
    if not _PROCS:
        signal.signal(signal.SIGTERM, _cleanup_children)

    _PROCS.add(weakref.ref(proc, _PROCS.remove))
