"""Backup a stopped server. SQLite backup API also copies a consistent database."""
import argparse
import sqlite3
from datetime import datetime
from pathlib import Path
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / '.env')
from app import storage

parser=argparse.ArgumentParser(description='Back up AI-NAM. Stop the server before starting.')
parser.add_argument('--output',required=True,help='Backup parent directory outside the data directory')
args=parser.parse_args()
target=Path(args.output).resolve()/datetime.now().strftime('ai-nam-%Y%m%d-%H%M%S')
if target.is_relative_to(storage.DATA_DIR):
    raise SystemExit('The backup destination must be outside the data directory.')
if not (storage.DATA_DIR/'app.sqlite3').is_file():
    raise SystemExit('No AI-NAM database was found.')
target.mkdir(parents=True,exist_ok=False)
with storage.connect() as src:
    dst=sqlite3.connect(target/'app.sqlite3')
    try:src.backup(dst)
    finally:dst.close()
uploads=storage.DATA_DIR/'uploads'
if uploads.exists():shutil.copytree(uploads,target/'uploads')
print(target)
