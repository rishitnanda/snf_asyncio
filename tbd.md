The Pattern Extractor vs. Pointer Analysis
The Trap: Your pipeline documentation openly admits it is a pattern extractor, not a true dataflow or points-to analysis. It misses synchronization primitives if they are passed as function arguments, stored inside containers (lists/dicts), or generated via factory functions.

The Reviewer Backlash: A systems reviewer evaluating a static utility expects handling of real-world patterns. They might argue that your 71.0% coverage metric is artificially narrow because the denominator only counts things your AST visitor can explicitly see, ignoring trickier, unanalyzed synchronization patterns.
