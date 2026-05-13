"""
GhostFix AI - Background Daemon
Monitors terminal processes and detects errors automatically
"""
import os
import sys
import time
import signal
import threading
import subprocess
import queue
import re
from pathlib import Path
from typing import Optional, List, Dict, Callable
from dataclasses import dataclass, field
from datetime import datetime
import json

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.memory import LocalMemory
from core.detector import detect_error
from core.parser import parse_error
from core.decision_engine import decide_fix


@dataclass
class DaemonConfig:
    """Configuration for the daemon"""
    poll_interval: float = 0.5  # seconds
    max_buffer_lines: int = 1000
    error_patterns_path: Optional[Path] = None
    auto_fix: bool = False
    notify: bool = True
    log_file: Optional[Path] = None
    watch_processes: bool = True
    watch_files: bool = False
    watch_directories: List[str] = field(default_factory=list)


@dataclass
class DetectedError:
    """Detected error information"""
    timestamp: datetime
    error_type: str
    error_message: str
    traceback: str
    file_path: Optional[str]
    line_number: Optional[int]
    process_id: Optional[int]
    context: str


class ProcessMonitor:
    """Monitor running processes for errors"""
    
    def __init__(self, config: DaemonConfig):
        self.config = config
        self.running = False
        self.processes: Dict[int, subprocess.Popen] = {}
        self.error_queue: queue.Queue = queue.Queue()
    
    def start(self):
        """Start monitoring"""
        self.running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
    
    def stop(self):
        """Stop monitoring"""
        self.running = False
        if hasattr(self, '_monitor_thread'):
            self._monitor_thread.join(timeout=2)
    
    def _monitor_loop(self):
        """Main monitoring loop"""
        while self.running:
            self._check_processes()
            time.sleep(self.config.poll_interval)
    
    def _check_processes(self):
        """Check all monitored processes for errors"""
        for pid, proc in list(self.processes.items()):
            if proc.poll() is not None:
                # Process ended
                del self.processes[pid]
                continue
            
            # Check stdout/stderr
            try:
                # Read available output
                if proc.stderr:
                    import select
                    if select.select([proc.stderr], [], [], 0)[0]:
                        line = proc.stderr.readline()
                        if line:
                            self._check_output(line, pid)
            except Exception:
                pass
    
    def _check_output(self, line: str, pid: int):
        """Check output line for errors"""
        result = detect_error(line)
        if result and result.get("status") == "error":
            error = parse_error(line)
            if error:
                detected = DetectedError(
                    timestamp=datetime.now(),
                    error_type=error.get("type", "Unknown"),
                    error_message=error.get("message", line),
                    traceback=line,
                    file_path=error.get("file"),
                    line_number=error.get("line"),
                    process_id=pid,
                    context=line
                )
                self.error_queue.put(detected)
    
    def watch_process(self, proc: subprocess.Popen):
        """Add a process to watch"""
        self.processes[proc.pid] = proc
    
    def get_errors(self) -> List[DetectedError]:
        """Get all queued errors"""
        errors = []
        while not self.error_queue.empty():
            try:
                errors.append(self.error_queue.get_nowait())
            except queue.Empty:
                break
        return errors


class FileMonitor:
    """Monitor files for errors (e.g., log files)"""
    
    def __init__(self, config: DaemonConfig):
        self.config = config
        self.running = False
        self.file_positions: Dict[str, int] = {}
        self.error_queue: queue.Queue = queue.Queue()
    
    def start(self):
        """Start monitoring"""
        self.running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
    
    def stop(self):
        """Stop monitoring"""
        self.running = False
        if hasattr(self, '_monitor_thread'):
            self._monitor_thread.join(timeout=2)
    
    def watch_file(self, path: str):
        """Add a file to watch"""
        if os.path.exists(path):
            self.file_positions[path] = os.path.getsize(path)
        else:
            self.file_positions[path] = 0
    
    def _monitor_loop(self):
        """Main monitoring loop"""
        while self.running:
            self._check_files()
            time.sleep(self.config.poll_interval)
    
    def _check_files(self):
        """Check all monitored files for new errors"""
        for path, position in list(self.file_positions.items()):
            try:
                if not os.path.exists(path):
                    continue
                
                current_size = os.path.getsize(path)
                if current_size < position:
                    # File was truncated, reset position
                    position = 0
                
                if current_size > position:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        f.seek(position)
                        new_lines = f.readlines()
                        f.seek(0)
                        current_size = f.tell()
                    
                    self.file_positions[path] = current_size
                    
                    for line in new_lines:
                        result = detect_error(line)
                        if result and result.get("status") == "error":
                            error = parse_error(line)
                            if error:
                                detected = DetectedError(
                                    timestamp=datetime.now(),
                                    error_type=error.get("type", "Unknown"),
                                    error_message=error.get("message", line),
                                    traceback=line,
                                    file_path=error.get("file"),
                                    line_number=error.get("line"),
                                    process_id=None,
                                    context=line
                                )
                                self.error_queue.put(detected)
            
            except Exception as e:
                print(f"Error checking file {path}: {e}")
    
    def get_errors(self) -> List[DetectedError]:
        """Get all queued errors"""
        errors = []
        while not self.error_queue.empty():
            try:
                errors.append(self.error_queue.get_nowait())
            except queue.Empty:
                break
        return errors


class GhostFixDaemon:
    """Main daemon class"""
    
    def __init__(self, config: Optional[DaemonConfig] = None):
        self.config = config or DaemonConfig()
        try:
            self.memory = LocalMemory()
        except Exception:
            self.memory = None
        self.process_monitor = ProcessMonitor(self.config)
        self.file_monitor = FileMonitor(self.config)
        self.running = False
        self.callbacks: List[Callable] = []
        self.inference_engine = None
        
        # Setup logging
        self._setup_logging()
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _setup_logging(self):
        """Setup logging"""
        if self.config.log_file:
            import logging
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                handlers=[
                    logging.FileHandler(self.config.log_file),
                    logging.StreamHandler()
                ]
            )
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        print("\n🛑 Received shutdown signal, stopping daemon...")
        self.stop()
        sys.exit(0)
    
    def start(self):
        """Start the daemon"""
        print("\n" + "=" * 50)
        print("👻 GhostFix Daemon Starting...")
        print("=" * 50)
        
        self.running = True
        
        # Start monitors
        if self.config.watch_processes:
            print("📡 Starting process monitor...")
            self.process_monitor.start()
        
        if self.config.watch_files:
            print("📁 Starting file monitor...")
            self.file_monitor.start()
        
        # Initialize inference engine (lazy load)
        print("🧠 Initializing inference engine...")
        
        print("\n✅ Daemon started successfully!")
        print(f"   Poll interval: {self.config.poll_interval}s")
        print(f"   Auto-fix: {self.config.auto_fix}")
        print(f"   Notify: {self.config.notify}")
        
        # Main loop
        self._main_loop()
    
    def stop(self):
        """Stop the daemon"""
        print("\n👻 GhostFix Daemon Stopping...")
        
        self.running = False
        self.process_monitor.stop()
        self.file_monitor.stop()
        
        if self.inference_engine:
            self.inference_engine.cleanup()
        
        print("✅ Daemon stopped")
    
    def _main_loop(self):
        """Main daemon loop"""
        while self.running:
            # Check for errors from process monitor
            errors = self.process_monitor.get_errors()
            for error in errors:
                self._handle_error(error)
            
            # Check for errors from file monitor
            errors = self.file_monitor.get_errors()
            for error in errors:
                self._handle_error(error)
            
            time.sleep(self.config.poll_interval)
    
    def _handle_error(self, error: DetectedError):
        """Handle a detected error"""
        print(f"\n🚨 Error detected: {error.error_type}")
        print(f"   Message: {error.error_message[:100]}...")
        
        if self.memory:
            self.memory.save_error(
                error_type=error.error_type,
                error_message=error.error_message,
                cause="",
                fix="",
                context=error.context
            )
        
        # Get fix suggestion
        fix = self._get_fix(error)
        
        # Notify callbacks
        for callback in self.callbacks:
            try:
                callback(error, fix)
            except Exception as e:
                print(f"Error in callback: {e}")
        
        # Print notification
        if self.config.notify:
            self._notify_error(error, fix)
        
        # Auto-fix if enabled
        if self.config.auto_fix and fix.get("fix"):
            self._apply_fix(error, fix)
    
    def _get_fix(self, error: DetectedError) -> Dict:
        """Get fix suggestion for error"""
        parsed = {
            "raw": error.traceback,
            "type": error.error_type,
            "message": error.error_message,
            "file": error.file_path,
            "line": error.line_number,
            "missing_package": None,
        }
        return decide_fix(parsed, {"snippet": error.context}).to_dict()
    
    def _notify_error(self, error: DetectedError, fix: Dict):
        """Notify user of error"""
        print("\n" + "=" * 50)
        print(f"🚨 {error.error_type}")
        print("=" * 50)
        print(f"Message: {error.error_message}")
        
        if fix.get("cause"):
            print(f"\n📍 Cause: {fix['cause']}")
        
        if fix.get("fix"):
            print(f"\n🔧 Fix:\n{fix['fix']}")
        
        print("=" * 50)
    
    def _apply_fix(self, error: DetectedError, fix: Dict):
        """Apply automatic fix"""
        # This is dangerous - implement with caution
        print(f"\n⚠️ Auto-fix requested but not implemented yet")
        pass
    
    def add_callback(self, callback: Callable):
        """Add a callback for error notifications"""
        self.callbacks.append(callback)
    
    def watch_file(self, path: str):
        """Add a file to watch"""
        self.file_monitor.watch_file(path)
    
    def run_command(self, cmd: List[str], cwd: Optional[str] = None) -> subprocess.Popen:
        """Run a command and monitor it"""
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        
        self.process_monitor.watch_process(proc)
        return proc


def create_daemon(
    poll_interval: float = 0.5,
    auto_fix: bool = False,
    notify: bool = True,
    log_file: Optional[str] = None
) -> GhostFixDaemon:
    """Create a daemon instance"""
    config = DaemonConfig(
        poll_interval=poll_interval,
        auto_fix=auto_fix,
        notify=notify,
        log_file=Path(log_file) if log_file else None
    )
    
    return GhostFixDaemon(config)


if __name__ == "__main__":
    # Example usage
    daemon = create_daemon(
        poll_interval=0.5,
        notify=True,
        log_file="ghostfix/daemon.log"
    )
    
    # Add custom callback
    def my_callback(error: DetectedError, fix: Dict):
        print(f"Custom callback: {error.error_type}")
    
    daemon.add_callback(my_callback)
    
    # Start daemon
    daemon.start()
