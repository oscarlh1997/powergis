# PowerGIS · tareas de desarrollo y operación
#
#   make setup      instala el entorno de desarrollo
#   make test       ejecuta la suite (sin Docker, en segundos)
#   make lint       ruff + mypy
#   make up         levanta todo el stack
#   make bootstrap  migra, sincroniza catálogo y carga geografías
#   make demo       lo anterior + datos sintéticos para ver el sistema andando

SHELL := /bin/bash
.DEFAULT_GOAL := help

# Gama de la máquina. El fichero base está dimensionado para 2 vCPU / 8 GB;
# cada override sólo mueve techos y paralelismo, nunca qué servicios existen.
#
#   make up                → Hostinger KVM2   2 vCPU ·  8 GB · 100 GB
#   make up TIER=kvm4      → Hostinger KVM4   4 vCPU · 16 GB · 200 GB
#   make up TIER=cx33      → Hetzner   CX33   4 vCPU ·  8 GB ·  80 GB
#   make up TIER=cx23      → Hetzner   CX23   2 vCPU ·  4 GB ·  40 GB  (pruebas)
#   make up TIER=oracle    → Oracle A1  ARM   2 OCPU · 12 GB · 200 GB  (gratis)
#
# `make tier` mira la máquina en la que estás y te dice cuál toca.
TIER ?= kvm2

TIERS_VALIDOS := kvm2 kvm4 cx33 cx23 oracle
ifeq ($(filter $(TIER),$(TIERS_VALIDOS)),)
$(error TIER='$(TIER)' no existe. Válidos: $(TIERS_VALIDOS))
endif

ifeq ($(TIER),kvm2)
COMPOSE := docker compose
else
COMPOSE := docker compose -f docker-compose.yml -f docker-compose.$(TIER).yml
endif

ENGINE := $(COMPOSE) exec -T api

.PHONY: help
help:  ## Muestra esta ayuda
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# -- desarrollo local -------------------------------------------------------

.PHONY: setup
setup:  ## Crea el venv e instala dependencias de desarrollo
	cd engine && python3 -m venv .venv && \
		.venv/bin/pip install --upgrade pip && \
		.venv/bin/pip install -e '.[dev,pdf,geo]'
	@echo "Listo. Activa con: source engine/.venv/bin/activate"

.PHONY: test
test:  ## Ejecuta la suite completa
	cd engine && python -m pytest -q

.PHONY: test-cov
test-cov:  ## Suite con informe de cobertura
	cd engine && python -m pytest --cov --cov-report=term-missing --cov-report=html
	@echo "Informe HTML en engine/htmlcov/index.html"

.PHONY: lint
lint:  ## ruff + mypy
	cd engine && python -m ruff check src tests
	cd engine && python -m mypy src || true

.PHONY: fmt
fmt:  ## Autoformato
	cd engine && python -m ruff check --fix src tests && python -m ruff format src tests

.PHONY: lint-php
lint-php:  ## Comprueba la sintaxis del plugin de WordPress
	@find wordpress -name '*.php' -exec php -l {} \; | grep -v 'No syntax errors' || echo "PHP OK"

.PHONY: seed-file
seed-file:  ## Regenera el fichero de geografías
	cd engine && python tools/build_seed.py

# -- entorno de pruebas con WordPress ---------------------------------------

DEV := docker compose -f docker-compose.dev.yml

.PHONY: dev
dev:  ## Arranca motor + WordPress y lo deja todo listo para probar
	$(DEV) up -d --build
	@echo "· Esperando a la base de datos…"
	@sleep 8
	$(DEV) exec -T api alembic upgrade head
	$(DEV) exec -T api powergis seed --demo
	$(DEV) --profile setup run --rm wpcli
	@echo ""
	@echo "  WordPress  http://localhost:8080   (admin/admin · cliente/cliente)"
	@echo "  Motor      http://localhost:8000/docs"
	@echo "  Empieza en http://localhost:8080/nuevo-proyecto/"

.PHONY: dev-down
dev-down:  ## Para el entorno de pruebas (conserva los datos)
	$(DEV) down

.PHONY: dev-reset
dev-reset:  ## Borra TODO el entorno de pruebas y vuelve a empezar
	$(DEV) down -v
	$(MAKE) dev

.PHONY: dev-logs
dev-logs:  ## Logs del motor y del worker
	$(DEV) logs -f api worker

.PHONY: probar-formulario
probar-formulario:  ## Mete el payload real de [crear_proyecto_v6] por todo el circuito
	$(DEV) --profile setup run --rm --entrypoint= wpcli \
		wp eval-file /scripts/probar-formulario.php --allow-root --path=/var/www/html

.PHONY: dev-rutas
dev-rutas:  ## Qué se ha registrado en saas/v1 (detecta choques plugin/tema)
	@$(DEV) --profile setup run --rm --entrypoint= wpcli \
		wp eval 'foreach (rest_get_server()->get_routes() as $$r => $$h) { if (str_starts_with($$r, "/saas/v1")) { echo $$r . "  →  " . count($$h) . " manejador(es)" . (count($$h) > 1 ? "  ⚠ CHOQUE" : "") . PHP_EOL; } }' \
		--allow-root --path=/var/www/html

.PHONY: diagnostico
diagnostico:  ## Vuelca todo el estado a diagnostico.txt, para mandarlo
	@./scripts/diagnostico.sh

.PHONY: doctor
doctor:  ## Diagnostica el motor desde dentro (empieza siempre por aquí)
	$(DEV) exec -T api powergis doctor

.PHONY: endpoints
endpoints:  ## Dispara TODOS los endpoints con los datos de scripts/fixtures.json
	$(DEV) exec -T api powergis endpoints

.PHONY: smoke
smoke:  ## Prueba de humo de punta a punta (en Python, dentro del contenedor)
	$(DEV) exec -T api powergis smoke

.PHONY: smoke-bash
smoke-bash:  ## La misma prueba en bash, desde fuera (no sirve en Windows)
	./scripts/smoke-test.sh http://localhost:8000 dev-secreto-compartido-cambialo-en-produccion-0123456789

.PHONY: dev-psql
dev-psql:  ## Consola SQL del entorno de pruebas
	$(DEV) exec postgres psql -U powergis -d powergis

# -- stack completo (producción) --------------------------------------------

.PHONY: tier
tier:  ## Qué TIER corresponde a esta máquina (mira CPU, RAM y disco)
	@nucleos=$$(nproc); \
	 ram=$$(awk '/MemTotal/ {printf "%d", $$2/1024/1024 + 0.5}' /proc/meminfo); \
	 disco=$$(df -BG --output=size / | tail -1 | tr -dc '0-9'); \
	 arco=$$(uname -m); \
	 echo "Esta máquina: $$nucleos vCPU · $$ram GB RAM · $$disco GB en / · $$arco"; \
	 echo ""; \
	 if   [ "$$arco" = "aarch64" ]; then sugerido=oracle; \
	 elif [ "$$ram" -le 5 ]; then sugerido=cx23; \
	 elif [ "$$ram" -ge 14 ]; then sugerido=kvm4; \
	 elif [ "$$nucleos" -ge 4 ]; then sugerido=cx33; \
	 else sugerido=kvm2; fi; \
	 echo "  make up TIER=$$sugerido"; \
	 if [ "$$sugerido" = "oracle" ]; then \
	   echo ""; \
	   echo "  ARM detectado. Comprueba PostGIS antes de seguir:"; \
	   echo "    docker run --rm postgis/postgis:16-3.4 postgres --version"; \
	   echo "  Si falla por manifiesto, mira docker-compose.oracle.yml"; \
	 fi; \
	 if [ "$$sugerido" = "cx23" ]; then \
	   echo ""; \
	   echo "  AVISO: 4 GB es un perfil de PRUEBAS. Las colas etl y reports"; \
	   echo "  comparten worker, así que una carga del INE bloquea informes."; \
	   echo "  Lee la cabecera de docker-compose.cx23.yml antes de vender nada."; \
	 fi

.PHONY: up
up:  ## Levanta el stack
	$(COMPOSE) up -d --build
	@echo "Motor en https://$${ENGINE_HOST:-localhost}   (TIER=$(TIER))"

.PHONY: down
down:  ## Para el stack (conserva volúmenes)
	$(COMPOSE) down

.PHONY: logs
logs:  ## Sigue los logs de todos los servicios
	$(COMPOSE) logs -f --tail=100

.PHONY: ps
ps:  ## Estado de los servicios
	$(COMPOSE) ps

.PHONY: shell
shell:  ## Shell dentro del contenedor de la API
	$(COMPOSE) exec api /bin/bash

.PHONY: psql
psql:  ## Consola de PostgreSQL
	$(COMPOSE) exec postgres psql -U $${POSTGRES_USER:-powergis} -d $${POSTGRES_DB:-powergis}

# -- base de datos ----------------------------------------------------------

.PHONY: migrate
migrate:  ## Aplica las migraciones
	$(ENGINE) alembic upgrade head

.PHONY: migration
migration:  ## Genera una migración: make migration m="descripción"
	$(ENGINE) alembic revision --autogenerate -m "$(m)"

.PHONY: bootstrap
bootstrap: migrate  ## Migra + catálogo + geografías
	$(ENGINE) powergis sync-catalog
	$(ENGINE) powergis seed

.PHONY: demo
demo: bootstrap  ## Bootstrap + datos SINTÉTICOS de demostración
	$(ENGINE) powergis seed --demo
	@echo ""
	@echo "AVISO: los datos --demo son sintéticos. No publiques un informe con ellos."

.PHONY: municipios
municipios:  ## Carga los ~8.100 municipios en dim_geo (la semilla sólo llega a provincia)
	$(ENGINE) powergis load-municipios

.PHONY: almacen
almacen: bootstrap municipios  ## Cimientos completos: migraciones + catálogo + geografías + municipios
	@echo ""
	@echo "Almacén montado hasta nivel municipio."
	@echo "Antes de cargar datos:  make ine-verify"

.PHONY: ingest-ine
ingest-ine:  ## Carga demografía del INE (tarda; va a la cola etl)
	@echo "Comprobando el mapeo del INE antes de cargar…"
	@$(ENGINE) powergis ine-verify || { \
		echo ""; \
		echo "ABORTADO: el mapeo del INE no cuadra. Cargar ahora llenaría el"; \
		echo "almacén de huecos que parecen secreto estadístico."; \
		exit 1; }
	$(ENGINE) powergis ingest ine --level municipio

.PHONY: derive
derive:  ## Recalcula indicadores derivados
	$(ENGINE) powergis derive --level provincia

.PHONY: coverage-report
coverage-report:  ## Indicadores del catálogo sin colector
	$(ENGINE) powergis coverage

.PHONY: check-config
check-config:  ## Verifica que la configuración es apta para producción
	$(ENGINE) powergis check-config

.PHONY: ine-verify
ine-verify:  ## Comprueba contra la API del INE que los IDs de tabla existen
	$(ENGINE) powergis ine-verify

# -- capacidad: cuándo pasar de KVM2 a KVM4 ---------------------------------

.PHONY: capacity
capacity:  ## Memoria/CPU por contenedor + profundidad de colas
	@echo "── Recursos ──────────────────────────────────────────────"
	@docker stats --no-stream \
		--format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.CPUPerc}}'
	@echo ""
	@echo "── Colas (mensajes en espera) ────────────────────────────"
	@$(COMPOSE) exec -T redis sh -c \
		'for q in reports.advanced reports.basic etl narrative celery; do \
			printf "  %-18s %s\n" "$$q" "$$(redis-cli -n 1 llen $$q)"; \
		 done'
	@echo ""
	@echo "── Conexiones a PostgreSQL ───────────────────────────────"
	@$(COMPOSE) exec -T postgres psql -U $${POSTGRES_USER:-powergis} -d $${POSTGRES_DB:-powergis} -tAc \
		"SELECT '  en uso: '||count(*)||' / '||current_setting('max_connections') FROM pg_stat_activity"
	@echo ""
	@echo "Señales para migrar a KVM4 (make up TIER=kvm4):"
	@echo "  · postgres sostenido por encima del 85 % de su techo"
	@echo "  · reports.* con cola > 0 de forma habitual en hora punta"
	@echo "  · conexiones cerca de max_connections"

# -- copias de seguridad ----------------------------------------------------

.PHONY: backup
backup:  ## Copia manual
	$(COMPOSE) exec -T backup /backup.sh

.PHONY: restore-test
restore-test:  ## PRUEBA la restauración del último backup en una BD temporal
	@echo "Un backup que nunca se ha restaurado no es un backup."
	$(COMPOSE) exec -T postgres psql -U $${POSTGRES_USER:-powergis} -c "DROP DATABASE IF EXISTS restore_test"
	$(COMPOSE) exec -T postgres psql -U $${POSTGRES_USER:-powergis} -c "CREATE DATABASE restore_test"
	@# Los backups viven en el VOLUMEN `backups`, montado en /backups dentro
	@# del contenedor — no en ./infra/backups, que es lo que se miraba antes.
	@# Con la ruta equivocada esto decía siempre «No hay backups» y la prueba
	@# de restauración no se ejecutaba nunca: justo el fallo que la tarea
	@# existe para detectar.
	@LATEST=$$($(COMPOSE) exec -T backup sh -c 'ls -t /backups/*.sql.gz 2>/dev/null | head -1'); \
	 if [ -z "$$LATEST" ]; then \
	   echo "No hay backups sin cifrar en el volumen. Lanza primero: make backup"; \
	   echo "(si BACKUP_GPG_PASSPHRASE está definida, descífralo antes con gpg -d)"; \
	   exit 1; fi; \
	 echo "Restaurando $$LATEST …"; \
	 $(COMPOSE) exec -T backup sh -c "gunzip -c '$$LATEST'" \
	   | $(COMPOSE) exec -T postgres psql -U $${POSTGRES_USER:-powergis} -d restore_test >/dev/null
	$(COMPOSE) exec -T postgres psql -U $${POSTGRES_USER:-powergis} -d restore_test \
		-c "SELECT count(*) AS geografias FROM dim_geo; SELECT count(*) AS hechos FROM fact_indicator;"
	@echo "Restauración verificada."

# -- teselas ----------------------------------------------------------------

.PHONY: tiles
tiles:  ## Genera las teselas PMTiles (necesita mapshaper y tippecanoe)
	@command -v tippecanoe >/dev/null || { echo "Instala tippecanoe primero"; exit 1; }
	./infra/build-tiles.sh
