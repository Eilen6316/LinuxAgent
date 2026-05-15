# execution

Local command execution uses argv semantics behind policy and the sandbox runner. Remote execution
uses configured SSH targets and host-key verification. stdout/stderr are captured, redacted where
needed, and supplied to the analysis path so summaries match observed execution results.
