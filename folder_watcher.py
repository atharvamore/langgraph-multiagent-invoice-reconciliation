# folder_watcher.py
import os
import time
from dotenv import load_dotenv

# Load environment variables at the absolute top
load_dotenv()

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from main_pipeline import ReconciliationPipelineEngine
from utils.logger import setup_logger

logger = setup_logger("FolderWatcher")

class InvoiceHandler(FileSystemEventHandler):
    def __init__(self, engine: ReconciliationPipelineEngine):
        """Create a watcher handler tied to the shared reconciliation engine."""
        self.engine = engine
        # Track processed files to avoid duplicate triggers within the same event window
        self.processed_files = set()

    def on_created(self, event):
        """Process new files dropped into the intake folder."""
        # Ignore directory creation events
        if event.is_directory:
            return

        file_path = event.src_path
        filename = os.path.basename(file_path)

        # Ignore temporary OS or editor files (e.g., hidden files, temporary downloads)
        if filename.startswith(".") or filename.endswith(".tmp") or filename.startswith("~"):
            return

        # Check if the file has already been captured
        if file_path in self.processed_files:
            return

        logger.info(f"New file detected in drop folder: {filename}")
        self.processed_files.add(file_path)

        # Give Windows/the OS a split second (0.5s) to finish writing the file to disk
        time.sleep(0.5)

        try:
            # Trigger the reconciliation pipeline
            success = self.engine.process_document(file_path)
            if success:
                logger.info(f"Pipeline executed successfully for {filename}")
            else:
                logger.warning(f"Pipeline executed with routing flags or errors for {filename}")
                
            # Safely remove the file from the intake folder since main_pipeline moved it
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info(f"Cleaned up original drop file: {filename}")
                except Exception as e:
                    logger.debug(f"Could not delete original drop file (moved already): {e}")

        except Exception as e:
            logger.error(f"Error executing pipeline for {filename}: {str(e)}")
        finally:
            # Clean tracking cache for this file
            time.sleep(1)
            self.processed_files.discard(file_path)

def start_watcher():
    """Start monitoring the incoming folder and route new files to the pipeline."""
    watch_directory = "incoming_invoices"
    os.makedirs(watch_directory, exist_ok=True)
    
    # Initialize our pipeline engine once
    engine = ReconciliationPipelineEngine()
    
    event_handler = InvoiceHandler(engine)
    observer = Observer()
    observer.schedule(event_handler, path=watch_directory, recursive=False)
    
    logger.info(f"Active Folder Watcher Daemon started. Monitoring folder: '{watch_directory}/'...")
    observer.start()
    
    try:
        while True:
            time.sleep(1)  # Keep the main execution thread alive
    except KeyboardInterrupt:
        logger.info("Stopping Folder Watcher Daemon...")
        observer.stop()
    observer.join()

if __name__ == "__main__":
    start_watcher()
