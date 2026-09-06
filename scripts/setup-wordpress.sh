#!/bin/sh
# Instalación automática de WordPress para la prueba conjunta.
#
# Lo ejecuta el servicio `wpcli` de docker-compose.dev.yml. Es idempotente:
# se puede volver a lanzar sin romper nada.
set -eu

echo "· Esperando a que WordPress responda…"
i=0
until wp core is-installed --allow-root 2>/dev/null || [ "$i" -ge 30 ]; do
	if wp db check --allow-root >/dev/null 2>&1; then break; fi
	i=$((i + 1)); sleep 2
done

if ! wp core is-installed --allow-root 2>/dev/null; then
	echo "· Instalando WordPress…"
	wp core install --allow-root \
		--url=http://localhost:8080 \
		--title="PowerGIS · pruebas" \
		--admin_user=admin \
		--admin_password=admin \
		--admin_email=admin@powergis.test \
		--skip-email
else
	echo "· WordPress ya estaba instalado."
fi

echo "· Activando el conector…"
wp plugin activate powergis-connector --allow-root

# El front real. Sólo si están sus ficheros: el repositorio trae los tres que
# cambian, pero `saas-studies.php` y `data/` los copia el usuario desde su
# carpeta (ver wordpress/saas-studies/LEEME.md).
if [ -f /var/www/html/wp-content/plugins/saas-studies/saas-studies.php ]; then
	echo "· Activando el front (SaaS Studies)…"
	wp plugin activate saas-studies --allow-root || \
		echo "  · no se pudo activar; revisa que esté el plugin completo"
else
	echo "· SaaS Studies no está completo: se omite."
	echo "  Copia saas-studies.php, uninstall.php, includes/{helpers,roles,taxonomies}.php"
	echo "  y data/ desde tu carpeta. Detalles en wordpress/saas-studies/LEEME.md"
fi

echo "· Enlaces permanentes (la REST API los necesita bonitos)…"
wp rewrite structure '/%postname%/' --allow-root
wp rewrite flush --hard --allow-root

echo "· Creando las páginas del flujo…"
create_page() {
	slug="$1"; title="$2"; content="$3"
	if ! wp post list --post_type=page --name="$slug" --format=count --allow-root | grep -q '^1$'; then
		wp post create --allow-root \
			--post_type=page --post_status=publish \
			--post_title="$title" --post_name="$slug" \
			--post_content="$content" >/dev/null
		echo "  · /$slug creada"
	else
		echo "  · /$slug ya existía"
	fi
}

create_page "nuevo-proyecto" "Nuevo proyecto"  "[powergis_form]"
create_page "mis-proyectos"  "Mis proyectos"   "[powergis_my_projects]"

# Las dos páginas del front real, con el mismo shortcode que powergis.es.
if wp plugin is-active saas-studies --allow-root 2>/dev/null; then
	create_page "crear-proyecto"               "Crear proyecto"               "[crear_proyecto_v6]"
	create_page "crear-proyecto-geolocalizado" "Crear proyecto geolocalizado" "[crear_proyecto_v6]"
fi

echo "· Usuario de prueba (no administrador, para comprobar los permisos)…"
if ! wp user get cliente --allow-root >/dev/null 2>&1; then
	wp user create cliente cliente@powergis.test \
		--role=subscriber --user_pass=cliente --allow-root >/dev/null
	echo "  · cliente / cliente"
fi

echo ""
echo "──────────────────────────────────────────────────────────"
echo " WordPress listo:  http://localhost:8080"
echo "   admin:    admin   / admin      (ve el simulador de pago)"
echo "   cliente:  cliente / cliente    (usuario normal)"
echo ""
echo " Formulario del conector:  http://localhost:8080/nuevo-proyecto/"
echo " TU formulario real:       http://localhost:8080/crear-proyecto/"
echo " Mis proyectos:  http://localhost:8080/mis-proyectos/"
echo " Diagnóstico:    http://localhost:8080/wp-admin/edit.php?post_type=project&page=powergis-status"
echo "──────────────────────────────────────────────────────────"
