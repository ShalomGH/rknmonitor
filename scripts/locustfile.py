"""
Locust load-test for rknmon API.
Run: locust -f scripts/locustfile.py --host http://127.0.0.1:8000
"""
from locust import HttpUser, task, between

API_KEY = "dev-key-change-me"


class RknmonUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        self.client.headers.update({"X-API-Key": API_KEY})

    @task(5)
    def get_targets(self):
        self.client.get("/targets")

    @task(3)
    def get_active_targets(self):
        self.client.get("/targets?active_only=true")

    @task(3)
    def get_stats(self):
        self.client.get("/stats")

    @task(3)
    def get_events(self):
        self.client.get("/events?limit=50")

    @task(3)
    def get_probes(self):
        self.client.get("/probes/latest?limit=50")

    @task(2)
    def export_targets_json(self):
        self.client.get("/export/targets?format=json")

    @task(2)
    def export_targets_csv(self):
        self.client.get("/export/targets?format=csv")

    @task(1)
    def health(self):
        self.client.get("/health", headers={})

    @task(1)
    def dashboard_ui(self):
        self.client.get("/ui/dashboard", headers={})
