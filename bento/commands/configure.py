import sys
import os

try:
    from cPickle import loads, dumps
except ImportError:
    from pickle import loads, dumps

from bento.core.utils import \
        pprint
from bento.core.platforms import \
        get_scheme
from bento.core import \
        PackageOptions, PackageDescription
from bento._config \
    import \
        CONFIGURED_STATE_DUMP, TOYDIST_SCRIPT

from bento.commands.core import \
        Command, SCRIPT_NAME, Option
from bento.commands.errors \
    import \
        UsageException

class ConfigureState(object):
    def __init__(self, filename, pkg, paths=None, flags=None):
        self.filename = filename
        self.pkg = pkg

        if flags is None:
            self.flags = {}
        else:
            self.flags = flags

        if paths is None:
            self.paths = {}
        else:
            self.paths = paths

    def dump(self, filename=CONFIGURED_STATE_DUMP):
        # Write into tmp file and atomtically rename the file to avoid
        # corruption
        f = open(filename + ".tmp", 'wb')
        try:
            s = dumps(self)
            f.write(s)
        finally:
            f.close()

        os.rename(filename + ".tmp", filename)

    @classmethod
    def from_dump(cls, filename=CONFIGURED_STATE_DUMP):
        f = open(filename, 'rb')
        try:
            s = f.read()
            return loads(s)
        finally:
            f.close()

def set_scheme_options(scheme, options):
    """Set path variables given in options in scheme dictionary."""
    for k in scheme:
        if hasattr(options, k):
            val = getattr(options, k)
            if val:
                scheme[k] = val
    # XXX: define default somewhere and stick with it
    if options.prefix is not None and options.exec_prefix is None:
        scheme["eprefix"] = scheme["prefix"]

def set_flag_options(flag_opts, options):
    """Set flag variables given in options in flag dictionary."""
    # FIXME: fix this mess
    flag_vals = {}
    for k in flag_opts:
        opt_name = "with_" + k
        if hasattr(options, opt_name):
            val = getattr(options, opt_name)
            if val:
                if val == "true":
                    flag_vals[k] = True
                elif val == "false":
                    flag_vals[k] = False
                else:
                    msg = """Error: %s: option %s expects a true or false argument"""
                    raise UsageException(msg % (SCRIPT_NAME, "--with-%s" % k))

    return flag_vals

class ConfigureCommand(Command):
    long_descr = """\
Purpose: configure the project
Usage: toymaker configure [OPTIONS]"""
    short_descr = "configure the project."
    opts = [Option('-h', '--help',
                   help="Show package-specific configuration options",
                   action="store_true")]
    def run(self, opts):

        # We need to obtain the package description ASAP, as we need to parse
        # it to get the options (i.e. we cannot use the option handling mechanism).
        filename = TOYDIST_SCRIPT
        if not os.path.exists(filename):
            msg = "%s: Error: No %s found" % (SCRIPT_NAME, TOYDIST_SCRIPT)
            msg += "\nTry: %s help configure" % SCRIPT_NAME
            raise UsageException(msg)

        pkg_opts = PackageOptions.from_file(filename)

        # As the configure command line handling is customized from
        # the script file (flags, paths variables), we cannot just
        # call set_options_parser, and we set it up manually instead
        self.reset_parser()
        for opt in self.opts:
            self.parser.add_option(opt)
        scheme, flag_opts = self.add_configuration_options(pkg_opts)

        o, a = self.parser.parse_args(opts)
        if o.help:
            self.parser.print_help()
            return

        set_scheme_options(scheme, o)
        flag_vals = set_flag_options(flag_opts, o)

        # Cache the built package description to avoid reparsing it for
        # subsequent commands
        pkg = PackageDescription.from_file(filename, flag_vals)

        s = ConfigureState(filename, pkg, scheme, flag_vals)
        s.dump()

    def add_configuration_options(self, pkg_opts):
        """Add the path and flags-related options as defined in the
        script file to the command."""
        scheme, scheme_opts_d = get_scheme(sys.platform)

        scheme_opts = {}
        for name, opt_d in scheme_opts_d.items():
            kw = {"help": opt_d["help"]}
            opt = Option(*opt_d["opts"], **kw)
            scheme_opts[name] = opt

        # XXX: abstract away those, as it is copied from distutils
        py_version = sys.version.split()[0]
        scheme['py_version_short'] = py_version[0:3]

        scheme['pkgname'] = pkg_opts.name

        # Add path options to the path scheme
        for name, f in pkg_opts.path_options.items():
            scheme[name] = f.default_value
            scheme_opts[name] = \
                Option('--%s' % f.name,
                       help='%s [%s]' % (f.description,
                                         f.default_value))

        install_group = self.parser.add_option_group(
                "Installation fine tuning")
        for opt in scheme_opts.values():
            self.opts.append(opt)
            install_group.add_option(opt)

        flag_opts = {}
        if pkg_opts.flag_options:
            flags_group = self.parser.add_option_group(
                    "Optional features")
        for name, v in pkg_opts.flag_options.items():
            flag_opts[name] = Option(
                    "--with-%s" % v.name,
                    help="%s [default=%s]" % (
                        v.description, v.default_value))
            self.opts.append(flag_opts[name])
            flags_group.add_option(flag_opts[name])

        return scheme, flag_opts

def get_configured_state():
    if not os.path.exists(CONFIGURED_STATE_DUMP):
        raise UsageException(
               "You need to run %s configure before building" % SCRIPT_NAME)

    s = ConfigureState.from_dump(CONFIGURED_STATE_DUMP)
    return s