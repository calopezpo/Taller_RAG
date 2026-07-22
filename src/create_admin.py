from pathlib import Path
import getpass

from .auth import AuthManager

if __name__ == "__main__":
    db_path = Path("storage/auth.db")
    manager = AuthManager(db_path)

    print("=== Crear usuario administrador ===")
    username = input("Usuario: ").strip()
    password = getpass.getpass("Contraseña: ")

    result = manager.create_user(username, password, "administrador")
    print(result.message)