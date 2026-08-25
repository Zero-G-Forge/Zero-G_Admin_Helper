# features/dashboard/resource_worker.py

import os
import psutil
import time
from PyQt6.QtCore import QThread, pyqtSignal


class ResourcePollingWorker(QThread):
    """
    Dedicated background worker thread for monitoring workstation resource usage.
    Emits periodic hardware usage metrics without blocking the primary UI thread.
    """
    signal_resources_received = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_running = True

    def run(self):
        """
        Main polling loop. Samples CPU and RAM usage and emits formatted telemetry dictionaries.
        """
        try:
            process = psutil.Process(os.getpid())
        except Exception as err:
            print(f"[ResourcePollingWorker] -WARN- Unable to attach to process: {err}")
            process = None

        print("[ResourcePollingWorker] -STATUS- Background resource monitoring initiated.")

        while self.is_running:
            try:
                # Using interval=None for non-blocking
                if process:
                    cpu_usage = process.cpu_percent(interval=None)
                    ram_usage = process.memory_percent()
                else:
                    # Fallback to system-wide metrics if process handle fails
                    cpu_usage = psutil.cpu_percent(interval=None)
                    ram_usage = psutil.virtual_memory().percent

                resources = {
                    "cpu": round(cpu_usage, 1),
                    "ram": round(ram_usage, 1),
                    "timestamp": time.strftime("%H:%M:%S")
                }
                self.signal_resources_received.emit(resources)

            except Exception as err:
                print(f"[ResourcePollingWorker] -ERROR- Error polling resources: {err}")

            time.sleep(4)

    def stop(self):
        """
        Safely halts the execution loop and waits for thread termination.
        """
        self.is_running = False
        self.wait(1000)