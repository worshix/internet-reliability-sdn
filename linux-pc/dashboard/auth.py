from flask_login import UserMixin
from werkzeug.security import generate_password_hash
from database import get_db


class User(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

    @staticmethod
    def get_by_id(user_id):
        conn = get_db()
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        conn.close()
        return User(row["id"], row["username"], row["password_hash"]) if row else None

    @staticmethod
    def get_by_username(username):
        conn = get_db()
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()
        return User(row["id"], row["username"], row["password_hash"]) if row else None

    def update_password(self, new_password):
        conn = get_db()
        conn.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (generate_password_hash(new_password), self.id),
        )
        conn.commit()
        conn.close()
