

## Aviso

Este juego dejará de ser de código abierto pronto.

El repositorio podría volverse privado o dejar de recibir actualizaciones públicas de código fuente en un futuro cercano. Las versiones existentes publicadas bajo la licencia actual permanecerán sujetas a dicha licencia, pero las versiones futuras podrían distribuirse bajo un modelo diferente.

Gracias a todos los que han seguido o apoyado el proyecto.

# Subway Surfers Blind Edition

Corredor infinito accesible inspirado en el ritmo basado en carriles y el ciclo de reacción de Subway Surfers, diseñado para jugarse principalmente con teclado e incluye retroalimentación por voz, audio espacial, soporte HRTF e integración amigable con lectores de pantalla de Windows.

Este proyecto está diseñado como una base de código de juego de código abierto que se puede ejecutar desde el código fuente durante el desarrollo o empaquetarse en una compilación de escritorio para Windows con PyInstaller.

## Características destacadas

- Jugabilidad solo con teclado con retroalimentación hablada de carriles, peligros, recompensas y menús
- Advertencias espaciales de peligros con salida OpenAL compatible con HRTF a través de `pyopenalsoft`
- Múltiples backends de voz: `accessible_output2` por defecto, voces opcionales de Microsoft SAPI en Windows
- Sistema de audio en capas con señales de menú, efectos de sonido del juego, pulsos de advertencia ambientales y reproducción de música
- Escalado de dificultad con patrones de generación legibles en lugar de spam puramente aleatorio de obstáculos
- Tienda, consumibles, flujo de revivir, hoverboards, ventajas iniciales (headstarts), potenciadores de puntuación, cajas misteriosas y mejoras de personaje
- Sistemas de progresión que incluyen misiones, Word Hunt, Season Hunt, recompensas de Cajas Misteriosas Super, logros y desbloqueo persistente de personajes
- Actualizador de GitHub Releases integrado en el menú del juego
- Especificación PyInstaller para distribuir una compilación de Windows con activos empaquetados y dependencias nativas

## Resumen de jugabilidad

El ciclo principal de carrera se basa en carriles:

- Muévete entre los carriles izquierdo, centro y derecho
- Salta sobre barreras bajas y arbustos
- Deslízate por debajo de barreras altas
- Evita trenes y reacciona a los avisos de peligro hablados
- Recolecta monedas, llaves, potenciadores, cajas misteriosas, letras de Word Hunt y tokens de Season Hunt

El juego rastrea la puntuación de la carrera, monedas guardadas, consumibles, métricas de misiones, progresión de personajes y estado de progresión entre sesiones.

## Accesibilidad y Audio

La accesibilidad es el objetivo de diseño central del proyecto.

### Soporte de voz y menús

- Los menús son completamente navegables con el teclado
- El enfoque del menú se anuncia a través de la voz
- Los estados de abrir, mover, límite, confirmar y cerrar menú tienen señales de audio dedicadas
- La jugabilidad puede anunciar cambios de carril, hitos de monedas, eventos de recompensa y acciones urgentes de obstáculos
- La voz se puede alternar durante la jugabilidad con `M`
- La gestión de voces SAPI de Windows está disponible a través de `Opciones -> Configuración de SAPI`

### Stack de audio

- `pygame` gestiona la ventana principal, la entrada del teclado, la mezcla y la reproducción de música
- `pyopenalsoft` impulsa la ruta de sonido 3D compatible con HRTF
- `accessible_output2` proporciona la abstracción de voz asistiva predeterminada
- `pywin32` permite la selección directa de voces SAPI en Windows

### Orientación de peligro espacial

El sistema de audio de amenazas rastrea el peligro relevante más cercano en cada carril y genera:

- Pulsos de advertencia direccionales
- Cambios de intensidad basados en la distancia
- Indicaciones habladas como `jump`, `roll`, `turn left` o `turn right`
- Manejo diferente para trenes en comparación con tipos de obstáculos más cercanos

### Aprender sonidos del juego

El menú principal incluye un navegador de biblioteca de sonidos dedicado para que los jugadores puedan previsualizar los sonidos del juego y comprender lo que significa cada señal antes de comenzar una carrera.

## Características

### Sistemas principales

- Bucle de carrera infinito con escalado de velocidad basado en la distancia
- Tres perfiles de dificultad: `easy`, `normal`, `hard`
- Generación de obstáculos basada en patrones con verificaciones de jugabilidad
- Detección de aciertos por poco y retroalimentación de audio reactiva
- Flujos de pausa y revivir

### Potenciadores y modificadores de carrera

- Hoverboard
- Headstart
- Score Booster
- Magnet
- Jetpack
- Multiplicador de puntuación doble
- Super Sneakers
- Pogo

### Economía y recompensas

- Banco de monedas persistente
- Llaves
- Hoverboards
- Ventajas iniciales
- Potenciadores de puntuación
- Cajas misteriosas
- Cajas Misteriosas Super
- Desbloqueo de personajes
- Niveles de mejora de personaje

### Progresión

- Conjuntos de misiones con objetivos escalonados
- Word Hunt diario
- Progresión de Season Hunt mensual
- Umbrales de recompensa y pagos desbloqueables por hitos
- Rastreo de logros con anuncios de desbloqueo
- Plantel de personajes con estado de desbloqueo persistente, selección activa y bonificaciones pasivas de carrera

### Sistema de mejora de personajes

La tienda incluye una sección de `Character Upgrades` con un plantel persistente y un flujo de selección de personaje activo.

Plantel actual:

- Jake
- Tricky
- Fresh
- Yutani
- Spike
- Dino
- Boombot

Las bonificaciones de los personajes están vinculadas al corredor activo y se escalan según el nivel de mejora. El sistema actual admite:

- Monedas guardadas adicionales al final de una carrera
- Protección de hoverboard más larga
- Duración más larga de potenciadores temporales
- Multiplicador inicial más alto

### Características de distribución

- Comprobación de actualizaciones de GitHub Releases en el juego
- Flujo de descarga e instalación de actualizaciones para compilaciones empaquetadas
- Especificación de empaquetado de PyInstaller con agrupación de activos

## Controles

El juego admite teclado además de controles Xbox y PlayStation compatibles con SDL, tanto por conexión cableada como por Bluetooth. Abre `Opciones -> Controles` para revisar el dispositivo activo, ver etiquetas de botones específicas del dispositivo y volver a asignar enlaces de teclado o control. Abre `Opciones -> Configuración de SAPI` para gestionar el backend SAPI de Windows, incluido el estado de habilitación, volumen, voz, velocidad y tono.

### En menús

- `Up` / `W`: mover hacia arriba
- `Down` / `S`: mover hacia abajo
- `Home`: saltar al primer elemento
- `End`: saltar al último elemento
- `Enter`: confirmar
- `Escape`: cerrar o volver atrás
- `Left` / `Right`: ajustar valores en los menús de Opciones y Configuración de SAPI

### Durante una carrera

- `Left Arrow`: mover a la izquierda
- `Right Arrow`: mover a la derecha
- `Up Arrow`: saltar
- `Down Arrow`: deslizar
- `Space`: activar hoverboard
- `Escape`: pausar
- `M`: alternar voz

### Disposición predeterminada del control

- `D-Pad Up` / `D-Pad Down`: navegar por los menús
- `A` / `Cross`: confirmar en menús y saltar durante una carrera
- `B` / `Circle`: volver atrás en menús y deslizar durante una carrera
- `Left Stick Left` / `Left Stick Right`: cambiar de carril durante una carrera
- `X` / `Square`: activar hoverboard
- `Y` / `Triangle`: alternar voz
- `Menu` / `Options`: pausar durante una carrera

## Sistema de traducción

El juego admite archivos de idioma externos en la carpeta `langs`.

- Cada traducción debe ser una carpeta dentro de `langs` (por ejemplo, `langs/turkish`)
- Cada carpeta de traducción debe incluir:
  - `manifest.json`
  - Un archivo `.lng` referenciado por `manifest.json`
- `manifest.json` admite:
  - `id`: clave de idioma utilizada por el juego (por ejemplo, `turkish`)
  - `name`: nombre de visualización que se muestra en la selección de idioma
  - `version`: versión de la traducción
  - `author`: creador de la traducción
  - `language_file`: nombre de archivo relativo del archivo `.lng` en la misma carpeta
- Cada línea de traducción utiliza `Texto en inglés [=] Tu traducción`
- Las líneas que comienzan con `;` son comentarios
- La coincidencia no distingue entre mayúsculas y minúsculas
- Se admiten marcadores de posición de parámetros de `%1` a `%9`
- Se admiten marcadores de posición de parámetros traducidos de `%t1` a `%t9` en el lado izquierdo

Puedes cambiar el idioma activo desde `Opciones -> Idioma`.

Ejemplos incluidos:

- `langs/turkish/manifest.json`
- `langs/turkish/turkish.lng`

## Superficie de menús

Los menús actuales orientados al usuario incluyen:

- Menú Principal
  - Iniciar Juego
  - Novedades
  - Tienda
  - Logros
  - Opciones
  - Cómo jugar
  - Aprender sonidos del juego
  - Buscar actualizaciones
  - Salir
- Configuración de carrera
  - Selección de ventaja inicial
  - Selección de potenciador de puntuación
  - Comenzar carrera
- Opciones
  - Volumen de SFX
  - Volumen de música
  - Comprobación de actualizaciones al inicio
  - Selección de dispositivo de salida
  - Alternar HRTF de menú
  - Alternar voz
  - Configuración de SAPI
  - Dificultad
  - Idioma
  - Anuncios de medidor
  - Contadores de monedas
  - Anuncios de cambios de misión
  - Controles
- Configuración de SAPI
  - Alternar voz SAPI
  - Volumen SAPI
  - Selección de voz SAPI
  - Velocidad SAPI
  - Tono SAPI
- Controles
  - Resumen de entrada activa
  - Selección de perfil de enlaces
  - Enlaces de teclado
  - Enlaces de control conectado
- Tienda
  - Hoverboards
  - Cajas misteriosas
  - Ventajas iniciales
  - Potenciadores de puntuación
  - Mejoras de personaje

## Requisitos

### Dependencias de ejecución

- Python 3.12 recomendado
- `pygame>=2.1`
- `accessible_output2>=0.14`
- `pyopenalsoft>=1.0.0`
- `pywin32>=306` en Windows

El proyecto actualmente se dirige primero a Windows porque:

- La integración de voces SAPI es específica de Windows
- las compilaciones de escritorio empaquetadas se generan con una especificación PyInstaller de Windows
- los datos de guardado y el comportamiento del actualizador se prueban contra el entorno de Windows

Otras plataformas pueden ejecutarse desde el código fuente con una funcionalidad específica de la plataforma reducida, pero Windows es el objetivo de lanzamiento compatible.

## Ejecutar desde el código fuente

### 1. Clonar el repositorio

```bash
git clone https://github.com/oguzhanproductions/subway_surfers_blind.git
cd subway_surfers_blind
```

### 2. Crear y activar un entorno virtual

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Símbolo del sistema de Windows:

```bat
python -m venv .venv
.venv\Scripts\activate.bat
```

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 4. Iniciar el juego

```bash
python main.py
```

## Datos de guardado y archivos locales

El juego almacena datos persistentes en el directorio de datos de aplicación en tránsito en Windows:

```text
%APPDATA%\Vireon Interactive\Subway Surfers Blind Edition\data
```

Esto incluye:

- `settings.json`
- Configuración de OpenAL
- archivos de caché mono generados para reproducción HRTF
- datos de caché del actualizador

El código también contiene lógica de migración para avanzar diseños de guardado más antiguos si existen.

## Estructura del proyecto

```text
subway_surfers_blind/
|- main.py
|- SubwaySurfersBlind.spec
|- assets/
|  |- menu/
|  |- music/
|  `- sfx/
|- subway_blind/
|  |- app.py
|  |- audio.py
|  |- balance.py
|  |- characters.py
|  |- config.py
|  |- controls.py
|  |- features.py
|  |- game.py
|  |- hrtf_audio.py
|  |- menu.py
|  |- models.py
|  |- progression.py
|  |- spatial_audio.py
|  |- spawn.py
|  |- updater.py
|  `- version.py
`- tests/
   `- test_game.py
```

## Arquitectura del código

### `main.py`

Punto de entrada mínimo. Delega el inicio a `subway_blind.app.main()`.

### `subway_blind/app.py`

Inicializa `pygame`, carga la configuración persistente, inicializa la salida de audio, crea la ventana principal e inicia el bucle `SubwayBlindGame`.

### `subway_blind/game.py`

Controlador principal del juego. Gestiona:

- menús
- estado de carrera
- estado del jugador
- colección de obstáculos
- flujo de progresión
- renderizado de HUD
- manejo de entrada
- lógica de recompensas
- flujo de mejora de personajes
- integración del flujo del actualizador

Esta es la capa de orquestación del proyecto.

### `subway_blind/audio.py`

Proporciona:

- inicialización del mezclador y selección de dispositivo de salida
- abstracción de voz e integración SAPI
- carga de efectos de sonido
- reproducción de menús y jugabilidad
- descubrimiento de pistas de música y transiciones
- comportamiento de respaldo cuando backends de audio específicos no están disponibles

### `subway_blind/hrtf_audio.py`

Envuelve `pyopenalsoft` para la reproducción de sonido 3D. También:

- escribe un archivo de configuración OpenAL Soft
- habilita el modo estéreo para auriculares y HRTF
- almacena en caché archivos `.wav` convertidos a mono cuando es necesario
- gestiona el estado del oyente y la fuente

### `subway_blind/spatial_audio.py`

Construye señales espaciales de peligro en tiempo real desde el estado del obstáculo. Esta es la capa responsable de las indicaciones de peligro direccionales y la retroalimentación de advertencia pulsante.

### `subway_blind/spawn.py`

Controla la colocación de obstáculos y elementos de apoyo utilizando patrones de ruta legibles, seguimiento de carriles seguros y validación de jugabilidad.

### `subway_blind/progression.py`

Gestiona objetivos de misiones, rotación de Word Hunt, estado de Season Hunt, progreso de logros y reclamo de recompensas.

### `subway_blind/features.py`

Contiene reglas de equilibrio para consumibles, precios de la tienda, tablas de recompensas y resultados de cajas misteriosas.

### `subway_blind/balance.py`

Define curvas de velocidad y distancia de generación por dificultad.

### `subway_blind/characters.py`

Define el plantel de personajes, costos de desbloqueo, niveles de mejora, resúmenes de beneficios, normalización del estado de guardado y resolución de bonificaciones en tiempo de ejecución para el personaje activo.

### `subway_blind/config.py`

Gestiona:

- resolución de rutas de recursos para ejecuciones desde código fuente y compilaciones empaquetadas
- resolución del directorio de datos de guardado
- configuración predeterminada
- carga y guardado de configuración
- valores predeterminados y persistencia de la configuración de voz SAPI
- persistencia del personaje seleccionado y estado de progresión del personaje
- migración desde ubicaciones de datos heredadas

### `subway_blind/updater.py`

Implementa el actualizador de GitHub Releases:

- búsqueda de la última versión
- comparación de versiones
- descarga de ZIP
- extracción
- preparación de reemplazo para ejecutables empaquetados
- generación de script de reinicio

### `tests/test_game.py`

Cobertura de regresión para reglas de jugabilidad, comportamiento de configuración, lógica de generación, flujo adyacente al audio, comportamiento de progresión, comportamiento del actualizador y progresión de personajes.

## Manejo de música y activos

El proyecto resuelve activos estáticos a través de `resource_path()` para que el mismo código funcione en ambos casos:

- ejecutar directamente desde el código fuente
- ejecutar desde un ejecutable compilado con PyInstaller

Los grupos principales de activos son:

- `assets/menu`
- `assets/music`
- `assets/sfx`

Las pistas de música se descubren dinámicamente desde el directorio de activos, permitiendo que el juego encuentre archivos compatibles por nombre de pista base.

## Pruebas

Ejecuta la suite de pruebas con:

```bash
pytest -q
```

El repositorio actualmente incluye una suite grande `tests/test_game.py` que ejerce la lógica del juego intensamente sin requerir juego manual.

## Compilar un ejecutable de Windows

El repositorio incluye un archivo de especificación PyInstaller:

```bash
pyinstaller --clean --noconfirm SubwaySurfersBlind.spec
```

La especificación está configurada para empaquetar:

- la aplicación Python
- todos los activos del proyecto
- bibliotecas dinámicas nativas de `pyopenalsoft` requeridas para la reproducción HRTF

Los resultados de la compilación deben permanecer locales y no deben cometerse al control de versiones. Las reglas de ignorar del repositorio ya excluyen `dist/`, `build/` y variantes de empaquetado local.

## Flujo de lanzamiento y actualización

Las compilaciones empaquetadas pueden verificar GitHub Releases y solicitar al usuario que:

- descargue e instale una actualización
- abra la página de lanzamiento
- salga del juego

Para los mantenedores, eso significa que la canalización de lanzamiento debe publicar un paquete ZIP que coincida con la estructura de directorio empaquetada esperada por el actualizador.

## Notas de desarrollo

- La base de código actual prefiere la orquestación directa de estado sobre la abstracción profunda de frameworks
- El soporte de accesibilidad para Windows se trata como un requisito de primera clase
- El stack de audio está diseñado para degradarse de manera elegante cuando algunos backends opcionales no están disponibles
- La configuración de guardado se persiste automáticamente cuando cambian las opciones o el estado de progresión

## Contribuir

Los issues y pull requests son bienvenidos.

Si contribuyes:

- mantén intacto el comportamiento de accesibilidad
- preserva la usabilidad solo con teclado
- no commitees artefactos de `dist/` o `build/`
- agrega o actualiza pruebas automatizadas cuando cambien la lógica de jugabilidad, actualizador o progresión
- mantén las referencias de activos de audio y el comportamiento de empaquetado consistentes con `SubwaySurfersBlind.spec`

## Licencia

Este repositorio está licenciado bajo los términos proporcionados en [LICENSE](LICENSE).
