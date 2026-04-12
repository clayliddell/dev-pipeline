Dev-Pipeline
---
Lightweight pipeline for the full software development process.

Key Decisions
---
1. Use `opencode run` command for all Agent calls.
2. Ensure visibility of Agent output from OpenCode as they are running.
3. Manage tasks using kanban.py.
4. Prioritize readability, and simplicity of code files.
5. Prefer functional software development patterns (separate logic from data).
6. Keep flow in one file. If necessary, separate tools and data classes out into separate files.
7. This tool is primarily being developed for the `~/dev/agentvm` project. Refer to it as necessary.

Flow
---
1. pickup task from KANBAN board (see `kanban.py`)
2. checkout main & git pull & checkout new feature branch for task
3. PM AGENT (tool-use: no):
	1. input: task id + task title + CODE-STANDARD.md + ARCHITECTURE.md + relevant PHASE file + current filesystem structure for project;
	2. output: detailed planning for task completion, relevant file paths, exit criteria.
4. SWE AGENT (tool-use: yes):
	1. input: expanded task details;
	2. side-effects: changes made to git project + committed to feature branch
	3. output: confirmation when task is complete
5. move task on KANBAN board to REVIEW
6. CR AGENT (tool-use: no):
	1. input: project git diff + task details + ARCHITECTURE.md + CODE-STANDARD.md + relevant PHASE file + current filesystem structure for project;
	2. output: code review feedback
7. CR EVAL AGENT (tool-use: yes):
	1. input: code review feedback;
	2. side-effect: evals whether feedback is accurate and good; applies good, accurate suggestions & ditches the rest
	3. output: confirmation when complete
8. EXIT CRITERIA MET CHECK AGENT (tool-use: no):
   1. input: task details + git diff + "does the git diff fulfill the exit criteria & not introduce major regressions >=75℅ confidence? Yes or No? If no, why not?";
   2. output: yes or no
9. Logic Branch:
   1. yes: commit any uncommitted changes with the kanban task content as the commit message, then merge feature branch to main & push main to origin;
   2. no: ask the exit criteria agent for a detailed checklist in the same session, then prompt the Fulfill Exit Criteria software engineer agent and recheck.
10. Logic Branch:
	1. Check Kanban: is phase complete?
	2. Yes: return to user;
	3. No: continue back to step 1
