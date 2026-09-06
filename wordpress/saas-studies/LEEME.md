# El front, en local

Copia de trabajo del plugin **SaaS Studies** de powergis.es, para probar el
formulario real contra el motor local sin tocar el sitio en producción.

## Qué hay aquí y qué falta

Están los tres ficheros que cambian y que ya llevan el guardia de rutas:

    includes/shortcodes.php     [crear_proyecto_v6] · versión de agosto de 2026
    includes/cpt-project.php    CPT project, con guardia
    includes/rest-projects.php  rutas saas/v1, con guardia

**Falta el resto del plugin, y no lo tengo yo: lo tienes tú.** Copia desde
`SAAS_STUDY/SAAS_studies/` de tus Descargas:

    saas-studies.php        el arranque del plugin
    uninstall.php
    includes/helpers.php
    includes/roles.php
    includes/taxonomies.php
    data/                   arbol.json, Estructura_CNAE2025.csv, paises.csv

Los `data/` pesan 1 MB y son los que alimentan los desplegables de ubicación,
actividad y nacionalidad del formulario.

## Por qué tres ficheros míos y no los tuyos

Los de tu carpeta son de febrero: el `shortcodes.php` de ahí manda un payload
plano de cinco campos, no el anidado que envía tu web hoy. Probar con esa copia
sería probar un contrato que ya no existe. Los que hay aquí son los que me
enviaste en agosto.

## El guardia de rutas

`rest-projects.php` y el conector registran las mismas rutas
(`saas/v1/projects/create`, `/save-draft`, `/callback`). WordPress no avisa:
apila los dos manejadores y despacha el primero que coincida, así que gana el
que cargue antes. Un accidente, no una decisión.

Con el guardia, si el conector está activo este plugin se aparta de las rutas
REST y del CPT, y conserva todo lo demás: shortcode, taxonomías, roles.
Desactiva el conector y vuelve a hacerse cargo solo.

Comprueba en cualquier momento que no hay choques:

    make dev-rutas          .\pg rutas   en Windows

Ninguna ruta debe salir con más de un manejador.
