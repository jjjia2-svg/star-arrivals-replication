# identity/ layer: red-line pure functions + constants (no IO / no network / no state / no operational control flow).
# Thresholds are always read from common._redlines.RED, with zero hardcoding in the module; an unset placeholder None -> the function raises on None.
