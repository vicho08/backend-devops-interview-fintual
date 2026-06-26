# Reporte 3: Production Readiness

## Análisis del problema

El proyecto está configurado como prototipo de desarrollo: secretos hardcodeados en el código, `DEBUG=True` fijo, sin servidor WSGI de producción, sin containerización, sin logging estructurado y sin endpoints de salud. Ninguno de estos elementos impide que el servicio _funcione_ localmente, pero todos impiden que sea operado de forma segura y observable en cualquier entorno compartido.

### Problemas identificados

#### Críticos (bloquean deploy seguro)

| Problema | Archivo | Detalle |
|----------|---------|---------|
| `SECRET_KEY` hardcodeada en el repositorio | `core/settings.py:5` | Cualquiera con acceso al repo puede forjar cookies de sesión y tokens CSRF. Django marca la clave con prefijo `django-insecure-` como señal de que no debe usarse en producción. |
| `DEBUG = True` fijo | `core/settings.py:7` | En producción, `DEBUG=True` expone stack traces completos con variables locales en las respuestas de error HTTP, y desactiva optimizaciones de caché de templates. |
| `ALLOWED_HOSTS = ["*"]` | `core/settings.py:9` | Permite ataques de Host header injection. Django solo protege contra esto cuando `ALLOWED_HOSTS` lista hosts explícitos. |
| Credenciales de BD hardcodeadas | `core/settings.py:53–62` | Usuario `postgres`, contraseña `postgres`, host `localhost` están en el código fuente. Imposible rotar credenciales sin modificar y commitear código. |

#### Altos (bloquean operación confiable)

| Problema | Detalle |
|----------|---------|
| Sin servidor WSGI de producción | `pyproject.toml` no incluye `gunicorn` ni `uvicorn`. El servidor de desarrollo de Django (`manage.py runserver`) es single-threaded, no maneja señales del SO correctamente y no está diseñado para carga real. |
| Sin containerización | No hay `Dockerfile` ni `docker-compose.yml`. Sin imagen reproducible, el entorno de producción depende del estado de la máquina host. |
| Sin CI/CD | No existe `.github/workflows/` ni equivalente. Los tests y el lint nunca se validan automáticamente. |

#### Medios (degradan operabilidad)

| Problema | Detalle |
|----------|---------|
| Sin `STATIC_ROOT` ni middleware para estáticos | `STATIC_URL` está configurado pero `STATIC_ROOT` no. En producción, Django no sirve archivos estáticos cuando `DEBUG=False` a menos que se use whitenoise u otro mecanismo. |
| Sin endpoint de health check | Los load balancers y orquestadores (ECS, K8s, Fly) necesitan un endpoint `/health` que responda 200 para saber si el contenedor está listo. Sin esto, el tráfico llega a instancias que no han completado su startup. |
| Sin logging estructurado | No hay configuración `LOGGING` en settings. Los errores van a stderr sin formato, nivel ni contexto de request. Dificulta alertas y debugging en producción. |
| Sin headers de seguridad HTTP | Faltan `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`. Relevantes cuando el servicio corre detrás de TLS. |

---

## Solución propuesta

### 1. Refactorizar `core/settings.py` con variables de entorno

Reemplazar todos los valores hardcodeados por lecturas de `os.environ`, con defaults seguros solo para desarrollo local. Sin dependencias externas adicionales.

```python
import os

SECRET_KEY = os.environ['SECRET_KEY']  # Falla explícitamente si no está definida
DEBUG = os.environ.get('DEBUG', 'False') == 'True'
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB', 'backend_devops_interview'),
        'USER': os.environ.get('POSTGRES_USER', 'postgres'),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD', 'postgres'),
        'HOST': os.environ.get('POSTGRES_HOST', 'localhost'),
        'PORT': os.environ.get('POSTGRES_PORT', '5432'),
    }
}

# Solo en producción (cuando DEBUG=False)
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
```

### 2. `Dockerfile` multi-stage

Stage de build instala dependencias con `uv`; stage de runtime usa imagen slim sin herramientas de compilación. Resultado: imagen final pequeña (~150MB) con solo lo necesario para correr.

```dockerfile
# Stage 1: instalación de dependencias
FROM python:3.14-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Stage 2: imagen de producción
FROM python:3.14-slim
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY . .
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["gunicorn", "core.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4"]
```

### 3. `docker-compose.yml` para desarrollo y staging

Servicios `db` (postgres:16-alpine) y `web` (imagen local) con variables de entorno leídas de `.env`. Permite `docker compose up` para tener el stack completo sin instalaciones manuales.

### 4. Agregar `gunicorn` a dependencias de producción

```toml
# pyproject.toml
dependencies = [
    "django>=5.2,<5.3",
    "django-ninja>=1.5,<2",
    "psycopg[binary]>=3.3,<4",
    "faker>=30",
    "gunicorn>=23",
    "whitenoise>=6",
]
```

`whitenoise` sirve archivos estáticos desde el proceso de gunicorn sin necesidad de nginx separado, simplificando el deployment en plataformas PaaS.

### 5. Endpoint `/api/health`

Endpoint simple en `core/urls.py` (o en el router de Ninja) que verifica conectividad con la base de datos y retorna 200/503:

```python
@router.get("/health")
def health(request):
    from django.db import connection
    connection.ensure_connection()
    return {"status": "ok"}
```

Permite que load balancers y orquestadores separen instancias sanas de las que fallan al conectar con la BD durante deploys o reinicios.

### 6. Configuración de logging estructurado

Agregar `LOGGING` dict en settings que envía logs a stdout (compatible con log aggregators como CloudWatch, Datadog, Loki):

```python
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {
        'django.request': {'handlers': ['console'], 'level': 'WARNING'},
    },
}
```

### 7. `STATIC_ROOT` y whitenoise

```python
STATIC_ROOT = BASE_DIR / 'staticfiles'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Justo después de SecurityMiddleware
    ...
]
```

Permite `python manage.py collectstatic` en el build del Dockerfile y que gunicorn sirva los estáticos del admin sin configuración adicional de nginx.

---

## Arquitectura de deploy propuesta

```
Internet → Load Balancer (HTTPS) → Gunicorn (container) → PostgreSQL (managed)
                                          ↓
                               /api/health (health check)
                               stdout logs → log aggregator
```

El deployment target más simple para este servicio: **ECS Fargate** (si ya se usa AWS) o **Fly.io** (mínima fricción para un servicio pequeño). Ambos consumen el `Dockerfile` directamente y manejan el certificado TLS, el load balancer y el escalado horizontal.

---

## Tiempo estimado de desarrollo

| Tarea | Tiempo |
|-------|--------|
| Refactor `core/settings.py` + `.env.example` | 30 min |
| `Dockerfile` multi-stage con gunicorn | 30 min |
| `docker-compose.yml` (solapado con Reporte 1) | 20 min |
| `gunicorn` + `whitenoise` en deps + `STATIC_ROOT` | 20 min |
| Endpoint `/api/health` | 15 min |
| Configuración `LOGGING` | 20 min |
| Headers de seguridad en settings | 15 min |
| CI con build y push de imagen Docker | 20 min |
| **Total** | **2h 50min – 3h 30min** |

El mayor riesgo de tiempo está en probar el Dockerfile localmente y validar que la imagen construida pasa los tests antes de configurar el CI. El refactor de settings es el cambio de mayor impacto con menor costo.
