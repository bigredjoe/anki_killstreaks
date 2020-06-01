from urllib.parse import urljoin
import requests

from ._vendor import attr

from .networking import sra_base_url, shared_headers


class UserRepository:
    def __init__(self, get_db_connection):
        self.get_db_connection = get_db_connection

    def save(self, uid, token, client, expiry):
        with self.get_db_connection() as conn:
            conn.execute(
                """
                UPDATE users
                SET uid = ?,
                    token = ?,
                    client = ?,
                    expiry = ?
                """,
                (uid, token, client, expiry)
            )

    def load(self):
        with self.get_db_connection() as conn:
            cursor = conn.execute("SELECT * FROM users")
            user_attrs = cursor.fetchone()
            return PersistedUser(*user_attrs)


@attr.s(frozen=True)
class PersistedUser:
    id_ = attr.ib()
    uid = attr.ib()
    token = attr.ib()
    client = attr.ib()
    expiry = attr.ib()
    token_type = attr.ib()


def login(email, password, listener, user_repo, shared_headers=shared_headers):
    body = dict(
        email=email,
        password=password,
    )
    url = urljoin(sra_base_url, "api/v1/auth/sign_in")

    try:
        response = requests.post(url, headers=shared_headers, json=body)

        print(response.status_code)
        print(response.text)

        if response.status_code == 200:
            store_auth_headers(user_repo, response.headers)
            listener.logged_in.emit(response.json()["data"])
        elif response.status_code == 401:
            listener.unauthorized_login.emit(response.json())
        else:
            raise RuntimeError("Unhandled response status", response)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        listener.on_connection_error()


def store_auth_headers(user_repo, headers):
    user_repo.save(
        uid=headers["uid"],
        token=headers["access-token"],
        client=headers["client"],
        expiry=headers["expiry"],
    )

# TODO try catch for timeout, server down
def logout(user_repo, listener, shared_headers=shared_headers):
    url = urljoin(sra_base_url, "api/v1/auth/sign_out")

    auth_headers = load_auth_headers(user_repo)

    headers = shared_headers.copy()
    headers.update(auth_headers)

    response = requests.delete(
        url,
        headers=headers
    )

    if response.status_code == 200:
        _clear_auth_headers(user_repo)
        listener.logged_out.emit()
    elif response.status_code == 404:
        listener.logout_error.emit(response.json())
    else:
        raise RuntimeError("Unhandled response status", response)


def load_auth_headers(user_repo):
    user = user_repo.load()
    headers = attr.asdict(user)

    headers["access-token"] = headers.pop("token")
    headers["token-type"] = headers.pop("token_type")
    del headers["id_"]

    return headers


def _clear_auth_headers(user_repo):
    user_repo.save(
        uid="",
        token="",
        client="",
        expiry="",
    )


def check_user_logged_in(user_repo):
    user = user_repo.load()
    return user.token and user.uid


# TODO try catch for timeout, server down
def validate_token(user_repo, listener, shared_headers=shared_headers):
    auth_headers = load_auth_headers(user_repo)

    headers = shared_headers.copy()
    headers.update(auth_headers)

    response = requests.get(
        url=urljoin(sra_base_url, "api/v1/auth/validate_token"),
        headers=headers,
    )

    if response.status_code == 200:
        store_auth_headers(user_repo, response.headers)
    elif response.status_code == 401:
        _clear_auth_headers(user_repo)
        listener.token_invalidated.emit(response.json())
    else:
        raise RuntimeError("Unhandled response status", response)