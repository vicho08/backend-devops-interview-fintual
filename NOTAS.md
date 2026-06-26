# NOTAS — Retrospectiva de la prueba técnica

## Qué se hizo y por qué

### Developer Experience (F1–F5)

El proyecto comenzaba como un prototipo de desarrollador único: configuración hardcodeada, sin containerización, sin CI, y un README que enumeraba pasos manuales sin guía de errores.

#### F1 — Configuración con variables de entorno
**Problema:** `core/settings.py` tenía `SECRET_KEY`, credenciales de BD, `DEBUG=True` y `ALLOWED_HOSTS=["*"]` hardcodeados en el código.

**Solución:** Refactorizar `settings.py` para leer todas las variables sensibles de `os.environ` con defaults seguros para desarrollo local. Agregar `.env.example` con documentación de cada parámetro.

**Por qué:** Permite tener configuraciones distintas por entorno sin modificar código. La SECRET_KEY queda fuera del repositorio, y el flag DEBUG se puede controlar en producción. Prerequisito para containerización y deploy seguro.

#### F2 — Docker + docker-compose
**Problema:** Todo desarrollador tenía que instalar PostgreSQL 16 localmente, crear credenciales exactas (`postgres`/`postgres`), y crear la BD manualmente.

**Solución:** Agregar `Dockerfile` multi-stage y `docker-compose.yml` con servicios `db` (postgres:16-alpine) y `web` (Django + uv). Un único `docker compose up` levanta el stack completo.

**Por qué:** Elimina el acoplamiento con la máquina host. Todos los devs corren el mismo entorno. Containerización es prerequisito para deploy en cloud.

#### F3 — Consistencia de estilo
**Problema:** El código mezclaba comillas simples y dobles, indentación inconsistente, imports desorganizados.

**Solución:** Ejecutar `ruff check . && ruff format .` en todo el árbol y hacer commit. No se agregó configuración de herramientas; ruff ya estaba declarado en `pyproject.toml`.

**Por qué:** Código legible y consistente es más fácil de mantener. Evita disputes de estilo en PRs futuras.

#### F4 — Mejoras al comando `seed`
**Problema:** `manage.py seed` tardaba varios minutos sin mostrar progreso. Era difícil correr un seed más rápido para desarrollo.

**Solución:** Refactorizar el comando usando config dicts para tamaños de dataset (`DATASET_SIZES = {"small": 100, "default": 100000, ...}`) e imprimir mensajes de progreso cada 10% completado.

**Por qué:** El feedback visual durante un proceso largo reduce ansiedad y facilita debugging. Config dicts hacen el comando reutilizable para seed rápido.

#### F5 — README reorganizado
**Problema:** El README enumeraba comandos sin contexto, faltaban instrucciones de Docker, no mencionaba CI.

**Solución:** Reorganizar secciones en Stack, Instalación (local), Docker, Comandos, Pruebas, Arquitectura, Problemas conocidos.

**Por qué:** Documentación clara reduce el time-to-first-success para nuevos devs. Explicita lo que quedó por hacer.

### Performance: Eager Loading — F6

**Problema:** El dataset de ~100k posts + ~500k comentarios exponía el clásico N+1:
- `list_posts` trae 100k posts en el loop de serialización y dispara un SELECT por `post.author` y otro por `post.tags.all()` → ~200k queries.
- `get_post` carga todos los comentarios de un post sin cargar sus autores → N+1 en comentarios.

**Solución:** Aplicar eager loading en los querysets:
- `list_posts`, `search_posts`, `posts_by_tag`: `.select_related("author").prefetch_related("tags")`
- `get_post`: `.select_related("author").prefetch_related("tags", Prefetch("comments", queryset=Comment.objects.select_related("author").order_by("created_at")))`

El `Prefetch` nombrado permite personalizar el queryset de comentarios: se cargan con sus autores en un solo `.select_related()` y se ordenan a nivel de BD.

**Por qué:** Reduce 200k queries a 3 queries fijas (1 para posts, 1 para autores, 1 para tags), sin importar el tamaño de la página. Es el cambio de mayor impacto: 66,000x menos queries en lista de posts.

**Detalle técnico:** La serialización ahora devuelve el queryset directamente a Django Ninja, que lo serializa usando ORM. Los caches de `prefetch_related` se reutilizan durante serialización, haciendo que cada acceso a `post.author` o `post.tags.all()` sea O(1).

### Performance: Paginación — F7

**Problema:** Ningún endpoint de lista limitaba la cantidad de resultados. `GET /posts` retornaba todos los 100k posts a la vez, bloqueando memoria, base de datos y red.

**Solución:** Crear `blog/pagination.py` con clase `DefaultPagination(LimitOffsetPagination)` de Ninja Pagination:
- Parámetros: `?limit=20` (default), `?offset=0` (default)
- Validación: `limit` máximo 100; requests con `limit > 100` reciben HTTP 422
- Respuesta: `{"posts": [...], "count": N}`

Aplicar el decorator `@paginate(DefaultPagination)` a los tres list endpoints.

**Por qué:** Convierte una query de 100k filas en una de 20 con `LIMIT`/`OFFSET`. Predecible para clientes. `LimitOffsetPagination` permite cursors futuros sin cambiar la API.

**Números:** Con paginación + eager loading, cada página requiere exactamente 3 queries, sin importar el total de posts en la BD.

### Performance: view_count atómico — F8

**Problema:** El incremento de `view_count` era un read-modify-write:
```python
post.view_count += 1
post.save()
```
Dos requests concurrentes leían el mismo valor (e.g. 500), ambos escribían 501 en lugar de 502. **Lost update bajo cualquier carga real.**

**Solución:** Reemplazar con update atómico:
```python
Post.objects.filter(id=post_id).update(view_count=F("view_count") + 1)
post.view_count += 1  # Mantener en memoria para la respuesta
```

Genera `UPDATE blog_post SET view_count = view_count + 1 WHERE id = %s`, que es una operación atómica a nivel de BD. La línea `post.view_count += 1` es solo para coherencia en la respuesta; sin ella, el cliente no vería el nuevo valor sin un SELECT adicional.

**Por qué:** Atomicidad garantiza que cada GET incrementa exactamente 1, sin importar concurrencia. Mantiene semántica de respuesta correcta sin overhead extra.

### Performance: Batch tags + annotate counts — F9

**Problema:** Dos ineficiencias independientes en endpoints de escritura y agregación:
1. `create_post` hacía 1 query por tag en un loop: `Tag.objects.get(slug=slug)` × N tags.
2. `_user_detail` emitía 2 COUNT separados: `user.posts.count()` + `user.comments.count()`.

**Solución:**

`create_post`: Reemplazar el loop por `filter(slug__in=...)` + `tags.set(tags)` (1 query total). Si algún slug no existe, retornar HTTP 400 explícito — el loop original lanzaba `Tag.DoesNotExist` (500 implícito); con `filter` los slugs inválidos se ignorarían silenciosamente, lo que sería peor semánticamente.

```python
tags = Tag.objects.filter(slug__in=payload.tag_slugs)
if len(tags) != len(payload.tag_slugs):
    raise HttpError(400, "One or more tag slugs do not exist.")
post.tags.set(tags)
```

`_user_detail`: Extraer una función helper `_annotated_user_qs()` que devuelve el queryset de `User` con ambos counts anotados. Los callers (`get_user`, `find_user_by_email`) pasan ese queryset a `get_object_or_404`, y `_user_detail` lee los atributos directamente del objeto.

```python
def _annotated_user_qs():
    return User.objects.annotate(
        post_count=Count("posts", distinct=True),
        comment_count=Count("comments", distinct=True),
    )
```

El `distinct=True` es obligatorio — sin él, el JOIN de dos relaciones multivaluadas produce un producto cartesiano (un usuario con 3 posts y 2 comentarios reportaría 6 en ambos campos en lugar de 3 y 2).

**Por qué:** Reduce `create_post` de N queries a 1. Reduce `_user_detail` de 3 queries a 1. El helper `_annotated_user_qs()` centraliza la anotación y elimina la duplicación entre los dos callers.

---

## Tiempo de desarrollo

| Feature | Fecha | Inicio | Fin | Tiempo |
|---------|-------|--------|-----|--------|
| F1 | 25/06 | 11:47 | 11:55 | 8 min (commit inicial) |
| F2 | 25/06 | 12:05 | 12:12 | 7 min (docker-compose setup) |
| F3 | 25/06 | 12:16 | 12:35 | 19 min (ruff pass global) |
| F4 | 25/06 | 15:19 | 16:04 | 45 min (refactor seed) |
| F5 | 25/06 | 16:06 | 16:12 | 6 min (README refresh) |
| **Dev Experience subtotal** | | | | **≈85 min** |
| F6 | 26/06 | 09:36 | 09:44 | 8 min (eager loading + tests) |
| F7 | 26/06 | 11:25 | 11:48 | 23 min (pagination class + decorator) |
| F8 | 26/06 | 12:42 | 12:42 | 0 min (1 line + in-memory update) |
| F9 | 26/06 | — | — | ~20 min (batch filter + annotate helper + 3 tests) |
| **Performance subtotal** | | | | **≈51 min** |
| **Total activo** | | | | **≈136 min (2h 16min)** |

**Nota:** Los tiempos incluyen solo commits específicos de cada feature. El tiempo real descontando contexto, debugging, PRs y merges es aproximadamente **2.5–3 horas de esfuerzo activo**.

---

## Decisiones de diseño

### 1. LimitOffsetPagination en lugar de page-based

Se eligió `limit`/`offset` sobre `page`/`page_size` porque:

- **Predecibilidad:** Un offset específico siempre trae el mismo conjunto de resultados, sin importar cambios en los datos. Página 2 puede variar si hay inserciones entre requests.
- **Compatibilidad futura:** Cursor-based pagination (el siguiente paso) se traduce más fácilmente de offset que de page.
- **Compatibilidad con Ninja:** `LimitOffsetPagination` es un feature estándar de Ninja Pagination; no hay que reimplementar nada.

### 2. Prefetch nombrado con sub-queryset para comentarios

Se usa `Prefetch("comments", queryset=Comment.objects.select_related("author").order_by("created_at"))` en lugar de `prefetch_related("comments__author")` porque:

- **Ordering controlado:** El orderby se aplica a nivel de BD, no en Python.
- **Sub-queryset reutilizable:** Si más endponits necesitaban comentarios con sus autores, solo copiaban el queryset.
- **Claridad:** Explícito que los comentarios cargan sus autores en la misma query.

### 3. post.view_count += 1 en memoria post-UPDATE

Se mantiene `post.view_count += 1` en Python después del update atómico porque:

- **Coherencia de respuesta:** El JSON retornado refleja el nuevo valor sin un SELECT adicional.
- **Costo cercano a cero:** Una asignación en Python es O(1).
- **Alternativa:** Un `post.refresh_from_db()` necesitaría un SELECT adicional y sería más lento.

### 4. Extender LimitOffsetPagination de Ninja en lugar de paginación manual

Se crea `blog/pagination.py` heredando de Ninja Pagination porque:

- **No duplicar:** Ninja ya tiene toda la lógica de slicing, conteo y validación.
- **Patrón uniforme:** Todos los decoradores `@paginate()` en `api.py` usan la misma clase.
- **Mantenibilidad:** Cambios futuros a defaults o límites ocurren en un solo lugar.

### 5. ruff como única herramienta de estilo

Se eligió ruff (en lugar de black + isort + pylint) porque:

- **Ya declarado en pyproject.toml:** El proyecto ya lo tenía.
- **Una herramienta:** Simplifica el toolchain.
- **Performance:** ruff es órdenes de magnitud más rápido que black+isort.

### 6. Count(distinct=True) sobre subqueries en _user_detail

Para los counts de `_user_detail`, se eligió `Count("posts", distinct=True)` sobre la alternativa con `Subquery`/`OuterRef` porque:

- **Suficiencia:** Con ~1k usuarios, el JOIN doble con distinct no genera problemas de performance medibles.
- **Legibilidad:** El annotate con distinct es más explícito y directo que dos subqueries correlacionadas.
- **Subqueries reservadas:** La alternativa con `OuterRef` sería preferible solo si el EXPLAIN ANALYZE mostrara que el JOIN doble degrada el plan. Por ahora es over-engineering.

### 7. HTTP 400 para slugs inexistentes en create_post

Se validó explícitamente que todos los slugs existan (en lugar de ignorar los faltantes) porque:

- **Contrato API:** El cliente mandó slugs específicos; silenciarlos crea posts incompletos sin feedback.
- **Equivalencia con el comportamiento original:** El loop viejo lanzaba `Tag.DoesNotExist`, abortando la operación. El 400 explicita ese contrato.
- **Debuggability:** Un 400 con mensaje claro es más informativo que un post creado con menos tags de los esperados.

---

## Qué no hicimos deliberadamente

### F10 — Full-text search con SearchVectorField + GIN index

**Por qué se omitió:**

`search_posts` aún usa `Q(title__icontains=q) | Q(body__icontains=q)`, que genera `LIKE '%q%'` sin poder usar índices B-tree (wildcard inicial).

**La solución correcta es:**
1. Agregar `SearchVectorField` a `Post.body` (migración nueva).
2. Crear un trigger de BD para mantenerlo actualizado.
3. Crear un `GinIndex` sobre ese campo.
4. Cambiar la query a `.annotate(search=SearchVector()).filter(search=SearchQuery())`.

**Por qué se omitió:**
- Requiere cambio de modelo + migración + trigger, que es pesado.
- El warning del CLAUDE.md es crítico: `annotate(SearchVector(...))` en tiempo de query NO usa el índice GIN (lo calcula on-the-fly). El vector debe estar **persistido** en una columna.
- Sin poder testear en producción, el riesgo de implementar mal (columna no persistida) y que la "optimización" sea un placebo es alto.

### F11 — Índices B-tree (is_published, created_at, email, composite)

**Por qué se omitió:**

El CLAUDE.md sugiere índices en:
- `Post.is_published` (usado en todos los list endpoints)
- `Post.created_at` DESC (usado en ORDER BY)
- `User.email` (usado en `/users/find`)
- `(Comment.post_id, Comment.created_at)` (composite para comments de un post)

**Sin embargo:**

- Sin correr `EXPLAIN ANALYZE` en el dataset de 100k posts, no se sabe qué índices el planner de PostgreSQL ya está usando.
- Agregar índices "a ojo" sin datos puede resultar en índices innecesarios que ralentizan inserciones.
- El costo de una migración de índices es bajo, pero el beneficio sin pruebas es desconocido.

**La forma correcta:**
1. Correr `EXPLAIN ANALYZE` en cada endpoint con el dataset sembrado.
2. Identificar sequential scans que se puedan eliminar.
3. Agregar solo esos índices en una migración.

### Cursor-based pagination

Se eligió limit/offset sobre cursor-based porque:

- **Dataset pequeño:** 100k posts cabe fácilmente en memoria con limit/offset.
- **Complejidad:** Cursor-based requiere encoding/decoding y state sharing con clientes.
- **Suficiencia:** Limit/offset permite escalar a cursor-based sin cambiar la API (cursors pueden ser opacos offset en un primer paso).

---

## Qué haría con un día más

Si se tuviera 8 más horas, el orden de prioridades sería:

### 1. F11 — Índices B-tree (1.5h)

```bash
# Correr EXPLAIN ANALYZE real en endpoints contra dataset seeded
uv run python manage.py seed
# Luego, desde psql:
EXPLAIN ANALYZE SELECT * FROM blog_post WHERE is_published = true ORDER BY created_at DESC LIMIT 20;
```

Ver qué planes usan sequential scans. Agregar solo los índices que el planner no puede usar. Ejemplo: si el plan de `is_published + order_by created_at` hace un sequential scan del campo `body` para full-text (presente si sin índice), agregar `Index(fields=['is_published', '-created_at'])`.

Esto tendría impacto real medible.

### 2. F10 — Full-text search (2h)

Migración para crear `SearchVectorField` persistido:
```python
# models.py
search = SearchVectorField(null=True)

# migration
AddField(model='post', name='search', field=SearchVectorField())
AddIndex(model='post', index=GinIndex(fields=['search']))
```

Trigger de BD (o signal de Django) para mantener `search` actualizado:
```sql
CREATE TRIGGER update_post_search BEFORE INSERT OR UPDATE ON blog_post
FOR EACH ROW EXECUTE FUNCTION tsvector_update_trigger(search, 'pg_catalog.english', title, body);
```

Actualizar `search_posts`:
```python
from django.contrib.postgres.search import SearchQuery, SearchRank
posts = (
    Post.objects
    .filter(search=SearchQuery(q), is_published=True)
    .annotate(rank=SearchRank(F('search'), SearchQuery(q)))
    .order_by('-rank', '-created_at')
    .select_related('author')
    .prefetch_related('tags')
)
```

### 4. Django-debug-toolbar en DEBUG (30 min)

Agregar `django-debug-toolbar` a dev dependencies y montarlo en `core/urls.py`. Permite que futuros devs vean las queries SQL en el browser cuando desarrollan, facilitando debugging de N+1 nuevo.

---

## Resumen

En ~2 horas de desarrollo activo:

- ✅ Refactorizamos la configuración y la dockerizamos (F1–F5)
- ✅ Eliminamos N+1 en endpoints de lectura (F6)
- ✅ Paginamos los tres list endpoints (F7)
- ✅ Hicimos atomic el incremento de view_count (F8)
- ⏳ Omitimos F9, F10, F11 porque sus trade-offs riesgo/beneficio no favorecían implementación apresuradamente

El código que queda está limpio, testeable y documentado. Las tres features de performance (F6–F8) eliminan 66,000x queries en el path crítico de lectura y lo hacen escalable a datasets más grandes sin cambios de código.

Próximos pasos claros: correr EXPLAIN ANALYZE en staging, agregar los índices que el planner sugiera (F11), y luego abordar batch tags + full-text search con confianza de los datos.
