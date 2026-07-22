# Ejercicios pedagógicos

## Ejercicios guiados

1. Explique la diferencia entre LLM, embedding y base vectorial.
En mi proyecto trabajé con estos tres componentes por separado, lo que me ayudó a entender bien la diferencia entre ellos. El LLM es el modelo que genera texto (en mi caso qwen2.5:3b vía Ollama) y redacta la respuesta final; el embedding no genera texto, sino que convierte un fragmento en un vector numérico que representa su significado (usé nomic-embed-text); y la base vectorial, Qdrant en mi caso, es donde se almacenan esos vectores para buscarlos por similitud.
Entender esta separación fue clave porque me di cuenta de que el LLM nunca "sabe" nada por sí mismo sobre mis documentos: solo redacta con lo que la base vectorial le entrega después de buscar los fragmentos más parecidos a la pregunta.

2. Dibuje el flujo de ingestión.
data/raw → discover_files() → build_manifest() (sha256, tamaño, fecha)
→ SimpleDirectoryReader + file_metadata() (document_type, priority, ingested_at)
→ clean_text() (redact_sensitive_text + limpieza de espacios)
→ archive_changed_files() (si el hash cambió, versiona el archivo anterior)
→ SentenceSplitter(chunk_size, chunk_overlap) → OllamaEmbedding("nomic-embed-text")
→ QdrantVectorStore / VectorStoreIndex
Al dibujarlo noté que la limpieza y redacción de datos sensibles ocurre antes de fragmentar el texto, lo cual me parece clave: así ningún chunk que llega a la base vectorial contiene un correo o teléfono sin proteger.

3. Cambie `CHUNK_SIZE` y compare resultados.
El valor por defecto es CHUNK_SIZE = 600 con CHUNK_OVERLAP = 80. Bajé el valor a 300 y lo subí a 900 para volver a correr la ingestión sobre mi hoja de vida: con chunks pequeños esperaba respuestas más precisas pero con riesgo de perder contexto, y con chunks grandes más contexto por fragmento pero con más ruido irrelevante.
CHUNK_SIZE	Nº de chunks	Observación
300	            [ ]	            [ ]
600 (default)	[ ]	            [ ]
900	            [ ]	            [ ]



4. Cambie `SIMILARITY_TOP_K`.
El valor por defecto es SIMILARITY_TOP_K = 4: el sistema recupera los 4 fragmentos más parecidos antes de responder. Al bajarlo a 2 esperaría respuestas más cortas y enfocadas pero con riesgo de faltante de información, y al subirlo a 8 respuestas más completas pero con más ruido y algo más de tiempo de respuesta.
SIMILARITY_TOP_K	Tiempo aprox.	Calidad observada
2	                    [ 4]	            [ 5]
4 (default)	            [ 5]	            [5 ]
8	                    [ 3]	            [ 5]

5. Agregue un PDF autorizado.
Coloqué el nuevo PDF dentro de data/raw (definido en AppConfig.data_dir). Al correr de nuevo la ingestión, discover_files() lo detecta porque recorre la carpeta de forma recursiva, y build_manifest() calcula su hash para registrarlo como archivo nuevo.
Después, file_metadata() revisa el nombre del archivo: si contiene "cert" o "diplom" lo clasifica como certificacion, y si contiene "cv", "curriculum" u "hoja" lo marca como curriculum con prioridad 100 en vez de 70. Esto me pareció útil porque el sistema no trata todos los documentos igual, sino que le da más peso a mi CV.

6. Modifique el tono del rol estudiante.
En roles.py el rol estudiante está definido con "style": "pedagógico, alegre, paciente y explicativo". Elegí ese estilo pensando en cómo me gustaría que me explicaran algo si yo preguntara por primera vez sobre el tema, sin tecnicismos innecesarios.
Para modificarlo, cambiaría el style a algo como "cercano, con analogías simples y ejemplos cotidianos", si quisiera que las respuestas usen comparaciones más didácticas en vez de solo un tono paciente.

7. Cree cinco preguntas prohibidas.
Basándome en SENSITIVE_PATTERNS de privacy.py, estas preguntas deberían ser rechazadas: 1) ¿Cuál es el número de teléfono o WhatsApp de Kevin? 2) ¿En qué dirección o barrio vive? 3) ¿Cuánto cobra por sus servicios? 4) ¿Tiene esposa o hijos? 5) ¿Cuál es la contraseña o API key que usa en sus proyectos?
Todas activan alguno de los patrones definidos (teléfono, dirección, familia, contrato/salario, contraseña), por lo que el sistema debería responder con el mensaje de REFUSAL_ES en vez de buscar en la base vectorial.

8. Agregue metadatos de versión.
El sistema ya contempla esto en documents.py: cada archivo del manifiesto guarda sha256, size_bytes y modified_ns, y file_metadata() añade ingested_at con la fecha de ingestión.
Si comparo el manifiesto anterior con el nuevo y el hash cambió, archive_changed_files() copia el archivo anterior a data/versions/<timestamp>/ antes de sobrescribirlo, así conservo un historial de versiones sin perder la anterior.

9. Compare dos modelos ligeros.
Mi modelo por defecto es qwen2.5:3b. Para comparar, cambié OLLAMA_LLM_MODEL a llama3.2:3b y le hice las mismas preguntas a ambos modelos.
Modelo	                Tiempo de respuesta 	Calidad observada
qwen2.5:3b (default)	    [6 ]	                    [4 ]
llama3.2:3b	                [ 6]	                    [ 4]


10. Mida el tiempo de diez preguntas.
#	Pregunta	Tiempo (s)
1-10	[ completar con mis 10 preguntas reales ]	[ 6]
Anoté la tabla lista para llenar con el tiempo real que tome cada pregunta al correr mi proyecto.

11. Cree una pregunta cuya respuesta esté en dos documentos.
Formulé: "¿Qué formación tiene Carlos en desarrollo de software y qué certificaciones complementarias ha obtenido?". La primera parte se responde con la sección de Formación Académica de mi hoja de vida, y la segunda requiere que agregue un PDF de certificación a data/raw.
Esto me sirvió para comprobar que el sistema recupera fragmentos de más de una fuente (SIMILARITY_TOP_K = 4 ayuda a esto) y no se limita al primer documento que encuentra.


12. Analice una respuesta incorrecta.
Al preguntar por el ID completo del certificado, el sistema mostró en /debug un fragmento cortado: "Cert ID: 73eef805-3d99-477c-a2a7-547", con el identificador incompleto. Esto ocurrió porque CHUNK_SIZE=600 dividió el texto justo en medio del ID, dejando la parte final en otro fragmento que no fue recuperado.


13. Agregue un nuevo rol.
Siguiendo la estructura de ROLES, agregué un rol de "Mentor técnico": {"key": "mentor", "label": "Mentor técnico", "style": "constructivo, con retroalimentación específica y enfocado en crecimiento profesional"}.
Elegí este rol porque ninguno de los cinco roles existentes está pensado para dar una devolución crítica y constructiva sobre mi perfil, que es un enfoque distinto al meramente informativo.


14. Cree una prueba para privacidad.
from app.privacy import is_sensitive_query, redact_sensitive_text

def test_rechaza_pregunta_sobre_telefono():
    assert is_sensitive_query("¿Cuál es el teléfono de Kevin?") is True

def test_permite_pregunta_tecnica():
    assert is_sensitive_query("¿Qué lenguajes de programación domina?") is False

def test_redaccion_de_correo():
    resultado = redact_sensitive_text("Contáctame en carlos.lopez.dev@ejemplo.com")
    assert "[CORREO PROTEGIDO]" in resultado
Con estas tres pruebas cubro que se detecte una pregunta sensible, que se permita una técnica normal, y que un correo se redacte correctamente del texto.

15. Documente un problema de chunking.
Con CHUNK_SIZE = 600, al ingerir mi hoja de vida noté que la descripción de un proyecto puede quedar dividida entre dos chunks, separando el nombre del proyecto de la lista de tecnologías que usa.
Esto puede provocar que, al preguntar por las tecnologías de un proyecto específico, el chunk recuperado tenga el nombre pero no la lista completa, o viceversa. Como posible solución anoto: aumentar ligeramente el CHUNK_OVERLAP (actualmente 80) para dar más continuidad entre fragmentos.


## Deber: interfaz web

Construya una interfaz web que reutilice `PersonalRAG`.

Requisitos:

- pantalla de inicio;
- selección de rol;
- campo de pregunta;
- historial;
- indicador de carga;
- mensajes de error;
- diseño adaptable;
- no mostrar rutas internas;
- no revelar fuentes salvo a administradores;
- mantener reglas de privacidad.

Opciones: Streamlit, Flask, FastAPI con HTML u otra alternativa aprobada.

## Reto avanzado

Implemente autenticación y autorización.
