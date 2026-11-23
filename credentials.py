import os


class CredentialStoreError(RuntimeError):
    pass


def _credential_api():
    if os.name != "nt":
        raise CredentialStoreError(
            "As credenciais deste aplicativo exigem o Gerenciador "
            "de Credenciais do Windows."
        )

    try:
        import win32cred
        import pywintypes
    except ImportError as error:
        raise CredentialStoreError(
            "O suporte ao Gerenciador de Credenciais do Windows não está "
            "instalado. Instale as dependências do projeto."
        ) from error

    return win32cred, pywintypes


def save_password(target, username, password):
    if not username.strip():
        raise CredentialStoreError("Informe o usuário do hotel.")
    if not password:
        raise CredentialStoreError("Informe uma senha para o hotel.")

    api, pywintypes = _credential_api()
    try:
        api.CredWrite(
            {
                "Type": api.CRED_TYPE_GENERIC,
                "TargetName": target,
                "CredentialBlob": password,
                "Persist": api.CRED_PERSIST_LOCAL_MACHINE,
                "UserName": username,
                "Comment": "Credencial PMS Report Automation",
            },
            0,
        )
    except pywintypes.error as error:
        raise CredentialStoreError(
            "Não foi possível salvar a credencial no Gerenciador "
            "de Credenciais do Windows."
        ) from error


def read_password(target):
    api, pywintypes = _credential_api()
    try:
        credential = api.CredRead(target, api.CRED_TYPE_GENERIC, 0)
    except pywintypes.error as error:
        if error.args and error.args[0] in (2, 1168):
            return None
        raise CredentialStoreError(
            "Não foi possível ler a credencial no Gerenciador "
            "de Credenciais do Windows."
        ) from error

    password = credential.get("CredentialBlob")
    if isinstance(password, bytes):
        password = password.decode("utf-16-le")
    return password


def delete_password(target):
    api, pywintypes = _credential_api()
    try:
        api.CredDelete(target, api.CRED_TYPE_GENERIC, 0)
    except pywintypes.error as error:
        if error.args and error.args[0] in (2, 1168):
            return
        raise CredentialStoreError(
            "Não foi possível remover a credencial do Gerenciador "
            "de Credenciais do Windows."
        ) from error
