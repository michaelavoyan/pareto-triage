"""Xcode project parsing for Swift target membership.

Swift has no file-level imports: a file can call anything in the module, and the
module is the target. So `import Foo` names a module, not a file, and two Swift
files are only neighbours when the project says they compile into the same
target. That data lives in `project.pbxproj`, an OpenStep property list.

This module reads just enough of it: the file references, the group tree that
gives them paths, and each native target's Sources build phase. Anything it
cannot read produces no membership, never a guess.
"""

import posixpath
import re

# `/* ... */` and `// ...` comments, a quoted string, one of the six punctuation
# characters, or a bare token such as `PBXNativeTarget` or `App.framework`.
_TOKEN_RE = re.compile(r"""
    (?P<comment>/\*.*?\*/|//[^\n]*)
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<punct>[{}()=;,])
  | (?P<ident>[^\s{}()=;,"]+)
""", re.S | re.X)


def _tokens(text):
    for match in _TOKEN_RE.finditer(text):
        if match.group("comment"):
            continue
        if match.group("string"):
            value = match.group("string")[1:-1]
            yield ("value", value.replace('\\"', '"').replace("\\\\", "\\"))
        elif match.group("punct"):
            yield (match.group("punct"), match.group("punct"))
        else:
            yield ("value", match.group("ident"))


def _parse(text):
    """Parse an OpenStep plist into dicts, lists and strings."""
    tokens = list(_tokens(text))
    pos = 0

    def expect(kind):
        nonlocal pos
        if pos >= len(tokens) or tokens[pos][0] != kind:
            raise ValueError("expected %s" % kind)
        value = tokens[pos][1]
        pos += 1
        return value

    def value():
        nonlocal pos
        if pos >= len(tokens):
            raise ValueError("unexpected end")
        kind, text_ = tokens[pos]
        if kind == "{":
            pos += 1
            out = {}
            while pos < len(tokens) and tokens[pos][0] != "}":
                key = expect("value")
                expect("=")
                out[key] = value()
                expect(";")
            expect("}")
            return out
        if kind == "(":
            pos += 1
            out = []
            while pos < len(tokens) and tokens[pos][0] != ")":
                out.append(value())
                if pos < len(tokens) and tokens[pos][0] == ",":
                    pos += 1
            expect(")")
            return out
        pos += 1
        return text_

    return value()


class Project:
    """One parsed `project.pbxproj`.

    `targets` maps a target name to the source file paths it lists explicitly,
    `directories` to the folders a synchronised root group compiles wholesale
    (Xcode 16 style, where the Sources phase is empty), and `products` maps a
    module name a Swift file could import to the targets that make it.
    """

    def __init__(self, data):
        objects = data.get("objects") if isinstance(data, dict) else None
        if not isinstance(objects, dict):
            raise ValueError("no objects table")
        self.objects = {k: v for k, v in objects.items() if isinstance(v, dict)}
        self.parent = {}
        for oid, obj in self.objects.items():
            if obj.get("isa") in ("PBXGroup", "PBXVariantGroup", "XCVersionGroup"):
                children = obj.get("children")
                if isinstance(children, list):
                    for child in children:
                        if isinstance(child, str):
                            self.parent[child] = oid
        self.targets = {}
        self.directories = {}
        self.excluded = {}
        self.products = {}

    def path_of(self, oid):
        """Relative path of a file reference, walking up its group chain.

        A group whose `sourceTree` is not `<group>` restarts the path (it is
        already relative to the project root), so the walk stops there.
        """
        parts = []
        seen = set()
        current = oid
        while current in self.objects and current not in seen:
            seen.add(current)
            obj = self.objects[current]
            if obj.get("sourceTree") not in (None, "<group>"):
                break
            path = obj.get("path")
            if isinstance(path, str) and path and path != ".":
                parts.append(path)
            current = self.parent.get(current)
        return "/".join(reversed(parts))

    def _build_sources(self):
        for oid in sorted(self.objects):
            obj = self.objects[oid]
            if obj.get("isa") != "PBXNativeTarget":
                continue
            name = obj.get("name") or obj.get("productName")
            if not isinstance(name, str) or not name:
                continue
            paths = []
            phases = obj.get("buildPhases")
            for phase_id in phases if isinstance(phases, list) else []:
                phase = self.objects.get(phase_id) or {}
                if phase.get("isa") != "PBXSourcesBuildPhase":
                    continue
                files = phase.get("files")
                for build_id in files if isinstance(files, list) else []:
                    build = self.objects.get(build_id) or {}
                    ref = build.get("fileRef")
                    if isinstance(ref, str) and ref in self.objects:
                        path = self.path_of(ref)
                        if path:
                            paths.append(path)
            self.targets[name] = sorted(set(paths))

            directories = []
            excluded = []
            groups = obj.get("fileSystemSynchronizedGroups")
            for group_id in groups if isinstance(groups, list) else []:
                group = self.objects.get(group_id) or {}
                if group.get("isa") != "PBXFileSystemSynchronizedRootGroup":
                    continue
                directory = self.path_of(group_id)
                if not directory:
                    continue
                directories.append(directory)
                for exception_id in group.get("exceptions") or []:
                    exception = self.objects.get(exception_id) or {}
                    for relative in exception.get("membershipExceptions") or []:
                        if isinstance(relative, str):
                            excluded.append(posixpath.join(directory, relative))
            self.directories[name] = sorted(set(directories))
            self.excluded[name] = sorted(set(excluded))

            names = {name}
            product_name = obj.get("productName")
            if isinstance(product_name, str) and product_name:
                names.add(product_name)
            product = self.objects.get(obj.get("productReference") or "")
            if isinstance(product, dict):
                product_path = product.get("path")
                if isinstance(product_path, str) and product_path:
                    names.add(posixpath.splitext(posixpath.basename(product_path))[0])
            for module in names:
                self.products.setdefault(module, []).append(name)
        for module in self.products:
            self.products[module] = sorted(set(self.products[module]))


def parse(text):
    """Parse `project.pbxproj` text. Raises ValueError when it cannot be read."""
    project = Project(_parse(text))
    project._build_sources()
    return project


def _suffix_index(paths):
    index = {}
    for rel in paths:
        parts = rel.split("/")
        for start in range(len(parts)):
            index.setdefault("/".join(parts[start:]), []).append(rel)
    return index


def _lookup(index, path):
    """Deterministic pick, matching the JVM resolver: shallower, then lexical."""
    hits = index.get(path)
    if not hits:
        return None
    return min(hits, key=lambda hit: (hit.count("/"), hit))


def _match(index, path):
    """Match a project path against the scanned set by trailing segments."""
    parts = [p for p in path.split("/") if p and p != "."]
    for cut in range(0, len(parts)):
        hit = _lookup(index, "/".join(parts[cut:]))
        if hit:
            return hit
    return None


def _under(rel, directory):
    """True when `directory` is a whole-segment run inside `rel`.

    The project path is relative to the project file, which need not sit at the
    scan root, so the directory is matched anywhere rather than as a prefix.
    """
    wanted = [part for part in directory.split("/") if part and part != "."]
    if not wanted:
        return False
    parts = rel.split("/")
    for start in range(len(parts) - len(wanted) + 1):
        if parts[start:start + len(wanted)] == wanted:
            return True
    return False


def membership(files):
    """Map scanned Swift files to the targets that compile them.

    `files` is the scanned set (`rel` and `text`). Every `project.pbxproj` under
    it is read; a file listed by two projects ends up with two targets. A Swift
    file no project mentions has no target and therefore no intra-target edges.
    """
    projects = [f for f in files
                if posixpath.basename(f["rel"]) == "project.pbxproj"]
    swift = [f["rel"] for f in files if f["ext"] == ".swift"]
    index = _suffix_index(swift)

    targets = {}
    products = {}
    parsed = []
    for project_file in sorted(projects, key=lambda f: f["rel"]):
        try:
            project = parse(project_file["text"])
        except (ValueError, IndexError):
            continue
        parsed.append(project_file["rel"])
        for target, paths in project.targets.items():
            found = set()
            for path in paths:
                hit = _match(index, path)
                if hit:
                    found.add(hit)
            for directory in project.directories.get(target, ()):
                for rel in swift:
                    if _under(rel, directory):
                        found.add(rel)
            for excluded in project.excluded.get(target, ()):
                found = {rel for rel in found if not _under(rel, excluded)}
            targets.setdefault(target, set()).update(found)
        for module, names in project.products.items():
            products.setdefault(module, set()).update(names)

    return {
        "pbxproj": parsed,
        "swift_files": sorted(swift),
        "targets": {name: sorted(rels) for name, rels in sorted(targets.items())},
        "products": {name: sorted(names) for name, names in sorted(products.items())},
    }
