"""Descriptive display names, separate from stable benchmark identifiers.

Terminology and sources are documented in docs/algorithm-names.md. Labels are
presentation metadata; report matching and CLI selection use identifiers.
"""

ALGORITHM_LABELS = {
    "linear": "Linear search",
    "binary": "Lower-bound binary search",
    "bisect": "Binary search (bisect_left)",
    "recursive": "Recursive binary search",
    "interpolation": "Interpolation search",
    "interpolation_hybrid": "Budgeted interpolation/binary hybrid",
    "exponential": "Exponential search",
    "jump": "Jump search",
    "set": "Hash-set membership",
    "dict": "First-index hash lookup",
    "radix": "Radix Binary Search (RBS)",
    "neighbor_prepared": "Interpolation/neighbor/binary hybrid",
    "guarded_prepared": "Binary search with range guards",
    "adaptive_index": "Heuristic lookup-strategy selector",
    "dict_reverse": "First-index hash lookup (reverse build)",
    "landmark_index": "Adaptive stride/run/radix hybrid",
    "certified_radix": "Radix with arithmetic/bitmap shortcuts",
    "parallel": "Routed binary search (cold process pool)",
    "parallel_warm": "Routed binary search (reused process pool)",
    "fibonacci": "Fibonacci array search",
    "ternary": "Ternary array search",
    "ternary_recursive": "Recursive ternary array search",
    "double_linear": "Double-ended linear search",
    "double_linear_recursive": "Recursive double-ended linear search",
    "sentinel": "Sentinel linear search (private buffer)",
    "interpolation_recursive": "Recursive interpolation search",
    "binary_slicing": "Recursive binary membership (slices)",
}


def algorithm_label(identifier: str) -> str:
    """Return the current display label, retaining unknown/custom identifiers."""
    return ALGORITHM_LABELS.get(identifier, identifier)


def format_algorithm(identifier: str) -> str:
    """Show a descriptive name and its compatible CLI/report identifier."""
    label = algorithm_label(identifier)
    return f"{label} [{identifier}]" if label != identifier else identifier
