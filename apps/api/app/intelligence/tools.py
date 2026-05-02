"""
Tools for agents - GitHub integration, file operations, shell commands, and skill access.
"""
import os
import re
import subprocess
import json
from typing import Optional, List, Dict, Any
from github import Github, GithubException
from langchain_core.tools import tool
from app.database.models import ActionHistory, CodeChunk
from app.database.session import SessionLocal
from app.core.config import get_settings
from app.core.embedding import get_embedding_model

settings = get_settings()


def get_github_client() -> Github:
    """Get authenticated GitHub client."""
    return Github(settings.github_token)


# ===== File Operations =====

@tool
def read_file(file_path: str) -> str:
    """Read content from a local file.
    
    Args:
        file_path: Absolute path to the file to read
        
    Returns:
        The file content as a string
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return f"Error: File not found: {file_path}"
    except Exception as e:
        return f"Error reading file: {str(e)}"


@tool
def write_file(thread_id: int, file_path: str, content: str) -> str:
    """Write content to a local file and record in ActionHistory.
    
    Args:
        thread_id: The thread ID for action history tracking
        file_path: Absolute path to the file to write
        content: The content to write
        
    Returns:
        Success message or error
    """
    db = SessionLocal()
    try:
        content_before = None
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                content_before = f.read()
        
        action = ActionHistory(
            thread_id=thread_id,
            action_type="write",
            file_path=file_path,
            content_before=content_before,
            content_after=content,
        )
        db.add(action)
        db.commit()
    finally:
        db.close()

    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return f"Successfully wrote to {file_path}"


@tool
def read_multiple_files(file_paths: List[str]) -> Dict[str, str]:
    """Read multiple files at once.
    
    Args:
        file_paths: List of file paths to read
        
    Returns:
        Dictionary mapping file paths to their contents
    """
    results = {}
    for path in file_paths:
        results[path] = read_file(path)
    return results


# ===== GitHub Operations =====

@tool
def get_repo_file(owner: str, repo: str, file_path: str, branch: str = "main") -> str:
    """Read a file from a GitHub repository.
    
    Args:
        owner: Repository owner
        repo: Repository name
        file_path: Path to the file within the repo
        branch: Branch name (default: main)
        
    Returns:
        File content or error message
    """
    try:
        g = get_github_client()
        repo_obj = g.get_repo(f"{owner}/{repo}")
        contents = repo_obj.get_contents(file_path, ref=branch)
        return contents.decoded_content.decode()
    except GithubException as e:
        return f"GitHub error: {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def create_or_update_file(
    owner: str,
    repo: str,
    file_path: str,
    content: str,
    message: str = "Update file",
    branch: str = "main"
) -> str:
    """Create or update a file in a GitHub repository.
    
    Args:
        owner: Repository owner
        repo: Repository name
        file_path: Path to the file within the repo
        content: New file content
        message: Commit message
        branch: Branch name
        
    Returns:
        Commit URL or error message
    """
    try:
        g = get_github_client()
        repo_obj = g.get_repo(f"{owner}/{repo}")
        
        try:
            # File exists, get current content and SHA
            contents = repo_obj.get_contents(file_path, ref=branch)
            repo_obj.update_file(
                contents.path,
                message,
                content,
                contents.sha,
                branch=branch
            )
            return f"Updated {file_path} on {branch}"
        except GithubException as e:
            if e.status == 404:
                # File doesn't exist, create it
                repo_obj.create_file(
                    file_path,
                    message,
                    content,
                    branch=branch
                )
                return f"Created {file_path} on {branch}"
    except GithubException as e:
        return f"GitHub error: {str(e)}"


@tool
def create_pull_request(
    owner: str,
    repo: str,
    title: str,
    body: str,
    head: str,
    base: str = "main"
) -> str:
    """Create a pull request in a GitHub repository.
    
    Args:
        owner: Repository owner
        repo: Repository name
        title: PR title
        body: PR description
        head: Branch containing the changes
        base: Target branch
        
    Returns:
        PR URL or error message
    """
    try:
        g = get_github_client()
        repo_obj = g.get_repo(f"{owner}/{repo}")
        
        pr = repo_obj.create_pull(
            title=title,
            body=body,
            head=head,
            base=base
        )
        
        return f"Created PR: {pr.html_url}"
    except GithubException as e:
        return f"GitHub error: {str(e)}"


@tool
def list_pull_requests(
    owner: str,
    repo: str,
    state: str = "open",
    limit: int = 10
) -> str:
    """List pull requests in a GitHub repository.
    
    Args:
        owner: Repository owner
        repo: Repository name
        state: Filter by state (open, closed, all)
        limit: Maximum number of PRs to return
        
    Returns:
        JSON string of PR list
    """
    try:
        g = get_github_client()
        repo_obj = g.get_repo(f"{owner}/{repo}")
        
        prs = repo_obj.get_pulls(state=state, sort="updated", direction="desc")[:limit]
        
        result = []
        for pr in prs:
            result.append({
                "number": pr.number,
                "title": pr.title,
                "state": pr.state,
                "user": pr.user.login,
                "url": pr.html_url,
                "created_at": str(pr.created_at),
                "updated_at": str(pr.updated_at),
                "head": pr.head.ref,
                "base": pr.base.ref
            })
        
        return json.dumps(result, indent=2)
    except GithubException as e:
        return f"GitHub error: {str(e)}"


@tool
def list_issues(
    owner: str,
    repo: str,
    state: str = "open",
    labels: Optional[List[str]] = None,
    limit: int = 10
) -> str:
    """List issues in a GitHub repository.
    
    Args:
        owner: Repository owner
        repo: Repository name
        state: Filter by state (open, closed, all)
        labels: List of label names to filter by
        limit: Maximum number of issues to return
        
    Returns:
        JSON string of issue list
    """
    try:
        g = get_github_client()
        repo_obj = g.get_repo(f"{owner}/{repo}")
        
        issues = repo_obj.get_issues(state=state, sort="updated", direction="desc")
        
        result = []
        count = 0
        for issue in issues:
            if issue.pull_request:
                continue  # Skip PRs
            
            if count >= limit:
                break
            
            if labels and not any(l.name in labels for l in issue.labels):
                continue
            
            result.append({
                "number": issue.number,
                "title": issue.title,
                "state": issue.state,
                "user": issue.user.login,
                "url": issue.html_url,
                "labels": [l.name for l in issue.labels],
                "created_at": str(issue.created_at)
            })
            count += 1
        
        return json.dumps(result, indent=2)
    except GithubException as e:
        return f"GitHub error: {str(e)}"


@tool
def create_issue(
    owner: str,
    repo: str,
    title: str,
    body: str = "",
    labels: Optional[List[str]] = None
) -> str:
    """Create an issue in a GitHub repository.
    
    Args:
        owner: Repository owner
        repo: Repository name
        title: Issue title
        body: Issue description
        labels: Optional list of label names
        
    Returns:
        Issue URL or error message
    """
    try:
        g = get_github_client()
        repo_obj = g.get_repo(f"{owner}/{repo}")
        
        issue = repo_obj.create_issue(
            title=title,
            body=body,
            labels=labels
        )
        
        return f"Created issue: {issue.html_url}"
    except GithubException as e:
        return f"GitHub error: {str(e)}"


@tool
def add_issue_comment(owner: str, repo: str, issue_number: int, body: str) -> str:
    """Add a comment to an issue or pull request.
    
    Args:
        owner: Repository owner
        repo: Repository name
        issue_number: Issue or PR number
        body: Comment text
        
    Returns:
        Success or error message
    """
    try:
        g = get_github_client()
        repo_obj = g.get_repo(f"{owner}/{repo}")
        
        issue = repo_obj.get_issue(issue_number)
        issue.create_comment(body)
        
        return f"Comment added to #{issue_number}"
    except GithubException as e:
        return f"GitHub error: {str(e)}"


@tool
def get_repo_structure(owner: str, repo: str, branch: str = "main", max_depth: int = 3) -> str:
    """Get the directory structure of a GitHub repository.
    
    Args:
        owner: Repository owner
        repo: Repository name
        branch: Branch to explore
        max_depth: Maximum depth of recursion
        
    Returns:
        JSON string of directory tree
    """
    def get_contents_recursive(contents, current_depth, max_depth):
        if current_depth >= max_depth:
            return []
        
        result = []
        for item in contents:
            entry = {
                "name": item.name,
                "type": "dir" if item.type == "dir" else "file",
                "path": item.path
            }
            if item.type == "dir" and current_depth < max_depth - 1:
                try:
                    sub_contents = item.get_contents()
                    entry["children"] = get_contents_recursive(sub_contents, current_depth + 1, max_depth)
                except GithubException:
                    entry["children"] = []
            result.append(entry)
        return result
    
    try:
        g = get_github_client()
        repo_obj = g.get_repo(f"{owner}/{repo}")
        contents = repo_obj.get_contents("", ref=branch)
        
        tree = get_contents_recursive(contents, 0, max_depth)
        return json.dumps(tree, indent=2)
    except GithubException as e:
        return f"GitHub error: {str(e)}"


@tool
def search_github_code(owner: str, repo: str, query: str, max_results: int = 10) -> str:
    """Search for code within a GitHub repository.
    
    Args:
        owner: Repository owner
        repo: Repository name
        query: Search query
        max_results: Maximum number of results
        
    Returns:
        JSON string of search results
    """
    try:
        g = get_github_client()
        repo_obj = g.get_repo(f"{owner}/{repo}")
        
        results = repo_obj.search_code(query=query, per_page=max_results)
        
        search_results = []
        for result in results:
            search_results.append({
                "name": result.name,
                "path": result.path,
                "url": result.html_url,
                "sha": result.sha
            })
        
        return json.dumps(search_results, indent=2)
    except GithubException as e:
        return f"GitHub error: {str(e)}"


# ===== Codebase Search =====

@tool
def search_codebase(workspace_id: int, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Search the codebase using vector embeddings.
    
    Args:
        workspace_id: The workspace ID to search in
        query: Search query text
        max_results: Maximum number of results
        
    Returns:
        List of matching code chunks
    """
    db = SessionLocal()
    try:
        embedding_model = get_embedding_model()
        query_embedding = embedding_model.embed_query(query)
        
        results = db.query(CodeChunk).filter(
            CodeChunk.workspace_id == workspace_id
        ).order_by(
            CodeChunk.embedding.cosine_distance(query_embedding)
        ).limit(max_results).all()
        
        return [
            {
                "file_path": r.file_path,
                "name": r.name,
                "chunk_type": r.chunk_type,
                "content": r.content,
                "signature": r.signature,
                "start_line": r.start_line,
                "end_line": r.end_line
            }
            for r in results
        ]
    except Exception as e:
        return [{"error": str(e)}]
    finally:
        db.close()


@tool
def analyze_security(workspace_id: int, query: str) -> str:
    """Analyze code for security vulnerabilities.
    
    Args:
        workspace_id: The workspace ID
        query: Security concern to check for
        
    Returns:
        Analysis results
    """
    db = SessionLocal()
    try:
        embedding_model = get_embedding_model()
        query_embedding = embedding_model.embed_query(query)
        
        results = db.query(CodeChunk).filter(
            CodeChunk.workspace_id == workspace_id,
            CodeChunk.chunk_type.in_(["function", "class"])
        ).order_by(
            CodeChunk.embedding.cosine_distance(query_embedding)
        ).limit(10).all()
        
        findings = []
        for chunk in results:
            # Check for common security patterns
            security_issues = []
            
            code_lower = chunk.content.lower()
            
            # SQL injection patterns
            if any(p in code_lower for p in ["execute", "query"]) and "%s" in chunk.content:
                security_issues.append("Potential SQL injection via string formatting")
            
            # Hardcoded secrets
            if any(p in code_lower for p in ["api_key", "password", "secret"]) and "=" in chunk.content:
                if not any(s in code_lower for s in ["os.environ", "os.getenv", "process.env"]):
                    security_issues.append("Potential hardcoded secret detected")
            
            # XSS patterns in frontend
            if "innerhtml" in code_lower or "dangerouslysetinnerhtml" in code_lower:
                security_issues.append("Potential XSS vulnerability")
            
            if security_issues:
                findings.append({
                    "file": chunk.file_path,
                    "function": chunk.name,
                    "issues": security_issues
                })
        
        return json.dumps({
            "files_analyzed": len(results),
            "findings": findings,
            "severity": "high" if findings else "low"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"error": str(e)})
    finally:
        db.close()


# ===== Shell Operations =====

@tool
def run_terminal(thread_id: int, command: str, timeout: int = 30, cwd: Optional[str] = None) -> str:
    """Execute a shell command and record in ActionHistory.
    
    Args:
        thread_id: Thread ID for action history
        command: Shell command to execute
        timeout: Command timeout in seconds
        cwd: Working directory for the command
        
    Returns:
        Command output or error
    """
    db = SessionLocal()
    try:
        action = ActionHistory(
            thread_id=thread_id,
            action_type="shell",
            command=command
        )
        db.add(action)
        db.commit()
    finally:
        db.close()

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd
        )
        
        output = result.stdout
        if result.stderr:
            output += "\n--- stderr ---\n" + result.stderr
        
        return output if output else "Command executed with no output."
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout} seconds"
    except Exception as e:
        return f"Error executing command: {str(e)}"


@tool
def run_tests(test_command: str = "pytest", cwd: Optional[str] = None) -> str:
    """Run test suite.
    
    Args:
        test_command: Test command to run (pytest, npm test, etc.)
        cwd: Working directory
        
    Returns:
        Test results
    """
    try:
        result = subprocess.run(
            test_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=cwd
        )
        
        return result.stdout + "\n" + result.stderr
    except subprocess.TimeoutExpired:
        return "Test suite timed out"
    except Exception as e:
        return f"Error running tests: {str(e)}"


# ===== Blocker Management =====

@tool
def report_blocker(task_id: int, reason: str, webhook_url: Optional[str] = None) -> str:
    """Report a blocker that prevents the agent from continuing.
    
    Args:
        task_id: The task ID
        reason: Description of the blocker
        webhook_url: Optional webhook URL for notifications
        
    Returns:
        Status message
    """
    db = SessionLocal()
    try:
        from app.database.models import BackgroundTask, BlockerNotification
        
        task = db.query(BackgroundTask).get(task_id)
        if task:
            task.status = "blocked"
            blocker = BlockerNotification(
                task_id=task_id,
                reason=reason
            )
            db.add(blocker)
            db.commit()
            
            if webhook_url:
                try:
                    import httpx
                    httpx.post(webhook_url, json={
                        "task_id": task_id,
                        "status": "blocked",
                        "reason": reason
                    }, timeout=5.0)
                except Exception as e:
                    print(f"Failed to send webhook: {e}")
            
            return f"Blocker reported: {reason}. Task is now paused."
        return "Task not found."
    finally:
        db.close()


# ===== Skill Access =====

@tool
def read_skill(skill_name: str, workspace_id: Optional[int] = None) -> str:
    """Read the full content of a skill from the skills library.
    
    Args:
        skill_name: The name of the skill to read. Options include:
            - python_expert: Python development best practices
            - react_specialist: React and frontend development
            - fastapi_best_practices: FastAPI and REST API patterns
            - sql_optimization: Database query optimization
            - tdd_master: Test-driven development
            - security_auditor: Security best practices
            - refactoring_master: Code refactoring patterns
            - api_designer: API design principles
            - devops_cicd: CI/CD and DevOps practices
            - documentation_specialist: Technical documentation
            - git_workflow: Git workflows and best practices
            - clean_architecture: Architecture patterns
            - performance_tuning: Performance optimization
        workspace_id: Optional workspace ID to look for workspace-specific skills first
        
    Returns:
        The full content of the skill with expert guidance.
    """
    db = SessionLocal()
    try:
        from app.intelligence.skill_registry import SkillRegistry
        
        registry = SkillRegistry(db)
        skill = registry.get_skill_by_name(skill_name, workspace_id)
        
        if not skill:
            available_skills = registry.list_skills(workspace_id=workspace_id)
            skill_names = [s.name for s in available_skills]
            return (
                f"Skill '{skill_name}' not found. "
                f"Available skills: {', '.join(skill_names) if skill_names else 'None'}"
            )
        
        metadata = (
            f"Type: {skill.skill_type}\n"
            f"Compatibility: {', '.join(skill.compatibilities) if skill.compatibilities else 'None'}\n"
            f"Category: {skill.category}"
        )
        
        return f"# {skill.name}\n\n{metadata}\n\n---\n\n{skill.content}"
    finally:
        db.close()


@tool
def list_available_skills(workspace_id: Optional[int] = None) -> str:
    """List all available skills.
    
    Args:
        workspace_id: Optional workspace ID to include workspace-specific skills
        
    Returns:
        JSON string of available skills
    """
    db = SessionLocal()
    try:
        from app.intelligence.skill_registry import SkillRegistry
        
        registry = SkillRegistry(db)
        skills = registry.list_skills(workspace_id=workspace_id)
        
        return json.dumps([
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "category": s.category,
                "skill_type": s.skill_type,
                "is_global": s.is_global
            }
            for s in skills
        ], indent=2)
    finally:
        db.close()


# ===== Utility Tools =====

@tool
def grep_files(pattern: str, directory: str = ".", file_pattern: str = "*") -> str:
    """Search for text patterns in files.
    
    Args:
        pattern: Regular expression pattern to search for
        directory: Directory to search in
        file_pattern: File pattern to match (e.g., "*.py")
        
    Returns:
        List of matching lines with file paths
    """
    try:
        result = subprocess.run(
            f"grep -rn --include='{file_pattern}' '{pattern}' {directory}",
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.stdout if result.stdout else "No matches found"
    except Exception as e:
        return f"Error searching files: {str(e)}"


@tool
def get_file_info(file_path: str) -> str:
    """Get information about a file.
    
    Args:
        file_path: Path to the file
        
    Returns:
        JSON string with file metadata
    """
    try:
        stat = os.stat(file_path)
        return json.dumps({
            "path": file_path,
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "created": stat.st_ctime,
            "is_file": os.path.isfile(file_path),
            "is_dir": os.path.isdir(file_path),
            "extension": os.path.splitext(file_path)[1]
        }, indent=2)
    except Exception as e:
        return f"Error getting file info: {str(e)}"