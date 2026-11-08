# Security policy

Describe the affected file, workflow, package behaviour or upstream artifact and include reproducible evidence where possible.

Open a private GitHub security advisory for vulnerabilities that must not be disclosed before a fix exists. Use a normal issue for non-sensitive packaging bugs.

Releases are pinned only after Horizon's signed `SHA256SUMS` verified against its pinned public release key, and automated updates are published only after the flake checks and package builds passed. Horizon's Nightlies are built from main plus pull requests its trusted reviewers picked: treat them as untrusted-by-default software.
