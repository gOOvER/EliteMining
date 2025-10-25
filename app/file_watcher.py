"""
Event-driven file monitoring system for Elite Dangerous files
Replaces polling with efficient file system events
"""

import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Optional, Set

try:
    from watchdog.events import (
        FileCreatedEvent,
        FileModifiedEvent,
        FileSystemEventHandler,
    )
    from watchdog.observers import Observer

    WATCHDOG_AVAILABLE = True
except ImportError:
    # Fallback to polling if watchdog is not available
    WATCHDOG_AVAILABLE = False
    print("[FILE_WATCHER] Watchdog not available, falling back to polling")

log = logging.getLogger("EliteMining.FileWatcher")


class EliteFileWatcher:
    """
    Event-driven file watcher for Elite Dangerous game files

    Monitors:
    - Journal*.log files (new entries)
    - Cargo.json (cargo updates)
    - Status.json (ship status changes)

    Provides callbacks for file changes instead of constant polling
    """

    def __init__(self, journal_dir: str):
        self.journal_dir = journal_dir
        self.observer = None
        self.event_handler = None
        self.is_monitoring = False
        self._lock = threading.RLock()

        # Callbacks for different file types
        self.journal_callback: Optional[Callable[[str], None]] = None
        self.cargo_callback: Optional[Callable[[str], None]] = None
        self.status_callback: Optional[Callable[[str], None]] = None

        # Track file sizes to detect actual changes vs. just access events
        self._file_sizes: Dict[str, int] = {}
        self._last_processed: Dict[str, float] = {}

        # Debounce rapid file changes (Elite Dangerous can trigger many events)
        self._debounce_delay = 0.5  # 500ms debounce

        if WATCHDOG_AVAILABLE:
            self._setup_watchdog()
        else:
            self._setup_polling_fallback()

    def _setup_watchdog(self):
        """Setup watchdog-based file monitoring"""

        class EliteFileHandler(FileSystemEventHandler):
            def __init__(self, watcher_instance):
                self.watcher = watcher_instance

            def on_modified(self, event):
                if not event.is_directory:
                    self.watcher._handle_file_change(event.src_path)

            def on_created(self, event):
                if not event.is_directory:
                    self.watcher._handle_file_change(event.src_path)

        self.event_handler = EliteFileHandler(self)
        self.observer = Observer()

    def _setup_polling_fallback(self):
        """Setup polling-based monitoring as fallback"""
        self._polling_active = False
        self._polling_thread = None

    def set_journal_callback(self, callback: Callable[[str], None]):
        """Set callback for journal file changes"""
        self.journal_callback = callback

    def set_cargo_callback(self, callback: Callable[[str], None]):
        """Set callback for Cargo.json changes"""
        self.cargo_callback = callback

    def set_status_callback(self, callback: Callable[[str], None]):
        """Set callback for Status.json changes"""
        self.status_callback = callback

    def start_monitoring(self):
        """Start file monitoring"""
        with self._lock:
            if self.is_monitoring:
                return

            if not os.path.exists(self.journal_dir):
                log.warning(f"Journal directory not found: {self.journal_dir}")
                return

            if WATCHDOG_AVAILABLE and self.observer:
                try:
                    self.observer.schedule(
                        self.event_handler, self.journal_dir, recursive=False
                    )
                    self.observer.start()
                    self.is_monitoring = True
                    log.info(f"Started event-driven monitoring of: {self.journal_dir}")
                except Exception as e:
                    log.error(f"Failed to start watchdog monitoring: {e}")
                    self._start_polling_fallback()
            else:
                self._start_polling_fallback()

    def _start_polling_fallback(self):
        """Start polling-based monitoring as fallback"""
        self._polling_active = True
        self.is_monitoring = True

        def polling_worker():
            """Optimized polling worker - only check when needed"""
            while self._polling_active:
                try:
                    self._check_files_polling()
                    time.sleep(1.0)  # 1 second polling (better than 0.5s constant)
                except Exception as e:
                    log.error(f"Polling error: {e}")
                    time.sleep(2.0)  # Back off on errors

        self._polling_thread = threading.Thread(target=polling_worker, daemon=True)
        self._polling_thread.start()
        log.info(f"Started polling-based monitoring of: {self.journal_dir}")

    def _check_files_polling(self):
        """Check files in polling mode (fallback)"""
        try:
            # Check journal files
            journal_pattern = os.path.join(self.journal_dir, "Journal.*.log")
            import glob

            journal_files = glob.glob(journal_pattern)
            if journal_files:
                latest_journal = max(journal_files, key=os.path.getmtime)
                self._check_file_change(latest_journal)

            # Check Cargo.json
            cargo_path = os.path.join(self.journal_dir, "Cargo.json")
            if os.path.exists(cargo_path):
                self._check_file_change(cargo_path)

            # Check Status.json
            status_path = os.path.join(self.journal_dir, "Status.json")
            if os.path.exists(status_path):
                self._check_file_change(status_path)

        except Exception as e:
            log.error(f"Error checking files: {e}")

    def _check_file_change(self, file_path: str):
        """Check if file has actually changed"""
        try:
            if not os.path.exists(file_path):
                return

            current_size = os.path.getsize(file_path)
            current_mtime = os.path.getmtime(file_path)

            file_key = os.path.basename(file_path).lower()

            # Check if file actually changed
            if (
                file_key not in self._file_sizes
                or self._file_sizes[file_key] != current_size
                or file_key not in self._last_processed
                or current_mtime > self._last_processed[file_key]
            ):

                self._file_sizes[file_key] = current_size
                self._last_processed[file_key] = current_mtime
                self._handle_file_change(file_path)

        except Exception as e:
            log.error(f"Error checking file change {file_path}: {e}")

    def _handle_file_change(self, file_path: str):
        """Handle file change event with debouncing"""
        try:
            file_name = os.path.basename(file_path).lower()
            current_time = time.time()

            # Debounce rapid events
            if file_name in self._last_processed:
                if (
                    current_time - self._last_processed[file_name]
                    < self._debounce_delay
                ):
                    return

            self._last_processed[file_name] = current_time

            # Route to appropriate callback
            if file_name.startswith("journal.") and file_name.endswith(".log"):
                if self.journal_callback:
                    self.journal_callback(file_path)
            elif file_name == "cargo.json":
                if self.cargo_callback:
                    self.cargo_callback(file_path)
            elif file_name == "status.json":
                if self.status_callback:
                    self.status_callback(file_path)

        except Exception as e:
            log.error(f"Error handling file change {file_path}: {e}")

    def stop_monitoring(self):
        """Stop file monitoring"""
        with self._lock:
            if not self.is_monitoring:
                return

            self.is_monitoring = False

            if WATCHDOG_AVAILABLE and self.observer:
                try:
                    self.observer.stop()
                    self.observer.join(timeout=2.0)
                except Exception as e:
                    log.error(f"Error stopping watchdog: {e}")

            if hasattr(self, "_polling_active"):
                self._polling_active = False
                if self._polling_thread and self._polling_thread.is_alive():
                    self._polling_thread.join(timeout=2.0)

            log.info("File monitoring stopped")

    def is_active(self) -> bool:
        """Check if monitoring is active"""
        return self.is_monitoring

    def get_status(self) -> str:
        """Get monitoring status for UI display"""
        if not self.is_monitoring:
            return "❌ Not monitoring"

        if WATCHDOG_AVAILABLE and self.observer:
            return "⚡ Event-driven monitoring active"
        else:
            return "🔄 Polling-based monitoring active"


# Utility function for easy integration
def create_elite_watcher(journal_dir: str) -> EliteFileWatcher:
    """Create and return a configured EliteFileWatcher"""
    return EliteFileWatcher(journal_dir)
