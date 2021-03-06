"""
Script to build a single-file distribution of bento. This code is
mostly taken from waf
"""
import base64
import os
import re
import sys
import glob
import optparse
import StringIO
from hashlib import md5

import os.path as op

sys.path.insert(0, op.abspath(op.join(op.dirname(__file__), os.pardir)))
try:
    import bento.core.node
    from bento.core import PackageDescription
finally:
    sys.path.pop(0)

ROOT = bento.core.node.Node("", None)

VERSION = "1"

def sfilter(path):
    f = open(path, "r")
    cnt = f.read()
    f.close()

    #cnt = process_decorators(cnt)
    #cnt = process_imports(cnt)
    #if path.endswith('Options.py') or path.endswith('Scripting.py'):
    #   cnt = cnt.replace('Utils.python_24_guard()', '')

    return (StringIO.StringIO(cnt), len(cnt), cnt)

def translate_entry_point(s):
    module, func = s.split(":", 1)
    return "import %s\n%s.%s()" % (module, module, func)

def read_config():
    import ConfigParser
    s = ConfigParser.ConfigParser()
    s.read("config.ini")

    def _parse_comma_list(s_list):
        return [i.strip() for i in s_list.split(",")]

    ret = {}
    section = "main"
    ret["script_template"] = s.get(section, "template")
    ret["script_name"] = s.get(section, "script_name")
    ret["script_pkg_root"] = s.get(section, "package_root")
    ret["script_version"] = s.get(section, "version")
    ret["script_entry_point"] = translate_entry_point(s.get(section, "entry_point"))
    try:
        ret["include_exe"] = s.getboolean(section, "include_exe")
    except ConfigParser.NoOptionError:
        ret["include_exe"] = False
    try:
        ret["include_waf"] = s.getboolean(section, "include_waf")
    except ConfigParser.NoOptionError:
        ret["include_waf"] = False

    ret["extra_files"] = []
    if ret["include_exe"]:
        ret["extra_files"].extend(_parse_comma_list(s.get("include_exe", "extra_files")))

    base_dir = s.get("waf", "base_dir")
    packages = _parse_comma_list(s.get("waf", "packages"))
    ret["waf"] = {"base_dir": base_dir, "packages": packages}
    return ret

def create_script_light(tpl, variables):
    # This is moronic...
    f = open(tpl, "r")
    try:
        cnt = f.read()
        r = {}
        for k, v in variables.items():
            r[k] = re.compile("@%s@" % k)
        lines = []
        for line in cnt.splitlines():
            for k, v in variables.items():
                v_lines = v.splitlines()
                if len(v_lines) > 1:
                    m = r[k].search(line)
                    if m:
                        indent = m.start()
                        v = "\n".join([v_lines[0]] + ["%s%s" % (" " * indent, v_line) for v_line in v_lines[1:]])
                line = r[k].sub(v, line)
            lines.append(line)
        return "\n".join(lines)
    finally:
        f.close()

def create_script(config):
    import tarfile, re

    script_name = config["script_name"]
    extra_files = config["extra_files"]
    print("Creating self-contained script %r in %s" % (script_name, os.getcwd()))
    mw = "tmp-foo-" + VERSION

    zip_type = "bz2"

    tar = tarfile.open('%s.tar.%s' % (mw, zip_type), "w:%s" % zip_type)

    # List of (source, arcname) pairs
    files = []
    nodes = []

    cwd_node = ROOT.find_node(os.getcwd())

    def list_nodes(packages, base_node=cwd_node):
        nodes = []
        for package_name in packages:
            init = os.path.join(*(package_name.split(".") + ["__init__.py"]))
            n = base_node.find_node(init)
            if n is None:
                raise IOError("init file for package %s not found (looked for %r)!" \
                              % (package_name, init))
            else:
                p = n.parent
                nodes.extend(p.find_node(f) for f in p.listdir() if f.endswith(".py"))
        return nodes

    package = PackageDescription.from_file("bento.info", user_flags={"bundle": True, "bundle_yaku": True})
    nodes.extend(list_nodes(package.packages))

    for module in package.py_modules:
        n = cwd_node.find_node(module + ".py")
        if n is None:
            raise IOError("init file for package %s not found (looked for %r)!" \
                          % (package_name, init))
        else:
            nodes.append(n)

    files.extend([(n.abspath(), n.path_from(cwd_node)) for n in nodes])

    if config["include_waf"]:
        base_dir = config["waf"]["base_dir"]
        packages = config["waf"]["packages"]
        base_node = ROOT.find_node(op.expanduser(base_dir))
        if base_node is None:
            raise ValueError("Waf base dir not found (misconfigured ?): %s" % base_dir)
        nodes = list_nodes(packages, base_node)
        files.extend([(n.abspath(), n.path_from(base_node)) for n in nodes])

    for pattern in extra_files:
        for f in glob.glob(pattern):
            files.append((f, f))

    for name, arcname in files:
        tarinfo = tar.gettarinfo(name, arcname)
        tarinfo.uid = tarinfo.gid = 1000
        tarinfo.uname = tarinfo.gname = "baka"
        (code, size, cnt) = sfilter(name)
        tarinfo.size = size
        tar.addfile(tarinfo, code)
    tar.close()

    variables = {}
    for k in ["script_name", "script_pkg_root", "script_version", "script_entry_point"]:
        variables[k] = config[k]
    variables["script_name"] = "'%s'" % variables["script_name"]
    variables["script_pkg_root"] = "'%s'" % variables["script_pkg_root"]

    code1 = create_script_light(config["script_template"], variables)

    f = open("%s.tar.%s" % (mw, zip_type), 'rb')
    cnt = f.read()
    f.close()

    m = md5()
    m.update(cnt)
    REVISION = m.hexdigest()
    reg = re.compile('^REVISION=(.*)', re.M)
    code1 = reg.sub(r'REVISION="%s"' % REVISION, code1)

    f = open(script_name, 'wb')
    #f.write(code1.replace("C1='x'", "C1='%s'" % C1).replace("C2='x'", "C2='%s'" % C2))
    f.write(code1)
    f.write('#==>\n')
    f.write('#')
    f.write(base64.b64encode(cnt))
    f.write('\n')
    f.write('#<==\n')
    f.close()

    if sys.platform != 'win32':
        from bento.utils.utils import MODE_755
        os.chmod(script_name, MODE_755)
    os.unlink('%s.tar.%s' % (mw, zip_type))

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    parser = optparse.OptionParser()
    parser.add_option("--noinclude-exe", action="store_true",
            dest="include_exe", default=False,
            help="Include windows binaries to build bdist installers")
    parser.add_option("--include-waf", action="store_true",
            dest="include_waf", default=False,
            help="Include waf")
    parser.add_option("--waf-dir", dest="waf_dir",
            help="Waf sources (if included)")
    config = read_config()

    opts, args = parser.parse_args(argv)
    if opts.include_exe is not None:
        config["include_exe"] = opts.include_exe
    if opts.include_waf:
        config["include_waf"] = True
    if opts.waf_dir is not None:
        base_dir = opts.waf_dir
        packages = config.get("waf", {}).get("packages", [])
        config["waf"] = {"base_dir": base_dir, "packages": packages}

    create_script(config)

if __name__ == "__main__":
    main()
