import os
import warnings
import hashlib
import cStringIO
import csv

from bento._config \
    import \
        IPKG_PATH
from bento.commands.core \
    import \
        Command, Option
from bento.commands.wheel_utils \
    import \
        WheelInfo, wheel_filename, urlsafe_b64encode
from bento.utils.utils import pprint, extract_exception
from bento.core \
    import \
        PackageMetadata
from bento.private.bytecode \
    import \
        bcompile, PyCompileError
from bento.installed_package_description \
    import \
        BuildManifest, iter_files

import bento.compat.api as compat
import bento.utils.path

class BuildWheelCommand(Command):
    long_descr = """\
Purpose: build wheel
Usage:   bentomaker build_wheel [OPTIONS]"""
    short_descr = "build wheel."
    common_options = Command.common_options \
                        + [Option("--output-dir",
                                  help="Output directory", default="dist"),
                           Option("--output-file",
                                  help="Output filename")]

    def run(self, ctx):
        argv = ctx.command_argv
        p = ctx.options_context.parser
        o, a = p.parse_args(argv)
        if o.help:
            p.print_help()
            return
        output_dir = o.output_dir
        output_file = o.output_file

        n = ctx.build_node.make_node(IPKG_PATH)
        build_manifest = BuildManifest.from_file(n.abspath())
        build_wheel(build_manifest, ctx.build_node, ctx.build_node, output_dir, output_file)
        
def hash_and_length(filename, hash=hashlib.sha256):
    """Return the (hash, length) of the named file."""
    h = hash()
    l = 0
    with open(filename, 'rb') as f:
        block = f.read(1<<20)
        while block:            
            h.update(block)
            l += len(block)
            block = f.read(1<<20)
    return (h.digest(), l)

def build_wheel(build_manifest, build_node, source_root, output_dir=None, output_file=None):
    meta = PackageMetadata.from_ipkg(build_manifest)
    egg_info = WheelInfo.from_ipkg(build_manifest, build_node)
    
    assert not '_' in meta.version

    # FIXME: fix egg name
    if output_dir is None:
        if output_file is None:
            egg = wheel_filename(os.path.join("dist", meta.fullname))
        else:
            egg = os.path.join("dist", output_file)
    else:
        if output_file is None:
            egg = wheel_filename(os.path.join(output_dir, meta.fullname))
        else:
            egg = os.path.join(output_dir, output_file)
    bento.utils.path.ensure_dir(egg)

    egg_scheme = {"prefix": source_root.abspath(),
                  "eprefix": source_root.abspath(),
                  "sitedir": source_root.abspath()}
    
    record = []

    zid = compat.ZipFile(egg, "w", compat.ZIP_DEFLATED)
    try:        
        for kind, source, target in build_manifest.iter_built_files(source_root, egg_scheme):
            if not kind in ["executables"]:
                abspath = source.abspath()
                target_path = target.path_from(source_root).replace(os.path.sep, '/')
                zid.write(abspath, target_path)
                hash, length = hash_and_length(abspath)
                digest = "sha256="+urlsafe_b64encode(hash)
                record.append((target_path, digest, length))
                
        for filename, cnt in egg_info.iter_meta(build_node):            
            name = '/'.join((meta.fullname + ".dist-info", filename))
            digest = "sha256="+urlsafe_b64encode(hashlib.sha256(cnt).digest())
            zid.writestr(name, cnt)
            record.append((name, digest, len(cnt)))
        
        name = '/'.join((meta.fullname + ".dist-info", "WHEEL"))
        wheelfile = b'Wheel-Version: 0.1\nGenerator: bento\nRoot-Is-Purelib: true\n\n'
        zid.writestr(name, wheelfile)
        digest = "sha256="+urlsafe_b64encode(hashlib.sha256(wheelfile).digest())
        record.append((name, digest, len(wheelfile)))
        
        name = '/'.join((meta.fullname + ".dist-info", "RECORD"))
        sio = cStringIO.StringIO()
        writer = csv.writer(sio)
        for row in record:
            writer.writerow(row)
        writer.writerow((name, '', ''))
        zid.writestr(name, sio.getvalue())
                
    finally:
        zid.close()

    return
