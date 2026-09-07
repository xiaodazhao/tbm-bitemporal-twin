# Stage7E Final Result Semantics

## A3

The primary endpoint is strict JSON protocol compliance: 125/147 valid chunks,
828/989 Claim mappings, and 32/45 complete tasks. Among the 149 numeric Claims
available under that strict endpoint, the corrected tokenizer finds 149 exact
tokens and zero numeric drift.

The fence-only result is secondary, post-hoc, offline, and deterministic. It
recovers 147/147 chunks and 989/989 mappings without modifying inner JSON. Its
164 numeric Claims contain 164 exact frozen values and zero numeric drift.

## A4

For all 162 referenced numeric FactLocks, the exact
frozen numeric token was present in the section text that declared use of the
corresponding FactLock ID.

对于 162 条被引用的数值型 FactLock, 在声明使用相应
FactLock ID 的 section 文本中, 均检测到了对应的冻结精确数值。

This is a section-level token-presence result. It does not show that all facts
were semantically bound correctly and it is not a semantic-accuracy estimate.
Overall FactLock trace coverage is 848/1022;
numeric trace coverage is 162/
171; numeric omission is
9/171; and numeric
token drift among referenced numeric FactLocks is
0/162.

Complex semantic evaluation remains `DEFERRED_TO_HUMAN`.
