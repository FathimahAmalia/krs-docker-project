
from locust import HttpUser, task, between


class KRSUser(HttpUser):
    # Jeda antarpermintaan setiap pengguna
    wait_time = between(1, 2)

    @task
    def akses_data_krs(self):
        with self.client.get(
            "/krs",
            name="GET /krs",
            catch_response=True
        ) as response:

            if response.status_code == 200:
                try:
                    data = response.json()

                    if data.get("status") == "success":
                        response.success()
                    else:
                        response.failure("Status API bukan success")

                except Exception:
                    response.failure("Respons bukan JSON valid")
            else:
                response.failure(
                    f"HTTP Error: {response.status_code}"
                )
