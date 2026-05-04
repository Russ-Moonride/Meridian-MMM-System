# Terminal Cheatsheet — MMM Workspace

## Virtual Environment

1. `source .venv/bin/activate`
   Activate your project venv

2. `deactivate`
   Exit the venv

3. `which python`
   Confirm you're using the right Python

4. `pip install package_name`
   Install a package into active venv

5. `pip freeze > requirements.txt`
   Save current packages to requirements

---

## Launching Tools

6. `claude`
   Launch Claude Code in current directory

7. `jupyter notebook`
   Open Jupyter in browser (whole project)

8. `jupyter notebook notebooks/modeling/northspore_model.ipynb`
   Open a specific notebook

9. `code .`
   Open VS Code in current directory

---

## Navigation

10. `cd ~/mmm-workspace`
    Go to your project

11. `cd ..`
    Go up one directory

12. `ls`
    List files in current directory

13. `ls -la`
    List files with hidden files and details

14. `pwd`
    Show current directory path

---

## Git

15. `git status`
    See what's changed

16. `git add .`
    Stage all changes

17. `git add filename`
    Stage a specific file

18. `git commit -m "your message"`
    Commit staged changes

19. `git log --oneline`
    See recent commits in compact view

20. `git diff`
    See exactly what changed in files

21. `git checkout -- filename`
    Discard changes to a specific file

---

## File Management

22. `mkdir -p folder/subfolder`
    Create nested folders

23. `cp source destination`
    Copy a file

24. `mv source destination`
    Move or rename a file

25. `find . -name "filename"`
    Search for a file by name