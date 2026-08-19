from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

BASELINE_COMMIT = "e5329b29d884d40dc7d3b14ca7fa26c83a14878b"
CURRENT_COMMIT = "ab98e39910d9dc70eacdad3fcb4df4d5e7b579de"
MANIFESTS = (
    (
        "ranking",
        "v0.4-ranking-holdout",
        "6fe09278638ccede6e4be981fcc8b2fd5fedcd9288dbcc780210032bce616736",
    ),
    (
        "edge-idf",
        "v0.4-edge-idf-holdout",
        "1b45b645362a26a24e3d89805282b4dfd14c583b527ebe326698fbce4f0b5eaf",
    ),
)
CONTROLS = (
    ("setup_project", "src/silobrief/state.py", "setup_project"),
    ("snapshot_sources", "src/silobrief/sources.py", "snapshot_sources"),
)
CANARY_ROOT = "examples/model-validation-fixture"
CANARY_PRIMARY = ("src/parcel_lab/retry.py", "retry_request")
CANARY_BOUNDARY = {
    "path": "private_adapter",
    "alias": "delivery-boundary",
    "description": "External delivery adapter",
}
CANARY_FORBIDDEN = (
    b"private_adapter",
    b"private_adapter.client",
    b"deliver_internal",
    b"PRIVATE_MODEL_GATE_CANARY",
    b"ignored-adapter-source",
)
CONTROL_BOUNDARIES = (
    ("examples", "benchmark-fixtures", "Fixture corpus"),
    ("validation", "validation-artifacts", "Reports"),
    ("tests/test_graph_retrieval_baseline.py", "benchmark-harness", "Baseline harness"),
    ("tests/test_graph_retrieval_comparison.py", "comparison-harness", "Comparison harness"),
    ("tests/__init__.py", "test-package-marker", "Test package marker"),
)
OUTGOING_RELATION = {
    "call": "calls",
    "import": "imports",
    "reference": "references",
    "contains": "contains",
}
INCOMING_RELATION = {
    "call": "called-by",
    "import": "imported-by",
    "reference": "referenced-by",
    "contains": "contained-by",
}
RELATION_ORDER = {
    "calls": 0,
    "called-by": 1,
    "imports": 2,
    "imported-by": 3,
    "references": 4,
    "referenced-by": 5,
    "contains": 6,
    "contained-by": 7,
}
KIND_ORDER = {"module": 0, "class": 1, "function": 2}
SCRUBBED_GIT_ENVIRONMENT = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
)
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RESULT_PATH = HERE / "results.json"
ORACLE_PATH = HERE / "oracle.json"
ORACLE_SHA256 = "39a617eab127040f6bfa4a1577dd1be04e4d0f11093ec2c40ffad41427a9b0f1"


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def git(project: Path, *arguments: str, input_data: bytes | None = None) -> bytes:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("GIT_"):
            environment.pop(name)
    for name in SCRUBBED_GIT_ENVIRONMENT:
        environment.pop(name, None)
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
        }
    )
    return subprocess.run(
        (
            "git",
            "--no-replace-objects",
            "--no-optional-locks",
            "-c",
            f"safe.directory={project.as_posix()}",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.untrackedCache=false",
            *arguments,
        ),
        cwd=project,
        env=environment,
        check=True,
        capture_output=True,
        input=input_data,
    ).stdout


class GitLoader(importlib.abc.SourceLoader):
    def __init__(self, commit: str, path: str, content: bytes) -> None:
        self.commit = commit
        self.path = path
        self.content = content

    def get_filename(self, fullname: str) -> str:
        return f"<git:{self.commit}:{self.path}>"

    def get_data(self, path: str) -> bytes:
        return self.content


class GitFinder(importlib.abc.MetaPathFinder):
    def __init__(self, commit: str, blobs: dict[str, bytes]) -> None:
        self.commit = commit
        self.blobs = blobs

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: object = None,
    ) -> importlib.machinery.ModuleSpec | None:
        if fullname != "silobrief" and not fullname.startswith("silobrief."):
            return None
        stem = "src/" + fullname.replace(".", "/")
        package_path = stem + "/__init__.py"
        module_path = stem + ".py"
        source_path = package_path if package_path in self.blobs else module_path
        if source_path not in self.blobs:
            return None
        loader = GitLoader(self.commit, source_path, self.blobs[source_path])
        return importlib.util.spec_from_loader(
            fullname,
            loader,
            origin=loader.get_filename(fullname),
            is_package=source_path == package_path,
        )


def product_api(commit: str) -> dict[str, Any]:
    resolved = git(ROOT, "rev-parse", f"{commit}^{{commit}}").decode().strip()
    if resolved != commit:
        raise RuntimeError(f"product commit did not resolve exactly: {commit}")
    names = git(ROOT, "ls-tree", "-r", "--name-only", commit, "--", "src/silobrief")
    paths = names.decode().splitlines()
    blobs = {path: git(ROOT, "show", f"{commit}:{path}") for path in paths if path.endswith(".py")}
    sys.meta_path.insert(0, GitFinder(commit, blobs))
    package_spec = importlib.machinery.ModuleSpec("silobrief", loader=None, is_package=True)
    package_spec.submodule_search_locations = []
    package = importlib.util.module_from_spec(package_spec)
    sys.modules["silobrief"] = package
    import silobrief.index as index_module
    import silobrief.python_structure as structure_module
    import silobrief.review as review_module
    import silobrief.sources as sources_module
    import silobrief.state as state_module

    return {
        "build_index": index_module.build_index,
        "render_index_json": index_module.render_index_json,
        "extract_structures": structure_module.extract_structures,
        "DisclosureChoices": review_module.DisclosureChoices,
        "review_selection": review_module.review_selection,
        "SourceFile": sources_module.SourceFile,
        "SourceSnapshot": sources_module.SourceSnapshot,
        "snapshot_sources": sources_module.snapshot_sources,
        "default_excludes": state_module.DEFAULT_EXCLUDES,
    }


def load_manifests(external_root: Path) -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for suite, directory, expected_digest in MANIFESTS:
        path = external_root / directory / "holdout.json"
        content = path.read_bytes()
        if sha256(content) != expected_digest:
            raise RuntimeError(f"frozen manifest digest changed: {path}")
        value = json.loads(content)
        for position, raw_case in enumerate(value["cases"], start=1):
            case = dict(raw_case)
            case["suite"] = suite
            case["position"] = position
            case["root"] = str(external_root / directory / "repos")
            cases.append(case)
    return cases


def related_value(node: Any) -> dict[str, object]:
    return {
        "kind": node.kind,
        "path": node.path,
        "qualified_name": node.qualified_name,
        "relations": list(node.relations),
    }


def inside(path: str, prefix: str) -> bool:
    clean = prefix.rstrip("/")
    return path == clean or path.startswith(clean + "/")


def excluded(path: str, config: dict[str, object]) -> bool:
    default_excludes = {str(value).removesuffix("/") for value in config["default_excludes"]}
    if any(part in default_excludes for part in path.split("/")):
        return True
    return any(inside(path, str(boundary["path"])) for boundary in config["boundaries"])


def git_python_blobs(
    project: Path,
    commit: str,
    config: dict[str, object],
    *,
    prefix: str = "",
) -> dict[str, tuple[str, bytes]]:
    arguments = ["ls-tree", "-r", "-z", commit]
    if prefix:
        arguments.extend(("--", prefix))
    records = git(project, *arguments).split(b"\0")
    entries: list[tuple[str, str, str]] = []
    clean_prefix = prefix.rstrip("/")
    for record in records:
        if not record:
            continue
        metadata, encoded_path = record.split(b"\t", 1)
        mode, object_type, object_id = metadata.split(b" ", 2)
        if object_type != b"blob":
            continue
        full_path = encoded_path.decode("utf-8", errors="surrogateescape")
        path = (
            full_path[len(clean_prefix) + 1 :]
            if clean_prefix and full_path.startswith(clean_prefix + "/")
            else full_path
        )
        if not path.endswith(".py") or excluded(path, config):
            continue
        entries.append((path, mode.decode(), object_id.decode()))
    request = b"".join(object_id.encode() + b"\n" for _path, _mode, object_id in entries)
    response = git(project, "cat-file", "--batch", input_data=request)
    offset = 0
    result: dict[str, tuple[str, bytes]] = {}
    for path, mode, expected_id in entries:
        header_end = response.index(b"\n", offset)
        object_id, object_type, encoded_size = response[offset:header_end].split(b" ")
        size = int(encoded_size)
        content_start = header_end + 1
        content_end = content_start + size
        if object_id.decode() != expected_id or object_type != b"blob":
            raise RuntimeError(f"unexpected Git object while reading {path}")
        result[path] = (mode, response[content_start:content_end])
        if response[content_end : content_end + 1] != b"\n":
            raise RuntimeError(f"malformed Git batch output while reading {path}")
        offset = content_end + 1
    if offset != len(response):
        raise RuntimeError("unexpected trailing Git batch output")
    return result


def source_digest(files: tuple[object, ...]) -> str:
    digest = hashlib.sha256(b"silobrief-source-snapshot-v1\0")
    for source in files:
        path = source.path.encode("utf-8")
        digest.update(len(path).to_bytes(8, byteorder="big"))
        digest.update(path)
        digest.update(bytes.fromhex(source.sha256))
    return digest.hexdigest()


def git_snapshot(
    api: dict[str, Any],
    project: Path,
    commit: str,
    config: dict[str, object],
    *,
    prefix: str = "",
) -> object:
    blobs = git_python_blobs(project, commit, config, prefix=prefix)
    files = tuple(
        api["SourceFile"](path, content, sha256(content))
        for path, (mode, content) in sorted(blobs.items())
        if mode in {"100644", "100755"}
    )
    return api["SourceSnapshot"](files=files, warnings=(), digest=source_digest(files))


def audit_working_snapshot(
    api: dict[str, Any],
    project: Path,
    commit: str,
    config: dict[str, object],
) -> dict[str, bool]:
    tracked_status = git(project, "status", "--porcelain=v1", "-z", "--untracked-files=no")
    if tracked_status:
        raise RuntimeError(f"external repository has tracked changes: {project}")
    tracked = git_python_blobs(project, commit, config)
    snapshot = api["snapshot_sources"](project, config)
    for source in snapshot.files:
        expected = tracked.get(source.path)
        if expected is None:
            raise RuntimeError(f"working snapshot contains untracked source: {source.path}")
        if source.content != expected[1] and source.content.replace(b"\r\n", b"\n") != expected[1]:
            raise RuntimeError(f"working source differs from HEAD blob: {source.path}")
    return {
        "canonical_git_snapshot": True,
        "tracked_clean_at_start": True,
        "working_snapshot_inputs_frozen": True,
    }


def adjacent_values(index: object, primary_id: str) -> list[dict[str, object]]:
    nodes = {node.id: node for node in index.nodes}
    relations: dict[str, set[str]] = {}
    for edge in index.edges:
        target_id = edge.target_id
        if edge.source_id not in nodes or target_id not in nodes or edge.source_id == target_id:
            continue
        if edge.source_id == primary_id:
            relations.setdefault(target_id, set()).add(OUTGOING_RELATION[edge.kind])
        if target_id == primary_id:
            relations.setdefault(edge.source_id, set()).add(INCOMING_RELATION[edge.kind])
    ordered = sorted(
        relations,
        key=lambda node_id: (
            nodes[node_id].path,
            KIND_ORDER[nodes[node_id].kind],
            nodes[node_id].name,
            nodes[node_id].qualified_name,
            node_id,
        ),
    )
    return [
        {
            "kind": nodes[node_id].kind,
            "path": nodes[node_id].path,
            "qualified_name": nodes[node_id].qualified_name,
            "relations": sorted(relations[node_id], key=RELATION_ORDER.__getitem__),
        }
        for node_id in ordered
    ]


def evaluate_index(
    api: dict[str, Any],
    snapshot: Any,
    structures: tuple[object, ...],
    config: dict[str, object],
    target_path: str,
    target_name: str,
    *,
    forbidden: tuple[bytes, ...] = (),
) -> dict[str, object]:
    index = api["build_index"](snapshot, structures, config)
    reversed_index = api["build_index"](
        dataclasses.replace(snapshot, files=tuple(reversed(snapshot.files))),
        tuple(reversed(structures)),
        config,
    )
    index_deterministic = api["render_index_json"](index) == api["render_index_json"](
        reversed_index
    )
    targets = [
        node
        for node in index.nodes
        if node.path == target_path and node.qualified_name == target_name
    ]
    if len(targets) != 1:
        raise RuntimeError(f"expected one fixed primary: {target_path} {target_name}")
    fields = api["DisclosureChoices"](False, False, False, False, False)
    selection = api["review_selection"](
        index, (), selected_numbers=(), added=(targets[0].id,), excluded=(), fields=fields
    )
    reordered = api["review_selection"](
        dataclasses.replace(
            index,
            nodes=tuple(reversed(index.nodes)),
            edges=tuple(reversed(index.edges)),
        ),
        (),
        selected_numbers=(),
        added=(targets[0].id,),
        excluded=(),
        fields=fields,
    )
    related = [related_value(node) for node in selection.expanded]
    adjacent = adjacent_values(index, targets[0].id)
    review_deterministic = related == [
        related_value(node) for node in reordered.expanded
    ] and adjacent == adjacent_values(reversed_index, targets[0].id)
    boundary_exposures = 0
    rendered_index = api["render_index_json"](index)
    rendered_related = json.dumps(related, ensure_ascii=False, sort_keys=True).encode()
    rendered_adjacent = json.dumps(adjacent, ensure_ascii=False, sort_keys=True).encode()
    rendered_snapshot = json.dumps(
        [(source.path, source.sha256) for source in snapshot.files],
        ensure_ascii=False,
        sort_keys=True,
    ).encode()
    for boundary in config["boundaries"]:
        prefix = boundary["path"]
        boundary_exposures += sum(inside(source.path, prefix) for source in snapshot.files)
        boundary_exposures += sum(inside(node.path, prefix) for node in index.nodes)
        boundary_exposures += sum(inside(node["path"], prefix) for node in related)
        boundary_exposures += sum(inside(node["path"], prefix) for node in adjacent)
    raw_canary_exposures = sum(
        value in artifact
        for value in forbidden
        for artifact in (
            rendered_snapshot,
            rendered_index,
            rendered_related,
            rendered_adjacent,
        )
    )
    return {
        "adjacent_edges": adjacent,
        "boundary_canary_exposures": boundary_exposures,
        "cap_ok": len(selection.expanded) <= 10,
        "deterministic": index_deterministic and review_deterministic,
        "edges": len(index.edges),
        "nodes": len(index.nodes),
        "primary": {"path": target_path, "qualified_name": target_name},
        "raw_canary_exposures": raw_canary_exposures,
        "related": related,
    }


def evaluate_external(api: dict[str, Any], case: dict[str, object]) -> dict[str, object]:
    repository = str(case["repository"])
    project = Path(str(case["root"])) / repository.rsplit("/", 1)[-1]
    head = git(project, "rev-parse", "HEAD").decode().strip()
    if head != case["commit"]:
        raise RuntimeError(f"unexpected external commit for {repository}: {head}")
    boundaries = [
        {
            "alias": f"holdout-boundary-{position}",
            "description": item["description"],
            "path": item["path"],
        }
        for position, item in enumerate(case.get("ignored_paths", []), start=1)
    ]
    config = {
        "boundaries": boundaries,
        "default_excludes": list(api["default_excludes"]),
        "schema_version": 1,
    }
    input_audit = audit_working_snapshot(api, project, head, config)
    snapshot = git_snapshot(api, project, head, config)
    structures = api["extract_structures"](snapshot)
    result = evaluate_index(
        api,
        snapshot,
        structures,
        config,
        str(case["target_path"]),
        str(case["target_qualified_name"]),
    )
    result.update(
        {
            "commit": head,
            "input_audit": input_audit,
            "manifest_position": case["position"],
            "repository": repository,
            "suite": case["suite"],
        }
    )
    return result


def control_snapshot(api: dict[str, Any], commit: str, config: dict[str, object]) -> object:
    return git_snapshot(api, ROOT, commit, config)


def run_worker(version: str, external_root: Path) -> bytes:
    commit = BASELINE_COMMIT if version == "baseline" else CURRENT_COMMIT
    api = product_api(commit)
    cases = [evaluate_external(api, case) for case in load_manifests(external_root)]
    boundaries = [
        {"path": path, "alias": alias, "description": description}
        for path, alias, description in CONTROL_BOUNDARIES
    ]
    config = {
        "boundaries": boundaries,
        "default_excludes": list(api["default_excludes"]),
        "schema_version": 1,
    }
    snapshot = control_snapshot(api, commit, config)
    structures = api["extract_structures"](snapshot)
    controls = []
    for name, path, qualified_name in CONTROLS:
        value = evaluate_index(api, snapshot, structures, config, path, qualified_name)
        value["name"] = name
        controls.append(value)
    canary_config = {
        "boundaries": [CANARY_BOUNDARY],
        "default_excludes": list(api["default_excludes"]),
        "schema_version": 1,
    }
    canary_snapshot = git_snapshot(
        api,
        ROOT,
        commit,
        canary_config,
        prefix=CANARY_ROOT,
    )
    canary = evaluate_index(
        api,
        canary_snapshot,
        api["extract_structures"](canary_snapshot),
        canary_config,
        *CANARY_PRIMARY,
        forbidden=CANARY_FORBIDDEN,
    )
    payload = {
        "canary": canary,
        "cases": cases,
        "commit": commit,
        "controls": controls,
        "runtime": {
            "implementation": sys.implementation.name,
            "version": list(sys.version_info[:3]),
        },
        "version": version,
    }
    rendered = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode()
    if any(value in rendered for value in CANARY_FORBIDDEN):
        raise RuntimeError("fixture boundary canary leaked into worker result")
    return rendered


def directory_digest(path: Path) -> str:
    digest = hashlib.sha256(b"present" if path.is_dir() else b"missing")
    if not path.is_dir():
        return digest.hexdigest()
    for item in sorted(path.rglob("*"), key=lambda value: value.as_posix()):
        relative = item.relative_to(path).as_posix().encode()
        digest.update(relative + b"\0")
        if item.is_symlink():
            digest.update(b"link\0" + os.readlink(item).encode())
        elif item.is_file():
            digest.update(b"file\0" + item.read_bytes())
        else:
            digest.update(b"directory\0")
    return digest.hexdigest()


def tracked_digest(project: Path) -> str:
    digest = hashlib.sha256()
    for encoded in (item for item in git(project, "ls-files", "-z").split(b"\0") if item):
        relative = encoded.decode("utf-8", errors="surrogateescape")
        target = project / relative
        digest.update(encoded + b"\0")
        if target.is_file():
            digest.update(target.read_bytes())
        else:
            digest.update(git(project, "ls-files", "-s", "--", relative))
        digest.update(b"\0")
    return digest.hexdigest()


def repository_state(project: Path) -> dict[str, str]:
    status = git(project, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    return {
        "silobrief_state_sha256": directory_digest(project / ".silobrief"),
        "status_sha256": sha256(status),
        "tracked_sha256": tracked_digest(project),
    }


def external_projects(cases: list[dict[str, object]]) -> dict[str, Path]:
    return {
        str(case["repository"]): Path(str(case["root"]))
        / str(case["repository"]).rsplit("/", 1)[-1]
        for case in cases
    }


def child_result(version: str, external_root: Path, seed: int) -> dict[str, object]:
    environment = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP"):
        environment.pop(name, None)
    environment.update(
        {
            "GIT_OPTIONAL_LOCKS": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": str(seed),
            "PYTHONNOUSERSITE": "1",
        }
    )
    completed = subprocess.run(
        (
            sys.executable,
            "-S",
            str(Path(__file__)),
            "--worker",
            version,
            "--external-root",
            str(external_root),
        ),
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        reason = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"{version} worker failed: {reason}")
    return json.loads(completed.stdout)


def node_key(value: dict[str, object]) -> tuple[str, str]:
    return str(value["path"]), str(value["qualified_name"])


def edge_keys(values: list[dict[str, object]]) -> set[tuple[str, str, str]]:
    return {
        (*node_key(value), str(relation)) for value in values for relation in value["relations"]
    }


def oracle_edges(values: list[dict[str, str]]) -> set[tuple[str, str, str]]:
    return {(value["path"], value["qualified_name"], value["relation"]) for value in values}


def control_signature(values: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {"name": value["name"], "primary": value["primary"], "related": value["related"]}
        for value in values
    ]


def compare(
    baseline: dict[str, object],
    current: dict[str, object],
    state: dict[str, dict[str, object]],
    *,
    cross_seed_deterministic: bool,
) -> dict[str, object]:
    before_cases = baseline["cases"]
    after_cases = current["cases"]
    identities = [(case["suite"], case["repository"]) for case in before_cases]
    if identities != [(case["suite"], case["repository"]) for case in after_cases]:
        raise RuntimeError("worker case order differs")
    affected = [
        index
        for index, (before, after) in enumerate(zip(before_cases, after_cases, strict=True))
        if before["adjacent_edges"] != after["adjacent_edges"]
    ]
    selected = affected[:4]
    stop_early = len(affected) < 3
    oracle_digest: str | None = None
    measurements: list[dict[str, object]] = []
    if not stop_early:
        oracle_content = ORACLE_PATH.read_bytes()
        oracle_digest = sha256(oracle_content)
        if oracle_digest != ORACLE_SHA256:
            raise RuntimeError("frozen oracle digest changed")
        oracle = json.loads(oracle_content)
        entries = {entry["repository"]: entry for entry in oracle["cases"]}
        expected = {str(after_cases[index]["repository"]) for index in selected}
        if set(entries) != expected:
            raise RuntimeError("oracle cases do not match the first affected cases")
        for index in selected:
            before = before_cases[index]
            after = after_cases[index]
            entry = entries[str(after["repository"])]
            required_nodes = {node_key(value) for value in entry["required_nodes"]}
            required_edges = oracle_edges(entry["required_edges"])
            allowed_edges = oracle_edges(entry["allowed_edges"])
            if not required_edges <= allowed_edges:
                raise RuntimeError("required oracle edges must also be allowed")
            before_nodes = {node_key(value) for value in before["related"]}
            after_nodes = {node_key(value) for value in after["related"]}
            before_edges = edge_keys(before["adjacent_edges"])
            after_edges = edge_keys(after["adjacent_edges"])
            measurements.append(
                {
                    "false_edges_removed": len((before_edges - allowed_edges) - after_edges),
                    "invalid_edges_after": len(after_edges - allowed_edges),
                    "invalid_edges_before": len(before_edges - allowed_edges),
                    "lost_required_nodes": len((required_nodes & before_nodes) - after_nodes),
                    "new_required_nodes": len((required_nodes & after_nodes) - before_nodes),
                    "related_after": len(after_nodes),
                    "related_before": len(before_nodes),
                    "repository": after["repository"],
                    "required_edges_after": len(required_edges & after_edges),
                    "required_edges_before": len(required_edges & before_edges),
                    "required_edges_total": len(required_edges),
                    "required_nodes_after": len(required_nodes & after_nodes),
                    "required_nodes_before": len(required_nodes & before_nodes),
                    "required_nodes_total": len(required_nodes),
                    "unnecessary_after": len(after_nodes - required_nodes),
                    "unnecessary_before": len(before_nodes - required_nodes),
                    "valid_edges_after": len(after_edges & allowed_edges),
                    "edges_after": len(after_edges),
                }
            )
    controls_unchanged = control_signature(baseline["controls"]) == control_signature(
        current["controls"]
    )
    all_values = [
        *before_cases,
        *after_cases,
        *baseline["controls"],
        *current["controls"],
        baseline["canary"],
        current["canary"],
    ]
    required_edge_total = sum(item["required_edges_total"] for item in measurements)
    required_edge_after = sum(item["required_edges_after"] for item in measurements)
    edge_total = sum(item["edges_after"] for item in measurements)
    valid_edge_total = sum(item["valid_edges_after"] for item in measurements)
    improved = sum(
        item["new_required_nodes"] > 0 or item["false_edges_removed"] > 0 for item in measurements
    )
    gates = {
        "affected_at_least_3": len(affected) >= 3,
        "boundary_canary_zero": all(
            item["boundary_canary_exposures"] == 0 and item["raw_canary_exposures"] == 0
            for item in all_values
        ),
        "canonical_deterministic": cross_seed_deterministic
        and all(item["deterministic"] for item in all_values),
        "controls_unchanged": controls_unchanged,
        "external_state_unchanged": all(
            all(bool(value) for value in audit.values()) for audit in state.values()
        ),
        "frozen_external_inputs": all(
            all(bool(value) for value in case["input_audit"].values())
            for case in (*before_cases, *after_cases)
        ),
        "improved_cases_at_least_2": improved >= 2,
        "invalid_edges_zero": sum(item["invalid_edges_after"] for item in measurements) == 0,
        "no_required_neighbor_lost": sum(item["lost_required_nodes"] for item in measurements) == 0,
        "related_cap_10": all(item["cap_ok"] for item in all_values),
        "required_edge_precision_100": edge_total > 0 and valid_edge_total == edge_total,
        "required_edge_recall_100": (
            required_edge_total > 0 and required_edge_after == required_edge_total
        ),
        "unnecessary_not_increased": sum(item["unnecessary_after"] for item in measurements)
        <= sum(item["unnecessary_before"] for item in measurements),
        "worker_runtime_same": baseline["runtime"] == current["runtime"],
    }
    required_node_after = sum(item["required_nodes_after"] for item in measurements)
    required_node_before = sum(item["required_nodes_before"] for item in measurements)
    required_node_total = sum(item["required_nodes_total"] for item in measurements)
    return {
        "affected": [after_cases[index]["repository"] for index in affected],
        "affected_first_4": [after_cases[index]["repository"] for index in selected],
        "decision": "stop" if stop_early or not all(gates.values()) else "proceed",
        "external_state": state,
        "gates": gates,
        "measurements": measurements,
        "metrics": {
            "affected_count": len(affected),
            "boundary_canary_exposures": sum(
                item["boundary_canary_exposures"] + item["raw_canary_exposures"]
                for item in all_values
            ),
            "controls_unchanged": controls_unchanged,
            "improved_cases": improved,
            "invalid_edges_after": sum(item["invalid_edges_after"] for item in measurements),
            "lost_required_nodes": sum(item["lost_required_nodes"] for item in measurements),
            "maximum_related": max(len(item["related"]) for item in all_values),
            "required_edge_precision": f"{valid_edge_total}/{edge_total}",
            "required_edge_recall": f"{required_edge_after}/{required_edge_total}",
            "required_node_recall_after": f"{required_node_after}/{required_node_total}",
            "required_node_recall_before": f"{required_node_before}/{required_node_total}",
            "unnecessary_after": sum(item["unnecessary_after"] for item in measurements),
            "unnecessary_before": sum(item["unnecessary_before"] for item in measurements),
        },
        "oracle_sha256": oracle_digest,
        "runtime": current["runtime"],
    }


def evaluate(external_root: Path) -> bytes:
    cases = load_manifests(external_root)
    projects = external_projects(cases)
    before_state = {name: repository_state(path) for name, path in projects.items()}
    error: BaseException | None = None
    baseline: dict[str, object] = {}
    current: dict[str, object] = {}
    try:
        baseline = child_result("baseline", external_root, 0)
        current = child_result("current", external_root, 0)
        baseline_second = child_result("baseline", external_root, 1)
        current_second = child_result("current", external_root, 1)
    except BaseException as caught:
        error = caught
    after_state = {name: repository_state(path) for name, path in projects.items()}
    if before_state != after_state:
        raise RuntimeError("evaluator changed an external repository")
    if error is not None:
        raise error
    state_audit = {
        name: {
            "silobrief_state_unchanged": value["silobrief_state_sha256"]
            == after_state[name]["silobrief_state_sha256"],
            "status_unchanged": value["status_sha256"] == after_state[name]["status_sha256"],
            "tracked_unchanged": value["tracked_sha256"] == after_state[name]["tracked_sha256"],
        }
        for name, value in before_state.items()
    }
    comparison = compare(
        baseline,
        current,
        state_audit,
        cross_seed_deterministic=(baseline == baseline_second and current == current_second),
    )
    value = {
        "baseline": baseline,
        "comparison": comparison,
        "current": current,
        "evaluator_sha256": sha256(Path(__file__).read_bytes()),
        "manifest_sha256": {suite: digest for suite, _directory, digest in MANIFESTS},
        "schema_version": 1,
    }
    rendered = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    if any(value in rendered for value in CANARY_FORBIDDEN):
        raise RuntimeError("fixture boundary canary leaked into canonical result")
    return rendered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--external-root",
        type=Path,
        default=ROOT.parent / "documents" / "validation",
    )
    parser.add_argument("--worker", choices=("baseline", "current"))
    arguments = parser.parse_args()
    if arguments.worker is not None:
        sys.stdout.buffer.write(run_worker(arguments.worker, arguments.external_root.resolve()))
        return 0
    rendered = evaluate(arguments.external_root.resolve())
    if arguments.check:
        if not RESULT_PATH.is_file() or RESULT_PATH.read_bytes() != rendered:
            raise RuntimeError("canonical result differs; run evaluator without --check")
        print(f"canonical_sha256={sha256(rendered)}")
        return 0
    RESULT_PATH.write_bytes(rendered)
    print(f"wrote {RESULT_PATH.relative_to(ROOT)} sha256={sha256(rendered)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
