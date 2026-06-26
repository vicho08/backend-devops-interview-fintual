# Reporte 2: Performance

## Análisis del problema

El dataset sembrado (~100k posts, ~500k comentarios, ~1k usuarios) expone patrones de consulta que escalan linealmente con el volumen de datos. La causa raíz es consistente en toda la API: los endpoints serializan relaciones ORM dentro de loops de Python, generando el problema clásico N+1, y ningún endpoint limita la cantidad de resultados retornados.

### Inventario de problemas por endpoint

#### GET /posts — `list_posts` (`blog/api.py:42`)
**Queries estimadas contra 100k posts publicados: ~200,001**

El queryset trae todos los posts publicados sin LIMIT. Por cada post en el loop de serialización:
- `post.author` dispara un SELECT adicional (FK lazy) → N queries para N posts
- `post.tags.all()` dispara otro SELECT adicional → N queries más

El endpoint trae 100k filas a memoria de Python, las itera, y dispara 200k queries adicionales.

#### GET /posts/search — `search_posts` (`blog/api.py:48`)
**Queries estimadas si el término devuelve 5k resultados: ~10,002 + costo de scan**

Además del N+1 heredado de la serialización, la búsqueda usa:
```
Q(title__icontains=q) | Q(body__icontains=q)
```
Esto genera `LIKE '%q%'` en dos columnas TEXT. PostgreSQL no puede usar índices B-tree para búsquedas con wildcard inicial, forzando un sequential scan sobre el campo `body` de 100k filas. Para términos comunes (e.g. "el", "python"), la combinación de scan caro + N+1 hace el endpoint prácticamente inutilizable.

#### GET /posts/by-tag/{slug} — `posts_by_tag` (`blog/api.py:57`)
**Queries estimadas si el tag tiene 1k posts: ~2,002**

Mismo N+1 de author + tags, más el hecho de que la paginación ausente permite que un tag popular devuelva miles de posts de una vez.

#### GET /posts/{post_id} — `get_post` (`blog/api.py:64`)
**Queries estimadas para un post con 1k comentarios: ~1,003 + 1 write con race condition**

Dos problemas:
1. `post.comments.order_by('created_at')` se itera en Python y cada `c.author` dispara un SELECT → N queries para N comentarios.
2. El incremento de `view_count` es un read-modify-write sin atomicidad:
   ```python
   post.view_count += 1
   post.save()
   ```
   Dos requests concurrentes que lean el mismo valor (e.g. 500) ambos escriben 501. El conteo real debería ser 502. Este lost update se amplifica bajo cualquier carga real.

#### POST /posts — `create_post` (`blog/api.py:92`)
**Queries extras: 1 por cada tag en el payload**

```python
for slug in payload.tag_slugs:
    tag = Tag.objects.get(slug=slug)  # 1 query por iteración
    post.tags.add(tag)
```
Para un post con 10 tags: 10 queries individuales en lugar de 1.

#### GET /users/{id} y GET /users/find — `_user_detail` (`blog/api.py:126`)
**Queries extras: 2 por cada llamada**

```python
"post_count": user.posts.count(),    # SELECT COUNT(*)
"comment_count": user.comments.count(),  # SELECT COUNT(*) adicional
```
Ambos counts pueden resolverse en un único queryset con `annotate()`.

### Índices faltantes

La migración inicial (`blog/migrations/0001_initial.py`) no define índices explícitos más allá de los creados automáticamente por `unique=True` y PKs. Faltan:

| Campo | Uso | Tipo de índice recomendado |
|-------|-----|---------------------------|
| `Post.is_published` | Filtro en todos los list endpoints | B-tree |
| `Post.created_at` | ORDER BY en todos los list endpoints | B-tree |
| `Post.title + Post.body` | Búsqueda de texto | GIN (full-text search) |
| `User.email` | Lookup en `/users/find` | B-tree (+ unique constraint) |
| `(Comment.post_id, Comment.created_at)` | ORDER BY comments de un post | B-tree compuesto |

---

## Solución propuesta

### 1. select_related + prefetch_related en endpoints de lista

Reemplazar el acceso lazy a relaciones por carga eagera declarada en el queryset:

```python
# Antes
posts = Post.objects.filter(is_published=True).order_by("-created_at")

# Después
posts = (
    Post.objects
    .filter(is_published=True)
    .select_related('author')
    .prefetch_related('tags')
    .order_by("-created_at")
)
```

Aplica a `list_posts`, `search_posts` y `posts_by_tag`. Reduce de ~200k queries a 3 queries fijas.

Para `get_post`, agregar prefetch de comentarios con sus autores:
```python
post = (
    Post.objects
    .select_related('author')
    .prefetch_related('tags', 'comments__author')
    .get(id=post_id)
)
```

### 2. Paginación en endpoints de lista

Agregar parámetros `page` (default 1) y `page_size` (default 20, máximo 100) a `list_posts`, `search_posts` y `posts_by_tag`. Esto convierte una query de 100k filas en una de 20 filas con LIMIT/OFFSET.

### 3. F() expression para view_count

Reemplazar el read-modify-write por una actualización atómica a nivel de base de datos:

```python
# Antes (race condition)
post.view_count += 1
post.save()

# Después (atómico)
Post.objects.filter(id=post_id).update(view_count=F('view_count') + 1)
post = get_object_or_404(Post.objects.select_related('author').prefetch_related('tags', 'comments__author'), id=post_id)
```

### 4. Full-text search con SearchVector y GIN index

Reemplazar `icontains` por búsqueda de texto completo de PostgreSQL, que usa índices GIN y es órdenes de magnitud más rápida:

```python
from django.contrib.postgres.search import SearchVector, SearchQuery

posts = (
    Post.objects
    .annotate(search=SearchVector('title', 'body'))
    .filter(search=SearchQuery(q), is_published=True)
    .select_related('author')
    .prefetch_related('tags')
    .order_by("-created_at")
)
```

Acompañado de una migración que agrega un `GinIndex` sobre un `SearchVectorField` persistido, evitando recalcular el vector en cada búsqueda.

### 5. Batch tag lookup en create_post

```python
# Antes: 1 query por tag
for slug in payload.tag_slugs:
    tag = Tag.objects.get(slug=slug)
    post.tags.add(tag)

# Después: 1 query total
tags = Tag.objects.filter(slug__in=payload.tag_slugs)
post.tags.set(tags)
```

### 6. annotate() para counts en _user_detail

```python
from django.db.models import Count

user = (
    User.objects
    .annotate(post_count=Count('posts'), comment_count=Count('comments'))
    .get(id=user_id)
)
```

Reduce de 3 queries a 1.

### 7. Nueva migración con índices

```python
# blog/migrations/0002_add_performance_indexes.py
operations = [
    migrations.AddIndex(Post, models.Index(fields=['is_published'], name='post_is_published_idx')),
    migrations.AddIndex(Post, models.Index(fields=['-created_at'], name='post_created_at_idx')),
    migrations.AddIndex(User, models.Index(fields=['email'], name='user_email_idx')),
    migrations.AddIndex(Comment, models.Index(fields=['post', 'created_at'], name='comment_post_created_idx')),
    # GIN index para full-text search (requiere SearchVectorField en el modelo)
]
```

---

## Impacto esperado

| Endpoint | Queries antes | Queries después | Mejora |
|----------|--------------|-----------------|--------|
| GET /posts | ~200,001 | 3 | 66,000x |
| GET /posts/search | ~10,002 + scan | 2 (con índice GIN) | >5,000x |
| GET /posts/by-tag/{slug} | ~2,002 | 3 | 667x |
| GET /posts/{id} (1k comentarios) | ~1,003 | 3 | 334x |
| POST /posts (10 tags) | ~12 | 3 | 4x |
| GET /users/{id} | 3 | 1 | 3x |

---

## Tiempo estimado de desarrollo

| Tarea | Tiempo |
|-------|--------|
| select_related/prefetch en los tres list endpoints | 30 min |
| Paginación (list_posts, search_posts, posts_by_tag) | 30 min |
| F() para view_count + refactor get_post | 15 min |
| Full-text search + SearchVectorField + migración GIN | 45 min |
| Batch tags en create_post + annotate counts en _user_detail | 20 min |
| Migración de índices adicionales (is_published, created_at, email, composite) | 20 min |
| **Total** | **2h 40min – 3h** |

El ítem más costoso en tiempo es el full-text search porque requiere entender cómo PostgreSQL gestiona los `SearchVector` persistidos y cómo Django los indexa. El resto son cambios mecánicos de una línea con alto impacto.
