# CLAUDE.md

Este archivo provee orientación a Claude Code (claude.ai/code) al trabajar con este repositorio.
El proyecto corresponde a una prueba técnica de entrevista de trabajo. La idea es mejorar el repositorio en temas de 
performance y la comodidad para developers para empezar a desarrollar

## Stack

Django 5.2 + Django Ninja (ruteo estilo FastAPI) + PostgreSQL 16. Python 3.14, gestionado con `mise` + `uv`.

## Comandos

```sh
# Instalar toolchain y dependencias
mise install
uv sync

# Setup de base de datos (requiere postgres corriendo en localhost:5432, db: backend_devops_interview, user/pass: postgres/postgres)
uv run python manage.py migrate
uv run python manage.py seed   # inserta ~100k posts y ~500k comentarios — demora varios minutos

# Servidor de desarrollo
uv run python manage.py runserver   # docs de la API en http://localhost:8000/api/docs

# Linting (debe probarse al final de cada tarea solicitada por el usuario)
uv run ruff check .
uv run ruff format .

# Correr todos los tests
uv run pytest

# Correr un archivo de tests
uv run pytest blog/tests/test_posts.py

# Correr un test específico
uv run pytest blog/tests/test_posts.py::test_list_posts_returns_published
```

## Arquitectura

El proyecto tiene una sola app Django (`blog`) conectada a una API Ninja montada en `/api/`.

- `core/settings.py` — configuración Django; DB hardcodeada a `localhost:5432/backend_devops_interview`
- `core/urls.py` — monta `NinjaAPI` en `/api/` con el router de blog
- `blog/models.py` — modelos `User`, `Tag`, `Post` (M2M con Tag), `Comment` (FK a Post y User)
- `blog/api.py` — todos los handlers de rutas; serializa manualmente con funciones auxiliares (`_serialize_author`, `_serialize_post_list`, etc.) en lugar de usar la integración ORM de Ninja
- `blog/schemas.py` — clases Pydantic `Schema` para validación de requests y responses
- `conftest.py` — configuración mínima de pytest que llama a `django.setup()` si los settings aún no están configurados

Los tests usan el `Client` de Django directamente con `@pytest.mark.django_db`. Sin fixtures ni factories más allá de la creación inline de objetos.

## Problemas de performance conocidos (objetivo del assignment)

El dataset sembrado (~100k posts, ~500k comentarios) expone consultas N+1 en los endpoints de listado: `list_posts`, `search_posts` y `posts_by_tag` acceden a `post.author` y `post.tags.all()` por cada fila sin usar `select_related`/`prefetch_related`. `get_post` carga todos los comentarios sin `select_related` en los autores. `_user_detail` emite dos consultas `.count()` separadas.


---

## Contexto del proyecto

Trabajás en un proyecto Django con PostgreSQL que expone una API (en `blog/api.py`) sobre un dataset grande: ~100k posts, ~500k comentarios, ~1k usuarios. A ese volumen, los endpoints exhiben un patrón de consulta que escala linealmente con los datos.

La causa raíz es consistente en toda la API: los endpoints serializan relaciones ORM **dentro de loops de Python**, generando el problema clásico **N+1**, y **ningún endpoint limita** la cantidad de resultados retornados. Además, faltan índices clave, la búsqueda usa `icontains` (sequential scan), el incremento de `view_count` tiene una race condition, y varias consultas de escritura/agregación hacen una query por iteración.

El objetivo de la épica es **eliminar los N+1, paginar los endpoints de lista y acelerar las consultas** mediante eager loading, índices apropiados y full-text search, sin cambiar el contrato externo de la API más allá de agregar paginación.

## Features de la épica

La épica se descompone en 6 features. Te las describo brevemente para que entiendas las dependencias antes de implementar cualquiera.

### F6 — Eliminar N+1 en endpoints de lectura (eager loading)
Agregar `select_related('author')` + `prefetch_related('tags')` a `list_posts`, `search_posts` y `posts_by_tag`; y `select_related('author')` + `prefetch_related('tags', 'comments__author')` a `get_post`. Reduce de ~200k queries a un puñado fijo, sin importar el volumen.
*Es el cambio de mayor impacto y el más transversal. Va primero.*

### F7 — Paginación en endpoints de lista
Agregar `page` (default 1) y `page_size` (default 20, máximo 100) a `list_posts`, `search_posts` y `posts_by_tag`. Convierte una query de 100k filas en una de 20 con LIMIT/OFFSET.
*Depende de F1 (envuelve el queryset ya optimizado).*

### F8 — `view_count` atómico
Reemplazar el read-modify-write (`post.view_count += 1; post.save()`) por un update atómico `F('view_count') + 1` en `get_post`, eliminando el lost update bajo concurrencia.
*Toca `get_post`, igual que F1: conviene hacerlo en el mismo PR o pegado después.*

### F9 — Optimizar escritura y detalle de usuario
Batch tag lookup en `create_post` (`filter(slug__in=...)` + `tags.set(...)`) y `annotate()` de counts en `_user_detail`.
*Independiente: toca `create_post` y `_user_detail`, que nadie más toca.*
*⚠️ Cuidado con el doble conteo del `annotate` sobre dos relaciones — ver el prompt de F4.*

### F10 — Full-text search con `SearchVectorField` + índice GIN
Reemplazar `icontains` por full-text search de PostgreSQL respaldado por una columna `SearchVectorField` persistida e indexada con GIN. Es el ítem más pesado: requiere cambio de modelo + migración.
*Depende de F1 y F2 (reescribe `search_posts` ya optimizado y paginado).*
*⚠️ El vector debe estar PERSISTIDO para que el GIN se use; un `annotate(SearchVector(...))` en tiempo de query NO usa el índice — ver el prompt de F5.*

### F11 — Migración de índices B-tree
Migración con índices B-tree para `Post.is_published`, `Post.created_at` (desc), `User.email` y compuesto `(Comment.post_id, Comment.created_at)`.
*Independiente. El índice GIN NO va acá: pertenece a F5.*

## Orden de implementación

1. **F1** primero (foundational, toca lo más).
2. **F3** junto con F1 o pegado después (mismo archivo, `get_post`).
3. **F2** sobre F1.
4. **F5** sobre F2 (rebasa `search_posts` ya optimizado y paginado).
5. **F4** y **F6** en paralelo en cualquier momento (independientes).

## Restricciones generales

- No cambiar el contrato externo de la API salvo el agregado de paginación.
- Verificar las mejoras con conteo de queries (`assertNumQueries`, `django-debug-toolbar`) y/o `EXPLAIN ANALYZE`, no solo "se siente más rápido".
- No agregar dependencias externas innecesarias; usar el ORM de Django y `django.contrib.postgres`.
- El número de queries de un endpoint de lista NO debe crecer con el número de filas retornadas.

## Dos advertencias de correctitud (no solo de performance)

El reporte de origen incluye código de ejemplo con dos errores que hay que corregir al implementar:

1. **F4 — doble conteo:** `annotate(Count('posts'), Count('comments'))` sobre dos relaciones multivaluadas a la vez produce un producto cartesiano que infla ambos counts. Usar `Count(..., distinct=True)` o subqueries.
2. **F5 — annotate vs GIN:** filtrar contra `annotate(SearchVector(...))` calcula el vector en tiempo de query y NO usa ningún índice GIN. El GIN solo sirve sobre una columna `SearchVectorField` persistida. El approach de query y el de migración deben ser coherentes.

---

> A continuación te pediré la implementación de **una feature específica**. Mantené presente este contexto, respetá el orden de dependencias y prestá atención a las dos advertencias de correctitud.
## Restricciones generales
 
- No agregar dependencias externas innecesarias; preferir la librería estándar.
- Todos los defaults deben permitir correr el proyecto en local sin configuración manual.
- Nunca commitear secretos ni archivos `.env` reales.
- Documenta los metodos utilizando formato estándar de un Docstring.
---
 
> A continuación te pediré la implementación de **una feature específica**. Mantené presente este contexto y respetá el orden de dependencias.