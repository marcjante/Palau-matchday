# HC Palau — Frontend de estadísticas en directo

Interfaz web que conecta con el backend de Python (`hcpalau-backend`). Pensada
para usar en el móvil o tablet durante el partido, con voz y también 100%
funcional a botón.

## Novedades de esta versión

- **Contexto activo ("jugador pegado")**: di "jugador 5" una vez y luego solo
  hace falta decir la acción ("gol", "pierde", "recupera"...) hasta que
  cambies de jugador. Se ve en pantalla en todo momento en el recuadro verde
  superior.
- **Confirmación por voz (TTS)**: el móvil dice en alto lo que ha registrado
  ("Registrado: Jugador 5, Gol") para no tener que mirar la pantalla. Se
  puede desactivar con la casilla si molesta.
- **Botón "Deshacer" fijo**: siempre visible en la parte inferior, funciona
  con un toque sin depender de la voz.

## Cómo usarla

1. Abre `index.html` **desde un servidor**, no con doble clic — el
   reconocimiento de voz necesita https:// o localhost (igual que el
   backend). Para probar en local:
   ```
   python3 -m http.server 8080
   ```
   y abre `http://localhost:8080` en Chrome. Para uso real, súbela a GitHub
   Pages.
2. En la primera pantalla, pon la URL de tu backend desplegado (Railway/
   Render) y tu `API_KEY`. Se guarda en este dispositivo, no hace falta
   repetirlo cada vez.
3. Selecciona o crea tu equipo, añade jugadores (marca quién es portero/a),
   selecciona o crea el rival, y pulsa "Empezar partido".
4. Recomendado para partido real: usa auriculares o un micro de solapa —
   mejora mucho el reconocimiento con el ruido del pabellón frente al micro
   del móvil a distancia.
