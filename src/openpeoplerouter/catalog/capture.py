"""Bound response previews without storing customer data."""
def prune(node):
    if isinstance(node, dict):
        return {k: prune(v) for k, v in node.items()}
    if isinstance(node, list):
        return [prune(v) for v in node[:5]]
    if isinstance(node, str):
        return node[:1000]
    return node
