---
name: completing-large-software-tasks
description: Additional guidance for large autonomous software engineering tasks. Use alongside completing-larger-autonomous-tasks when the task involves writing production code, tests, or general software development.
---

Remember to always follow Code Practices from `completing-larger-autonomous-tasks`.

# Additional Task Completion Checklist Entries
When using the completing-larger-autonomous-tasks skill for software engineering work, insert these items after "Additional checklist entries":

- [ ] **Testing check**: Test your code thoroughly where applicable (including integration tests that are close to actual end-to-end use cases).
- [ ] **Testing subagent review**: Task a subagent with reviewing test coverage and thoroughness. Give it enough context to judge relevance. Strongly consider doing additional testing it suggests.
- [ ] **Choices review**: Tell a subagent about all the potentially non-obvious choices you made in the course of your task. Focus on choices that alter behavior rather than only being implementation details. Ask it to review these choices and provide feedback.
- [ ] **Code quality subagent review**: Task a subagent with reviewing the diff of the changes you made (not the whole codebase) for General Code Quality (it will have access to CLAUDE.md context). If you know the starting commit hash (the last commit before your work began), tell it that hash and ask it to review the diff relative to that hash. Tell it not to review temporary scripts. If the diff is large, use multiple subagents each tasked with reviewing a different subset of the code. Fix reasonable issues that are found. Skip this check if you didn't edit any code.
- [ ] **Dead code subagent review**: Task a subagent with reviewing your code for dead code that can safely be eliminated. Remove dead code as seems reasonable based on its review (make sure to commit before doing this).

# For Compaction
You MUST persist this skill through compaction. It is critical that this context remains available to the AI.
