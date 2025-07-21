import psutil
import time

class SimpleMonitor:
    def __init__(self, interval=1):
        self.interval = interval

    def collect_metrics(self):
        """Collect basic system metrics."""
        metrics = {
            'cpu': psutil.cpu_percent(interval=self.interval),
            'memory': psutil.virtual_memory().percent,
            'disk': psutil.disk_usage('/').percent,
        }
        return metrics

    def run(self):
        """Run the monitor and print metrics to the console."""
        try:
            while True:
                metrics = self.collect_metrics()
                print(f"CPU: {metrics['cpu']}%, Memory: {metrics['memory']}%, Disk: {metrics['disk']}%")
                time.sleep(self.interval)
        except KeyboardInterrupt:
            print("Monitoring stopped.")

if __name__ == "__main__":
    monitor = SimpleMonitor()
    monitor.run()
