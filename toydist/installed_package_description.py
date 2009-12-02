import shutil
import os

from toydist.utils import \
    subst_vars

META_DELIM = "!- FILELIST"
FIELD_DELIM = ("\t", " ")

class InstalledPkgDescription(object):
    def __init__(self, files, path_options):
        self.files = files
        self._path_variables = path_options

        self._path_variables['_srcrootdir'] = "."

    def write(self, filename):
        fid = open(filename, "w")
        try:
            path_fields = "\n".join([
                "\t%s=%s" % (name, value) for name, value in
                                              self._path_variables.items()])

            path_section = """\
paths
%s
%s
""" % (path_fields, META_DELIM)
            fid.write(path_section)

            for name, value in self.files.items():
                if name in ["pythonfiles"]:
                    source = "$_srcrootdir"
                section = """\
%(section)s
%(source)s
%(target)s
%(files)s
""" % {"section": name,
       "source": "\tsource=%s" % source,
       "target": "\ttarget=%s" % value["target"],
       "files": "\n".join(["\t%s" % f for f in value["files"]])}
                fid.write(section)

        finally:
            fid.close()

if __name__ == "__main__":
    files = {}
    files["pythonfiles"] = {
            "files": ["hello.py"],
            "target": "$sitedir",
            }
    p = InstalledPkgDescription(files,
                                {"sitedir": "/usr/lib/python26/site-packages"})
    p.write("yo.txt")

def read_meta_sections(lines):
    sections = {}

    def _read_section():
        if lines[0].startswith(FIELD_DELIM):
            raise ValueError("First line starts with field delimiter" % \
                             lines[0])
        cursec = lines.pop(0).strip()
        if cursec == "paths":
            fields = {}
            sections[cursec] = {}
            while len(lines) > 0 and lines[0].startswith(FIELD_DELIM):
                field = lines.pop(0)
                name, value = [i.strip() for i in field.split("=")]
                sections[cursec][name] = value
        else:
            raise ValueError("unrecognized section %s" % cursec)

    _read_section()

    return sections

def read_file_sections(lines, paths):
    sections = {}
    if lines[0].startswith(FIELD_DELIM):
        raise ValueError("First line starts with field delimiter" % lines[0])
    cursec = lines.pop(0).strip()
    if len(lines) < 2:
        raise ValueError("no source/target ?")
    files = []
    sections[cursec] = files

    source_field = lines.pop(0)
    if not source_field.startswith(FIELD_DELIM):
        raise ValueError("no source ? %s" % source_field)
    else:
        source_field = source_field.strip()
        if not source_field.startswith("source="):
            raise ValueError("no source ? %s" % source_field)
    source = source_field.split("=")[1].strip()

    target_field = lines.pop(0)
    if not target_field.startswith(FIELD_DELIM):
        raise ValueError("no target ? %s" % target_field)
    else:
        target_field = target_field.strip()
        if not target_field.startswith("target="):
            raise ValueError("no target ? %s" % target_field)
    target = target_field.split("=")[1].strip()

    target = subst_vars(target, paths)
    source = subst_vars(source, paths)
    #print source, target

    while len(lines) > 0 and lines[0].startswith("\t"):
        file = lines.pop(0).strip()
        files.append((os.path.join(source, file), os.path.join(target, file)))

    return sections

def read_installed_pkg_description(filename):
    f = open(filename)
    try:
        line = f.readline()
        meta = []
        while not line.startswith(META_DELIM):
            meta.append(line)
            line = f.readline()
        meta_sections = read_meta_sections(meta)
        filelist = f.readlines()
        return read_file_sections(filelist, meta_sections["paths"])
    finally:
        f.close()