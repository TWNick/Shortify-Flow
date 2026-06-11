import os
import json
import subprocess
import random
import logging

# Set up logging for scheduler
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - Scheduler - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("workspace/scheduler.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("Scheduler")

QUERIES = [
    "funny programmer shorts",
    "coding life hacks",
    "VS Code shortcut tips",
    "software developer memes",
    "python programming tricks",
    "web developer secrets",
    "github tips and hacks",
    "local LLM setup tutorial shorts",
    "ai coding assistant hacks"
]

def get_next_query():
    state_path = "workspace/scheduler_state.json"
    index = 0
    if os.path.exists(state_path):
        try:
            with open(state_path, "r") as f:
                state = json.load(f)
                index = state.get("next_index", 0)
        except Exception:
            pass
            
    query = QUERIES[index % len(QUERIES)]
    
    # Save next index
    try:
        with open(state_path, "w") as f:
            json.dump({"next_index": index + 1}, f)
    except Exception as e:
        logger.error(f"Failed to save scheduler state: {e}")
        
    return query

def main():
    logger.info("=========================================")
    logger.info("Starting scheduled Shortify-Flow run...")
    
    query = get_next_query()
    logger.info(f"Selected query for this run: '{query}'")
    
    # Set up command
    python_exe = os.path.join("venv", "Scripts", "python.exe")
    cmd = [
        python_exe, "main.py",
        "--action", "run",
        "--search-query", query,
        "--flow-video",
        "--publish"
    ]
    
    try:
        logger.info(f"Executing command: {' '.join(cmd)}")
        # Run process and capture output
        res = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        logger.info("Pipeline executed successfully!")
        logger.debug(res.stdout)
    except subprocess.CalledProcessError as err:
        logger.error(f"Pipeline failed with exit code {err.returncode}!")
        logger.error(err.stdout)
    except Exception as e:
        logger.error(f"An unexpected error occurred during execution: {e}")
        
    logger.info("Scheduled run completed.")
    logger.info("=========================================")

if __name__ == "__main__":
    main()
