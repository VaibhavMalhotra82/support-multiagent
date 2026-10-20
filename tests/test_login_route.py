import unittest
import io
import re

from fastapi.testclient import TestClient

from app import auth, db, observability
from app.main import app


class LoginRouteCompatibilityTests(unittest.TestCase):
    def setUp(self):
        db.init_db()
        session = db.SessionLocal()
        try:
            session.query(db.SessionToken).delete()
            session.query(db.User).filter(db.User.username == "support").delete(synchronize_session=False)
            session.commit()

            user = db.User(
                username="support",
                hashed_password=auth.hash_password("support123"),
                is_active=True,
            )
            session.add(user)
            session.commit()
        finally:
            session.close()

    def test_get_login_route_returns_compatibility_message(self):
        client = TestClient(app)
        response = client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn("POST /login", response.json()["detail"])

    def test_post_login_route_accepts_legacy_alias(self):
        client = TestClient(app)
        response = client.post("/login", json={"username": "support", "password": "support123"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("access_token", response.json())
        self.assertEqual(response.json()["username"], "support")

    def test_login_logs_include_request_id(self):
        stream = io.StringIO()
        handler = observability.logger.handlers[0].__class__(stream)
        handler.setFormatter(observability.logger.handlers[0].formatter)
        observability.logger.addHandler(handler)
        try:
            response = TestClient(app).post(
                "/auth/login", json={"username": "support", "password": "support123"}
            )
        finally:
            observability.logger.removeHandler(handler)
            handler.close()

        self.assertEqual(response.status_code, 200)
        request_ids = re.findall(
            r"step=auth\.(?:authenticate_user|create_session_token) request_id=([^ ]+)",
            stream.getvalue(),
        )
        self.assertGreaterEqual(len(request_ids), 2)
        self.assertEqual(len(set(request_ids)), 1)
        self.assertNotEqual(request_ids[0], "-")

    def test_admin_activity_returns_persisted_login_event(self):
        client = TestClient(app)
        login_response = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
        token = login_response.json()["access_token"]

        admin_activity = client.get("/admin/activity", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(admin_activity.status_code, 200)
        self.assertGreaterEqual(admin_activity.json()["total"], 1)
        self.assertTrue(any(item["event_type"] == "login" for item in admin_activity.json()["items"]))

    def test_admin_activity_supports_limit_and_offset(self):
        client = TestClient(app)
        login_response = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        first_page = client.get("/admin/activity?limit=1&offset=0", headers=headers)
        second_page = client.get("/admin/activity?limit=1&offset=1", headers=headers)

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(len(first_page.json()["items"]), 1)
        self.assertEqual(len(second_page.json()["items"]), 1)
        self.assertEqual(first_page.json()["total"], second_page.json()["total"])
        self.assertGreaterEqual(
            first_page.json()["items"][0]["id"],
            second_page.json()["items"][0]["id"],
        )

    def test_logout_revokes_the_current_token(self):
        client = TestClient(app)
        first_login = client.post("/auth/login", json={"username": "support", "password": "support123"})
        second_login = client.post("/auth/login", json={"username": "support", "password": "support123"})
        first_token = first_login.json()["access_token"]
        second_token = second_login.json()["access_token"]

        logout_response = client.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {second_token}"},
        )
        self.assertEqual(logout_response.status_code, 200)
        self.assertEqual(logout_response.json(), {"status": "ok"})

        first_protected_response = client.get(
            "/admin/stats",
            headers={"Authorization": f"Bearer {first_token}"},
        )
        second_protected_response = client.get(
            "/admin/stats",
            headers={"Authorization": f"Bearer {second_token}"},
        )
        self.assertEqual(first_protected_response.status_code, 401)
        self.assertEqual(second_protected_response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
