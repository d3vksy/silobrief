from __future__ import annotations

from pathlib import Path

from silobrief.path_safety import has_link_like_component


class ExampleProjectError(Exception):
    pass


_LOG_COMMAND = 'sb log app.py --comment "JWT 서명 키는 private.jwt의 JWT_SECRET을 사용합니다."'
_SEARCH_COMMAND = 'sb search "로그인 성공 응답"'
_BRIEF_COMMAND = "sb brief"
_TASK_REQUEST = (
    "requirements.txt에 PyJWT를 추가하고 로그인 성공 시 1시간짜리 access_token을 "
    "반환해줘. 토큰에는 user_id와 username만 포함하고, 비밀번호와 private 설정은 "
    "노출하지 마. diff와 테스트를 작성해줘."
)

_README = f"""# Flask 예제

SQLite에 회원을 저장하고 로그인하는 작은 Flask 프로젝트입니다.

```console
python -m pip install -r requirements.txt
python app.py
```

기본 동작은 다음 두 요청입니다.

```text
POST /signup  {{"username": "minsu", "password": "1234"}}
POST /login   {{"username": "minsu", "password": "1234"}}
```

비밀번호는 해시로 저장하며, 로그인 성공 시 아직 JWT를 발급하지 않습니다.

siloBrief 시연은 아래 명령만 순서대로 실행합니다.

```console
sb setup .
sb language --cli ko --brief ko
sb ignore private --as "JWT 설정"
sb init
{_LOG_COMMAND}
{_SEARCH_COMMAND}
{_BRIEF_COMMAND}
```

`작업`에는 아래 문장을 입력합니다.

```text
{_TASK_REQUEST}
```

`정보 추가`에서 `/file`로 `requirements.txt`를 고르고, `/func`로 `app.py`의 `login`을
고른 뒤 Enter를 누릅니다.

생성된 `.silobrief/exports/brief.md`를 확인하면 됩니다. 이 예제의 데이터베이스와
서명 키는 실습 전용입니다.
"""

_FILES = (
    ("README.md", _README),
    (
        "app.py",
        """from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import Flask, request
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
DATABASE_PATH = Path(__file__).with_name("users.db")


def init_db() -> None:
    with sqlite3.connect(DATABASE_PATH) as database:
        database.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "username TEXT UNIQUE NOT NULL, "
            "password_hash TEXT NOT NULL)"
        )


@app.post("/signup")
def signup():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    if not username or not password:
        return {"error": "아이디와 비밀번호가 필요합니다."}, 400

    try:
        with sqlite3.connect(DATABASE_PATH) as database:
            database.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, generate_password_hash(password)),
            )
    except sqlite3.IntegrityError:
        return {"error": "이미 존재하는 아이디입니다."}, 409
    return {"message": "회원가입 성공"}, 201


@app.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))

    with sqlite3.connect(DATABASE_PATH) as database:
        user = database.execute(
            "SELECT id, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if user is None or not check_password_hash(user[1], password):
        return {"error": "아이디 또는 비밀번호가 올바르지 않습니다."}, 401
    return {"message": "로그인 성공"}


if __name__ == "__main__":
    init_db()
    app.run()
""",
    ),
    ("requirements.txt", "Flask\n"),
    (".gitignore", "users.db\n"),
    (
        "private/jwt.py",
        """from __future__ import annotations

JWT_SECRET = "demo-only-change-me"
""",
    ),
)


def create_example_project(target: Path) -> int:
    if has_link_like_component(target):
        raise ExampleProjectError("example path must not contain a symbolic link or reparse point")
    if target.exists():
        if not target.is_dir():
            raise ExampleProjectError("example path must be a directory")
        try:
            if any(target.iterdir()):
                raise ExampleProjectError("example directory must be empty")
        except OSError as error:
            raise ExampleProjectError(f"cannot inspect example directory: {error}") from error
    else:
        try:
            target.mkdir(parents=True)
        except OSError as error:
            raise ExampleProjectError(f"cannot create example directory: {error}") from error

    try:
        for relative, content in _FILES:
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
    except OSError as error:
        raise ExampleProjectError(f"cannot write example project: {error}") from error
    return len(_FILES)
