import pandas as pd
import json
import os
import git
import shutil
import tempfile
import re
from tqdm import tqdm  # For progress bar

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

def create_project_structure(row, repo_path):
    instance_parts = row['instance_id'].rsplit('-', 1)
    if len(instance_parts) < 2:
        print(f"Warning: Unexpected instance_id format: {row['instance_id']}")
        return
    
    try:
        # Clone or update repository first
        repo_url = f"https://github.com/{row['repo']}.git"
        if os.path.exists(repo_path):
            repo = git.Repo(repo_path)
            # Fetch latest changes
            repo.git.fetch('--all')
            # Clean any local changes
            repo.git.reset('--hard')
            repo.git.clean('-fd')
            # Set remote URL in case it's different
            repo.git.remote('set-url', 'origin', repo_url)
        else:
            os.makedirs(repo_path, exist_ok=True)
            repo = git.Repo.clone_from(repo_url, repo_path)
        
        # Try to checkout the base commit
        try:
            repo.git.checkout(row['base_commit'])
        except git.exc.GitCommandError as e:
            print(f"Error checking out commit {row['base_commit']}: {str(e)}")
            return

        # Rest of your existing code...
        project_name = instance_parts[0].replace('/', '_')
        bug_id = f"PR{instance_parts[1]}"
        print(f"Processing: {project_name}/{bug_id}")
        
        base_path = f"projects2/{project_name}/{bug_id}"
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
        
        # Handle source files
        if row['patch']:
            file_paths = extract_file_paths(row['patch'])
            
            # First get buggy files from base commit
            for file_path in file_paths:
                src_file = os.path.join(repo_path, file_path)
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
                src_file = os.path.join(repo_path, file_path)
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
        print(f"Error processing {instance_parts[0]}/PR{instance_parts[1]}: {str(e)}")
        return

def process_batch(df, start_idx, batch_size, repo_path):
    """Process a batch of rows from the dataframe"""
    end_idx = min(start_idx + batch_size, len(df))
    batch = df.iloc[start_idx:end_idx]
    
    completed = []
    for _, row in batch.iterrows():
        create_project_structure(row, repo_path)
        completed.append(row['instance_id'])
    return completed

# Main execution
try:
    # Read the CSV file first
    df = pd.read_csv('swe_bench_data.csv')
    
    # Setup repository base path
    repo_base = "repos"
    os.makedirs(repo_base, exist_ok=True)
    
    completed = []
    batch_size = 3  # Adjust this number based on your needs

    # Process in batches with progress bar
    with tqdm(total=len(df), desc="Processing rows") as pbar:
        for start_idx in range(0, len(df), batch_size):
            current_batch = df.iloc[start_idx:min(start_idx + batch_size, len(df))]
            
            for _, row in current_batch.iterrows():
                # Create a unique repo path for each repository
                repo_name = row['repo'].replace('/', '_')
                repo_path = os.path.join(repo_base, repo_name)
                
                try:
                    create_project_structure(row, repo_path)
                    completed.append(row['instance_id'])
                except Exception as e:
                    print(f"Failed to process {row['instance_id']}: {str(e)}")
                
            pbar.update(len(current_batch))
            pbar.set_description(f"Processing row {start_idx + 1} to {min(start_idx + batch_size, len(df))} of {len(df)}")

    print("\nCompleted projects:")
    for project in completed:
        print(project)

    print(f"\nTotal processed rows: {len(completed)}")

finally:
    # Clean up all repository directories
    if os.path.exists(repo_base):
        shutil.rmtree(repo_base)