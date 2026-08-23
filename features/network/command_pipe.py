"""
Outbound Command Pipeline for Zero-G Admin Helper.
Encapsulates command queueing, \r\n line termination, and GTX Gaming 500ms delay calibration.
"""

import time
import queue
from typing import Optional
from PyQt6.QtCore import QThread, pyqtSignal


class CommandPipe(QThread):
    """
    Dedicated worker thread managing serialized outbound command dispatch
    with mandatory GTX Gaming line termination and delay calibrations.
    """

    command_dispatched = pyqtSignal(str)
    queue_empty = pyqtSignal()

    def __init__(self, telemetry_worker, input_delay_sec: float = 0.5, parent=None):
        super().__init__(parent)
        self._telemetry_worker = telemetry_worker
        self._input_delay_sec = input_delay_sec
        self._command_queue: queue.Queue = queue.Queue()
        self._is_running = True

    def enqueue_command(self, command_str: str):
        """
        Appends an outbound command to the dispatch queue.
        """
        if not command_str or not command_str.strip():
            return

        clean_command = command_str.strip()
        self._command_queue.put(clean_command)
        print(f"[CommandPipe] -INFO- Enqueued command: {clean_command} (Queue depth: {self._command_queue.qsize()})")

    def run(self):
        """
        Processes enqueued commands sequentially with mandatory buffer delay.
        """
        while self._is_running:
            try:
                # Wait for next command with a timeout to allow thread shutdown check
                command = self._command_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                if self._telemetry_worker:
                    # Dispatch to TelemetryWorker
                    self._telemetry_worker.send_command(command)
                    self.command_dispatched.emit(command)
                    print(f"[CommandPipe] -STATUS- Dispatched '{command}' over Port 30500.")

                # Enforce mandatory 500ms input buffer delay for GTX Gaming calibrations
                time.sleep(self._input_delay_sec)

            except Exception as err:
                print(f"[CommandPipe] -ERROR- Exception dispatching command '{command}': {err}")

            finally:
                self._command_queue.task_done()

            if self._command_queue.empty():
                self.queue_empty.emit()

    def stop(self):
        """
        Stops the command queue processing thread.
        """
        self._is_running = False
        self.wait(1000)