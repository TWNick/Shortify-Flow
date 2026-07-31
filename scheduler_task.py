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
    "coding life hacks shorts",
    "VS Code shortcut tips shorts",
    "software developer memes shorts",
    "python programming tricks shorts",
    "web developer secrets shorts",
    "github tips and hacks shorts",
    "ai coding assistant hacks shorts",
    "funny pet shorts",
    "funny cat shorts"
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

import argparse

def main():
    parser = argparse.ArgumentParser(description="Shortify-Flow Scheduler Task")
    parser.add_argument(
        "--mode", 
        choices=["commentary", "flow"], 
        default="commentary", 
        help="Select video generation mode: 'commentary' for voiceover二創, 'flow' for Google Labs Flow AI video generation"
    )
    args = parser.parse_args()

    logger.info("=========================================")
    logger.info(f"Starting scheduled Shortify-Flow run ({args.mode} mode)...")
    
    query = get_next_query()
    logger.info(f"Selected query for this run: '{query}'")
    
    # Set up command
    python_exe = os.path.join("venv", "Scripts", "python.exe")
    mode_flag = "--commentary" if args.mode == "commentary" else "--flow-video"
    cmd = [
        python_exe, "main.py",
        "--action", "run",
        "--search-query", query,
        mode_flag,
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
