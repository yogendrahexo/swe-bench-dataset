import pandas as pd
import json
import os
import git
import shutil
import tempfile
import re

def extract_file_paths(patch):
    """Extract file paths from git diff headers"""
    paths = []
    for line in patch.split('\n'):
        if line.startswith('diff --git'):
            # Extract both a/ and b/ paths
            parts = line.split()
            a_path = parts[2][2:]  # Remove a/ prefix
            paths.append(a_path)
    return paths

def create_project_structure(row):
    instance_parts = row['instance_id'].rsplit('-', 1)
    if len(instance_parts) < 2:
        print(f"Warning: Unexpected instance_id format: {row['instance_id']}")
        return
    
    project_name = instance_parts[0].replace('/', '_')
    bug_id = f"PR{instance_parts[1]}"
    print(f"Processing: {project_name}/{bug_id}")
    
    base_path = f"projects/{project_name}/{bug_id}"
    buggy_path = f"{base_path}/buggy"
    fixed_path = f"{base_path}/fixed"
    
    os.makedirs(buggy_path, exist_ok=True)
    os.makedirs(fixed_path, exist_ok=True)
    
    # Write bug description
    with open(f"{base_path}/bug_description.txt", 'w') as f:
        f.write(f"{row['problem_statement']}\n\n")
        if row['hints_text']:
            f.write(f"Hints:\n{row['hints_text']}\n\n")
        f.write(f"Created at: {row['created_at']}\n")
        f.write(f"Version: {row['version']}\n")
    
    # Write test information (renamed from requirements.txt)
    with open(f"{base_path}/test_files.txt", 'w') as f:
        f.write("Test files that should fail before fix and pass after:\n")
        fail_to_pass = json.loads(row['FAIL_TO_PASS'])
        f.write("\n".join(fail_to_pass))
        f.write("\n\nTest files that should pass both before and after fix:\n")
        pass_to_pass = json.loads(row['PASS_TO_PASS'])
        f.write("\n".join(pass_to_pass))
    
    # Create temporary directory for repo
    with tempfile.TemporaryDirectory() as temp_repo_path:
        try:
            # Clone and checkout base commit
            repo = git.Repo.clone_from(f"https://github.com/{row['repo']}.git", temp_repo_path)
            repo.git.checkout(row['base_commit'])
            
            # Handle source files
            if row['patch']:
                file_paths = extract_file_paths(row['patch'])
                
                # First get buggy files from base commit
                for file_path in file_paths:
                    src_file = os.path.join(temp_repo_path, file_path)
                    if os.path.exists(src_file):
                        dest_file = os.path.join(buggy_path, os.path.basename(file_path))
                        shutil.copy2(src_file, dest_file)
                        print(f"  Copied buggy file: {os.path.basename(file_path)}")
                
                # Create patch file
                patch_file = os.path.join(base_path, "changes.patch")
                with open(patch_file, 'w') as f:
                    f.write(row['patch'])
                
                # Create a new temp directory for fixed files
                with tempfile.TemporaryDirectory() as fixed_repo_path:
                    # Clone again for fixed version
                    fixed_repo = git.Repo.clone_from(f"https://github.com/{row['repo']}.git", fixed_repo_path)
                    fixed_repo.git.checkout(row['base_commit'])
                    
                    # Write patch to a temporary file and apply it
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False) as temp_patch:
                        temp_patch.write(row['patch'])
                        temp_patch.flush()
                        try:
                            fixed_repo.git.apply(['--allow-empty', temp_patch.name])
                        finally:
                            os.unlink(temp_patch.name)
                    
                    # Copy fixed files
                    for file_path in file_paths:
                        src_file = os.path.join(fixed_repo_path, file_path)
                        if os.path.exists(src_file):
                            dest_file = os.path.join(fixed_path, os.path.basename(file_path))
                            shutil.copy2(src_file, dest_file)
                            print(f"  Copied fixed file: {os.path.basename(file_path)}")
            
            # Handle test files
            if row['test_patch']:
                test_file_paths = extract_file_paths(row['test_patch'])
                
                # Get original test files
                for file_path in test_file_paths:
                    src_file = os.path.join(temp_repo_path, file_path)
                    if os.path.exists(src_file):
                        dest_file = os.path.join(buggy_path, os.path.basename(file_path))
                        shutil.copy2(src_file, dest_file)
                        print(f"  Copied buggy test: {os.path.basename(file_path)}")
                
                # Create test patch file
                test_patch_file = os.path.join(base_path, "test_changes.patch")
                with open(test_patch_file, 'w') as f:
                    f.write(row['test_patch'])
                
                # Create a new temp directory for fixed test files
                with tempfile.TemporaryDirectory() as fixed_test_repo_path:
                    # Clone again for fixed version
                    fixed_test_repo = git.Repo.clone_from(f"https://github.com/{row['repo']}.git", fixed_test_repo_path)
                    fixed_test_repo.git.checkout(row['base_commit'])
                    
                    # Write test patch to a temporary file and apply it
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False) as temp_patch:
                        temp_patch.write(row['test_patch'])
                        temp_patch.flush()
                        try:
                            fixed_test_repo.git.apply(['--allow-empty', temp_patch.name])
                        finally:
                            os.unlink(temp_patch.name)
                    
                    # Copy fixed test files
                    for file_path in test_file_paths:
                        src_file = os.path.join(fixed_test_repo_path, file_path)
                        if os.path.exists(src_file):
                            dest_file = os.path.join(fixed_path, os.path.basename(file_path))
                            shutil.copy2(src_file, dest_file)
                            print(f"  Copied fixed test: {os.path.basename(file_path)}")
                
        except Exception as e:
            print(f"Error processing {project_name}/{bug_id}: {str(e)}")

# Read the CSV file
df = pd.read_csv('swe_bench_data.csv')
completed = []

# Process each row
for _, row in df.iterrows():
    create_project_structure(row)
    completed.append(row['instance_id'])

print("\nCompleted projects:")
for project in completed:
    print(project)