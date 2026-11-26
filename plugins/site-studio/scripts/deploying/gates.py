"""deploying.gates -- the seam with `check_site.py`: the gates run as a subprocess, never imported (design 7.3).

`GATE_SCRIPT` is `check_site.py` beside the entry points; tests point it at a fake (`patch.object(gates, "GATE_SCRIPT", ...)`).
`run_gates` refuses a build the gates fail (`NOT CHECKED` when the script is absent: a gate that cannot run is never a
pass); `_gate_findings` is the offline `--json` read `--preflight` uses (its findings, dev 1068: the reader lists them, not only their
families), and `_gate_families` the families among them.
"""
import json
import os
import subprocess
import sys

from deploying.gitrun import GIT_TIMEOUT, DeployError

GATE_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "check_site.py")


def run_gates(tree, repo, label):
    if not os.path.isfile(GATE_SCRIPT):
        raise DeployError("NOT CHECKED: %s is not present, so the gates (%s) cannot run, and "
                          "publishing is refused; update or reinstall the plugin, then publish again" % (os.path.basename(GATE_SCRIPT), label))
    p = subprocess.run([sys.executable, GATE_SCRIPT, "--out", tree, "--repo", repo], stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, universal_newlines=True, timeout=GIT_TIMEOUT)
    if p.returncode != 0:
        first = "; ".join(l for l in p.stdout.strip().splitlines()[:5])
        raise DeployError("a gate failed on %s: %s; fix what it reports, then publish again" % (label, first or "exit %d" % p.returncode))


def _gate_findings(out_dir, tree):
    """([{family, path, message}], NOT CHECKED reason or None) from `check_site.py --out --json`, offline."""
    if not os.path.isfile(GATE_SCRIPT):
        return [], "%s is not present" % os.path.basename(GATE_SCRIPT)
    p = subprocess.run([sys.executable, GATE_SCRIPT, "--out", out_dir, "--repo", tree, "--json"],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=GIT_TIMEOUT)
    if p.returncode not in (0, 1):
        return [], "the gates exited %d" % p.returncode
    found = []
    for line in p.stdout.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("level") == "error" and isinstance(rec.get("family"), str):
            found.append({"family": rec["family"], "path": str(rec.get("path", "")), "message": str(rec.get("message", ""))})
    return found, None


def _gate_families(out_dir, tree):
    """(families that have findings, NOT CHECKED reason or None) from `check_site.py --out --json`, offline."""
    found, why = _gate_findings(out_dir, tree)
    return sorted(set(f["family"] for f in found)), why
