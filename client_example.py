"""
Example client script to interact with the Support Multi-Agent API.

Usage:
    python client_example.py
"""

import json
import requests
from typing import Optional

BASE_URL = "http://localhost:8000"


def login(username: str, password: str) -> Optional[str]:
    """Authenticate and get access token."""
    response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"username": username, "password": password},
    )
    if response.status_code == 200:
        return response.json()["access_token"]
    else:
        print(f"Login failed: {response.status_code} {response.text}")
        return None


def query_support(
    token: str, question: str, product: Optional[str] = None, version: Optional[str] = None
) -> dict:
    """Submit a support query."""
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "question": question,
        "metadata": {
            "product": product,
            "version": version,
        },
    }
    response = requests.post(
        f"{BASE_URL}/query",
        json=payload,
        headers=headers,
    )
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Query failed: {response.status_code} {response.text}")
        return {}


def submit_feedback(
    token: str, request_id: str, helpful: bool, comment: Optional[str] = None
) -> dict:
    """Submit feedback on a response."""
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "request_id": request_id,
        "helpful": helpful,
        "comment": comment,
    }
    response = requests.post(
        f"{BASE_URL}/feedback",
        json=payload,
        headers=headers,
    )
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Feedback submission failed: {response.status_code} {response.text}")
        return {}


def create_rca(
    token: str, symptom: str, root_cause: str, resolution: str, product: Optional[str] = None
) -> dict:
    """Create a root cause analysis record."""
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "symptom": symptom,
        "root_cause": root_cause,
        "resolution": resolution,
        "product": product,
    }
    response = requests.post(
        f"{BASE_URL}/rca",
        json=payload,
        headers=headers,
    )
    if response.status_code == 200:
        return response.json()
    else:
        print(f"RCA creation failed: {response.status_code} {response.text}")
        return {}


def main():
    """Run example interactions."""
    print("=== Support Multi-Agent API Example ===\n")

    # 1. Login
    print("1. Authenticating...")
    token = login("support", "support123")
    if not token:
        print("Failed to authenticate. Ensure the API is running and the database is seeded.")
        return
    print(f"✓ Logged in successfully\n")

    # 2. Submit a support query
    print("2. Submitting support query...")
    query_result = query_support(
        token,
        question="How do I fix a database connection error?",
        product="MyApp",
        version="1.2.3",
    )
    if query_result:
        print(f"✓ Query successful")
        print(f"  Answer: {query_result.get('answer', 'N/A')[:100]}...")
        print(f"  Confidence: {query_result.get('confidence', 0):.2f}")
        print(f"  Request ID: {query_result.get('request_id', 'N/A')}\n")

        request_id = query_result.get("request_id")

        # 3. Submit feedback
        if request_id:
            print("3. Submitting feedback...")
            feedback_result = submit_feedback(
                token, request_id, helpful=True, comment="This was very helpful!"
            )
            if feedback_result:
                print(f"✓ Feedback submitted\n")

        # 4. Create an RCA record
        print("4. Creating RCA record...")
        rca_result = create_rca(
            token,
            symptom="Database connection timeout",
            root_cause="Connection pool exhaustion due to slow queries",
            resolution="Optimize slow queries and increase pool size",
            product="MyApp",
        )
        if rca_result:
            print(f"✓ RCA created with ID: {rca_result.get('id', 'N/A')}\n")

    print("=== Example Complete ===")


if __name__ == "__main__":
    main()
