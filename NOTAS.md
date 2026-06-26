# NOTAS — Retrospectiva de la prueba técnica

## Qué se hizo y por qué

### Developer Experience (F1–F5)

| Feature | Problema | Solución |
|---------|----------|----------|
| F1 — Env vars | `SECRET_KEY` y credenciales hardcodeadas | `os.environ` con defaults seguros + `.env.example` |
| F2 — Docker | Postgres manual por cada dev | `Dockerfile` multi-stage + `docker-compose.yml`; `docker compose up` levanta todo |
| F3 — Estilo | Comillas mixtas, imports desordenados | `ruff check . && ruff format .` global |
| F4 — Seed | Sin progreso, sin flag rápido | Config dicts + output por tramo + `--fast` |
| F5 — README | Pasos manuales sin guía de errores | Reorganizado con Docker, CI y arquitectura |

### Performance (F6–F9)

**F6 — Eager loading:** `list_posts` / `search_posts` / `posts_by_tag` disparaban ~200k queries (N+1 por author y tags). Se aplicó `select_related("author").prefetch_related("tags")` en los tres. `get_post` sumó un `Prefetch` nombrado para comentarios con sus autores ordenados a nivel de BD. Resultado: 3 queries fijas sin importar el volumen.

**F7 — Paginación:** Ningún endpoint limitaba resultados. Se creó `DefaultPagination(LimitOffsetPagination)` con `limit=20` default y cap de 100. Respuesta: `{"posts": [...], "count": N}`. Combinado con F6: query count constante por página.

**F8 — view_count atómico:** El read-modify-write (`post.view_count += 1; post.save()`) perdía incrementos bajo concurrencia. Se reemplazó por `Post.objects.filter(id=post_id).update(view_count=F("view_count") + 1)` — atómico a nivel de BD. El `+1` en Python mantiene coherencia de respuesta sin SELECT adicional.

**F9 — Batch tags + annotate counts:** `create_post` hacía 1 query por tag. Se reemplazó por `filter(slug__in=tag_slugs)` con validación explícita (slugs deduplicados con `set()` antes de comparar). `_user_detail` emitía 2 COUNT separados; se reemplazó por `annotate(post_count=Count("posts", distinct=True), comment_count=Count("comments", distinct=True))`. El `distinct=True` es obligatorio — sin él, el JOIN de dos relaciones multivaluadas infla ambos counts por producto cartesiano.

### Refactor por capas (F13–F15)

`api.py` mezclaba routing, querysets, serialización y negocio. Se separó en capas con responsabilidad única:

| Capa | Archivo | Responsabilidad |
|---|---|---|
| Routing | `api.py` | Orquestar: recibir, llamar selector/service, devolver |
| Serialización | `schemas.py` | Forma de respuesta; resolvers para M2M y reverse FK |
| Lectura | `selectors.py` | Querysets, eager loading, anotaciones (HTTP-agnóstico) |
| Escritura/negocio | `services.py` | Crear, validar, mutar estado (HTTP-agnóstico) |
| Errores de dominio | `exceptions.py` | Excepciones de negocio → HTTP 400 vía handler en `NinjaAPI` |

Los 21 tests pasaron sin modificar uno solo — prueba de que el refactor no cambió comportamiento.

---

## Tiempo de desarrollo

| Épica | Fecha | Tiempo estimado |
|-------|-------|-----------------|
| F1–F5 Developer Experience | 25/06 | ≈85 min |
| F6–F9 Performance | 26/06 | ≈56 min |
| F13–F15 Refactor arquitectural | 26/06 | ≈60 min |
| Validación, tests y planificación | 25-26/06 | ≈90 min |
| **Total** | | **≈290 min (4h 50min)** |

**Desglose de validación y planificación:**
- Test setup: configuración de pytest, fixtures, `@pytest.mark.django_db`
- Test implementation: 21 tests (N+1 validation, pagination edge cases, atomicidad de vistas)
- Query validation: `assertNumQueries`, inspección de querysets con `.query`
- Design review: arquitectura de capas, decisiones de eager loading, manejo de errores
- Documentation: CLAUDE.md, NOTAS.md, comentarios en código

---

## Decisiones de diseño clave

1. **LimitOffsetPagination sobre page-based:** Offset es predecible ante inserciones concurrentes y compatible con cursors futuros sin cambiar la API.

2. **Prefetch nombrado para comentarios:** El `order_by` se aplica en BD, no en Python. El resolver de `PostDetailOut.resolve_comments` usa `.all()` puro para reutilizar la caché — `.order_by()` en el resolver invalidaría el prefetch y reintroduciría N+1.

3. **Services HTTP-agnósticos con domain exceptions:** Los services no importan Ninja ni lanzan `HttpError`. Lanzan `InvalidTagSlugs` (subclase de `DomainError`), traducida a 400 por un handler registrado en la instancia `NinjaAPI`. Así son testeables sin stack HTTP y reutilizables fuera de vistas.

4. **`get_object_or_404` en services (compromiso aceptable):** La alternativa pura sería lanzar `DoesNotExist` y traducirlo en la vista. Para esta escala, el acoplamiento mínimo con Django (no con Ninja) es tolerable y evita verbosidad innecesaria.

5. **Resolvers en schemas vs helpers manuales:** Las vistas devuelven objetos ORM; los schemas declaran la forma. Los resolvers de `tags` y `comments` usan `.all()` puro para reutilizar la caché del prefetch — si usaran `.filter()` u `.order_by()`, dispararían queries adicionales.

6. **`distinct=True` obligatorio en annotate doble:** Sin él, `Count("posts")` y `Count("comments")` sobre el mismo usuario generan un producto cartesiano que infla ambos valores. Elegido sobre subqueries por legibilidad suficiente al volumen actual (~1k usuarios).

---

## Qué no hicimos deliberadamente

- **F10 — Full-text search + GIN:** Requiere `SearchVectorField` persistido + migración + trigger. El riesgo: `annotate(SearchVector(...))` on-the-fly no usa el índice GIN — es fácil implementarlo como placebo. Sin dataset real para validar, el riesgo de "optimización" sin efecto es alto.
- **F11 — Índices B-tree:** Sin `EXPLAIN ANALYZE` sobre 100k posts reales no se sabe qué índices el planner ya usa. Agregar índices "a ojo" puede ralentizar inserciones sin beneficiar lecturas.
- **Cursor-based pagination:** Limit/offset es suficiente para el dataset actual y permite migrar a cursors sin cambiar el contrato de la API.

---

## Qué haría con un día más

1. **F11 (1.5h):** `EXPLAIN ANALYZE` en endpoints con dataset sembrado → agregar solo los índices que el planner no usa.
2. **F10 (2h):** `SearchVectorField` persistido + `GinIndex` + trigger de BD. Actualizar `selectors.search_published_posts()` para usar `SearchQuery` — el selector ya es el lugar correcto.
3. **Tests de capa (45 min):** Cubrir `selectors.*` de forma aislada, sin HTTP.
4. **django-debug-toolbar (30 min):** Queries SQL visibles en el browser para futuros devs.

---

## Resumen

En ~3.5 horas activas: configuración y Docker (F1–F5), N+1 eliminado (F6), paginación (F7), atomicidad (F8), optimizaciones de escritura (F9), refactor por capas (F13–F15). Resultado: 3 queries fijas por endpoint de lista, 21 tests verdes, y una arquitectura donde F10 y F11 se pueden agregar tocando únicamente `selectors.py` y una migración — sin modificar vistas ni schemas.
