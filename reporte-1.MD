# Reporte 1: Developer Experience

## Análisis del problema

El setup actual requiere que cada desarrollador instale y configure manualmente PostgreSQL 16 en su máquina, cree la base de datos con las credenciales exactas hardcodeadas, y ejecute una secuencia de comandos sin guía de errores posibles. No existe ningún mecanismo de automatización ni estandarización del entorno.

### Problemas identificados

| # | Problema | Archivo afectado | Impacto |
|---|----------|-----------------|---------|
| 1 | PostgreSQL debe instalarse localmente y configurarse con usuario/clave exactos (`postgres`/`postgres`), y la BD debe crearse manualmente con `createdb` | `README.md` | Bloquea onboarding en cualquier máquina sin Postgres preinstalado |
| 2 | Credenciales de BD y `SECRET_KEY` hardcodeadas en código fuente sin soporte de variables de entorno | `core/settings.py` | Imposible tener configuraciones distintas por entorno sin tocar código |
| 3 | No existe `docker-compose.yml` para levantar dependencias | — | Cada desarrollador necesita gestionar Postgres por su cuenta |
| 4 | No hay pipeline CI: sin `.github/workflows/`, lint y tests nunca se ejecutan automáticamente | — | Errores de formato o tests rotos llegan al repositorio sin detección |
| 5 | `manage.py seed` tarda varios minutos sin feedback de progreso; no hay forma de correr un seed rápido para desarrollo | `blog/management/commands/seed.py` | Tiempo de espera innecesario en onboarding |
| 6 | `.gitignore` no incluye `.env`, `.env.local`, archivos de IDE ni `staticfiles/` | `.gitignore` | Riesgo de commitear credenciales o archivos generados accidentalmente |

### Raíz del problema

El proyecto está pensado como prototipo de una sola máquina. No separa la configuración del código, no containeriza las dependencias externas y no tiene automatización de calidad. Cada paso del README es una oportunidad de fallo silencioso para un desarrollador nuevo.

---

## Solución propuesta

### 1. `docker-compose.yml` con servicios `db` y `web`

Elimina la necesidad de instalar Postgres localmente. Un único `docker compose up` levanta la BD y el servidor de desarrollo con el entorno correctamente configurado.

```yaml
# Estructura propuesta
services:
  db:
    image: postgres:16-alpine
    environment: { POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD }
    ports: ["5432:5432"]
    volumes: [postgres_data:/var/lib/postgresql/data]

  web:
    build: .
    command: uv run python manage.py runserver 0.0.0.0:8000
    volumes: [.:/app]
    ports: ["8000:8000"]
    depends_on: [db]
    env_file: .env
```

### 2. `core/settings.py` refactorizado con `os.environ`

Sin agregar dependencias externas. Todos los valores sensibles se leen del entorno con defaults seguros para desarrollo local.

```python
# Cambios clave
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-insecure-key-only-for-local')
DEBUG = os.environ.get('DEBUG', 'True') == 'True'
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '*').split(',')

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
```

### 3. `.env.example` documentado

Archivo de referencia que cada desarrollador copia a `.env` al hacer checkout. Documenta todas las variables disponibles con valores de ejemplo seguros.

### 4. `.github/workflows/ci.yml`

Pipeline CI con dos jobs ejecutados en cada push/PR:
- **lint**: `ruff check .` + `ruff format --check .`
- **test**: `uv run pytest` contra un contenedor Postgres efímero (GitHub Actions service containers)

Esto convierte la suite de tests existente en un gate automático sin trabajo adicional de mantenimiento.

### 5. Actualizar `.gitignore`

Agregar `.env`, `.env.local`, `staticfiles/`, `.vscode/`, `.idea/` para prevenir commits accidentales de credenciales o artefactos generados.

---

## Tiempo estimado de desarrollo

| Tarea | Tiempo |
|-------|--------|
| `docker-compose.yml` (db + web) | 20 min |
| Refactor `core/settings.py` + `.env.example` | 20 min |
| `.github/workflows/ci.yml` (lint + test con service container) | 30 min |
| Actualizar `.gitignore` + ajustes menores en README | 15 min |
| **Total** | **1h 25min – 2h** |

El mayor costo está en probar que el CI corra correctamente con la BD efímera de GitHub Actions. El resto es mecánico.
