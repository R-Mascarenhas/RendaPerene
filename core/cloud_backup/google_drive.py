"""Desktop authorization and narrowly scoped Google Drive backup storage."""

import json
import logging
import re
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import requests

from core.cloud_backup.models import (
    CloudAuthorizationError,
    CloudBackupArtifact,
    CloudBackupError,
    OAuthClientConfiguration,
    RemoteBackup,
)
from core.cloud_backup.package import MAX_PACKAGE_BYTES, PACKAGE_KIND
from core.ports import CredentialVaultPort

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
DRIVE_API = "https://www.googleapis.com/drive/v3"
TOKEN_URI = "https://oauth2.googleapis.com/token"
HTTP_TIMEOUT = (5, 30)
AUTHORIZATION_TIMEOUT_SECONDS = 180
FILE_FIELDS = "id,name,version,modifiedTime,appProperties"
FOLDER_KIND = "rendaperene-backup-folder"
logger = logging.getLogger(__name__)


def load_oauth_client(path: Path) -> OAuthClientConfiguration:
    try:
        configuration = json.loads(path.read_text(encoding="utf-8"))
        payload = configuration["installed"]
        if set(configuration) != {"installed"} or set(payload) - {
            "client_id",
            "client_secret",
            "project_id",
            "auth_uri",
            "token_uri",
            "auth_provider_x509_cert_url",
            "redirect_uris",
        }:
            raise ValueError("Unexpected desktop OAuth fields.")
        client_id = payload["client_id"]
        secret = payload.get("client_secret", "")
        if (
            not isinstance(client_id, str)
            or not client_id
            or client_id.startswith("YOUR_")
            or not isinstance(secret, str)
        ):
            raise ValueError("Invalid desktop OAuth configuration.")
        return OAuthClientConfiguration(client_id, secret)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise CloudBackupError(
            "Configure o cliente OAuth desktop do Google para habilitar a conexão com o Drive."
        ) from None


def authorize_desktop(
    client: OAuthClientConfiguration,
    *,
    open_browser: Callable[[str], bool] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    """Use PKCE/state with a bounded loopback listener and no request logging."""
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        {
            "installed": {
                "client_id": client.client_id,
                "client_secret": client.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": TOKEN_URI,
                "redirect_uris": ["http://127.0.0.1"],
            }
        },
        scopes=[DRIVE_SCOPE],
        autogenerate_code_verifier=True,
    )
    callback = {}
    logger.info("google_oauth.authorization.started")

    class LoopbackServer(HTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(2)
            return connection, address

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            pass

        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            if parsed.path != "/" or query.get("state") != [callback.get("state")]:
                logger.warning("google_oauth.callback.rejected reason=state_or_path")
                self.send_error(400, "Resposta inválida")
                return
            if query.get("error"):
                callback["error"] = True
                logger.info("google_oauth.callback.cancelled")
            elif len(query.get("code", [])) == 1:
                callback["code"] = query["code"][0]
                logger.info("google_oauth.callback.accepted")
            else:
                logger.warning("google_oauth.callback.rejected reason=missing_code")
                self.send_error(400, "Resposta inválida")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Pode fechar esta janela e voltar ao RendaPerene.")

    try:
        with LoopbackServer(("127.0.0.1", 0), Handler) as server:
            server.timeout = 1
            flow.redirect_uri = f"http://127.0.0.1:{server.server_port}/"
            authorization_url, state = flow.authorization_url(
                access_type="offline", prompt="consent"
            )
            callback["state"] = state
            logger.info("google_oauth.listener.ready")
            if cancelled is not None and cancelled():
                raise CloudAuthorizationError("A conexão com o Google foi cancelada.")
            if open_browser is None or not open_browser(authorization_url):
                raise CloudAuthorizationError(
                    "Não foi possível abrir o navegador para conectar ao Google."
                )
            logger.info("google_oauth.authorization.url_delivered")
            deadline = time.monotonic() + AUTHORIZATION_TIMEOUT_SECONDS
            while "code" not in callback and "error" not in callback:
                if cancelled is not None and cancelled():
                    raise CloudAuthorizationError("A conexão com o Google foi cancelada.")
                if time.monotonic() >= deadline:
                    logger.warning("google_oauth.authorization.timed_out")
                    raise CloudAuthorizationError(
                        "A conexão com o Google expirou. Tente novamente."
                    )
                server.handle_request()
            if callback.get("error"):
                raise CloudAuthorizationError("A conexão com o Google foi cancelada.")
            logger.info("google_oauth.token_exchange.started")
            flow.fetch_token(code=callback["code"], timeout=HTTP_TIMEOUT)
            logger.info("google_oauth.token_exchange.completed")
            if cancelled is not None and cancelled():
                raise CloudAuthorizationError("A conexão com o Google foi cancelada.")
            return json.loads(flow.credentials.to_json())
    except CloudBackupError as error:
        logger.warning("google_oauth.authorization.failed error_type=%s", type(error).__name__)
        raise
    except Exception as error:
        logger.warning("google_oauth.authorization.failed error_type=%s", type(error).__name__)
        raise CloudAuthorizationError(
            "Não foi possível concluir a autorização do Google."
        ) from None


class GoogleDriveBackupProvider:
    def __init__(
        self,
        client: OAuthClientConfiguration,
        vault: CredentialVaultPort,
        *,
        http=None,
        authorize: Callable = authorize_desktop,
    ):
        self._client = client
        self._vault = vault
        self._http = http or requests.Session()
        self._authorize = authorize
        self._credential = None
        self._authorizing = False
        self._folder_id = None
        self._folder_ids = ()
        self._lock = threading.RLock()

    def connect(self) -> str:
        with self._lock:
            logger.info("google_oauth.vault.check_started")
            self._vault.ensure_available()
            logger.info("google_oauth.vault.check_completed")
            credential = self._authorize(self._client)
            if not credential.get("refresh_token"):
                raise CloudAuthorizationError(
                    "O Google não autorizou acesso duradouro. Conecte novamente."
                )
            self._credential = credential
            self._folder_id = None
            self._authorizing = True
            try:
                account = self._account_id()
                logger.info("google_oauth.account.verified")
                self._vault.write(json.dumps(credential))
                logger.info("google_oauth.credentials.saved")
                return account
            except CloudBackupError:
                self._credential = None
                raise CloudBackupError(
                    "A conexão não pôde ser salva. Revogue o acesso nas permissões da conta Google "
                    "e tente novamente com o cofre desbloqueado."
                ) from None
            finally:
                self._authorizing = False

    def resume(self) -> str | None:
        with self._lock:
            serialized = self._vault.read()
            if serialized is None:
                return None
            self._vault.ensure_available()
            try:
                credential = json.loads(serialized)
                if (
                    not isinstance(credential, dict)
                    or credential.get("client_id") != self._client.client_id
                    or not credential.get("refresh_token")
                ):
                    raise ValueError("Invalid stored credentials.")
                self._credential = credential
                return self._account_id()
            except (ValueError, CloudAuthorizationError):
                self._credential = None
                raise CloudAuthorizationError("A conexão Google precisa ser refeita.") from None

    def disconnect(self) -> None:
        with self._lock:
            self._credential = None
            self._folder_id = None
            try:
                self._vault.delete()
            except CloudBackupError:
                raise CloudBackupError(
                    "A conexão foi interrompida, mas os tokens não puderam ser removidos do cofre. "
                    "Tente desconectar novamente ou remova-os no cofre do sistema."
                ) from None

    def _account_id(self) -> str:
        response = self._request(
            "GET", f"{DRIVE_API}/about", params={"fields": "user(permissionId)"}
        )
        try:
            account = response.json().get("user", {}).get("permissionId")
            if not isinstance(account, str) or not account:
                raise ValueError("Invalid account identifier.")
            return account
        except (ValueError, AttributeError, TypeError):
            raise CloudAuthorizationError(
                "Não foi possível identificar a conta conectada."
            ) from None
        finally:
            response.close()

    def _token(self) -> str:
        from google.auth.exceptions import TransportError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        serialized = self._vault.read()
        if not serialized and not self._authorizing:
            self._credential = None
            raise CloudAuthorizationError("Conecte novamente sua conta Google.")
        if self._credential is None:
            try:
                self._credential = json.loads(serialized) if serialized else None
            except ValueError:
                self._credential = None
        if (
            not isinstance(self._credential, dict)
            or self._credential.get("client_id") != self._client.client_id
        ):
            raise CloudAuthorizationError("Conecte novamente sua conta Google.")
        if not self._authorizing:
            try:
                stored = json.loads(serialized)
                if not isinstance(stored, dict) or stored.get(
                    "refresh_token"
                ) != self._credential.get("refresh_token"):
                    raise ValueError("Authorization changed in another process.")
            except (ValueError, TypeError):
                self._credential = None
                raise CloudAuthorizationError(
                    "A conexão Google mudou. Conecte novamente."
                ) from None
        try:
            credentials = Credentials.from_authorized_user_info(
                {**self._credential, "client_secret": self._client.client_secret},
                scopes=[DRIVE_SCOPE],
            )
            if not credentials.valid:

                class BoundedRequest(Request):
                    def __call__(self, *args, **kwargs):
                        kwargs["timeout"] = HTTP_TIMEOUT
                        return super().__call__(*args, **kwargs)

                credentials.refresh(BoundedRequest())
                self._credential = json.loads(credentials.to_json())
                self._vault.write(json.dumps(self._credential))
            return credentials.token
        except CloudBackupError:
            raise
        except (TransportError, requests.RequestException):
            raise CloudBackupError(
                "Não foi possível renovar a conexão Google. Tente novamente mais tarde."
            ) from None
        except Exception:
            raise CloudAuthorizationError(
                "A autorização Google expirou ou foi revogada. Conecte novamente."
            ) from None

    def _request(self, method: str, url: str, **kwargs):
        try:
            headers = kwargs.pop("headers", {})
            headers["Authorization"] = f"Bearer {self._token()}"
            response = self._http.request(
                method, url, headers=headers, timeout=HTTP_TIMEOUT, **kwargs
            )
            if response.status_code == 401:
                response.close()
                raise CloudAuthorizationError(
                    "O Google recusou a operação. Verifique a conexão e as permissões."
                )
            if not 200 <= response.status_code < 300:
                response.close()
                raise CloudBackupError(
                    "O Google Drive não concluiu a operação. Tente novamente mais tarde."
                )
            return response
        except requests.RequestException:
            raise CloudBackupError(
                "Não foi possível acessar o Google Drive. Verifique sua conexão."
            ) from None

    def _list(self, query: str) -> tuple[dict, ...]:
        files = []
        token = None
        seen_tokens = set()
        while len(seen_tokens) < 100:
            params = {
                "q": query,
                "spaces": "drive",
                "fields": f"nextPageToken,incompleteSearch,files({FILE_FIELDS})",
                "pageSize": 100,
            }
            if token:
                params["pageToken"] = token
            response = self._request("GET", f"{DRIVE_API}/files", params=params)
            try:
                payload = response.json()
                if payload.get("incompleteSearch") or not isinstance(payload.get("files"), list):
                    raise CloudBackupError("A listagem do Drive está incompleta. Tente novamente.")
                files.extend(payload["files"])
                token = payload.get("nextPageToken")
                if not token:
                    return tuple(files)
                if not isinstance(token, str) or token in seen_tokens:
                    raise CloudBackupError("A listagem do Drive está incompleta. Tente novamente.")
                seen_tokens.add(token)
            except (ValueError, AttributeError, TypeError):
                raise CloudBackupError("O Google Drive retornou uma listagem inválida.") from None
            finally:
                response.close()
        raise CloudBackupError("A listagem do Drive excede o limite suportado. Revise os backups.")

    def _folder(self, *, create: bool) -> str | None:
        if self._folder_id:
            return self._folder_id
        found = self._list(
            "trashed = false and mimeType = 'application/vnd.google-apps.folder' "
            f"and appProperties has {{ key='kind' and value='{FOLDER_KIND}' }}"
        )
        if found:
            self._folder_ids = tuple(
                sorted({self._valid_file_id(item.get("id")) for item in found})
            )
            self._folder_id = self._folder_ids[0]
        elif create:
            response = self._request(
                "POST",
                f"{DRIVE_API}/files",
                params={"fields": "id"},
                json={
                    "name": "RendaPerene",
                    "mimeType": "application/vnd.google-apps.folder",
                    "appProperties": {"kind": FOLDER_KIND},
                },
            )
            try:
                self._folder_id = self._valid_file_id(response.json().get("id"))
            finally:
                response.close()
            # Another installation may have created a folder concurrently. Keep
            # every folder discoverable and converge new writes without deleting backups.
            created_id = self._folder_id
            found = self._list(
                "trashed = false and mimeType = 'application/vnd.google-apps.folder' "
                f"and appProperties has {{ key='kind' and value='{FOLDER_KIND}' }}"
            )
            self._folder_ids = tuple(
                sorted({created_id, *(self._valid_file_id(item.get("id")) for item in found)})
            )
            self._folder_id = self._folder_ids[0]
        return self._folder_id

    def list_backups(self) -> tuple[RemoteBackup, ...]:
        with self._lock:
            # Re-resolve the folder so a deleted or trashed folder is never reused.
            self._folder_id = None
            self._folder_ids = ()
            folder = self._folder(create=False)
            if not folder:
                return ()
            parents = " or ".join(f"'{item}' in parents" for item in self._folder_ids)
            return tuple(
                self._parse_remote(item)
                for item in self._list(
                    f"trashed = false and ({parents}) "
                    f"and appProperties has {{ key='kind' and value='{PACKAGE_KIND}' }}"
                )
            )

    def upload(self, artifact: CloudBackupArtifact) -> RemoteBackup:
        with self._lock:
            matches = [
                remote
                for remote in self.list_backups()
                if remote.portfolio_id == artifact.portfolio_id
                and remote.installation_id == artifact.installation_id
            ]
            if len(matches) > 1:
                raise CloudBackupError(
                    "Há backups duplicados desta carteira e computador. Nenhum foi sobrescrito."
                )
            folder = self._folder(create=True)
            name = (
                re.sub(r"[^\w .-]", "_", f"{artifact.display_name}_{artifact.machine_name}")[:180]
                + ".rpbc"
            )
            properties = {
                "kind": PACKAGE_KIND,
                "portfolio_id": artifact.portfolio_id,
                "installation_id": artifact.installation_id,
                "display_name": artifact.display_name.encode("utf-8")[:100].decode(
                    "utf-8", errors="ignore"
                ),
                "machine_name": artifact.machine_name.encode("utf-8")[:100].decode(
                    "utf-8", errors="ignore"
                ),
            }
            metadata = {"name": name, "mimeType": "application/zip", "appProperties": properties}
            if not matches:
                metadata["parents"] = [folder]
            url = "https://www.googleapis.com/upload/drive/v3/files"
            if matches:
                url += f"/{matches[0].file_id}"
            if len(artifact.content) > 5 * 1024 * 1024:
                return self._upload_large(url, bool(matches), metadata, artifact.content)
            boundary = uuid.uuid4().hex
            payload = (
                f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()
                + json.dumps(metadata, ensure_ascii=False).encode()
                + f"\r\n--{boundary}\r\nContent-Type: application/zip\r\n\r\n".encode()
                + artifact.content
                + f"\r\n--{boundary}--\r\n".encode()
            )
            response = self._request(
                "PATCH" if matches else "POST",
                url,
                params={"uploadType": "multipart", "fields": FILE_FIELDS},
                headers={"Content-Type": f"multipart/related; boundary={boundary}"},
                data=payload,
            )
            try:
                return self._parse_remote(response.json())
            finally:
                response.close()

    def _upload_large(
        self, url: str, updating: bool, metadata: dict, content: bytes
    ) -> RemoteBackup:
        response = self._request(
            "PATCH" if updating else "POST",
            url,
            params={"uploadType": "resumable", "fields": FILE_FIELDS},
            json=metadata,
            headers={
                "X-Upload-Content-Type": "application/zip",
                "X-Upload-Content-Length": str(len(content)),
            },
        )
        try:
            location = response.headers.get("Location", "")
            parsed = urlsplit(location)
            if (
                parsed.scheme != "https"
                or parsed.netloc != "www.googleapis.com"
                or not parsed.path.startswith("/upload/drive/v3/files")
            ):
                raise CloudBackupError("O Drive retornou uma sessão de envio inválida.")
        finally:
            response.close()
        response = self._request(
            "PUT",
            location,
            headers={"Content-Type": "application/zip"},
            data=content,
        )
        try:
            return self._parse_remote(response.json())
        finally:
            response.close()

    def download(self, backup: RemoteBackup) -> bytes:
        with self._lock:
            current = next(
                (item for item in self.list_backups() if item.file_id == backup.file_id), None
            )
            if current != backup:
                raise CloudBackupError(
                    "O backup remoto mudou. Consulte a lista novamente antes de recuperar."
                )
            response = self._request(
                "GET", f"{DRIVE_API}/files/{backup.file_id}", params={"alt": "media"}, stream=True
            )
            try:
                content = bytearray()
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if len(content) + len(chunk) > MAX_PACKAGE_BYTES:
                        raise CloudBackupError(
                            "O backup excede o tamanho suportado para recuperação."
                        )
                    content.extend(chunk)
                return bytes(content)
            except requests.RequestException:
                raise CloudBackupError("O download não foi concluído. Tente novamente.") from None
            finally:
                response.close()

    @staticmethod
    def _valid_file_id(value) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", value):
            raise CloudBackupError("O Google Drive retornou um identificador inválido.")
        return value

    @classmethod
    def _parse_remote(cls, item: dict) -> RemoteBackup:
        try:
            properties = item["appProperties"]
            if properties.get("kind") != PACKAGE_KIND:
                raise ValueError("Invalid backup kind.")
            for key in ("portfolio_id", "installation_id"):
                if str(uuid.UUID(properties[key])) != properties[key]:
                    raise ValueError("Invalid backup identity.")
            if any(
                not isinstance(value, str) or not value.strip()
                for value in (
                    properties["display_name"],
                    properties["machine_name"],
                    item["version"],
                )
            ):
                raise ValueError("Invalid remote backup metadata.")
            modified = datetime.fromisoformat(item["modifiedTime"].replace("Z", "+00:00"))
            if modified.utcoffset() != timezone.utc.utcoffset(modified):
                raise ValueError("Invalid remote backup timestamp.")
            return RemoteBackup(
                cls._valid_file_id(item["id"]),
                properties["portfolio_id"],
                properties["installation_id"],
                properties["display_name"],
                properties["machine_name"],
                item["modifiedTime"],
                item["version"],
            )
        except (KeyError, TypeError, ValueError, AttributeError):
            raise CloudBackupError("Os metadados de um backup no Drive são inválidos.") from None
