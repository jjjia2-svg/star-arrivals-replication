"""Exact comparison of two estimator result JSONs. Equality means identical scalars (no tolerance)
after dropping wall-clock (`secs`) and input-file-name (`file`) keys at any depth."""
import json, sys

IGNORE = ("secs", "file")

def compare(new, expected, ignore=IGNORE, path=""):
    diffs = []
    if isinstance(expected, dict):
        if not isinstance(new, dict):
            return [f"{path or '<root>'}: type {type(new).__name__} != dict"]
        for k, v in expected.items():
            if k in ignore: continue
            p = f"{path}.{k}" if path else k
            if k not in new: diffs.append(f"{p}: missing in new"); continue
            diffs += compare(new[k], v, ignore, p)
        for k in new:
            if k not in expected and k not in ignore: diffs.append(f"{path + '.' if path else ''}{k}: extra in new")
        return diffs
    if isinstance(expected, list):
        if not isinstance(new, list): return [f"{path}: type {type(new).__name__} != list"]
        if len(new) != len(expected): return [f"{path}: list length {len(new)} != {len(expected)}"]
        for i, (a, b) in enumerate(zip(new, expected)):
            diffs += compare(a, b, ignore, f"{path}[{i}]")
        return diffs
    if new != expected or type(new) is not type(expected):
        return [f"{path}: {new!r} != {expected!r}"]
    return []

def main(argv):
    if len(argv) != 3: print("usage: compare_json NEW.json EXPECTED.json"); return 2
    new = json.load(open(argv[1])); exp = json.load(open(argv[2]))
    d = compare(new, exp)
    print("EQUAL" if not d else "\n".join(["DIFF"] + d))
    return 0 if not d else 1

if __name__ == "__main__": sys.exit(main(sys.argv))
