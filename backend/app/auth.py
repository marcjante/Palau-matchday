"""
Autenticación mínima por API key.

Como el backend va a estar accesible desde internet (no en red local), hace
falta al menos una barrera básica para que no cualquiera pueda escribir en
la base de datos. Es una clave compartida (no hay usuarios ni contraseñas
individuales) — suficiente para un solo cuerpo técnico, no para un sistema
multiusuario con roles.

La clave se define con la variable de entorno API_KEY. El frontend debe
mandarla en la cabecera 'X-API-Key' en cada petición.
"""
import os
from fastapi import Header, HTTPException, status

API_KEY = os.getenv("API_KEY", "")


def verify_api_key(x_api_key: str = Header(default="")):
    if not API_KEY:
        # Si no se ha configurado ninguna clave (p.ej. en desarrollo local),
        # no se exige autenticación. En producción SIEMPRE hay que definir API_KEY.
        return
    if x_api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key inválida o ausente. Añade la cabecera X-API-Key.",
        )
