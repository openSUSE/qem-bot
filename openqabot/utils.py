from copy import deepcopy

def walk(inc):
    if isinstance(inc, list):
        for i, j in enumerate(inc):
            inc[i] = walk(j)
    if isinstance(inc, dict):
        if len(inc) == 1:
            if "edges" in inc:
                return walk(inc["edges"])
            elif "node" in inc:
                tmp = deepcopy(inc["node"])
                del inc["node"]
                inc.update(tmp)
        for key in inc:
            if isinstance(inc[key], (list, dict)):
                inc[key] = walk(inc[key])
    return inc
