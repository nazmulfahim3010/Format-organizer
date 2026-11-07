"""Helpers shared by the API tests (the `client` fixture lives in conftest.py)."""
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def auth(client, email="a@example.org"):
    r = client.post("/api/auth/register", json={"email": email, "password": "password123", "name": "A"})
    if r.status_code == 409:
        r = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def upload_template(client, headers, path, name="Uni"):
    with open(path, "rb") as f:
        r = client.post("/api/templates/upload", headers=headers,
                        files={"file": ("t.docx", f, DOCX)}, data={"name": name})
    assert r.status_code == 200, r.text
    return r.json()
