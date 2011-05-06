#! /usr/bin/env python
#import demandimport
#demandimport.enable()
import sys
import os
import getopt
import traceback

import bento

from bento.compat.api \
    import \
        relpath

from bento.core.utils import \
        pprint
from bento.core.parser.api import \
        ParseError
from bento._config import \
        BENTO_SCRIPT, BUILD_DIR, DB_FILE
import bento.core.node

from bento.commands.api \
    import \
        HelpCommand, ConfigureCommand, BuildCommand, InstallCommand, \
        ParseCommand, ConvertCommand, SdistCommand, DetectTypeCommand, \
        BuildPkgInfoCommand, BuildEggCommand, BuildWininstCommand, \
        DistCheckCommand, COMMANDS_REGISTRY, ConvertionError, UsageException, \
        CommandExecutionFailure
from bento.commands.dependency \
    import \
        CommandScheduler, CommandDataProvider
from bento.commands.options \
    import \
        OptionsRegistry, OptionsContext

from bento.commands.hooks \
    import \
        get_pre_hooks, get_post_hooks, get_command_override, create_hook_module
from bento.commands.context \
    import \
        CmdContext, BuildYakuContext, ConfigureYakuContext, CONTEXT_REGISTRY, \
        HelpContext, GlobalContext
import bento.core.errors

from bentomakerlib.package_cache \
    import \
        CachedPackage

if os.environ.get("BENTOMAKER_DEBUG", "0") != "0":
    BENTOMAKER_DEBUG = True
else:
    BENTOMAKER_DEBUG = False

SCRIPT_NAME = 'bentomaker'

CMD_SCHEDULER = CommandScheduler()
CMD_SCHEDULER.set_before("build", "configure")
CMD_SCHEDULER.set_before("build_egg", "build")
CMD_SCHEDULER.set_before("build_wininst", "build")
CMD_SCHEDULER.set_before("install", "build")

CMD_DATA_DUMP = os.path.join(BUILD_DIR, "cmd_data.db")
CMD_DATA_STORE = CommandDataProvider.from_file(CMD_DATA_DUMP)

OPTIONS_REGISTRY = OptionsRegistry()

__CACHED_PACKAGE = None
def _set_cached_package(node):
    global __CACHED_PACKAGE
    if __CACHED_PACKAGE is not None:
        raise ValueError("Global cached package already set !")
    else:
        __CACHED_PACKAGE = CachedPackage(node)
        return __CACHED_PACKAGE

def _get_cached_package():
    global __CACHED_PACKAGE
    if __CACHED_PACKAGE is None:
        raise ValueError("Global cached package not set yet !")
    else:
        return __CACHED_PACKAGE

__PACKAGE_OPTIONS = None
def __get_package_options():
    global __PACKAGE_OPTIONS
    if __PACKAGE_OPTIONS:
        return __PACKAGE_OPTIONS
    else:
        __PACKAGE_OPTIONS = _get_cached_package().get_options(BENTO_SCRIPT)
        return __PACKAGE_OPTIONS

#================================
#   Create the command line UI
#================================
def register_commands():
    COMMANDS_REGISTRY.register_command("help", HelpCommand)
    COMMANDS_REGISTRY.register_command("configure", ConfigureCommand)
    COMMANDS_REGISTRY.register_command("build", BuildCommand)
    COMMANDS_REGISTRY.register_command("install", InstallCommand)
    COMMANDS_REGISTRY.register_command("convert", ConvertCommand)
    COMMANDS_REGISTRY.register_command("sdist", SdistCommand)
    COMMANDS_REGISTRY.register_command("build_egg", BuildEggCommand)
    COMMANDS_REGISTRY.register_command("build_wininst", BuildWininstCommand)
    COMMANDS_REGISTRY.register_command("distcheck", DistCheckCommand)

    COMMANDS_REGISTRY.register_command("build_pkg_info", BuildPkgInfoCommand, public=False)
    COMMANDS_REGISTRY.register_command("parse", ParseCommand, public=False)
    COMMANDS_REGISTRY.register_command("detect_type", DetectTypeCommand, public=False)
 
    if sys.platform == "darwin":
        import bento.commands.build_mpkg
        COMMANDS_REGISTRY.register_command("build_mpkg",
            bento.commands.build_mpkg.BuildMpkgCommand)
        CMD_SCHEDULER.set_before("build_mpkg", "build")

def register_options(cmd_name):
    cmd_klass = COMMANDS_REGISTRY.get_command(cmd_name)
    usage = cmd_klass.long_descr.splitlines()[1]
    context = OptionsContext.from_command(cmd_klass, usage=usage)
    OPTIONS_REGISTRY.register_command(cmd_name, context)

def register_command_contexts():
    CONTEXT_REGISTRY.set_default(CmdContext)
    if not CONTEXT_REGISTRY.is_registered("configure"):
        CONTEXT_REGISTRY.register("configure", ConfigureYakuContext)
    if not CONTEXT_REGISTRY.is_registered("build"):
        CONTEXT_REGISTRY.register("build", BuildYakuContext)
    if not CONTEXT_REGISTRY.is_registered("help"):
        CONTEXT_REGISTRY.register("help", HelpContext)

# All the global state/registration stuff goes here
def register_stuff():
    register_commands()
    for cmd_name in COMMANDS_REGISTRY.get_command_names():
        register_options(cmd_name)
    register_command_contexts()

def set_main(top_node):
    # Some commands work without a bento description file (convert, help)
    if not os.path.exists(BENTO_SCRIPT):
        return []

    _set_cached_package(top_node.bldnode.make_node(DB_FILE))

    pkg = _get_cached_package().get_package(BENTO_SCRIPT)
    #create_package_description(BENTO_SCRIPT)

    modules = []
    for f in pkg.hook_files:
        main_file = os.path.abspath(f)
        if not os.path.exists(main_file):
            raise ValueError("Hook file %s not found" % main_file)
        modules.append(create_hook_module(f))
    return modules

def main(argv=None):
    if hasattr(os, "getuid"):
        if os.getuid() == 0:
            pprint("RED", "Using bentomaker under root/sudo is *strongly* discouraged - do you want to continue ? y/N")
            ans = raw_input()
            if not ans.lower() in ["y", "yes"]:
                raise UsageException("bentomaker execution canceld (not using bentomaker with admin privileges)")

    if argv is None:
        argv = sys.argv[1:]
    popts = parse_global_options(argv)
    cmd_name = popts["cmd_name"]

    # FIXME: top_node vs srcnode
    source_root = os.getcwd()
    build_root = os.path.join(os.getcwd(), "build")

    root = bento.core.node.create_root_with_source_tree(source_root, build_root)
    top_node = root.srcnode

    if cmd_name and cmd_name not in ["convert"] or not cmd_name:
        _wrapped_main(popts, top_node)
    else:
        register_stuff()
        _main(popts, top_node)

def _wrapped_main(popts, top_node):
    def _big_ugly_hack():
        # FIXME: huge ugly hack - we need to specify once and for all when the
        # package info is parsed and available, so that we can define options
        # and co for commands
        from bento.commands.configure import _setup_options_parser
        # FIXME: logic to handle codepaths which work without a bento.info
        # should be put in one place
        if os.path.exists(BENTO_SCRIPT):
            package_options = __get_package_options()
            _setup_options_parser(OPTIONS_REGISTRY.get_options("configure"), package_options)
        else:
            import warnings
            warnings.warn("No %r file in current directory - not all options "
                          "will be displayed" % BENTO_SCRIPT)
            return

    global_context = GlobalContext(COMMANDS_REGISTRY, CONTEXT_REGISTRY,
                                   OPTIONS_REGISTRY, CMD_SCHEDULER)
    mods = set_main(top_node)
    for mod in mods:
        mod.startup(global_context)

    register_stuff()
    _big_ugly_hack()

    # FIXME: this registered options for new commands registered in hook. It
    # should be made all in one place (hook and non-hook)
    for cmd_name in COMMANDS_REGISTRY.get_command_names():
        if not OPTIONS_REGISTRY.is_registered(cmd_name):
            register_options(cmd_name)

    try:
        return _main(popts, top_node)
    finally:
        for mod in mods:
            mod.shutdown()

def parse_global_options(argv):
    ret = {"cmd_name": None, "cmd_opts": None,
           "show_version": False, "show_full_version": False,
           "show_usage": False}

    try:
        opts, pargs = getopt.getopt(argv, "hv", ["help", "version", "full-version"])
        for opt, arg in opts:
            if opt in ("--help", "-h"):
                ret["show_usage"] = True
            if opt in ("--version", "-v"):
                ret["show_version"] = True
            if opt in ("--full-version"):
                ret["show_full_version"] = True

        if len(pargs) > 0:
            ret["cmd_name"] = pargs.pop(0)
            ret["cmd_opts"] = pargs
    except getopt.GetoptError, e:
        emsg = "%s: illegal global option: %r" % (SCRIPT_NAME, e.opt)
        raise UsageException(emsg)

    return ret

def _main(popts, top):
    if popts["show_version"]:
        print bento.__version__
        return 0

    if popts["show_full_version"]:
        print bento.__version__ + "git" + bento.__git_revision__
        return 0

    if popts["show_usage"]:
        cmd = COMMANDS_REGISTRY.get_command('help')()
        cmd.run(CmdContext([], OPTIONS_REGISTRY.get_options('help'), None, None))
        return 0

    cmd_name = popts["cmd_name"]
    cmd_opts = popts["cmd_opts"]

    if not cmd_name:
        print "Type '%s help' for usage." % SCRIPT_NAME
        return 1
    else:
        if not cmd_name in COMMANDS_REGISTRY.get_command_names():
            raise UsageException("%s: Error: unknown command %s" % (SCRIPT_NAME, cmd_name))
        else:
            run_cmd(cmd_name, cmd_opts, top)

def _get_package_with_user_flags(cmd_name, cmd_opts, package_options):
    from bento.commands.configure import _get_flag_values

    p = OPTIONS_REGISTRY.get_options(cmd_name)
    o, a = p.parser.parse_args(cmd_opts)
    flag_values = _get_flag_values(package_options.flag_options.keys(), o)

    return _get_cached_package().get_package(BENTO_SCRIPT, flag_values)

def _get_subpackage(pkg, top, local_node):
    rpath = local_node.path_from(top)
    k = os.path.join(rpath, "bento.info")
    if local_node == top:
        return pkg
    else:
        if k in pkg.subpackages:
            return pkg.subpackages[k]
        else:
            return None

def run_dependencies(cmd_name, top, pkg):
    deps = CMD_SCHEDULER.order(cmd_name)
    for cmd_name in deps:
        cmd_klass = COMMANDS_REGISTRY.get_command(cmd_name)
        cmd_argv = CMD_DATA_STORE.get_argv(cmd_name)
        ctx_klass = CONTEXT_REGISTRY.get(cmd_name)
        run_cmd_in_context(cmd_klass, cmd_name, cmd_argv, ctx_klass, top, pkg)

def is_help_only(cmd_name, cmd_argv):
    p = OPTIONS_REGISTRY.get_options(cmd_name)
    o, a = p.parser.parse_args(cmd_argv)
    return o.help is True

def run_cmd(cmd_name, cmd_opts, top):
    cmd_klass = COMMANDS_REGISTRY.get_command(cmd_name)

    # XXX: fix this special casing (commands which do not need a pkg instance)
    if cmd_name in ["help", "convert"]:
        cmd = cmd_klass()
        options_ctx = OPTIONS_REGISTRY.get_options(cmd_name)
        ctx_klass = CONTEXT_REGISTRY.get(cmd_name)
        ctx = ctx_klass(cmd_opts, options_ctx, None, top)
        # XXX: hack for help command to get option context for any command
        # without making help depends on bentomakerlib
        ctx.options_registry = OPTIONS_REGISTRY
        cmd.run(ctx)
        return

    if not os.path.exists(BENTO_SCRIPT):
        raise UsageException("Error: no %s found !" % BENTO_SCRIPT)

    package_options = __get_package_options()
    pkg = _get_package_with_user_flags(cmd_name, cmd_opts, package_options)
    if is_help_only(cmd_name, cmd_opts):
        ctx_klass = CONTEXT_REGISTRY.get(cmd_name)
        run_cmd_in_context(cmd_klass, cmd_name, cmd_opts, ctx_klass, top, pkg)
    else:
        run_dependencies(cmd_name, top, pkg)

        ctx_klass = CONTEXT_REGISTRY.get(cmd_name)
        run_cmd_in_context(cmd_klass, cmd_name, cmd_opts, ctx_klass, top, pkg)

        CMD_DATA_STORE.set(cmd_name, cmd_opts)
        CMD_DATA_STORE.store(CMD_DATA_DUMP)

def run_cmd_in_context(cmd_klass, cmd_name, cmd_opts, ctx_klass, top, pkg):
    """Run the given Command instance inside its context, including any hook
    and/or override."""
    cmd = cmd_klass()
    options_ctx = OPTIONS_REGISTRY.get_options(cmd_name)
    ctx = ctx_klass(cmd_opts, options_ctx, pkg, top)
    # FIXME: hack to pass package_options to configure command - most likely
    # this needs to be known in option context ?
    ctx.package_options = __get_package_options()
    if get_command_override(cmd_name):
        cmd_funcs = get_command_override(cmd_name)
    else:
        cmd_funcs = [(cmd.run, top.abspath())]

    try:
        def _run_hooks(hook_iter):
            for hook, local_dir, help_bypass in hook_iter:
                local_node = top.find_dir(relpath(local_dir, top.abspath()))
                ctx.pre_recurse(local_node)
                try:
                    if not ctx.help and help_bypass:
                        hook(ctx)
                finally:
                    ctx.post_recurse()

        _run_hooks(get_pre_hooks(cmd_name))

        while cmd_funcs:
            cmd_func, local_dir = cmd_funcs.pop(0)
            local_node = top.find_dir(relpath(local_dir, top.abspath()))
            ctx.pre_recurse(local_node)
            try:
                cmd_func(ctx)
            finally:
                ctx.post_recurse()

        _run_hooks(get_post_hooks(cmd_name))

        cmd.shutdown(ctx)
    finally:
        ctx.shutdown()

def noexc_main(argv=None):
    def _print_debug():
        if BENTOMAKER_DEBUG:
            tb = sys.exc_info()[2]
            traceback.print_tb(tb)
    try:
        ret = main(argv)
    except UsageException, e:
        _print_debug()
        pprint('RED', e)
        sys.exit(1)
    except ParseError, e:
        _print_debug()
        pprint('RED', str(e))
        sys.exit(2)
    except ConvertionError, e:
        _print_debug()
        pprint('RED', "".join(e.args))
        sys.exit(3)
    except CommandExecutionFailure, e:
        _print_debug()
        pprint('RED', "".join(e.args))
        sys.exit(4)
    except bento.core.errors.BuildError, e:
        _print_debug()
        pprint('RED', e)
        sys.exit(8)
    except bento.core.errors.InvalidPackage, e:
        _print_debug()
        pprint('RED', e)
        sys.exit(16)
    except Exception, e:
        msg = """\
%s: Error: %s crashed (uncaught exception %s: %s).
Please report this on bento issue tracker:
    http://github.com/cournape/bento/issues"""
        if not BENTOMAKER_DEBUG:
            msg += "\nYou can get a full traceback by setting BENTOMAKER_DEBUG=1"
        else:
            _print_debug()
        pprint('RED',  msg % (SCRIPT_NAME, SCRIPT_NAME, e.__class__, str(e)))
        sys.exit(1)
    sys.exit(ret)

if __name__ == '__main__':
    noexc_main()
