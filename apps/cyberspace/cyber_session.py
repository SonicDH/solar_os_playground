"""Opt-in Cyberspace refresh-token persistence."""

import json


class SessionStore:
    def __init__(self, path, storage=None):
        self.path = path
        self.temporary_path = path + ".new"
        self.storage = storage

    def load(self):
        try:
            with open(self.path, "r") as source:
                document = json.loads(source.read())
        except (OSError, ValueError, TypeError):
            return None
        if not isinstance(document, dict):
            return None
        email = document.get("email")
        refresh_token = document.get("refreshToken")
        if not isinstance(email, str) or not isinstance(refresh_token, str):
            return None
        if not email or not refresh_token:
            return None
        return {"email": email, "refreshToken": refresh_token}

    def save(self, email, refresh_token):
        if not isinstance(email, str) or not isinstance(refresh_token, str):
            raise ValueError("email and refresh token must be text")
        document = {"email": email, "refreshToken": refresh_token}
        encoded = json.dumps(document)
        with open(self.temporary_path, "w") as output:
            output.write(encoded)
            output.write("\n")
        self._replace()

    def clear(self):
        self._remove(self.temporary_path)
        self._remove(self.path)

    def exists(self):
        try:
            with open(self.path, "r"):
                return True
        except OSError:
            return False

    def _replace(self):
        self._remove(self.path)
        if self.storage is not None and hasattr(self.storage, "rename"):
            self.storage.rename(self.temporary_path, self.path)
            return
        import os
        os.rename(self.temporary_path, self.path)

    def _remove(self, path):
        try:
            if self.storage is not None and hasattr(self.storage, "remove"):
                self.storage.remove(path)
            else:
                import os
                os.remove(path)
        except OSError:
            pass
